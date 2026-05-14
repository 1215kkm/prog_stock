"""Agent 추상 + 의사결정 데이터 클래스 + 영속화 헬퍼."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from prog_stock.storage.db import Database


class DecisionType(str, Enum):
    PARAM_CHANGE = "PARAM_CHANGE"          # 파라미터 자동 조정
    STRATEGY_WEIGHT = "STRATEGY_WEIGHT"    # 멀티 전략 비중 변경
    HALT = "HALT"                          # 매매 일시 중단
    RESUME = "RESUME"                      # 중단 해제
    CAPITAL_SCALE = "CAPITAL_SCALE"        # 자본 비중 변경 (레짐 따라)
    ANOMALY_ALERT = "ANOMALY_ALERT"        # 이상치 경고
    INSIGHT = "INSIGHT"                    # 분석 통찰 (실행 X, 보고만)


class DecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"      # 제안됨, 카나리 시작 전
    CANARY = "CANARY"          # 자본 1%로 검증 중
    APPROVED = "APPROVED"      # 100% 적용 중
    REJECTED = "REJECTED"      # 사용자 거부 또는 카나리 실패
    EXPIRED = "EXPIRED"        # 적용 안 됨, 만료


@dataclass
class Decision:
    agent: str                          # researcher / auditor / regime / portfolio
    type: DecisionType
    summary: str                        # 텔레그램에 보낼 한 줄
    payload: dict                       # 구체 변경 내용 (예: {"hard_stop_loss": -0.08})
    rationale: str                      # 왜 이걸 제안하는지
    expected_impact: str = ""           # 예상 효과 (예: "Sharpe +0.2")
    status: DecisionStatus = DecisionStatus.PROPOSED
    proposed_at: str = ""
    activated_at: str = ""
    expires_at: str = ""

    def to_payload_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


class Agent(Protocol):
    """모든 에이전트는 이 인터페이스를 구현."""

    name: str

    def run(self) -> list[Decision]:
        """주기 작업 실행 → 의사결정 목록 반환."""
        ...


# DB 스키마 — 에이전트 의사결정 영속화
AGENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    rationale TEXT,
    expected_impact TEXT,
    status TEXT NOT NULL,
    proposed_at TEXT NOT NULL,
    activated_at TEXT,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    strategy TEXT NOT NULL,
    params_json TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    cagr REAL,
    sharpe REAL,
    mdd REAL,
    win_rate REAL,
    profit_factor REAL,
    trades INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS regime_history (
    detected_at TEXT PRIMARY KEY,
    regime TEXT NOT NULL,            -- BULL / BEAR / SIDEWAYS
    capital_scale REAL NOT NULL,     -- 0.0 ~ 1.0
    rationale TEXT
);

CREATE TABLE IF NOT EXISTS strategy_weights (
    set_at TEXT NOT NULL,
    strategy TEXT NOT NULL,
    weight REAL NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (set_at, strategy)
);

CREATE INDEX IF NOT EXISTS idx_decisions_agent_status ON agent_decisions(agent, status);
CREATE INDEX IF NOT EXISTS idx_experiments_strategy ON experiments(strategy);
"""


def ensure_agent_schema(db: Database) -> None:
    with db.connect() as conn:
        conn.executescript(AGENT_SCHEMA)


def record_decision(db: Database, decision: Decision) -> int:
    decision.proposed_at = decision.proposed_at or datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO agent_decisions
               (agent, type, summary, payload_json, rationale, expected_impact,
                status, proposed_at, activated_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (decision.agent, decision.type.value, decision.summary,
             decision.to_payload_json(), decision.rationale, decision.expected_impact,
             decision.status.value, decision.proposed_at,
             decision.activated_at or None, decision.expires_at or None),
        )
        return int(cur.lastrowid)
