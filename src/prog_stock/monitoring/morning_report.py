"""08:50 사전 점검 리포트 — 오늘 매수 후보, 청산 예정, 잔여 한도."""
from __future__ import annotations

from datetime import date

import pandas as pd

from prog_stock.brokers.port import BrokerPort
from prog_stock.config import settings
from prog_stock.data import universe as univ
from prog_stock.data.history import load_history
from prog_stock.strategies.canslim_sepa import CanslimSepaStrategy


def build_report(today: date, broker: BrokerPort, strategy: CanslimSepaStrategy) -> str:
    snapshot = univ.load_snapshot(today, settings.cache_dir_universe)
    if snapshot is None:
        return f"[{today}] 사전 점검 — universe 미생성"

    fundamentals = (
        pd.read_parquet(settings.fundamentals_path)
        if settings.fundamentals_path.exists() else pd.DataFrame()
    )
    market_idx_path = settings.cache_dir_market / "kospi200_index.parquet"
    market_idx = pd.read_parquet(market_idx_path) if market_idx_path.exists() else pd.DataFrame()

    history_loader = lambda s: load_history(s, settings.cache_dir_ohlcv)

    buys = strategy.select_candidates(today, snapshot, history_loader, fundamentals, market_idx)
    positions = broker.positions()
    sells = strategy.evaluate_holdings(today, positions, history_loader, fundamentals)
    balance = broker.balance()

    lines = [f"📊 [{today}] 사전 점검", ""]
    lines.append(f"잔고: {balance.total_equity:,.0f}원 (현금 {balance.cash:,.0f})")
    lines.append(f"보유: {len(positions)}/{settings.max_positions}종목")
    lines.append("")

    if buys:
        lines.append(f"🟢 매수 후보 {len(buys)}종목:")
        for s in buys[:10]:
            lines.append(f"  • {s.symbol} @ {s.target_price:,.0f} ({s.reason})")
    else:
        lines.append("🟢 매수 후보 없음 (시장 필터 OFF 또는 신호 없음)")
    lines.append("")

    sell_signals = [s for s in sells if s.action.value == "SELL"]
    if sell_signals:
        lines.append(f"🔴 청산 예정 {len(sell_signals)}종목:")
        for s in sell_signals:
            lines.append(f"  • {s.symbol} ({s.reason})")
    else:
        lines.append("🔴 청산 예정 없음")

    return "\n".join(lines)
