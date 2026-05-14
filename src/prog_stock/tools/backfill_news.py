"""뉴스 백필 CLI — 최초 1회 또는 운영 중단 후 캐치업."""
from __future__ import annotations

import argparse

import structlog

from prog_stock.agents.base import ensure_agent_schema
from prog_stock.config import settings
from prog_stock.news import monitor
from prog_stock.storage.db import Database

log = structlog.get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-dart", action="store_true", help="DART 공시 스킵")
    args = parser.parse_args()

    settings.ensure_dirs()
    db = Database(settings.db_path)
    ensure_agent_schema(db)

    items = monitor.collect_news()
    items = monitor.classify_and_match(items, holdings={})
    n = monitor.persist_news(db, items)
    print(f"backfilled {n} news items (total fetched: {len(items)})")

    from prog_stock.news.sources import get_macro_events
    from datetime import date

    events = get_macro_events(date.today(), lookahead_days=90)
    monitor.persist_macro_events(db, events)
    print(f"backfilled {len(events)} macro events (next 90 days)")


if __name__ == "__main__":
    main()
