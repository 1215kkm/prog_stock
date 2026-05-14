"""Auditor — 연속 손절 자동 HALT, 승률 저하 알림."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from prog_stock.agents.auditor import AuditorAgent, AuditorConfig
from prog_stock.agents.base import DecisionType, ensure_agent_schema
from prog_stock.storage.db import Database


def _seed_trades(db: Database, pnls: list[float], symbol: str = "A") -> None:
    today = datetime(2026, 5, 7, 16, 0)
    with db.connect() as conn:
        for i, p in enumerate(pnls):
            exit_at = (today - timedelta(days=len(pnls) - i)).isoformat()
            entry_at = (today - timedelta(days=len(pnls) - i + 5)).isoformat()
            conn.execute(
                """INSERT INTO trades (symbol, mode, entry_at, entry_price, exit_at,
                   exit_price, quantity, gross_pnl, net_pnl, return_pct, holding_days, exit_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, "paper", entry_at, 100, exit_at, 100 + p / 10, 10, p, p, p / 1000, 5,
                 "STOP_LOSS" if p < 0 else "TAKE_PROFIT"),
            )


class TestAuditor:
    def test_five_consecutive_losses_triggers_halt(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        _seed_trades(db, [-100, -100, -100, -100, -100])
        a = AuditorAgent(db, AuditorConfig(consecutive_losses_to_halt=5))
        decisions = a.run()
        halts = [d for d in decisions if d.type == DecisionType.HALT]
        assert halts, "expected automatic HALT after 5 consecutive losses"

    def test_no_halt_with_mixed_results(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        _seed_trades(db, [-100, +200, -50, +150])
        a = AuditorAgent(db, AuditorConfig(consecutive_losses_to_halt=5))
        decisions = a.run()
        halts = [d for d in decisions if d.type == DecisionType.HALT]
        assert not halts

    def test_low_win_rate_alert(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        # 1승 9패 = 10% 승률
        _seed_trades(db, [-100] * 9 + [+500])
        a = AuditorAgent(db, AuditorConfig(win_rate_floor=0.25, consecutive_losses_to_halt=999))
        decisions = a.run()
        anomalies = [d for d in decisions if d.type == DecisionType.ANOMALY_ALERT]
        assert any("승률" in d.summary for d in anomalies)

    def test_empty_trades_returns_no_decisions(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        a = AuditorAgent(db)
        assert a.run() == []
