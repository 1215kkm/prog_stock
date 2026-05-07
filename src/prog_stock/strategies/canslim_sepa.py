"""v1 전략 — 한국형 CAN SLIM + SEPA.

펀더멘털 필터(F1~F6) + 트렌드 템플릿(T1~T5) + 시장 필터(M) + 신고가 돌파 진입.
청산: -7% 손절 / 펀더멘털 꺾임 즉시 / 50MA 5일 이탈 / 200MA 즉시 이탈 / 트레일링 스탑.

세부 사양: docs/knowledge_base/01_strategy_canslim_sepa.md, 04_risk_management.md, CLAUDE.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

import numpy as np
import pandas as pd
import structlog

from prog_stock.brokers.port import Position
from prog_stock.data.fundamentals import passes_fundamental_filter, yoy_growth
from prog_stock.strategies.base import Action, Signal, Strategy

log = structlog.get_logger(__name__)


@dataclass
class CanslimSepaConfig:
    fundamental_quarters: int = 4
    min_op_income_yoy: float = 0.25
    rs_top_pct: float = 0.30
    breakout_volume_ratio: float = 1.5
    trailing_activate_pct: float = 0.20
    trailing_drop_pct: float = 0.10
    hard_stop_loss: float = -0.07
    consecutive_below_50ma_days: int = 5
    high_lookback_days: int = 252  # 52주


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """일봉에 50/150/200MA, 52주 고저, 거래량평균 부여."""
    df = df.sort_values("date").copy()
    df["ma50"] = df["close"].rolling(50).mean()
    df["ma150"] = df["close"].rolling(150).mean()
    df["ma200"] = df["close"].rolling(200).mean()
    df["high_252"] = df["close"].rolling(252).max()
    df["low_252"] = df["close"].rolling(252).min()
    df["volume_ma20"] = df["volume"].rolling(20).mean()
    df["ma200_slope_1m"] = df["ma200"].diff(20)
    return df


def _trend_template_pass(row: pd.Series) -> bool:
    """SEPA Trend Template 8조건 통과 여부."""
    if any(pd.isna(row[c]) for c in ("ma50", "ma150", "ma200", "high_252", "low_252", "ma200_slope_1m")):
        return False
    close = row["close"]
    return bool(
        close > row["ma150"] > row["ma200"]
        and row["ma50"] > row["ma150"] > row["ma200"]
        and close > row["ma50"]
        and row["ma200_slope_1m"] > 0
        and close >= row["low_252"] * 1.30
        and close >= row["high_252"] * 0.75
    )


def _market_filter_on(market_index: pd.DataFrame, today: date) -> bool:
    """KOSPI200 > 200MA?"""
    if market_index.empty:
        return False
    df = market_index.sort_values("date").copy()
    df["ma200"] = df["close"].rolling(200).mean()
    df = df[df["date"] <= today]
    if df.empty or pd.isna(df.iloc[-1]["ma200"]):
        return False
    return bool(df.iloc[-1]["close"] > df.iloc[-1]["ma200"])


def _relative_strength(df: pd.DataFrame, today: date, lookback: int = 126) -> float:
    df = df[df["date"] <= today].sort_values("date").tail(lookback + 1)
    if len(df) < lookback + 1:
        return float("nan")
    return float(df.iloc[-1]["close"] / df.iloc[0]["close"] - 1)


class CanslimSepaStrategy(Strategy):
    name = "canslim_sepa"

    def __init__(self, cfg: CanslimSepaConfig | None = None) -> None:
        self.cfg = cfg or CanslimSepaConfig()

    def select_candidates(
        self,
        today: date,
        universe: pd.DataFrame,
        history_loader: Callable[[str], pd.DataFrame],
        fundamentals: pd.DataFrame,
        market_index: pd.DataFrame,
    ) -> list[Signal]:
        if not _market_filter_on(market_index, today):
            log.info("market_filter_off")
            return []

        fund_growth = yoy_growth(fundamentals)

        rs_scores: dict[str, float] = {}
        candidates: list[tuple[str, pd.Series, pd.DataFrame]] = []

        for sym in universe["symbol"].tolist():
            if not passes_fundamental_filter(
                fund_growth, sym, today,
                quarters=self.cfg.fundamental_quarters,
                min_op_income_growth_yoy=self.cfg.min_op_income_yoy,
            ):
                continue
            df = history_loader(sym)
            if df.empty or len(df) < 252:
                continue
            df = _compute_indicators(df)
            df_today = df[df["date"] <= today]
            if df_today.empty:
                continue
            row = df_today.iloc[-1]
            if not _trend_template_pass(row):
                continue
            rs = _relative_strength(df, today)
            if np.isnan(rs):
                continue
            rs_scores[sym] = rs
            candidates.append((sym, row, df_today))

        if not candidates:
            return []

        # 상위 RS 30% 컷
        cutoff = pd.Series(rs_scores).quantile(1 - self.cfg.rs_top_pct)
        signals: list[Signal] = []
        for sym, row, df_today in candidates:
            if rs_scores[sym] < cutoff:
                continue
            # 신고가 돌파 + 거래량 1.5배
            recent_high = df_today.iloc[-2]["high_252"] if len(df_today) >= 2 else row["high_252"]
            volume_ok = pd.notna(row["volume_ma20"]) and row["volume"] >= row["volume_ma20"] * self.cfg.breakout_volume_ratio
            if row["close"] >= recent_high and volume_ok:
                signals.append(
                    Signal(symbol=sym, action=Action.BUY, reason="BREAKOUT", target_price=float(row["close"]))
                )
        return signals

    def evaluate_holdings(
        self,
        today: date,
        positions: list[Position],
        history_loader: Callable[[str], pd.DataFrame],
        fundamentals: pd.DataFrame,
    ) -> list[Signal]:
        out: list[Signal] = []
        fund_growth = yoy_growth(fundamentals)

        for pos in positions:
            df = history_loader(pos.symbol)
            if df.empty:
                out.append(Signal(pos.symbol, Action.HOLD, "no_history"))
                continue
            df = _compute_indicators(df)
            df_today = df[df["date"] <= today]
            if df_today.empty:
                continue
            row = df_today.iloc[-1]
            close = float(row["close"])
            ret = (close - pos.avg_price) / pos.avg_price

            # 1. 하드 손절 -7%
            if ret <= self.cfg.hard_stop_loss:
                out.append(Signal(pos.symbol, Action.SELL, "STOP_LOSS"))
                continue

            # 2. 펀더멘털 꺾임 (가장 최신 분기에서 매출 또는 영업이익 YoY 마이너스)
            sym_fund = fund_growth[fund_growth["symbol"] == pos.symbol].sort_values(["year", "quarter"])
            if not sym_fund.empty:
                last = sym_fund.iloc[-1]
                if (pd.notna(last["revenue_yoy"]) and last["revenue_yoy"] < 0) or (
                    pd.notna(last["op_income_yoy"]) and last["op_income_yoy"] < 0
                ):
                    out.append(Signal(pos.symbol, Action.SELL, "FUNDAMENTAL_BREAK"))
                    continue

            # 3. 추세 이탈
            if pd.notna(row["ma200"]) and close < row["ma200"]:
                out.append(Signal(pos.symbol, Action.SELL, "BELOW_200MA"))
                continue
            below_50_streak = (
                df_today.tail(self.cfg.consecutive_below_50ma_days)["close"]
                < df_today.tail(self.cfg.consecutive_below_50ma_days)["ma50"]
            ).sum()
            if below_50_streak >= self.cfg.consecutive_below_50ma_days:
                out.append(Signal(pos.symbol, Action.SELL, "BELOW_50MA_STREAK"))
                continue

            # 4. 트레일링 스탑
            if ret >= self.cfg.trailing_activate_pct:
                peak = df_today[df_today["date"] >= df_today["date"].max() - pd.Timedelta(days=120)]["close"].max()
                if close <= peak * (1 - self.cfg.trailing_drop_pct):
                    out.append(Signal(pos.symbol, Action.SELL, "TRAILING_STOP"))
                    continue

            out.append(Signal(pos.symbol, Action.HOLD, "trend_intact"))
        return out
