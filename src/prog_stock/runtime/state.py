"""런타임 상태 영속화 — peak equity, daily start equity, 시장 필터 캐시.

루프 재시작 시 직전 상태를 복원해 MDD/일일손실/카나리 카운터가 끊기지 않게 한다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


@dataclass
class RuntimeState:
    peak_equity: float = 0.0
    daily_start_equity: float = 0.0
    daily_start_date: str = ""             # YYYY-MM-DD
    canary_start_date: str = ""            # 카나리 모드 시작일
    canary_active: bool = False
    halt_engaged: bool = False             # /halt 명령으로 신규 매수 잠금
    last_market_filter_check: str = ""     # 시장 필터 캐시 만료
    market_filter_on: bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "RuntimeState":
        return cls(**json.loads(s))


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> RuntimeState:
        if not self.path.exists():
            log.info("state_initialize_fresh")
            return RuntimeState()
        try:
            return RuntimeState.from_json(self.path.read_text())
        except Exception as e:
            log.warning("state_load_failed_reset", error=str(e))
            return RuntimeState()

    def save(self, state: RuntimeState) -> None:
        self.path.write_text(state.to_json())

    def reset_daily(self, state: RuntimeState, today: date, current_equity: float) -> RuntimeState:
        if state.daily_start_date != today.isoformat():
            state.daily_start_date = today.isoformat()
            state.daily_start_equity = current_equity
            self.save(state)
        return state
