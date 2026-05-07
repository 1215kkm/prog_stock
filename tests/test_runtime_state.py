"""RuntimeState 영속화 테스트."""
from __future__ import annotations

from datetime import date

from prog_stock.runtime.state import RuntimeState, StateStore


def test_state_roundtrip(tmp_path):
    store = StateStore(tmp_path / "state.json")
    s = RuntimeState(peak_equity=12_345.0, halt_engaged=True, daily_start_equity=10_000.0)
    store.save(s)
    loaded = store.load()
    assert loaded.peak_equity == 12_345.0
    assert loaded.halt_engaged is True
    assert loaded.daily_start_equity == 10_000.0


def test_fresh_state_when_missing(tmp_path):
    store = StateStore(tmp_path / "state.json")
    s = store.load()
    assert s.peak_equity == 0.0
    assert s.halt_engaged is False


def test_reset_daily_only_when_date_changes(tmp_path):
    store = StateStore(tmp_path / "state.json")
    s = RuntimeState(daily_start_date="2026-05-06", daily_start_equity=10_000.0)
    s = store.reset_daily(s, date(2026, 5, 6), 11_000.0)
    assert s.daily_start_equity == 10_000.0  # 같은 날 — 변경 없음

    s = store.reset_daily(s, date(2026, 5, 7), 11_000.0)
    assert s.daily_start_date == "2026-05-07"
    assert s.daily_start_equity == 11_000.0
