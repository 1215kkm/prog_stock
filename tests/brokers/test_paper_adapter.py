"""PaperAdapter — 매매 산식 + 영속화 검증."""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import pytest

from prog_stock.brokers.paper_adapter import PaperAdapter
from prog_stock.brokers.port import (
    Balance,
    BrokerPort,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    Tick,
)


class FakeQuoteSource(BrokerPort):
    def __init__(self, last: float = 50_000):
        self.last = last

    def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, bid=self.last - 50, ask=self.last + 50,
                     last=self.last, volume=1000)

    def place_order(self, order):  # unused
        raise NotImplementedError

    def cancel(self, broker_order_id):
        return True

    def positions(self):
        return []

    def balance(self):
        return Balance(cash=0, positions_value=0, total_equity=0)

    async def subscribe(self, symbols):
        return
        yield  # type: ignore[unreachable]

    def is_tradeable(self, symbol: str) -> bool:
        return True


class TestPaperAdapter:
    def test_buy_then_sell_cycle(self):
        src = FakeQuoteSource(last=50_000)
        paper = PaperAdapter(quote_source=src, starting_cash=10_000_000)

        order = Order(symbol="005930", side=Side.BUY, order_type=OrderType.MARKET,
                      quantity=10, price=None, idempotency_key="x")
        res = paper.place_order(order)
        assert res.status == OrderStatus.FILLED
        assert res.filled_qty == 10
        # 매수가 ≈ 50,000 × 1.001 (slippage)
        assert 50_000 < res.avg_fill_price < 50_100

        # 잔고 감소 확인
        bal = paper.balance()
        assert bal.cash < 10_000_000
        assert bal.positions_value > 0

        # 매도
        sell = Order(symbol="005930", side=Side.SELL, order_type=OrderType.MARKET,
                     quantity=10, price=None, idempotency_key="y")
        res2 = paper.place_order(sell)
        assert res2.status == OrderStatus.FILLED

        bal2 = paper.balance()
        # 수수료 + 거래세 + 슬리피지로 약간 손실
        assert bal2.cash < 10_000_000
        # 포지션 청산
        assert paper.positions() == []

    def test_insufficient_cash_rejects(self):
        src = FakeQuoteSource(last=50_000)
        paper = PaperAdapter(quote_source=src, starting_cash=100_000)
        order = Order(symbol="005930", side=Side.BUY, order_type=OrderType.MARKET,
                      quantity=100, price=None, idempotency_key="x")
        res = paper.place_order(order)
        assert res.status == OrderStatus.REJECTED

    def test_sell_without_position_rejects(self):
        src = FakeQuoteSource(last=50_000)
        paper = PaperAdapter(quote_source=src)
        sell = Order(symbol="005930", side=Side.SELL, order_type=OrderType.MARKET,
                     quantity=10, price=None, idempotency_key="x")
        res = paper.place_order(sell)
        assert res.status == OrderStatus.REJECTED

    def test_persistence_roundtrip(self, tmp_path):
        src = FakeQuoteSource(last=50_000)
        path = tmp_path / "paper.json"

        p1 = PaperAdapter(quote_source=src, starting_cash=10_000_000, state_path=path)
        p1.place_order(Order(symbol="005930", side=Side.BUY,
                             order_type=OrderType.MARKET, quantity=10,
                             price=None, idempotency_key="x"))

        # 새 인스턴스 — 상태 복원 확인
        p2 = PaperAdapter(quote_source=src, starting_cash=10_000_000, state_path=path)
        assert "005930" in {pos.symbol for pos in p2.positions()}
        assert p2.balance().cash < 10_000_000

    def test_avg_price_recomputed_on_pyramiding(self):
        src = FakeQuoteSource(last=50_000)
        paper = PaperAdapter(quote_source=src, starting_cash=20_000_000)
        paper.place_order(Order(symbol="A", side=Side.BUY,
                                order_type=OrderType.MARKET, quantity=10,
                                price=None, idempotency_key="1"))
        src.last = 55_000  # 가격 상승 후 추가 매수
        paper.place_order(Order(symbol="A", side=Side.BUY,
                                order_type=OrderType.MARKET, quantity=10,
                                price=None, idempotency_key="2"))
        positions = paper.positions()
        a = next(p for p in positions if p.symbol == "A")
        assert a.quantity == 20
        # 평단 ≈ (50,050 × 10 + 55,055 × 10) / 20 ≈ 52,552
        assert 51_000 < a.avg_price < 54_000
