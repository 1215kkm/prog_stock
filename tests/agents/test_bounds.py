"""파라미터 경계 검증 — 불변 룰 약화 차단."""
from __future__ import annotations

import pytest

from prog_stock.agents.bounds import PARAM_BOUNDS, Bounds


class TestBounds:
    def test_clamp_within_range(self):
        b = Bounds(min=-0.10, max=-0.05)
        assert b.clamp(-0.07) == -0.07

    def test_clamp_below_min(self):
        b = Bounds(min=-0.10, max=-0.05)
        assert b.clamp(-0.15) == -0.10

    def test_clamp_above_max(self):
        b = Bounds(min=-0.10, max=-0.05)
        assert b.clamp(-0.02) == -0.05

    def test_valid_inside(self):
        b = Bounds(min=-0.10, max=-0.05)
        assert b.valid(-0.07)

    def test_invalid_outside(self):
        b = Bounds(min=-0.10, max=-0.05)
        assert not b.valid(-0.15)
        assert not b.valid(-0.02)


class TestParamBounds:
    """PARAM_BOUNDS의 디폴트 값들이 안전 범위인지."""

    def test_stop_loss_never_weaker_than_minus_10(self):
        # 손절을 -15% 같은 약한 값으로 못 바꾸게
        assert PARAM_BOUNDS["hard_stop_loss"].min == -0.10
        assert PARAM_BOUNDS["hard_stop_loss"].max == -0.05

    def test_mdd_never_weaker_than_minus_20(self):
        # MDD를 -30% 같은 끔찍한 값으로 못 바꾸게
        assert PARAM_BOUNDS["mdd_limit"].min == -0.20

    def test_position_cap_never_above_30_pct(self):
        # 단일 종목 비중 30% 초과 금지
        assert PARAM_BOUNDS["max_position_pct"].max == 0.30

    def test_max_positions_capped(self):
        assert PARAM_BOUNDS["max_positions"].min == 3
        assert PARAM_BOUNDS["max_positions"].max == 7

    def test_cooldown_minimum_10_days(self):
        # 손절 후 쿨다운 10일 미만 금지
        assert PARAM_BOUNDS["cooldown_days"].min == 10

    def test_all_bounds_have_min_and_max(self):
        for name, b in PARAM_BOUNDS.items():
            assert b.min is not None and b.max is not None, f"{name} bounds incomplete"
            assert b.min <= b.max, f"{name} min > max"
