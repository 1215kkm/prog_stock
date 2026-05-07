"""주문 매니저 — 게이트 통과 / 레이트리밋 / 멱등성 / 재시도.

KIS API 초당 20호출 제한을 토큰버킷으로 관수.
멱등성 키는 (symbol, side, intent_timestamp) 기반.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass

import structlog

from prog_stock.brokers.port import (
    BrokerPort,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
)
from prog_stock.risk.guard import Decision, GuardContext, GuardResult, RiskGuard
from prog_stock.storage.db import Database

log = structlog.get_logger(__name__)


class TokenBucket:
    """초당 N개 토큰 버킷. KIS 실거래 20/s, 모의 2/s."""

    def __init__(self, rate_per_second: float) -> None:
        self.rate = rate_per_second
        self.tokens = rate_per_second
        self.last = time.monotonic()

    def consume(self, n: int = 1) -> None:
        while True:
            now = time.monotonic()
            elapsed = now - self.last
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last = now
            if self.tokens >= n:
                self.tokens -= n
                return
            time.sleep((n - self.tokens) / self.rate)


@dataclass
class ManagerConfig:
    rate_per_second: float = 18.0  # 안전 마진(20 미만)
    mode: str = "paper"


def make_idempotency_key(symbol: str, side: Side, reason: str, ts_ms: int) -> str:
    raw = f"{symbol}|{side.value}|{reason}|{ts_ms}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class OrderManager:
    def __init__(
        self,
        broker: BrokerPort,
        guard: RiskGuard,
        db: Database,
        cfg: ManagerConfig | None = None,
    ) -> None:
        self.broker = broker
        self.guard = guard
        self.db = db
        self.cfg = cfg or ManagerConfig()
        self.bucket = TokenBucket(self.cfg.rate_per_second)

    def submit(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        order_type: OrderType,
        price: float | None,
        reason: str,
        ctx: GuardContext,
    ) -> tuple[GuardResult, OrderResult | None]:
        if quantity <= 0:
            return GuardResult(Decision.REJECT, "non_positive_qty"), None

        idem = make_idempotency_key(symbol, side, reason, int(time.time() * 1000))
        order = Order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            idempotency_key=idem,
            reason=reason,
        )

        gres = self.guard.evaluate(order, ctx)
        if not gres.approved:
            self._record_rejection(order, gres)
            return gres, None

        self.bucket.consume(1)
        result = self.broker.place_order(order)
        self._record_order(order, result)
        return gres, result

    def submit_with_market_fallback(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        limit_price: float,
        reason: str,
        ctx: GuardContext,
        slippage_buffer_pct: float = 0.005,
    ) -> tuple[GuardResult, OrderResult | None]:
        """지정가 우선, 미체결 시 시장가 폴백. 단 동시호가 시간엔 시장가 금지."""
        gres, res = self.submit(
            symbol=symbol, side=side, quantity=quantity,
            order_type=OrderType.LIMIT, price=limit_price,
            reason=reason, ctx=ctx,
        )
        if not gres.approved or res is None:
            return gres, res

        if res.status in (OrderStatus.FILLED, OrderStatus.PARTIAL):
            return gres, res

        # 미체결: 시장가 폴백 (동시호가 가드는 guard가 처리)
        return self.submit(
            symbol=symbol, side=side, quantity=quantity,
            order_type=OrderType.MARKET, price=None,
            reason=f"{reason}_FALLBACK", ctx=ctx,
        )

    def _record_order(self, order: Order, res: OrderResult) -> None:
        from datetime import datetime as _dt

        with self.db.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO orders
                   (idempotency_key, broker_order_id, symbol, side, order_type, quantity, price,
                    status, submitted_at, filled_qty, avg_fill_price, reason, mode)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order.idempotency_key,
                    res.broker_order_id,
                    order.symbol,
                    order.side.value,
                    order.order_type.value,
                    order.quantity,
                    order.price,
                    res.status.value,
                    _dt.now().isoformat(timespec="seconds"),
                    res.filled_qty,
                    res.avg_fill_price,
                    order.reason,
                    self.cfg.mode,
                ),
            )

    def _record_rejection(self, order: Order, gres: GuardResult) -> None:
        self.db.log_event(
            "WARN",
            "GUARD_REJECT",
            f"{order.symbol} {order.side.value} qty={order.quantity} reason={gres.reason}",
            {"decision": gres.decision.value, "order_reason": order.reason},
        )
