"""Strategy 인터페이스. 신호 생성과 청산 룰을 분리한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Protocol

import pandas as pd


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: Action
    reason: str
    target_price: float | None = None  # None = 시장가/현재가 매매


class Strategy(Protocol):
    """모든 전략은 이 프로토콜을 구현한다."""

    name: str

    def select_candidates(
        self,
        today: date,
        universe: pd.DataFrame,
        history_loader,  # callable(symbol) -> DataFrame
        fundamentals: pd.DataFrame,
        market_index: pd.DataFrame,
    ) -> list[Signal]:
        """오늘 매수 후보 신호 (BUY)."""
        ...

    def evaluate_holdings(
        self,
        today: date,
        positions: list,  # list[Position]
        history_loader,
        fundamentals: pd.DataFrame,
    ) -> list[Signal]:
        """현재 보유 종목 청산 평가 (SELL/HOLD)."""
        ...
