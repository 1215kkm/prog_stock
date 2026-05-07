"""python-kis 라이브러리 어댑터.

라이브러리가 변경되거나 KIS API 직결이 필요할 때 이 파일만 교체한다.
런타임은 BrokerPort 인터페이스에만 의존한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import structlog

from prog_stock.brokers.port import (
    Balance,
    BrokerPort,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    Tick,
)

log = structlog.get_logger(__name__)


class KisAdapter(BrokerPort):
    """python-kis 래퍼. 모의투자 / 실거래 동일 인터페이스.

    실제 KIS 호출은 python-kis가 수행. 이 어댑터는 BrokerPort 형태로 정규화만 담당.
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account_number: str,
        virtual: bool = True,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_number = account_number
        self.virtual = virtual
        self._client = self._build_client()

    def _build_client(self):  # type: ignore[no-untyped-def]
        try:
            from pykis import PyKis  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError(
                "python-kis not installed. Run: pip install python-kis"
            ) from e

        return PyKis(
            appkey=self.app_key,
            appsecret=self.app_secret,
            account=self.account_number,
            virtual_account=self.virtual,
        )

    def place_order(self, order: Order) -> OrderResult:
        log.info("place_order", symbol=order.symbol, side=order.side, qty=order.quantity,
                 order_type=order.order_type, price=order.price, idem=order.idempotency_key)
        try:
            stock = self._client.stock(order.symbol)
            if order.side == Side.BUY:
                fn = stock.buy
            else:
                fn = stock.sell
            kwargs: dict = {"quantity": order.quantity}
            if order.order_type == OrderType.LIMIT:
                kwargs["price"] = order.price
            result = fn(**kwargs)
            broker_id = str(getattr(result, "order_id", ""))
            return OrderResult(
                broker_order_id=broker_id,
                status=OrderStatus.PENDING,
            )
        except Exception as e:
            log.error("kis_place_order_failed", error=str(e))
            return OrderResult(
                broker_order_id="",
                status=OrderStatus.REJECTED,
            )

    def cancel(self, broker_order_id: str) -> bool:
        try:
            self._client.account.order(broker_order_id).cancel()
            return True
        except Exception as e:
            log.warning("kis_cancel_failed", order_id=broker_order_id, error=str(e))
            return False

    def positions(self) -> list[Position]:
        balance = self._client.account.balance()
        out: list[Position] = []
        for p in getattr(balance, "stocks", []):
            out.append(
                Position(
                    symbol=str(getattr(p, "symbol", "")),
                    quantity=int(getattr(p, "quantity", 0)),
                    avg_price=float(getattr(p, "purchase_price", 0)),
                    current_price=float(getattr(p, "current_price", 0)),
                )
            )
        return out

    def balance(self) -> Balance:
        b = self._client.account.balance()
        cash = float(getattr(b, "deposit", 0))
        positions_value = sum(
            float(getattr(p, "current_price", 0)) * int(getattr(p, "quantity", 0))
            for p in getattr(b, "stocks", [])
        )
        return Balance(
            cash=cash,
            positions_value=positions_value,
            total_equity=cash + positions_value,
        )

    def quote(self, symbol: str) -> Quote:
        stock = self._client.stock(symbol)
        q = stock.quote()
        return Quote(
            symbol=symbol,
            bid=float(getattr(q, "bid_price", 0)),
            ask=float(getattr(q, "ask_price", 0)),
            last=float(getattr(q, "current_price", 0)),
            volume=int(getattr(q, "volume", 0)),
            vi_active=bool(getattr(q, "vi_active", False)),
            is_locked_upper=bool(getattr(q, "is_upper_limit", False)),
            is_locked_lower=bool(getattr(q, "is_lower_limit", False)),
            timestamp=datetime.now(),
        )

    async def subscribe(self, symbols: list[str]) -> AsyncIterator[Tick]:
        # WebSocket 구독은 python-kis async API에 의존
        # python-kis가 동기/비동기 혼재라 실제 구현은 라이브러리 버전에 따라 조정
        raise NotImplementedError("WebSocket subscribe — wire up to python-kis async client")
        yield  # type: ignore[unreachable]

    def is_tradeable(self, symbol: str) -> bool:
        """VI/상하한가 체크. 거래정지/관리종목은 universe에서 사전 제외."""
        try:
            q = self.quote(symbol)
            return not (q.vi_active or q.is_locked_upper or q.is_locked_lower)
        except Exception:
            return False
