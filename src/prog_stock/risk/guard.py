"""주문 게이트.

모든 신규/청산 주문은 이 게이트를 통과해야 한다.
04_risk_management.md의 룰을 코드화.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from prog_stock.brokers.port import Order, OrderType, Side


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REJECT_AND_HALT = "REJECT_AND_HALT"
    REJECT_AND_STOP = "REJECT_AND_STOP"
    QUEUE_NEXT_OPEN = "QUEUE_NEXT_OPEN"


@dataclass
class GuardContext:
    now: datetime
    equity: float
    cash: float
    daily_pnl_pct: float
    drawdown_from_peak: float
    open_positions_count: int
    pending_orders_count: int
    recent_balance_change_pct: float
    market_filter_off: bool       # KOSPI200 < 200MA
    kill_switch_engaged: bool
    in_call_auction: bool
    is_tradeable_map: dict[str, bool] = field(default_factory=dict)
    locked_limit_map: dict[str, bool] = field(default_factory=dict)
    cooldown_symbols: set[str] = field(default_factory=set)

    def is_tradeable(self, symbol: str) -> bool:
        return self.is_tradeable_map.get(symbol, True)

    def is_locked_limit(self, symbol: str) -> bool:
        return self.locked_limit_map.get(symbol, False)

    def in_cooldown(self, symbol: str) -> bool:
        return symbol in self.cooldown_symbols


@dataclass
class GuardConfig:
    daily_loss_limit: float = -0.03
    mdd_limit: float = -0.15
    max_positions: int = 5
    max_position_pct: float = 0.25
    pending_orders_alarm: int = 10
    balance_change_alarm: float = 0.05


@dataclass
class GuardResult:
    decision: Decision
    reason: str = ""

    @property
    def approved(self) -> bool:
        return self.decision == Decision.APPROVE


class RiskGuard:
    def __init__(self, config: GuardConfig | None = None) -> None:
        self.cfg = config or GuardConfig()

    def evaluate(self, order: Order, ctx: GuardContext) -> GuardResult:
        # 시스템 정지 상태
        if ctx.kill_switch_engaged:
            return GuardResult(Decision.REJECT, "kill_switch_engaged")

        if ctx.drawdown_from_peak <= self.cfg.mdd_limit:
            return GuardResult(Decision.REJECT_AND_STOP, "mdd_limit_breach")

        if ctx.daily_pnl_pct <= self.cfg.daily_loss_limit:
            return GuardResult(Decision.REJECT, "daily_loss_limit_breach")

        # 이상치
        if ctx.recent_balance_change_pct > self.cfg.balance_change_alarm:
            return GuardResult(Decision.REJECT_AND_HALT, "balance_anomaly")
        if ctx.pending_orders_count >= self.cfg.pending_orders_alarm:
            return GuardResult(Decision.REJECT_AND_HALT, "too_many_pending")

        # 동시호가 시장가 금지
        if ctx.in_call_auction and order.order_type == OrderType.MARKET:
            return GuardResult(Decision.REJECT, "market_order_in_call_auction")

        # 종목 상태
        if not ctx.is_tradeable(order.symbol):
            return GuardResult(Decision.REJECT, "symbol_not_tradeable")

        # 상하한가 잠금: 매도면 다음날 시초가 큐, 매수면 거부
        if ctx.is_locked_limit(order.symbol):
            if order.side == Side.SELL:
                return GuardResult(Decision.QUEUE_NEXT_OPEN, "limit_locked")
            return GuardResult(Decision.REJECT, "buying_locked_limit_forbidden")

        # 매수 전용 룰
        if order.side == Side.BUY:
            if ctx.market_filter_off:
                return GuardResult(Decision.REJECT, "market_filter_off")
            if ctx.in_cooldown(order.symbol):
                return GuardResult(Decision.REJECT, "in_cooldown")
            if ctx.open_positions_count >= self.cfg.max_positions:
                return GuardResult(Decision.REJECT, "max_positions_reached")

            notional = (order.price or 0) * order.quantity
            if order.price is not None and notional > ctx.cash:
                return GuardResult(Decision.REJECT, "insufficient_cash")
            if order.price is not None and notional > ctx.equity * self.cfg.max_position_pct:
                return GuardResult(Decision.REJECT, "exceeds_position_cap")

        return GuardResult(Decision.APPROVE)
