"""변동성 돌파 전략 (Larry Williams).

진입: 당일 시가 + (전일 고가 - 전일 저가) × K 돌파 시 매수
청산: 익일 시가 매도 또는 진입가 -7% 손절
필터: 5MA > 20MA (추세 상승 중일 때만)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

import pandas as pd

from prog_stock.brokers.port import Position
from prog_stock.strategies.base import Action, Signal, Strategy


@dataclass
class VolatilityBreakoutConfig:
    k: float = 0.5
    hard_stop_loss: float = -0.07


class VolatilityBreakoutStrategy(Strategy):
    name = "volatility_breakout"

    def __init__(self, cfg: VolatilityBreakoutConfig | None = None) -> None:
        self.cfg = cfg or VolatilityBreakoutConfig()

    def select_candidates(
        self,
        today: date,
        universe: pd.DataFrame,
        history_loader: Callable[[str], pd.DataFrame],
        fundamentals: pd.DataFrame,
        market_index: pd.DataFrame,
    ) -> list[Signal]:
        signals = []
        for sym in universe["symbol"].tolist():
            df = history_loader(sym)
            if df.empty:
                continue
            df_t = df[df["date"] <= today].sort_values("date").copy()
            if len(df_t) < 25:
                continue
            df_t["ma5"] = df_t["close"].rolling(5).mean()
            df_t["ma20"] = df_t["close"].rolling(20).mean()

            yesterday = df_t.iloc[-2]
            today_row = df_t.iloc[-1]
            if pd.isna(today_row["ma5"]) or pd.isna(today_row["ma20"]):
                continue
            if today_row["ma5"] <= today_row["ma20"]:
                continue

            range_yest = float(yesterday["high"]) - float(yesterday["low"])
            target = float(today_row["open"]) + range_yest * self.cfg.k
            if float(today_row["high"]) >= target:
                signals.append(Signal(sym, Action.BUY, "VOL_BREAKOUT", target))
        return signals

    def evaluate_holdings(
        self,
        today: date,
        positions: list[Position],
        history_loader: Callable[[str], pd.DataFrame],
        fundamentals: pd.DataFrame,
    ) -> list[Signal]:
        # 변동성 돌파는 1일 보유 — 다음날 시가 매도
        out = []
        for pos in positions:
            df = history_loader(pos.symbol)
            if df.empty:
                out.append(Signal(pos.symbol, Action.HOLD, "no_history"))
                continue
            row = df[df["date"] <= today].iloc[-1]
            ret = (row["close"] - pos.avg_price) / pos.avg_price
            if ret <= self.cfg.hard_stop_loss:
                out.append(Signal(pos.symbol, Action.SELL, "STOP_LOSS"))
            else:
                out.append(Signal(pos.symbol, Action.SELL, "NEXT_OPEN_EXIT"))
        return out
