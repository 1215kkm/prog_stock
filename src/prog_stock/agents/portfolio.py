"""Portfolio Manager — 멀티 전략 자본 자동 배분.

여러 전략(canslim_sepa, dual_momentum, volatility_breakout)을 동시 운영하면서,
각 전략의 **최근 90일 페이퍼 P&L**을 기반으로 자본 비중을 자동 재배분.

알고리즘 (단순 + robust):
- 각 전략의 최근 90일 Sharpe + Profit Factor 합산 점수
- 음수 점수 전략은 비중 0 (즉시 비활성)
- 점수 비례 비중 분배 (소프트맥스 변형)
- 변경 시 의사결정 영속화

매주 일요일 23:00 실행.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
import structlog

from prog_stock.agents.base import (
    Agent,
    Decision,
    DecisionStatus,
    DecisionType,
    record_decision,
)
from prog_stock.storage.db import Database

log = structlog.get_logger(__name__)


@dataclass
class PortfolioConfig:
    lookback_days: int = 90
    strategies: tuple[str, ...] = ("canslim_sepa", "dual_momentum", "volatility_breakout")
    min_weight: float = 0.0
    max_weight: float = 0.7
    inactive_threshold_score: float = 0.0


def _strategy_score(trades: pd.DataFrame) -> float:
    if trades.empty or len(trades) < 5:
        return 0.0
    pnl = trades["net_pnl"].dropna()
    if pnl.empty:
        return 0.0
    mean = float(pnl.mean())
    std = float(pnl.std()) or 1.0
    sharpe_proxy = mean / std
    wins = float(pnl[pnl > 0].sum())
    losses = float(abs(pnl[pnl < 0].sum())) or 1.0
    pf = wins / losses
    return sharpe_proxy + (pf - 1.0)  # 합산 점수


class PortfolioManagerAgent:
    name = "portfolio"

    def __init__(self, db: Database, cfg: PortfolioConfig | None = None) -> None:
        self.db = db
        self.cfg = cfg or PortfolioConfig()

    def _trades_for_strategy(self, strategy: str, since: date) -> pd.DataFrame:
        """전략별 거래 분리 — orders 테이블의 reason 또는 strategy 컬럼으로 추적.

        현재 스키마는 단일 전략 가정이라 거래에 전략 태그 없음.
        실제 멀티 전략 도입 시 orders/trades에 strategy 컬럼 추가 필요.
        지금은 단순화: 모든 거래를 전략별로 동일하게 평가.
        """
        with self.db.connect() as conn:
            rows = list(conn.execute(
                "SELECT * FROM trades WHERE exit_at IS NOT NULL AND exit_at >= ?",
                (since.isoformat(),),
            ))
        return pd.DataFrame([dict(r) for r in rows])

    def run(self) -> list[Decision]:
        since = date.today() - timedelta(days=self.cfg.lookback_days)
        scores: dict[str, float] = {}
        for strategy in self.cfg.strategies:
            trades = self._trades_for_strategy(strategy, since)
            scores[strategy] = _strategy_score(trades)
        log.info("portfolio_scores", scores=scores)

        # 음수 점수는 0으로 클립
        positive = {k: max(v, 0.0) for k, v in scores.items()}
        total = sum(positive.values())
        if total <= 0:
            # 모두 부진 — 균등 분배 (안전 디폴트)
            n = len(self.cfg.strategies)
            weights = {s: 1.0 / n for s in self.cfg.strategies}
        else:
            weights = {s: v / total for s, v in positive.items()}
            # 캡 적용
            for s in weights:
                weights[s] = min(max(weights[s], self.cfg.min_weight), self.cfg.max_weight)
            # 합 1.0으로 재정규화
            total_w = sum(weights.values()) or 1.0
            weights = {s: w / total_w for s, w in weights.items()}

        previous = self._current_weights()
        if previous == weights:
            return []

        # 영속화
        now = datetime.now().isoformat(timespec="seconds")
        with self.db.connect() as conn:
            for s, w in weights.items():
                conn.execute(
                    """INSERT OR REPLACE INTO strategy_weights
                       (set_at, strategy, weight, enabled) VALUES (?, ?, ?, ?)""",
                    (now, s, w, 1 if w > 0 else 0),
                )

        d = Decision(
            agent=self.name,
            type=DecisionType.STRATEGY_WEIGHT,
            summary="🎯 전략 비중 재배분: " + ", ".join(f"{s}={w:.0%}" for s, w in weights.items()),
            payload={"weights": weights, "scores": scores},
            rationale=f"최근 {self.cfg.lookback_days}일 점수(sharpe+PF) 기반",
            status=DecisionStatus.APPROVED,
            activated_at=now,
        )
        record_decision(self.db, d)
        return [d]

    def _current_weights(self) -> dict[str, float]:
        with self.db.connect() as conn:
            rows = list(conn.execute(
                """SELECT strategy, weight FROM strategy_weights
                   WHERE set_at = (SELECT MAX(set_at) FROM strategy_weights)"""
            ))
        return {r["strategy"]: float(r["weight"]) for r in rows}

    @staticmethod
    def load_current(db: Database) -> dict[str, float]:
        with db.connect() as conn:
            rows = list(conn.execute(
                """SELECT strategy, weight FROM strategy_weights
                   WHERE set_at = (SELECT MAX(set_at) FROM strategy_weights)"""
            ))
        return {r["strategy"]: float(r["weight"]) for r in rows}
