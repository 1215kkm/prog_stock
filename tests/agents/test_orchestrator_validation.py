"""Orchestrator의 invariant 룰 보호 — 경계 밖 PARAM_CHANGE는 거부되어야 한다."""
from __future__ import annotations

import pytest

from prog_stock.agents.base import Decision, DecisionStatus, DecisionType, ensure_agent_schema
from prog_stock.agents.orchestrator import Orchestrator
from prog_stock.storage.db import Database


class TestParameterValidation:
    def test_in_bounds_change_accepted(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        orch = Orchestrator(db, notifier=None)
        assert orch._validate_param_change({"new_params": {"hard_stop_loss": -0.08}})

    def test_stop_loss_weakening_rejected(self, tmp_path):
        """누군가 -15% 손절로 약화 시도 → 거부."""
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        orch = Orchestrator(db, notifier=None)
        assert not orch._validate_param_change({"new_params": {"hard_stop_loss": -0.15}})

    def test_mdd_weakening_rejected(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        orch = Orchestrator(db, notifier=None)
        assert not orch._validate_param_change({"new_params": {"mdd_limit": -0.30}})

    def test_unknown_param_rejected(self, tmp_path):
        """알려지지 않은 파라미터(잠재적 룰 우회) → 거부."""
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        orch = Orchestrator(db, notifier=None)
        assert not orch._validate_param_change({"new_params": {"disable_stop_loss": True}})

    def test_position_cap_over_30_rejected(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        orch = Orchestrator(db, notifier=None)
        assert not orch._validate_param_change({"new_params": {"max_position_pct": 0.50}})

    def test_max_positions_capped_at_7(self, tmp_path):
        db = Database(tmp_path / "t.db")
        ensure_agent_schema(db)
        orch = Orchestrator(db, notifier=None)
        assert not orch._validate_param_change({"new_params": {"max_positions": 10}})
