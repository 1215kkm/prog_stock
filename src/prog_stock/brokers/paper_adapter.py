"""Paper / dry-run 어댑터 — 가상 주문장부.

실시간 시세는 위임받은 BrokerPort(보통 KisAdapter)에서 가져오고,
주문은 실제로 보내지 않고 메모리/SQLite에 가상 체결로 기록한다.

dry_run 모드: 전략 X, 인프라만 검증
paper 모드: 전략 ON, 가상 자본 운용
"""
from __future__ import annotations

import uuid
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


class PaperAdapter(BrokerPort):
    """가상 자본 + 실시간 시세."""

    def __init__(
        self,
        quote_source: BrokerPort,
        starting_cash: float = 10_000_000.0,
        slippage_rate: float = 0.001,
        commission_rate: float = 0.00015,
        sell_tax_rate: float = 0.0018,
    ) -> None:
        self._quote_source = quote_source
        self._cash = starting_cash
        self._positions: dict[str, Position] = {}
        self.slippage_rate = slippage_rate
        self.commission_rate = commission_rate
        self.sell_tax_rate = sell_tax_rate

    def place_order(self, order: Order) -> OrderResult:
        try:
            quote = self._quote_source.quote(order.symbol)
        except Exception as e:
            log.warning("paper_quote_failed", symbol=order.symbol, error=str(e))
            return OrderResult(broker_order_id="", status=OrderStatus.REJECTED)

        # 체결가 산정: 시장가 = last ± slippage, 지정가 = price (수긍 가능 호가만)
        if order.order_type == OrderType.MARKET:
            fill_price = quote.last * (1 + self.slippage_rate * (1 if order.side == Side.BUY else -1))
        else:
            assert order.price is not None
            # 지정가는 단순히 호가 만족 시 체결로 가정
            if order.side == Side.BUY and order.price < quote.ask:
                return OrderResult(broker_order_id=str(uuid.uuid4()), status=OrderStatus.PENDING)
            if order.side == Side.SELL and order.price > quote.bid:
                return OrderResult(broker_order_id=str(uuid.uuid4()), status=OrderStatus.PENDING)
            fill_price = order.price

        notional = fill_price * order.quantity
        commission = notional * self.commission_rate

        if order.side == Side.BUY:
            cost = notional + commission
            if cost > self._cash:
                log.warning("paper_insufficient_cash", needed=cost, have=self._cash)
                return OrderResult(broker_order_id="", status=OrderStatus.REJECTED)
            self._cash -= cost
            existing = self._positions.get(order.symbol)
            if existing:
                new_qty = existing.quantity + order.quantity
                new_avg = (existing.avg_price * existing.quantity + fill_price * order.quantity) / new_qty
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, quantity=new_qty, avg_price=new_avg, current_price=fill_price,
                )
            else:
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, quantity=order.quantity, avg_price=fill_price, current_price=fill_price,
                )
        else:
            existing = self._positions.get(order.symbol)
            if not existing or existing.quantity < order.quantity:
                log.warning("paper_no_position", symbol=order.symbol, qty=order.quantity)
                return OrderResult(broker_order_id="", status=OrderStatus.REJECTED)
            tax = notional * self.sell_tax_rate
            proceeds = notional - commission - tax
            self._cash += proceeds
            new_qty = existing.quantity - order.quantity
            if new_qty == 0:
                del self._positions[order.symbol]
            else:
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, quantity=new_qty, avg_price=existing.avg_price, current_price=fill_price,
                )

        return OrderResult(
            broker_order_id=str(uuid.uuid4()),
            status=OrderStatus.FILLED,
            filled_qty=order.quantity,
            avg_fill_price=fill_price,
        )

    def cancel(self, broker_order_id: str) -> bool:
        # paper 어댑터는 즉시 체결 가정 → 취소 대상 없음 (PENDING 처리 미구현)
        return True

    def positions(self) -> list[Position]:
        # 현재가 갱신
        out = []
        for sym, p in list(self._positions.items()):
            try:
                last = self._quote_source.quote(sym).last
            except Exception:
                last = p.current_price
            updated = Position(symbol=sym, quantity=p.quantity, avg_price=p.avg_price, current_price=last)
            self._positions[sym] = updated
            out.append(updated)
        return out

    def balance(self) -> Balance:
        positions_value = sum(p.current_price * p.quantity for p in self.positions())
        return Balance(
            cash=self._cash,
            positions_value=positions_value,
            total_equity=self._cash + positions_value,
        )

    def quote(self, symbol: str) -> Quote:
        return self._quote_source.quote(symbol)

    async def subscribe(self, symbols: list[str]) -> AsyncIterator[Tick]:
        async for tick in self._quote_source.subscribe(symbols):
            yield tick

    def is_tradeable(self, symbol: str) -> bool:
        return self._quote_source.is_tradeable(symbol)
