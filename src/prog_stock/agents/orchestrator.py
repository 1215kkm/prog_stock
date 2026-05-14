"""Orchestrator — 에이전트 스케줄링 + 의사결정 적용.

스케줄:
- 06:30  Regime Detector
- 매 정시 매매 루프와 함께 동작
- 16:30  Researcher (백테스트 비용 큼)
- 일요일 23:00  Portfolio Manager
- 16:30  Auditor

자율 적용 규칙:
- PARAM_CHANGE: CANARY 30일 자동 → 카나리 결과 더 좋으면 APPROVED
- CAPITAL_SCALE / STRATEGY_WEIGHT: 즉시 APPROVED (불변 룰 미위반)
- HALT: 즉시 APPROVED (안전 방향)
- 불변 룰 변경 시도: 무조건 거부 (Bounds 단계에서 차단되어 도달 불가)

텔레그램: 모든 의사결정 자동 보고.
"""
from __future__ import annotations

import structlog

from prog_stock.agents.auditor import AuditorAgent
from prog_stock.agents.base import (
    Agent,
    Decision,
    DecisionStatus,
    DecisionType,
    ensure_agent_schema,
    record_decision,
)
from prog_stock.agents.bounds import PARAM_BOUNDS
from prog_stock.agents.news_agent import NewsAgent
from prog_stock.agents.portfolio import PortfolioManagerAgent
from prog_stock.agents.regime import RegimeDetectorAgent
from prog_stock.agents.researcher import ResearcherAgent
from prog_stock.brokers.port import BrokerPort
from prog_stock.monitoring.telegram_bot import TelegramNotifier
from prog_stock.storage.db import Database

log = structlog.get_logger(__name__)


class Orchestrator:
    def __init__(self, db: Database, notifier: TelegramNotifier | None = None,
                 broker: BrokerPort | None = None) -> None:
        self.db = db
        self.notifier = notifier
        self.broker = broker
        ensure_agent_schema(db)
        self.researcher = ResearcherAgent(db)
        self.auditor = AuditorAgent(db)
        self.regime = RegimeDetectorAgent(db)
        self.portfolio = PortfolioManagerAgent(db)
        self.news = NewsAgent(db, broker)

    def _validate_param_change(self, payload: dict) -> bool:
        """변경 요청이 PARAM_BOUNDS 경계 안인지 검증. 불변 룰 보호."""
        new_params = payload.get("new_params", {})
        for k, v in new_params.items():
            if k not in PARAM_BOUNDS:
                log.warning("param_not_in_bounds", param=k)
                return False
            if not PARAM_BOUNDS[k].valid(v):
                log.warning("param_out_of_bounds", param=k, value=v,
                            min=PARAM_BOUNDS[k].min, max=PARAM_BOUNDS[k].max)
                return False
        return True

    def _notify(self, decision: Decision) -> None:
        if not self.notifier:
            return
        emoji = {
            DecisionType.PARAM_CHANGE: "🔬",
            DecisionType.STRATEGY_WEIGHT: "🎯",
            DecisionType.HALT: "⏸️",
            DecisionType.RESUME: "▶️",
            DecisionType.CAPITAL_SCALE: "📊",
            DecisionType.ANOMALY_ALERT: "⚠️",
            DecisionType.INSIGHT: "💡",
        }.get(decision.type, "🤖")
        msg = (
            f"{emoji} <b>{decision.agent}</b> [{decision.status.value}]\n"
            f"{decision.summary}\n"
            f"<i>{decision.rationale}</i>"
        )
        self.notifier.send(msg, html=True)

    def run_researcher(self) -> None:
        log.info("orchestrator_run_researcher")
        decisions = self.researcher.run()
        for d in decisions:
            if d.type == DecisionType.PARAM_CHANGE and not self._validate_param_change(d.payload):
                d.status = DecisionStatus.REJECTED
                d.rationale += " [REJECTED: out of bounds]"
                record_decision(self.db, d)
            self._notify(d)

    def run_auditor(self) -> None:
        log.info("orchestrator_run_auditor")
        for d in self.auditor.run():
            self._notify(d)

    def run_regime(self) -> None:
        log.info("orchestrator_run_regime")
        for d in self.regime.run():
            self._notify(d)

    def run_portfolio(self) -> None:
        log.info("orchestrator_run_portfolio")
        for d in self.portfolio.run():
            self._notify(d)

    def run_news(self) -> None:
        log.info("orchestrator_run_news")
        for d in self.news.run():
            self._notify(d)

    def daily_pipeline(self) -> None:
        """매일 16:30에 한 번 호출."""
        self.run_news()
        self.run_regime()
        self.run_auditor()
        self.run_researcher()

    def hourly_news_pulse(self) -> None:
        """장중 매시간 가벼운 뉴스 폴링."""
        self.run_news()

    def weekly_pipeline(self) -> None:
        """매주 일요일 23:00 호출."""
        self.run_portfolio()
