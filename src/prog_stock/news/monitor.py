"""뉴스 수집 + 보유 종목 매칭 + DB 저장."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import structlog

from prog_stock.brokers.port import BrokerPort
from prog_stock.config import settings
from prog_stock.data import universe as univ
from prog_stock.news import sources as news_sources
from prog_stock.news.classifier import classify, is_holding_relevant
from prog_stock.news.models import MacroEvent, NewsItem, Priority
from prog_stock.storage.db import Database

log = structlog.get_logger(__name__)


def _holding_symbols_to_names(broker: BrokerPort, today: date) -> dict[str, str]:
    """보유 종목 symbol → name 매핑 (헤드라인 매칭용)."""
    snapshot = univ.load_snapshot(today, settings.cache_dir_universe)
    name_map: dict[str, str] = {}
    if snapshot is not None and not snapshot.empty:
        name_map = dict(zip(snapshot["symbol"], snapshot["name"]))
    out: dict[str, str] = {}
    for pos in broker.positions():
        out[pos.symbol] = name_map.get(pos.symbol, "")
    return out


def collect_news(today: date | None = None) -> list[NewsItem]:
    """모든 무료 소스 수집."""
    items: list[NewsItem] = []
    items.extend(news_sources.fetch_all_rss())

    if settings.dart_api_key:
        since = (today or date.today()) - timedelta(days=1)
        items.extend(news_sources.fetch_dart_disclosures(settings.dart_api_key, since))

    fred_key = getattr(settings, "fred_api_key", "")
    if fred_key:
        for series in ("CPIAUCSL", "FEDFUNDS", "UNRATE"):
            items.extend(news_sources.fetch_fred_observations(series, fred_key))

    return items


def persist_news(db: Database, items: list[NewsItem]) -> int:
    """중복 회피하면서 DB에 저장. 신규 row 수 반환."""
    new_count = 0
    with db.connect() as conn:
        for it in items:
            exists = conn.execute(
                "SELECT 1 FROM news_items WHERE headline = ? AND source = ? LIMIT 1",
                (it.headline, it.source),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO news_items
                   (collected_at, published_at, source, symbol, headline, url,
                    priority, keywords_json, delivered)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (it.collected_at or datetime.now().isoformat(timespec="seconds"),
                 it.published_at, it.source, it.symbol, it.headline, it.url,
                 it.priority.value, it.keywords_json()),
            )
            new_count += 1
    return new_count


def persist_macro_events(db: Database, events: list[MacroEvent]) -> int:
    n = 0
    with db.connect() as conn:
        for e in events:
            conn.execute(
                """INSERT OR REPLACE INTO macro_events
                   (event_date, event_type, impact_level, description) VALUES (?, ?, ?, ?)""",
                (e.event_date, e.event_type, e.impact_level.value, e.description),
            )
            n += 1
    return n


def classify_and_match(items: list[NewsItem], holdings: dict[str, str]) -> list[NewsItem]:
    """우선순위 분류 + 보유 종목 매칭."""
    out = []
    for it in items:
        it = classify(it)
        sym = is_holding_relevant(it, holdings)
        if sym:
            it.symbol = sym
            # 보유 종목 + 부정 키워드 → 무조건 HIGH
            if it.priority != Priority.HIGH and any(it.keywords):
                it.priority = Priority.HIGH
        out.append(it)
    return out


def todays_news_summary(db: Database, today: date | None = None, limit: int = 20) -> list[dict]:
    """모닝 리포트용 — 오늘 수집된 HIGH 우선순위 뉴스."""
    today = today or date.today()
    with db.connect() as conn:
        rows = list(conn.execute(
            """SELECT * FROM news_items
               WHERE collected_at >= ? AND priority IN ('HIGH', 'MEDIUM')
               ORDER BY priority ASC, collected_at DESC LIMIT ?""",
            (today.isoformat(), limit),
        ))
    return [dict(r) for r in rows]


def upcoming_macro_events(db: Database, today: date | None = None, days: int = 3) -> list[dict]:
    today = today or date.today()
    end = (today + timedelta(days=days)).isoformat()
    with db.connect() as conn:
        rows = list(conn.execute(
            """SELECT * FROM macro_events
               WHERE event_date >= ? AND event_date <= ?
               ORDER BY event_date ASC""",
            (today.isoformat(), end),
        ))
    return [dict(r) for r in rows]
