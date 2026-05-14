"""뉴스 수집 영속화 — 중복 회피, 보유 종목 우선순위 격상."""
from __future__ import annotations

from prog_stock.agents.base import ensure_agent_schema
from prog_stock.news import monitor
from prog_stock.news.models import NewsItem, Priority
from prog_stock.storage.db import Database


def test_persist_dedupes_same_headline_source(tmp_path):
    db = Database(tmp_path / "t.db")
    ensure_agent_schema(db)
    items = [
        NewsItem(headline="X 횡령", source="naver_rss", priority=Priority.HIGH),
        NewsItem(headline="X 횡령", source="naver_rss", priority=Priority.HIGH),
    ]
    n = monitor.persist_news(db, items)
    assert n == 1


def test_persist_distinct_sources_kept(tmp_path):
    db = Database(tmp_path / "t.db")
    ensure_agent_schema(db)
    items = [
        NewsItem(headline="A", source="naver_rss"),
        NewsItem(headline="A", source="hankyung_rss"),
    ]
    n = monitor.persist_news(db, items)
    assert n == 2


def test_classify_and_match_promotes_holding_negatives(tmp_path):
    db = Database(tmp_path / "t.db")
    ensure_agent_schema(db)
    items = [NewsItem(headline="삼성전자 횡령", source="naver_rss")]
    classified = monitor.classify_and_match(items, {"005930": "삼성전자"})
    assert classified[0].priority == Priority.HIGH
    assert classified[0].symbol == "005930"


def test_todays_news_summary_returns_recent(tmp_path):
    db = Database(tmp_path / "t.db")
    ensure_agent_schema(db)
    from datetime import date, datetime
    today_iso = date.today().isoformat()
    item = NewsItem(headline="X", source="s", priority=Priority.HIGH,
                    collected_at=today_iso + "T10:00:00")
    monitor.persist_news(db, [item])
    rows = monitor.todays_news_summary(db)
    assert len(rows) == 1
    assert rows[0]["headline"] == "X"
