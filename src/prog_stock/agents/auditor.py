"""Auditor Agent — 주간 거래 일지 분석 + 이상치 탐지.

매주 일요일 (또는 매일 16:30) 실행:
1. 최근 거래의 통계 분석 (승률, 손익비, 보유 기간 분포)
2. 이상치 탐지 (룰 위반, 같은 종목 연속 손절, 시장 평균 대비 과도한 손실)
3. 자동 HALT 트리거 조건 검사 (예: 최근 5거래 모두 손절 → 자동 일시 중단)
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
class AuditorConfig:
    lookback_days: int = 30
    consecutive_losses_to_halt: int = 5
    win_rate_floor: float = 0.25         # 25% 미만 시 경고
    avg_holding_min_days: float = 5.0    # 평균 보유 5일 미만 시 경고 (전략 의도와 다름)


class AuditorAgent:
    name = "auditor"

    def __init__(self, db: Database, cfg: AuditorConfig | None = None) -> None:
        self.db = db
        self.cfg = cfg or AuditorConfig()

    def _load_trades(self, since: date) -> pd.DataFrame:
        with self.db.connect() as conn:
            rows = list(conn.execute(
                "SELECT * FROM trades WHERE exit_at IS NOT NULL AND exit_at >= ?",
                (since.isoformat(),),
            ))
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    def _count_recent_consecutive_losses(self, trades: pd.DataFrame) -> int:
        if trades.empty:
            return 0
        s = trades.sort_values("exit_at", ascending=False)["net_pnl"].tolist()
        n = 0
        for v in s:
            if v is None:
                continue
            if v < 0:
                n += 1
            else:
                break
        return n

    def run(self) -> list[Decision]:
        since = date.today() - timedelta(days=self.cfg.lookback_days)
        trades = self._load_trades(since)
        decisions: list[Decision] = []

        if trades.empty:
            return decisions

        # 1) 연속 손절 자동 HALT
        consecutive_losses = self._count_recent_consecutive_losses(trades)
        if consecutive_losses >= self.cfg.consecutive_losses_to_halt:
            d = Decision(
                agent=self.name, type=DecisionType.HALT,
                summary=f"⚠️ 최근 {consecutive_losses}거래 연속 손절 — 자동 일시 중단",
                payload={"consecutive_losses": consecutive_losses},
                rationale="시장 환경이 전략과 맞지 않거나 룰 버그 가능성. 사람 검토 필요.",
                expected_impact="신규 매수 잠금, 보유는 유지",
                status=DecisionStatus.APPROVED,
                activated_at=datetime.now().isoformat(timespec="seconds"),
            )
            record_decision(self.db, d)
            self.db.log_event(
                "WARN", "CMD_HALT",
                f"Auditor auto-halt: {consecutive_losses} consecutive losses",
                {"trigger": "auditor"},
            )
            decisions.append(d)

        # 2) 승률 / 보유 기간 통찰
        win_rate = (trades["net_pnl"] > 0).mean()
        avg_hold = trades["holding_days"].dropna().mean()

        if win_rate < self.cfg.win_rate_floor:
            decisions.append(Decision(
                agent=self.name, type=DecisionType.ANOMALY_ALERT,
                summary=f"⚠️ 최근 {self.cfg.lookback_days}일 승률 {win_rate:.1%} (기준 {self.cfg.win_rate_floor:.0%} 미달)",
                payload={"win_rate": float(win_rate),
                         "avg_holding_days": float(avg_hold) if pd.notna(avg_hold) else None,
                         "trades": int(len(trades))},
                rationale="승률 저하는 시장 레짐 변화 또는 신호 노이즈 가능성.",
                status=DecisionStatus.APPROVED,
            ))

        if pd.notna(avg_hold) and avg_hold < self.cfg.avg_holding_min_days:
            decisions.append(Decision(
                agent=self.name, type=DecisionType.ANOMALY_ALERT,
                summary=f"📉 평균 보유 {avg_hold:.1f}일 — 추세추종 의도와 불일치",
                payload={"avg_holding_days": float(avg_hold)},
                rationale="보유 기간이 짧으면 손절 빈발 또는 추세 미성숙 시그널.",
                status=DecisionStatus.APPROVED,
            ))

        # 3) 종목별 연속 손절 패턴
        with self.db.connect() as conn:
            same_symbol = list(conn.execute(
                """SELECT symbol, COUNT(*) AS n FROM trades
                   WHERE exit_at >= ? AND net_pnl < 0
                   GROUP BY symbol HAVING n >= 2""",
                (since.isoformat(),),
            ))
        if same_symbol:
            decisions.append(Decision(
                agent=self.name, type=DecisionType.INSIGHT,
                summary=f"🔁 같은 종목 반복 손절: {len(same_symbol)}종목",
                payload={"symbols": [{"symbol": r["symbol"], "losses": int(r["n"])} for r in same_symbol]},
                rationale="동일 종목 반복 손절은 추격 매수 또는 쿨다운 룰 미작동 가능성.",
                status=DecisionStatus.APPROVED,
            ))

        for d in decisions:
            record_decision(self.db, d)
        return decisions
