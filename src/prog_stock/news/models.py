"""뉴스 데이터 모델."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Source(str, Enum):
    NAVER_RSS = "naver_rss"
    HANKYUNG_RSS = "hankyung_rss"
    MAEIL_RSS = "maeil_rss"
    DART = "dart"
    REUTERS_RSS = "reuters_rss"
    YAHOO_RSS = "yahoo_rss"
    FRED = "fred"
    CALENDAR = "calendar"


@dataclass
class NewsItem:
    headline: str
    source: str
    url: str = ""
    symbol: str | None = None
    published_at: str = ""
    collected_at: str = ""
    priority: Priority = Priority.LOW
    keywords: list[str] = field(default_factory=list)

    def keywords_json(self) -> str:
        return json.dumps(self.keywords, ensure_ascii=False)


@dataclass
class MacroEvent:
    event_date: str           # YYYY-MM-DD
    event_type: str           # FOMC / BOK_RATE / CPI / PCE / OPTIONS_EXPIRY
    impact_level: Priority = Priority.MEDIUM
    description: str = ""
