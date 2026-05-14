"""Regime Detector 테스트."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from prog_stock.agents.regime import CAPITAL_SCALE, Regime, RegimeDetectorAgent
from prog_stock.storage.db import Database


def _index(days: int, drift: float, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    end = date(2026, 5, 7)
    dates = [end - timedelta(days=days - i - 1) for i in range(days)]
    noise = rng.normal(0, 0.005, days)
    closes = 300 * np.cumprod(1 + drift + noise)
    return pd.DataFrame({"date": dates, "close": closes,
                         "open": closes * 0.998, "high": closes * 1.005,
                         "low": closes * 0.995, "volume": [1000] * days})


class TestRegimeClassification:
    def test_bull_regime_when_above_rising_200ma(self, tmp_path):
        db = Database(tmp_path / "t.db")
        from prog_stock.agents.base import ensure_agent_schema
        ensure_agent_schema(db)
        agent = RegimeDetectorAgent(db)
        df = _index(300, 0.002)
        df["ma200"] = df["close"].rolling(200).mean()
        df["ma200_slope"] = df["ma200"].diff(20)
        assert agent._classify(df) == Regime.BULL

    def test_bear_regime_when_below_falling_200ma(self, tmp_path):
        db = Database(tmp_path / "t.db")
        from prog_stock.agents.base import ensure_agent_schema
        ensure_agent_schema(db)
        agent = RegimeDetectorAgent(db)
        df = _index(300, -0.002)
        df["ma200"] = df["close"].rolling(200).mean()
        df["ma200_slope"] = df["ma200"].diff(20)
        assert agent._classify(df) == Regime.BEAR

    def test_capital_scale_map_matches_spec(self):
        assert CAPITAL_SCALE[Regime.BULL] == 1.00
        assert CAPITAL_SCALE[Regime.SIDEWAYS] == 0.50
        assert CAPITAL_SCALE[Regime.BEAR] == 0.25


class TestRegimePersistence:
    def test_default_scale_when_no_history(self, tmp_path):
        db = Database(tmp_path / "t.db")
        from prog_stock.agents.base import ensure_agent_schema
        ensure_agent_schema(db)
        assert RegimeDetectorAgent.current_capital_scale(db) == 1.0
