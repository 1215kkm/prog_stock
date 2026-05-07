"""포지션 사이징 — 자본 1.5% 리스크 기반.

position_size_krw = (equity × risk_per_trade) / abs(stop_loss_pct)
                  ≒ equity × 21.4%   (risk=1.5%, stop=-7%)

추가 캡: max_position_pct (예: 자본의 25%).
"""
from __future__ import annotations

import math


def calc_position_size_krw(
    equity: float,
    risk_per_trade: float,
    stop_loss_pct: float,
    max_position_pct: float,
) -> float:
    if risk_per_trade <= 0 or stop_loss_pct >= 0:
        raise ValueError("risk_per_trade > 0, stop_loss_pct < 0 expected")
    risk_based = (equity * risk_per_trade) / abs(stop_loss_pct)
    cap = equity * max_position_pct
    return float(min(risk_based, cap))


def calc_quantity(
    equity: float,
    price: float,
    risk_per_trade: float,
    stop_loss_pct: float,
    max_position_pct: float,
) -> int:
    if price <= 0:
        return 0
    target_krw = calc_position_size_krw(
        equity=equity,
        risk_per_trade=risk_per_trade,
        stop_loss_pct=stop_loss_pct,
        max_position_pct=max_position_pct,
    )
    return int(math.floor(target_krw / price))
