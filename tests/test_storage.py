"""SQLite 스키마 테스트."""
from __future__ import annotations

from prog_stock.storage.db import Database


def test_database_creates_schema(tmp_path):
    db = Database(tmp_path / "test.db")
    with db.connect() as conn:
        tables = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    expected = {"orders", "positions", "trades", "equity_snapshots", "cooldowns", "system_events"}
    assert expected.issubset(tables)


def test_log_event_persists(tmp_path):
    db = Database(tmp_path / "test.db")
    db.log_event("INFO", "TEST", "hello", {"k": "v"})
    with db.connect() as conn:
        rows = list(conn.execute("SELECT * FROM system_events"))
    assert len(rows) == 1
    assert rows[0]["kind"] == "TEST"
    assert "hello" in rows[0]["message"]


def test_cooldown_lifecycle(tmp_path):
    db = Database(tmp_path / "test.db")
    db.add_cooldown("005930", "paper", "2026-06-01", "STOP_LOSS")
    assert db.in_cooldown("005930", "paper", "2026-05-15")
    assert not db.in_cooldown("005930", "paper", "2026-06-02")
