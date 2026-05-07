"""RiskGuard 게이트 테스트 — 모든 거부 분기 커버."""
from __future__ import annotations

from datetime import datetime

import pytest

from prog_stock.brokers.port import Order, OrderType, Side
from prog_stock.risk.guard import Decision, GuardConfig, GuardContext, RiskGuard


def _ctx(**overrides) -> GuardContext:
    base = GuardContext(
        now=datetime(2026, 5, 7, 10, 0),
        equity=10_000_000,
        cash=5_000_000,
        daily_pnl_pct=0.0,
        drawdown_from_peak=0.0,
        open_positions_count=0,
        pending_orders_count=0,
        recent_balance_change_pct=0.0,
        market_filter_off=False,
        kill_switch_engaged=False,
        in_call_auction=False,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _buy(symbol: str = "005930", qty: int = 10, price: float | None = 70000,
         otype: OrderType = OrderType.LIMIT) -> Order:
    return Order(
        symbol=symbol, side=Side.BUY, order_type=otype, quantity=qty,
        price=price, idempotency_key="t", reason="ENTRY",
    )


def _sell(symbol: str = "005930", qty: int = 10, price: float | None = 70000,
          otype: OrderType = OrderType.LIMIT) -> Order:
    return Order(
        symbol=symbol, side=Side.SELL, order_type=otype, quantity=qty,
        price=price, idempotency_key="t", reason="STOP_LOSS",
    )


class TestRiskGuard:
    def setup_method(self):
        self.guard = RiskGuard(GuardConfig())

    # 시스템 정지
    def test_kill_switch_rejects(self):
        res = self.guard.evaluate(_buy(), _ctx(kill_switch_engaged=True))
        assert res.decision == Decision.REJECT
        assert "kill" in res.reason

    def test_mdd_breach_stops(self):
        res = self.guard.evaluate(_buy(), _ctx(drawdown_from_peak=-0.16))
        assert res.decision == Decision.REJECT_AND_STOP

    def test_daily_loss_breach_rejects(self):
        res = self.guard.evaluate(_buy(), _ctx(daily_pnl_pct=-0.04))
        assert res.decision == Decision.REJECT

    # 이상치
    def test_balance_anomaly_halts(self):
        res = self.guard.evaluate(_buy(), _ctx(recent_balance_change_pct=0.06))
        assert res.decision == Decision.REJECT_AND_HALT

    def test_too_many_pending_halts(self):
        res = self.guard.evaluate(_buy(), _ctx(pending_orders_count=10))
        assert res.decision == Decision.REJECT_AND_HALT

    # 동시호가
    def test_market_order_in_call_auction_rejected(self):
        res = self.guard.evaluate(_buy(otype=OrderType.MARKET, price=None),
                                   _ctx(in_call_auction=True))
        assert res.decision == Decision.REJECT
        assert "call_auction" in res.reason

    def test_limit_in_call_auction_ok(self):
        res = self.guard.evaluate(_buy(), _ctx(in_call_auction=True))
        assert res.approved

    # 종목 상태
    def test_not_tradeable_rejected(self):
        ctx = _ctx()
        ctx.is_tradeable_map["005930"] = False
        res = self.guard.evaluate(_buy(), ctx)
        assert res.decision == Decision.REJECT
        assert "not_tradeable" in res.reason

    def test_locked_limit_sell_queued_for_next_open(self):
        ctx = _ctx()
        ctx.locked_limit_map["005930"] = True
        res = self.guard.evaluate(_sell(), ctx)
        assert res.decision == Decision.QUEUE_NEXT_OPEN

    def test_locked_limit_buy_rejected(self):
        ctx = _ctx()
        ctx.locked_limit_map["005930"] = True
        res = self.guard.evaluate(_buy(), ctx)
        assert res.decision == Decision.REJECT

    # 매수 룰
    def test_market_filter_off_blocks_buy(self):
        res = self.guard.evaluate(_buy(), _ctx(market_filter_off=True))
        assert res.decision == Decision.REJECT
        assert "market_filter" in res.reason

    def test_market_filter_off_allows_sell(self):
        ctx = _ctx(market_filter_off=True)
        res = self.guard.evaluate(_sell(), ctx)
        assert res.approved

    def test_cooldown_blocks_buy(self):
        ctx = _ctx()
        ctx.cooldown_symbols.add("005930")
        res = self.guard.evaluate(_buy(), ctx)
        assert res.decision == Decision.REJECT
        assert "cooldown" in res.reason

    def test_max_positions_blocks_buy(self):
        res = self.guard.evaluate(_buy(), _ctx(open_positions_count=5))
        assert res.decision == Decision.REJECT

    def test_insufficient_cash_blocks_buy(self):
        res = self.guard.evaluate(_buy(qty=1000, price=70000), _ctx(cash=100_000))
        assert res.decision == Decision.REJECT
        assert "cash" in res.reason

    def test_position_cap_blocks_buy(self):
        # equity 1,000만 × 25% = 250만. 70,000 × 100주 = 700만 > cap
        res = self.guard.evaluate(_buy(qty=100, price=70000), _ctx(cash=10_000_000))
        assert res.decision == Decision.REJECT
        assert "cap" in res.reason

    def test_normal_buy_approved(self):
        res = self.guard.evaluate(_buy(qty=30, price=70000), _ctx())
        assert res.approved


class TestGuardEdgeCases:
    def setup_method(self):
        self.guard = RiskGuard(GuardConfig())

    def test_stop_loss_sell_bypasses_market_filter(self):
        """시장 필터 OFF여도 손절 매도는 허용 (보유 종목 개별 룰)."""
        res = self.guard.evaluate(_sell(), _ctx(market_filter_off=True))
        assert res.approved

    def test_exact_limit_thresholds(self):
        # 정확히 -15% 손익은 차단되어야 함
        res = self.guard.evaluate(_buy(), _ctx(drawdown_from_peak=-0.15))
        assert res.decision == Decision.REJECT_AND_STOP

        # 정확히 -3% 일일 손익도 차단
        res = self.guard.evaluate(_buy(), _ctx(daily_pnl_pct=-0.03))
        assert res.decision == Decision.REJECT
