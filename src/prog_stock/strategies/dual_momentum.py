"""듀얼 모멘텀 전략 (보조).

CAN SLIM의 펀더멘털 필터 없이 가격 모멘텀만 사용.
강세장에서는 CAN SLIM과 비슷한 성과, 약세장에서 더 빠른 자본 보전.

룰:
- 절대 모멘텀: 12개월 수익률 > 0
- 상대 모멘텀: 코스피200 대비 6개월 상위 30%
- 진입: 두 조건 만족 + 50MA 위
- 청산: 50MA 이탈 또는 절대 모멘텀 < 0 또는 -7% 손절
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

import pandas as pd

from prog_stock.brokers.port import Position
from prog_stock.strategies.base import Action, Signal, Strategy


@dataclass
class DualMomentumConfig:
    abs_momentum_lookback: int = 252       # 12개월
    rel_momentum_lookback: int = 126       # 6개월
    rs_top_pct: float = 0.30
    hard_stop_loss: float = -0.07


def _annual_return(df: pd.DataFrame, lookback: int, today: date) -> float | None:
    df = df[df["date"] <= today].tail(lookback + 1)
    if len(df) < lookback + 1:
        return None
    return float(df.iloc[-1]["close"] / df.iloc[0]["close"] - 1)


class DualMomentumStrategy(Strategy):
    name = "dual_momentum"

    def __init__(self, cfg: DualMomentumConfig | None = None) -> None:
        self.cfg = cfg or DualMomentumConfig()

    def select_candidates(
        self,
        today: date,
        universe: pd.DataFrame,
        history_loader: Callable[[str], pd.DataFrame],
        fundamentals: pd.DataFrame,
        market_index: pd.DataFrame,
    ) -> list[Signal]:
        # 시장 절대 모멘텀 — 코스피200 12M 수익률 음수면 신규 매수 X
        if not market_index.empty:
            kr = _annual_return(market_index, self.cfg.abs_momentum_lookback, today)
            if kr is None or kr <= 0:
                return []

        rs_scores: dict[str, tuple[float, float]] = {}  # symbol -> (close, rs)
        for sym in universe["symbol"].tolist():
            df = history_loader(sym)
            if df.empty:
                continue
            abs_r = _annual_return(df, self.cfg.abs_momentum_lookback, today)
            rel_r = _annual_return(df, self.cfg.rel_momentum_lookback, today)
            if abs_r is None or rel_r is None or abs_r <= 0 or rel_r <= 0:
                continue
            df_t = df[df["date"] <= today].sort_values("date").copy()
            df_t["ma50"] = df_t["close"].rolling(50).mean()
            row = df_t.iloc[-1]
            if pd.isna(row["ma50"]) or row["close"] <= row["ma50"]:
                continue
            rs_scores[sym] = (float(row["close"]), rel_r)

        if not rs_scores:
            return []

        cutoff = pd.Series([v[1] for v in rs_scores.values()]).quantile(1 - self.cfg.rs_top_pct)
        signals = []
        for sym, (price, rs) in rs_scores.items():
            if rs >= cutoff:
                signals.append(Signal(sym, Action.BUY, "DUAL_MOMENTUM", price))
        return signals

    def evaluate_holdings(
        self,
        today: date,
        positions: list[Position],
        history_loader: Callable[[str], pd.DataFrame],
        fundamentals: pd.DataFrame,
    ) -> list[Signal]:
        out = []
        for pos in positions:
            df = history_loader(pos.symbol)
            if df.empty:
                out.append(Signal(pos.symbol, Action.HOLD, "no_history"))
                continue
            df_t = df[df["date"] <= today].sort_values("date").copy()
            if df_t.empty:
                continue
            df_t["ma50"] = df_t["close"].rolling(50).mean()
            row = df_t.iloc[-1]
            ret = (row["close"] - pos.avg_price) / pos.avg_price
            if ret <= self.cfg.hard_stop_loss:
                out.append(Signal(pos.symbol, Action.SELL, "STOP_LOSS"))
                continue
            abs_r = _annual_return(df, self.cfg.abs_momentum_lookback, today)
            if abs_r is not None and abs_r <= 0:
                out.append(Signal(pos.symbol, Action.SELL, "ABS_MOMENTUM_BREAK"))
                continue
            if pd.notna(row["ma50"]) and row["close"] < row["ma50"]:
                out.append(Signal(pos.symbol, Action.SELL, "BELOW_50MA"))
                continue
            out.append(Signal(pos.symbol, Action.HOLD, "momentum_intact"))
        return out
