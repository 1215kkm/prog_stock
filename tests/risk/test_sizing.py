"""포지션 사이징 테스트 — 04_risk_management.md 수치 검증."""
from __future__ import annotations

import pytest

from prog_stock.risk.sizing import calc_position_size_krw, calc_quantity


class TestPositionSizing:
    def test_risk_based_with_default_params(self):
        # equity 1,000만 × 1.5% / 7% ≈ 214만원
        size = calc_position_size_krw(
            equity=10_000_000, risk_per_trade=0.015, stop_loss_pct=-0.07,
            max_position_pct=0.25,
        )
        assert size == pytest.approx(2_142_857.14, rel=1e-4)

    def test_max_position_cap_kicks_in_with_loose_stop(self):
        # 손절폭이 -3%처럼 작으면 risk_based가 cap보다 크다 → cap 적용
        size = calc_position_size_krw(
            equity=10_000_000, risk_per_trade=0.015, stop_loss_pct=-0.03,
            max_position_pct=0.25,
        )
        # risk_based = 1,500만 × 0.015 / 0.03 = 500만 → cap 250만
        assert size == 2_500_000.0

    def test_quantity_floored(self):
        qty = calc_quantity(
            equity=10_000_000, price=70_000,
            risk_per_trade=0.015, stop_loss_pct=-0.07, max_position_pct=0.25,
        )
        # 2,142,857 / 70,000 = 30.6 → 30주
        assert qty == 30

    def test_zero_price_returns_zero(self):
        qty = calc_quantity(
            equity=10_000_000, price=0.0,
            risk_per_trade=0.015, stop_loss_pct=-0.07, max_position_pct=0.25,
        )
        assert qty == 0

    def test_invalid_inputs_raise(self):
        with pytest.raises(ValueError):
            calc_position_size_krw(
                equity=10_000_000, risk_per_trade=-0.01, stop_loss_pct=-0.07,
                max_position_pct=0.25,
            )
        with pytest.raises(ValueError):
            calc_position_size_krw(
                equity=10_000_000, risk_per_trade=0.015, stop_loss_pct=0.07,
                max_position_pct=0.25,
            )
