"""08:50 사전 점검 리포트 — 오늘 매수 후보, 청산 예정, 잔여 한도, 뉴스, 거시 이벤트."""
from __future__ import annotations

from datetime import date

import pandas as pd

from prog_stock.brokers.port import BrokerPort
from prog_stock.config import settings
from prog_stock.data import universe as univ
from prog_stock.data.history import load_history
from prog_stock.news import monitor as news_monitor
from prog_stock.storage.db import Database
from prog_stock.strategies.canslim_sepa import CanslimSepaStrategy


def build_report(today: date, broker: BrokerPort, strategy: CanslimSepaStrategy,
                 db: Database | None = None) -> str:
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

    if db is not None:
        lines.append("")
        events = news_monitor.upcoming_macro_events(db, today, days=3)
        if events:
            lines.append(f"📅 향후 3일 거시 이벤트 {len(events)}건:")
            for e in events:
                lines.append(f"  • {e['event_date']} {e['event_type']} [{e['impact_level']}] {e['description']}")

        news = news_monitor.todays_news_summary(db, today, limit=5)
        if news:
            lines.append("")
            lines.append(f"📰 오늘 주요 뉴스:")
            for n in news:
                sym = f"[{n['symbol']}] " if n.get("symbol") else ""
                lines.append(f"  • {sym}{n['headline']}")

    return "\n".join(lines)
