"""Run mode 스위치 + Promotion gate.

backtest: 과거 데이터 시뮬
dry_run: 실시간 KIS 피드 + 가상 주문장부, 전략 X
paper: 가상 자본 + 전략 ON
live: 실거래 (게이트 통과 후만)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from prog_stock.config import RunMode


@dataclass
class PromotionCriteria:
    paper_min_days: int = 90
    paper_min_uptime_ratio: float = 0.95
    max_slippage_drift_pct: float = 0.20
    min_sharpe: float = 0.8
    max_mdd: float = -0.20


@dataclass
class PromotionResult:
    eligible: bool
    reasons: list[str]


def evaluate_promotion(
    paper_equity_curve: pd.DataFrame,
    paper_trades: pd.DataFrame,
    backtest_summary: dict,
    today: date,
    criteria: PromotionCriteria | None = None,
) -> PromotionResult:
    c = criteria or PromotionCriteria()
    reasons: list[str] = []

    if paper_equity_curve.empty:
        return PromotionResult(False, ["no_paper_data"])

    span = (today - paper_equity_curve["date"].min()).days
    if span < c.paper_min_days:
        reasons.append(f"paper_span_too_short:{span}d")

    daily = paper_equity_curve["return"].dropna()
    if len(daily) < 30:
        reasons.append("insufficient_paper_returns")
    else:
        std = float(daily.std())
        # std가 0 또는 floating-point 노이즈 수준이면 의미 있는 변동성 부족 → 자격 미달
        if std < 1e-6:
            reasons.append("paper_volatility_too_low_unrealistic")
            sharpe = 0.0
        else:
            sharpe = (float(daily.mean()) / std) * (252 ** 0.5)
            if sharpe < c.min_sharpe:
                reasons.append(f"paper_sharpe_low:{sharpe:.2f}")
        rolling_max = paper_equity_curve["equity"].cummax()
        mdd = float(((paper_equity_curve["equity"] - rolling_max) / rolling_max).min())
        if mdd < c.max_mdd:
            reasons.append(f"paper_mdd_breach:{mdd:.2%}")

    bt_pf = backtest_summary.get("profit_factor")
    if isinstance(bt_pf, float) and not paper_trades.empty:
        wins = paper_trades.loc[paper_trades["net_pnl"] > 0, "net_pnl"].sum()
        losses = abs(paper_trades.loc[paper_trades["net_pnl"] < 0, "net_pnl"].sum())
        live_pf = wins / losses if losses > 0 else float("inf")
        if abs(live_pf - bt_pf) / max(bt_pf, 1e-6) > c.max_slippage_drift_pct:
            reasons.append(f"profit_factor_drift:{live_pf:.2f}_vs_{bt_pf:.2f}")

    return PromotionResult(eligible=not reasons, reasons=reasons)


def can_promote(mode: RunMode) -> bool:
    return mode == RunMode.PAPER  # paper에서만 live로 승격 평가
