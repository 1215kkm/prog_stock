"""파라미터 자동 조정 경계.

자율 에이전트는 이 경계 안에서만 변경 가능. 불변 룰(CLAUDE.md)은 코드로 잠금.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bounds:
    """수치 범위. None이면 변경 금지."""
    min: float | None
    max: float | None
    step: float | None = None

    def clamp(self, value: float) -> float:
        if self.min is not None:
            value = max(value, self.min)
        if self.max is not None:
            value = min(value, self.max)
        return value

    def valid(self, value: float) -> bool:
        if self.min is not None and value < self.min:
            return False
        if self.max is not None and value > self.max:
            return False
        return True


# 자율 에이전트가 변경 가능한 파라미터의 허용 범위.
# 이 값은 절대 약화 방향으로 변경 금지 (예: hard_stop_loss.min을 -0.20으로 늘리지 말 것).
PARAM_BOUNDS: dict[str, Bounds] = {
    # 손절 폭 (음수)
    "hard_stop_loss": Bounds(min=-0.10, max=-0.05),
    # 종목당 자본 리스크
    "risk_per_trade": Bounds(min=0.005, max=0.025),
    # 일일 손실 한도 (음수)
    "daily_loss_limit": Bounds(min=-0.05, max=-0.02),
    # 최대 낙폭 한도 (음수) — -15%보다 약하게 못 만듦
    "mdd_limit": Bounds(min=-0.20, max=-0.10),
    # 동시 보유 종목 수
    "max_positions": Bounds(min=3, max=7),
    # 단일 종목 자본 캡
    "max_position_pct": Bounds(min=0.15, max=0.30),
    # 펀더멘털 필터
    "min_op_income_yoy": Bounds(min=0.10, max=0.50),
    "rs_top_pct": Bounds(min=0.20, max=0.50),
    "breakout_volume_ratio": Bounds(min=1.2, max=2.5),
    # 트레일링
    "trailing_activate_pct": Bounds(min=0.10, max=0.30),
    "trailing_drop_pct": Bounds(min=0.05, max=0.15),
    # 카나리 / 쿨다운
    "cooldown_days": Bounds(min=10, max=60),
}


# 절대 변경 금지 — 룰 자체 (불변 룰 6가지)
INVARIANT_RULES = (
    "fundamental_breakdown_immediate_exit",   # 펀더멘털 꺾임 즉시 청산
    "no_averaging_down",                       # 물타기 금지
    "no_market_order_in_call_auction",         # 동시호가 시장가 금지
    "no_bottom_prediction",                    # 바닥 예측 금지
    "stop_loss_required",                      # 손절 룰 자체 존재
    "rebuy_cooldown_after_stop_loss",          # 손절 후 쿨다운
)
