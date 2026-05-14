"""News Agent — 일일 수집 + 보유 종목 매칭 + HIGH priority 알림.

매일 06:00 + 매시간 정시(장중). 자동 매매 X — 알림만.
사용자 결정: AI 감성분석으로 자동 청산은 위험. 사람이 판단한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import structlog

from prog_stock.agents.base import (
    Agent,
    Decision,
    DecisionStatus,
    DecisionType,
    record_decision,
)
from prog_stock.brokers.port import BrokerPort
from prog_stock.news import monitor
from prog_stock.news.models import Priority
from prog_stock.news.sources import get_macro_events
from prog_stock.storage.db import Database

log = structlog.get_logger(__name__)


@dataclass
class NewsAgentConfig:
    macro_lookahead_days: int = 3


class NewsAgent:
    name = "news"

    def __init__(self, db: Database, broker: BrokerPort | None,
                 cfg: NewsAgentConfig | None = None) -> None:
        self.db = db
        self.broker = broker
        self.cfg = cfg or NewsAgentConfig()

    def run(self) -> list[Decision]:
        today = date.today()
        items = monitor.collect_news(today)

        holdings: dict[str, str] = {}
        if self.broker is not None:
            try:
                holdings = monitor._holding_symbols_to_names(self.broker, today)
            except Exception as e:
                log.warning("holdings_lookup_failed", error=str(e))

        items = monitor.classify_and_match(items, holdings)
        new_count = monitor.persist_news(self.db, items)
        log.info("news_persisted", new=new_count, total=len(items))

        events = get_macro_events(today, self.cfg.macro_lookahead_days)
        monitor.persist_macro_events(self.db, events)

        decisions: list[Decision] = []

        # HIGH priority 보유 종목 매칭 → 즉시 알림 (자동 매매 X)
        holding_alerts = [
            it for it in items
            if it.priority == Priority.HIGH and it.symbol in holdings
        ]
        for it in holding_alerts:
            d = Decision(
                agent=self.name, type=DecisionType.ANOMALY_ALERT,
                summary=f"🔴 보유 종목 악재: [{it.symbol}] {it.headline}",
                payload={"symbol": it.symbol, "url": it.url, "keywords": it.keywords,
                         "source": it.source},
                rationale=f"키워드 매칭: {', '.join(it.keywords)}. 사람의 판단 필요.",
                expected_impact="자동 매매 X — 사용자가 /halt 또는 청산 결정",
                status=DecisionStatus.APPROVED,
                activated_at=datetime.now().isoformat(timespec="seconds"),
            )
            record_decision(self.db, d)
            decisions.append(d)

        # 거시 이벤트 알림 (오늘 또는 익일)
        urgent_events = [e for e in events
                         if date.fromisoformat(e.event_date) <= today.replace(day=min(today.day + 1, 28))]
        for e in urgent_events[:5]:
            d = Decision(
                agent=self.name, type=DecisionType.INSIGHT,
                summary=f"📅 거시 이벤트: {e.event_date} {e.event_type} — {e.description}",
                payload={"event_date": e.event_date, "type": e.event_type,
                         "impact": e.impact_level.value},
                rationale="변동성 큰 날 — 신규 매수 주의.",
                status=DecisionStatus.APPROVED,
            )
            record_decision(self.db, d)
            decisions.append(d)

        return decisions
