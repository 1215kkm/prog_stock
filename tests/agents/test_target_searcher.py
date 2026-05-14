"""Target Searcher — 프리셋 검증, 과적합 휴리스틱, PARAM_BOUNDS 우회 거부."""
from __future__ import annotations

import json

import pytest

from prog_stock.agents.base import ensure_agent_schema
from prog_stock.agents.bounds import PARAM_BOUNDS
from prog_stock.agents.target_searcher import (
    PRESETS,
    TargetSearcherAgent,
    _overfit_warning,
)
from prog_stock.storage.db import Database


class TestPresets:
    def test_three_presets_defined(self):
        assert set(PRESETS) == {"conservative", "balanced", "aggressive"}

    def test_aggressive_has_higher_target_than_conservative(self):
        assert PRESETS["aggressive"]["annual"] > PRESETS["conservative"]["annual"]

    def test_aggressive_allows_wider_mdd(self):
        # MDD는 음수, 공격형이 더 큰 손실 허용 (더 작은 값)
        assert PRESETS["aggressive"]["mdd"] < PRESETS["conservative"]["mdd"]


class TestOverfitWarning:
    def test_high_sharpe_flagged(self):
        warn = _overfit_warning({"sharpe": 4.5, "trades": 100})
        assert warn and "high_sharpe" in warn

    def test_low_sample_flagged(self):
        warn = _overfit_warning({"sharpe": 1.0, "trades": 15})
        assert warn and "low_sample" in warn

    def test_clean_metrics_no_warning(self):
        warn = _overfit_warning({"sharpe": 1.5, "trades": 100})
        assert warn is None


class TestApplyValidates:
    def test_apply_rejects_out_of_bounds_params(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        agent = TargetSearcherAgent(db)
        # 강제로 세션과 경계 위배 후보 삽입
        with db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO target_sessions
                   (created_at, preset, target_annual_return, max_mdd, min_sharpe,
                    horizon_months, status, candidates_found)
                   VALUES (?, 'balanced', 0.15, -0.15, 1.0, 6, 'FOUND', 1)""",
                ("2026-05-07T10:00:00",),
            )
            sid = int(cur.lastrowid)
            conn.execute(
                """INSERT INTO target_candidates
                   (session_id, params_json, cagr, sharpe, mdd, profit_factor, trades, rank, overfit_warning)
                   VALUES (?, ?, 0.20, 1.5, -0.10, 2.0, 50, 1, NULL)""",
                (sid, json.dumps({"hard_stop_loss": -0.20})),  # 범위 밖 (-0.20 < -0.10 min)
            )
        with pytest.raises(ValueError, match="out of bounds"):
            agent.apply(sid, 1)

    def test_apply_creates_canary_decision(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        agent = TargetSearcherAgent(db)
        with db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO target_sessions
                   (created_at, preset, target_annual_return, max_mdd, min_sharpe,
                    horizon_months, status, candidates_found)
                   VALUES ('2026-05-07T10:00:00', 'balanced', 0.15, -0.15, 1.0, 6, 'FOUND', 1)"""
            )
            sid = int(cur.lastrowid)
            conn.execute(
                """INSERT INTO target_candidates
                   (session_id, params_json, cagr, sharpe, mdd, profit_factor, trades, rank, overfit_warning)
                   VALUES (?, ?, 0.18, 1.4, -0.12, 1.8, 50, 1, NULL)""",
                (sid, json.dumps({"hard_stop_loss": -0.07})),
            )
        d = agent.apply(sid, 1)
        from prog_stock.agents.base import DecisionStatus
        assert d.status == DecisionStatus.CANARY
        with db.connect() as conn:
            sess = conn.execute("SELECT * FROM target_sessions WHERE id = ?", (sid,)).fetchone()
        assert sess["status"] == "APPLIED"


class TestStatus:
    def test_status_lists_sessions(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        agent = TargetSearcherAgent(db)
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO target_sessions
                   (created_at, preset, target_annual_return, max_mdd, min_sharpe,
                    horizon_months, status, candidates_found)
                   VALUES ('2026-05-07T10:00:00', 'conservative', 0.08, -0.10, 0.8, 6, 'FOUND', 2)"""
            )
        sessions = agent.status()
        assert len(sessions) == 1
        assert sessions[0]["preset"] == "conservative"


class TestUnknownPresetRaises:
    def test_unknown_preset(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        agent = TargetSearcherAgent(db)
        with pytest.raises(ValueError, match="unknown preset"):
            agent.search("ultra_aggressive", horizon_months=6)
