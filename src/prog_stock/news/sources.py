"""뉴스 소스 클라이언트.

무료 + 인증 불필요 또는 기존 API 키 재사용. 외부 호출 실패 시 빈 리스트 반환(안전).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

import structlog

from prog_stock.news.models import MacroEvent, NewsItem, Priority, Source

log = structlog.get_logger(__name__)


# RSS feeds (무료, 인증 없음)
RSS_FEEDS = {
    Source.HANKYUNG_RSS.value: "https://www.hankyung.com/feed/economy",
    Source.MAEIL_RSS.value: "https://www.mk.co.kr/rss/30000001/",  # 경제
    Source.REUTERS_RSS.value: "https://feeds.reuters.com/reuters/businessNews",
    Source.YAHOO_RSS.value: "https://finance.yahoo.com/news/rssindex",
}


def fetch_rss(feed_url: str, source: str, limit: int = 50) -> list[NewsItem]:
    try:
        import feedparser  # type: ignore[import-untyped]
    except ImportError:
        log.warning("feedparser_not_installed_skip", feed=feed_url)
        return []

    try:
        parsed = feedparser.parse(feed_url)
    except Exception as e:
        log.warning("rss_fetch_failed", feed=feed_url, error=str(e))
        return []

    now_iso = datetime.now().isoformat(timespec="seconds")
    items: list[NewsItem] = []
    for entry in parsed.entries[:limit]:
        items.append(
            NewsItem(
                headline=getattr(entry, "title", ""),
                source=source,
                url=getattr(entry, "link", ""),
                published_at=getattr(entry, "published", "") or now_iso,
                collected_at=now_iso,
            )
        )
    return items


def fetch_all_rss(limit_per_feed: int = 50) -> list[NewsItem]:
    out: list[NewsItem] = []
    for source, url in RSS_FEEDS.items():
        out.extend(fetch_rss(url, source, limit_per_feed))
    return out


def fetch_dart_disclosures(api_key: str, since: date, end: date | None = None) -> list[NewsItem]:
    """DART 일반 공시 (재무 외). 재무는 fundamentals.py에서 처리."""
    if not api_key:
        return []
    try:
        import OpenDartReader  # type: ignore[import-not-found]
    except ImportError:
        return []

    dart = OpenDartReader(api_key)
    end = end or date.today()
    now_iso = datetime.now().isoformat(timespec="seconds")

    try:
        df = dart.list(start=since.isoformat().replace("-", ""),
                       end=end.isoformat().replace("-", ""))
    except Exception as e:
        log.warning("dart_list_failed", error=str(e))
        return []

    out: list[NewsItem] = []
    if df is None or df.empty:
        return out
    for row in df.itertuples():
        out.append(NewsItem(
            headline=str(getattr(row, "report_nm", "")),
            source=Source.DART.value,
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={getattr(row, 'rcept_no', '')}",
            symbol=str(getattr(row, "stock_code", "") or "") or None,
            published_at=str(getattr(row, "rcept_dt", "")),
            collected_at=now_iso,
        ))
    return out


# 정적 거시 이벤트 캘린더 (FOMC, 한은 금통위, CPI 등은 정기 일정)
# 매년 1월 갱신 필요. 자동 fetch가 어려운 항목은 사용자 또는 maintainer가 추가.
STATIC_MACRO_EVENTS_2026: list[MacroEvent] = [
    # 한은 금통위 (정기)
    MacroEvent("2026-01-16", "BOK_RATE", Priority.HIGH, "한은 1월 금통위"),
    MacroEvent("2026-02-27", "BOK_RATE", Priority.HIGH, "한은 2월 금통위"),
    MacroEvent("2026-04-10", "BOK_RATE", Priority.HIGH, "한은 4월 금통위"),
    MacroEvent("2026-05-29", "BOK_RATE", Priority.HIGH, "한은 5월 금통위"),
    MacroEvent("2026-07-10", "BOK_RATE", Priority.HIGH, "한은 7월 금통위"),
    MacroEvent("2026-08-28", "BOK_RATE", Priority.HIGH, "한은 8월 금통위"),
    MacroEvent("2026-10-15", "BOK_RATE", Priority.HIGH, "한은 10월 금통위"),
    MacroEvent("2026-11-27", "BOK_RATE", Priority.HIGH, "한은 11월 금통위"),
    # FOMC (정기)
    MacroEvent("2026-01-28", "FOMC", Priority.HIGH, "FOMC 1월"),
    MacroEvent("2026-03-18", "FOMC", Priority.HIGH, "FOMC 3월"),
    MacroEvent("2026-04-29", "FOMC", Priority.HIGH, "FOMC 4월"),
    MacroEvent("2026-06-17", "FOMC", Priority.HIGH, "FOMC 6월"),
    MacroEvent("2026-07-29", "FOMC", Priority.HIGH, "FOMC 7월"),
    MacroEvent("2026-09-16", "FOMC", Priority.HIGH, "FOMC 9월"),
    MacroEvent("2026-10-28", "FOMC", Priority.HIGH, "FOMC 10월"),
    MacroEvent("2026-12-16", "FOMC", Priority.HIGH, "FOMC 12월"),
    # 한국 코스피 옵션만기일 (매월 둘째 목요일) — 변동성 큼
    MacroEvent("2026-01-08", "OPTIONS_EXPIRY", Priority.MEDIUM, "옵션만기일"),
    MacroEvent("2026-02-12", "OPTIONS_EXPIRY", Priority.MEDIUM, "옵션만기일"),
    MacroEvent("2026-03-12", "OPTIONS_EXPIRY", Priority.HIGH, "선물옵션 동시만기일"),
    MacroEvent("2026-06-11", "OPTIONS_EXPIRY", Priority.HIGH, "선물옵션 동시만기일"),
    MacroEvent("2026-09-10", "OPTIONS_EXPIRY", Priority.HIGH, "선물옵션 동시만기일"),
    MacroEvent("2026-12-10", "OPTIONS_EXPIRY", Priority.HIGH, "선물옵션 동시만기일"),
]


def get_macro_events(today: date, lookahead_days: int = 7) -> list[MacroEvent]:
    """오늘 이후 N일 내 거시 이벤트."""
    end = today.toordinal() + lookahead_days
    return [
        e for e in STATIC_MACRO_EVENTS_2026
        if today.toordinal() <= date.fromisoformat(e.event_date).toordinal() <= end
    ]


def fetch_fred_observations(series_id: str, api_key: str) -> list[NewsItem]:
    """FRED API (미 연준 데이터). api_key 없으면 빈 리스트.

    실제 트레이딩 결정은 안 함 — 알림 + 기록용.
    """
    if not api_key:
        return []
    try:
        import httpx
    except ImportError:
        return []
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json",
              "limit": 5, "sort_order": "desc"}
    try:
        r = httpx.get(url, params=params, timeout=10.0)
        data = r.json()
    except Exception as e:
        log.warning("fred_fetch_failed", error=str(e))
        return []

    now_iso = datetime.now().isoformat(timespec="seconds")
    out = []
    for obs in data.get("observations", [])[:5]:
        out.append(NewsItem(
            headline=f"{series_id} {obs.get('date')}: {obs.get('value')}",
            source=Source.FRED.value,
            url=f"https://fred.stlouisfed.org/series/{series_id}",
            published_at=obs.get("date", ""),
            collected_at=now_iso,
        ))
    return out
