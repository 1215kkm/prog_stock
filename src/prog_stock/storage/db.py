"""SQLite 영속 저장소. 거래/포지션/잔고스냅샷/시스템 이벤트."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT UNIQUE NOT NULL,
    broker_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,            -- BUY / SELL
    order_type TEXT NOT NULL,      -- MARKET / LIMIT
    quantity INTEGER NOT NULL,
    price REAL,
    status TEXT NOT NULL,          -- PENDING / FILLED / PARTIAL / CANCELLED / REJECTED
    submitted_at TEXT NOT NULL,
    filled_at TEXT,
    filled_qty INTEGER DEFAULT 0,
    avg_fill_price REAL,
    reason TEXT,                   -- ENTRY / STOP_LOSS / FUNDAMENTAL_BREAK / TRAIL / TREND_BREAK / MANUAL
    mode TEXT NOT NULL             -- backtest / dry_run / paper / live
);

CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT NOT NULL,
    mode TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    avg_price REAL NOT NULL,
    opened_at TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    high_water_price REAL,         -- for trailing stop
    PRIMARY KEY (symbol, mode)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    mode TEXT NOT NULL,
    entry_at TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_at TEXT,
    exit_price REAL,
    quantity INTEGER NOT NULL,
    gross_pnl REAL,
    commission REAL,
    tax REAL,
    net_pnl REAL,
    return_pct REAL,
    holding_days INTEGER,
    exit_reason TEXT
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    snapshot_date TEXT NOT NULL,
    mode TEXT NOT NULL,
    cash REAL NOT NULL,
    positions_value REAL NOT NULL,
    total_equity REAL NOT NULL,
    daily_pnl REAL,
    drawdown_from_peak REAL,
    PRIMARY KEY (snapshot_date, mode)
);

CREATE TABLE IF NOT EXISTS cooldowns (
    symbol TEXT NOT NULL,
    mode TEXT NOT NULL,
    until_date TEXT NOT NULL,
    reason TEXT,
    PRIMARY KEY (symbol, mode)
);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    level TEXT NOT NULL,           -- INFO / WARN / ERROR / CRITICAL
    kind TEXT NOT NULL,            -- KILL_SWITCH / DAILY_LIMIT / MDD_HALT / GUARD_REJECT / etc
    message TEXT NOT NULL,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_symbol_mode ON orders(symbol, mode);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_trades_mode_exit ON trades(mode, exit_at);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON system_events(occurred_at);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, isolation_level=None)  # autocommit-ish
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def log_event(self, level: str, kind: str, message: str, payload: dict | None = None) -> None:
        import json

        with self.connect() as conn:
            conn.execute(
                "INSERT INTO system_events (occurred_at, level, kind, message, payload_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    level,
                    kind,
                    message,
                    json.dumps(payload, ensure_ascii=False) if payload else None,
                ),
            )

    def in_cooldown(self, symbol: str, mode: str, today: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT until_date FROM cooldowns WHERE symbol = ? AND mode = ?",
                (symbol, mode),
            ).fetchone()
        return row is not None and row["until_date"] >= today

    def add_cooldown(self, symbol: str, mode: str, until_date: str, reason: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cooldowns (symbol, mode, until_date, reason) "
                "VALUES (?, ?, ?, ?)",
                (symbol, mode, until_date, reason),
            )
