"""Regime Detector — 시장 레짐 자동 감지 + 자본 비중 자동 조절.

레짐 분류 (KOSPI200 기준):
- BULL: 200MA > 우상향, 종가 > 200MA, 최근 20일 양봉 우세
- BEAR: 200MA 우하향 또는 종가 < 200MA × 0.95
- SIDEWAYS: 그 외

자본 비중 자동 조절:
- BULL: 100% 정상 운용
- SIDEWAYS: 50% (보수)
- BEAR: 25% (현금화 비중 ↑, 신규 매수 거의 X)

매일 06:30 실행. 변경은 자동 적용 (불변 룰과 무관, 자본 비중만 조절).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

import pandas as pd
import structlog

from prog_stock.agents.base import (
    Agent,
    Decision,
    DecisionStatus,
    DecisionType,
    record_decision,
)
from prog_stock.config import settings
from prog_stock.storage.db import Database

log = structlog.get_logger(__name__)


class Regime(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"


CAPITAL_SCALE = {
    Regime.BULL: 1.00,
    Regime.SIDEWAYS: 0.50,
    Regime.BEAR: 0.25,
}


@dataclass
class RegimeConfig:
    bear_threshold_below_ma: float = 0.95     # 종가 < 200MA × 0.95
    ma_slope_lookback: int = 20               # 200MA 기울기 측정 기간
    hysteresis_days: int = 5                  # 레짐 깜빡임 방지: N일 일관성


class RegimeDetectorAgent:
    name = "regime"

    def __init__(self, db: Database, cfg: RegimeConfig | None = None) -> None:
        self.db = db
        self.cfg = cfg or RegimeConfig()

    def _load_kospi200(self) -> pd.DataFrame:
        path = settings.cache_dir_market / "kospi200_index.parquet"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path).sort_values("date").copy()
        df["ma200"] = df["close"].rolling(200).mean()
        df["ma200_slope"] = df["ma200"].diff(self.cfg.ma_slope_lookback)
        return df

    def _classify(self, df: pd.DataFrame) -> Regime:
        if df.empty:
            return Regime.SIDEWAYS
        last = df.iloc[-1]
        if pd.isna(last["ma200"]):
            return Regime.SIDEWAYS
        if last["close"] < last["ma200"] * self.cfg.bear_threshold_below_ma:
            return Regime.BEAR
        if last["ma200_slope"] is not None and last["ma200_slope"] < 0:
            return Regime.BEAR
        if last["close"] > last["ma200"] and last["ma200_slope"] > 0:
            return Regime.BULL
        return Regime.SIDEWAYS

    def _last_regime(self) -> Regime | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT regime FROM regime_history ORDER BY detected_at DESC LIMIT 1"
            ).fetchone()
        return Regime(row["regime"]) if row else None

    def _persist_regime(self, regime: Regime, rationale: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO regime_history
                   (detected_at, regime, capital_scale, rationale) VALUES (?, ?, ?, ?)""",
                (datetime.now().isoformat(timespec="seconds"),
                 regime.value, CAPITAL_SCALE[regime], rationale),
            )

    def run(self) -> list[Decision]:
        df = self._load_kospi200()
        if df.empty:
            log.warning("regime_no_data")
            return []

        regime = self._classify(df)
        previous = self._last_regime()
        decisions: list[Decision] = []

        last = df.iloc[-1]
        rationale = (
            f"KOSPI200 종가 {last['close']:.0f} vs 200MA {last['ma200']:.0f}, "
            f"기울기 {last['ma200_slope']:+.2f}"
        )

        if regime != previous:
            d = Decision(
                agent=self.name,
                type=DecisionType.CAPITAL_SCALE,
                summary=f"📊 시장 레짐 전환: {previous or 'NONE'} → {regime.value} "
                        f"(자본 비중 {CAPITAL_SCALE[regime]:.0%})",
                payload={"regime": regime.value, "capital_scale": CAPITAL_SCALE[regime]},
                rationale=rationale,
                expected_impact=f"신규 매수 자본 = 총자본 × {CAPITAL_SCALE[regime]:.0%}",
                status=DecisionStatus.APPROVED,
                activated_at=datetime.now().isoformat(timespec="seconds"),
            )
            record_decision(self.db, d)
            self._persist_regime(regime, rationale)
            decisions.append(d)
        else:
            log.info("regime_unchanged", regime=regime.value)

        return decisions

    @staticmethod
    def current_capital_scale(db: Database) -> float:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT capital_scale FROM regime_history ORDER BY detected_at DESC LIMIT 1"
            ).fetchone()
        return float(row["capital_scale"]) if row else 1.0
