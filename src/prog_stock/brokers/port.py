"""BrokerPort — 증권사 어댑터 추상.

이 인터페이스는 KIS, paper, backtest 어댑터가 모두 구현한다.
런타임은 이 추상에만 의존 — python-kis 라이브러리 락인 회피.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import AsyncIterator, Protocol


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Order:
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int
    price: float | None  # None for MARKET
    idempotency_key: str
    reason: str = "ENTRY"


@dataclass(frozen=True)
class OrderResult:
    broker_order_id: str
    status: OrderStatus
    filled_qty: int = 0
    avg_fill_price: float | None = None


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    avg_price: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.current_price * self.quantity

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def return_pct(self) -> float:
        return (self.current_price - self.avg_price) / self.avg_price if self.avg_price else 0.0


@dataclass(frozen=True)
class Balance:
    cash: float
    positions_value: float
    total_equity: float


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int
    vi_active: bool = False
    is_locked_upper: bool = False
    is_locked_lower: bool = False
    timestamp: datetime | None = None


@dataclass(frozen=True)
class Tick:
    symbol: str
    price: float
    volume: int
    timestamp: datetime


class BrokerPort(Protocol):
    """증권사 추상 인터페이스. 모든 매매·조회는 여기를 통한다."""

    def place_order(self, order: Order) -> OrderResult: ...

    def cancel(self, broker_order_id: str) -> bool: ...

    def positions(self) -> list[Position]: ...

    def balance(self) -> Balance: ...

    def quote(self, symbol: str) -> Quote: ...

    async def subscribe(self, symbols: list[str]) -> AsyncIterator[Tick]: ...

    def is_tradeable(self, symbol: str) -> bool:
        """VI/거래정지/관리종목 체크."""
        ...
