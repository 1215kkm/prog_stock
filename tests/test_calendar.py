"""거래일 캘린더 / 동시호가 시간 판정 테스트."""
from __future__ import annotations

from datetime import datetime

from prog_stock.data import calendar as cal


class TestCallAuction:
    def test_open_auction_window(self):
        assert cal.in_call_auction(datetime(2026, 5, 7, 8, 30))
        assert cal.in_call_auction(datetime(2026, 5, 7, 8, 59))

    def test_close_auction_window(self):
        assert cal.in_call_auction(datetime(2026, 5, 7, 15, 20))
        assert cal.in_call_auction(datetime(2026, 5, 7, 15, 29))

    def test_outside_auction(self):
        assert not cal.in_call_auction(datetime(2026, 5, 7, 9, 30))
        assert not cal.in_call_auction(datetime(2026, 5, 7, 14, 0))
        assert not cal.in_call_auction(datetime(2026, 5, 7, 16, 0))

    def test_regular_session_window(self):
        assert cal.in_regular_session(datetime(2026, 5, 7, 9, 0))
        assert cal.in_regular_session(datetime(2026, 5, 7, 15, 29))
        assert not cal.in_regular_session(datetime(2026, 5, 7, 8, 59))
        assert not cal.in_regular_session(datetime(2026, 5, 7, 15, 30))
