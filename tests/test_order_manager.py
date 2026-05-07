"""OrderManager — TokenBucket / 멱등성 / 게이트 통합 테스트."""
from __future__ import annotations

import time
from datetime import datetime
from typing import AsyncIterator

import pytest

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
from prog_stock.execution.order_manager import (
    ManagerConfig,
    OrderManager,
    TokenBucket,
    make_idempotency_key,
)
from prog_stock.risk.guard import GuardConfig, GuardContext, RiskGuard
from prog_stock.storage.db import Database


class FakeBroker(BrokerPort):
    def __init__(self):
        self.orders: list[Order] = []

    def place_order(self, order: Order) -> OrderResult:
        self.orders.append(order)
        return OrderResult(
            broker_order_id=f"fake-{len(self.orders)}",
            status=OrderStatus.FILLED,
            filled_qty=order.quantity,
            avg_fill_price=order.price or 100.0,
        )

    def cancel(self, broker_order_id: str) -> bool:
        return True

    def positions(self) -> list[Position]:
        return []

    def balance(self) -> Balance:
        return Balance(cash=10_000_000, positions_value=0, total_equity=10_000_000)

    def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, bid=100, ask=101, last=100, volume=1000)

    async def subscribe(self, symbols):
        return
        yield  # type: ignore[unreachable]

    def is_tradeable(self, symbol: str) -> bool:
        return True


def _ctx(**overrides) -> GuardContext:
    base = GuardContext(
        now=datetime(2026, 5, 7, 10, 0),
        equity=10_000_000, cash=5_000_000,
        daily_pnl_pct=0.0, drawdown_from_peak=0.0,
        open_positions_count=0, pending_orders_count=0,
        recent_balance_change_pct=0.0,
        market_filter_off=False, kill_switch_engaged=False,
        in_call_auction=False,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


class TestTokenBucket:
    def test_first_consume_is_immediate(self):
        bucket = TokenBucket(rate_per_second=10)
        t0 = time.monotonic()
        bucket.consume(1)
        assert time.monotonic() - t0 < 0.01

    def test_burst_then_throttled(self):
        bucket = TokenBucket(rate_per_second=20)
        for _ in range(20):
            bucket.consume(1)
        # 20개 소진 후 1개 더는 ~50ms 대기
        t0 = time.monotonic()
        bucket.consume(1)
        elapsed = time.monotonic() - t0
        assert 0.03 < elapsed < 0.2


class TestIdempotency:
    def test_same_inputs_produce_same_key(self):
        ts = 1700000000000
        k1 = make_idempotency_key("005930", Side.BUY, "ENTRY", ts)
        k2 = make_idempotency_key("005930", Side.BUY, "ENTRY", ts)
        assert k1 == k2

    def test_different_timestamps_diverge(self):
        k1 = make_idempotency_key("005930", Side.BUY, "ENTRY", 1)
        k2 = make_idempotency_key("005930", Side.BUY, "ENTRY", 2)
        assert k1 != k2


class TestOrderManagerIntegration:
    def setup_method(self):
        self.broker = FakeBroker()
        self.guard = RiskGuard(GuardConfig())
        self.db = Database(__import__("pathlib").Path("/tmp/_om_test.db"))

    def test_approved_order_routes_to_broker(self, tmp_path):
        db = Database(tmp_path / "x.db")
        om = OrderManager(self.broker, self.guard, db,
                          ManagerConfig(rate_per_second=100, mode="test"))
        gres, res = om.submit(
            symbol="005930", side=Side.BUY, quantity=10,
            order_type=OrderType.LIMIT, price=70_000,
            reason="ENTRY", ctx=_ctx(),
        )
        assert gres.approved
        assert res.status == OrderStatus.FILLED
        assert len(self.broker.orders) == 1

    def test_rejected_order_never_reaches_broker(self, tmp_path):
        db = Database(tmp_path / "y.db")
        om = OrderManager(self.broker, self.guard, db,
                          ManagerConfig(rate_per_second=100, mode="test"))
        gres, res = om.submit(
            symbol="005930", side=Side.BUY, quantity=10,
            order_type=OrderType.MARKET, price=None,
            reason="ENTRY", ctx=_ctx(in_call_auction=True),
        )
        assert not gres.approved
        assert res is None
        assert len(self.broker.orders) == 0

    def test_rejection_logged_to_events(self, tmp_path):
        db = Database(tmp_path / "z.db")
        om = OrderManager(self.broker, self.guard, db,
                          ManagerConfig(rate_per_second=100, mode="test"))
        om.submit(
            symbol="005930", side=Side.BUY, quantity=10,
            order_type=OrderType.MARKET, price=None,
            reason="ENTRY", ctx=_ctx(kill_switch_engaged=True),
        )
        with db.connect() as conn:
            rows = list(conn.execute("SELECT * FROM system_events WHERE kind = 'GUARD_REJECT'"))
        assert len(rows) == 1
