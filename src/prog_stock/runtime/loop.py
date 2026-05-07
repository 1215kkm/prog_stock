"""운영 이벤트 루프 — dry_run / paper / live 공통.

매일 06:00 데이터 갱신, 08:50 사전점검, 09:00 매매 시작, 16:00 일일 리포트.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import date, datetime, time as dtime

import pandas as pd
import structlog

from prog_stock.brokers.kis_adapter import KisAdapter
from prog_stock.brokers.paper_adapter import PaperAdapter
from prog_stock.brokers.port import BrokerPort, OrderType, Side
from prog_stock.config import RunMode, settings
from prog_stock.data import calendar as cal
from prog_stock.data import universe as univ
from prog_stock.data.history import load_history, update_cache as update_history_cache
from prog_stock.execution.order_manager import ManagerConfig, OrderManager
from prog_stock.risk.guard import GuardConfig, GuardContext, RiskGuard
from prog_stock.risk.sizing import calc_quantity
from prog_stock.storage.db import Database
from prog_stock.strategies.base import Action
from prog_stock.strategies.canslim_sepa import CanslimSepaStrategy

log = structlog.get_logger(__name__)


class TradingLoop:
    def __init__(self, mode: RunMode) -> None:
        self.mode = mode
        settings.ensure_dirs()
        self.db = Database(settings.db_path)
        self.broker: BrokerPort = self._build_broker()
        self.strategy = CanslimSepaStrategy()
        self.guard = RiskGuard(GuardConfig(
            daily_loss_limit=settings.daily_loss_limit,
            mdd_limit=settings.mdd_limit,
            max_positions=settings.max_positions,
            max_position_pct=settings.max_position_pct,
        ))
        self.om = OrderManager(self.broker, self.guard, self.db,
                               ManagerConfig(rate_per_second=18.0, mode=mode.value))
        self._kill = False
        self._peak_equity: float | None = None

    def _build_broker(self) -> BrokerPort:
        if self.mode == RunMode.LIVE:
            return KisAdapter(
                app_key=settings.kis_app_key,
                app_secret=settings.kis_app_secret,
                account_number=settings.kis_account_number,
                virtual=False,
            )
        # dry_run / paper 모두 KIS 시세 + Paper 어댑터
        kis = KisAdapter(
            app_key=settings.kis_app_key,
            app_secret=settings.kis_app_secret,
            account_number=settings.kis_account_number,
            virtual=settings.kis_virtual,
        )
        return PaperAdapter(
            quote_source=kis,
            slippage_rate=settings.slippage_rate,
            commission_rate=settings.commission_rate,
            sell_tax_rate=settings.sell_tax_rate,
        )

    def request_stop(self) -> None:
        self._kill = True
        log.warning("kill_switch_requested")

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self.request_stop())
        signal.signal(signal.SIGTERM, lambda *_: self.request_stop())
        log.info("loop_started", mode=self.mode.value)

        while not self._kill:
            now = datetime.now()
            today = now.date()
            if not cal.is_session(today):
                self._sleep_until_next_session()
                continue

            self._morning_prep(today)

            # 장 시작 대기
            if now.time() < dtime(9, 0):
                self._sleep_until(today, dtime(9, 0))

            self._intraday_loop(today)

            self._post_market(today)
            self._sleep_until_next_session()

        log.info("loop_stopped")

    def _morning_prep(self, today: date) -> None:
        log.info("morning_prep", date=today.isoformat())
        try:
            df = univ.build_universe(today, settings.min_market_cap_krw)
            univ.save_snapshot(df, today, settings.cache_dir_universe)
        except Exception as e:
            log.error("universe_build_failed", error=str(e))

    def _intraday_loop(self, today: date) -> None:
        end_time = dtime(15, 20)
        while datetime.now().time() < end_time and not self._kill:
            try:
                self._tick_iteration(today)
            except Exception as e:
                log.exception("tick_iteration_failed", error=str(e))
            time.sleep(60)  # 1분 주기

    def _tick_iteration(self, today: date) -> None:
        balance = self.broker.balance()
        if self._peak_equity is None or balance.total_equity > self._peak_equity:
            self._peak_equity = balance.total_equity
        drawdown = (balance.total_equity - self._peak_equity) / self._peak_equity if self._peak_equity else 0.0

        ctx = GuardContext(
            now=datetime.now(),
            equity=balance.total_equity,
            cash=balance.cash,
            daily_pnl_pct=0.0,  # TODO: 일일 P&L 계산 (전일 종가 대비)
            drawdown_from_peak=drawdown,
            open_positions_count=len(self.broker.positions()),
            pending_orders_count=0,
            recent_balance_change_pct=0.0,
            market_filter_off=False,  # TODO: KOSPI200 vs 200MA
            kill_switch_engaged=self._kill,
            in_call_auction=cal.in_call_auction(datetime.now()),
        )

        # 보유 종목 청산 평가
        positions = self.broker.positions()
        history_loader = lambda s: load_history(s, settings.cache_dir_ohlcv)
        fundamentals = (
            pd.read_parquet(settings.fundamentals_path)
            if settings.fundamentals_path.exists() else pd.DataFrame()
        )

        if positions:
            sells = self.strategy.evaluate_holdings(today, positions, history_loader, fundamentals)
            for sig in sells:
                if sig.action == Action.SELL:
                    pos = next((p for p in positions if p.symbol == sig.symbol), None)
                    if pos is None:
                        continue
                    quote = self.broker.quote(sig.symbol)
                    self.om.submit_with_market_fallback(
                        symbol=sig.symbol,
                        side=Side.SELL,
                        quantity=pos.quantity,
                        limit_price=quote.bid,
                        reason=sig.reason,
                        ctx=ctx,
                    )

        # 신규 매수 (장 초반 30분 회피)
        if datetime.now().time() < dtime(9, 30):
            return
        snapshot = univ.load_snapshot(today, settings.cache_dir_universe)
        if snapshot is None or snapshot.empty:
            return
        market_idx_path = settings.cache_dir_market / "kospi200_index.parquet"
        market_idx = pd.read_parquet(market_idx_path) if market_idx_path.exists() else pd.DataFrame()

        buys = self.strategy.select_candidates(today, snapshot, history_loader, fundamentals, market_idx)
        for sig in buys:
            if sig.action != Action.BUY or sig.target_price is None:
                continue
            qty = calc_quantity(
                equity=balance.total_equity,
                price=sig.target_price,
                risk_per_trade=settings.risk_per_trade,
                stop_loss_pct=settings.hard_stop_loss,
                max_position_pct=settings.max_position_pct,
            )
            if qty <= 0:
                continue
            self.om.submit_with_market_fallback(
                symbol=sig.symbol,
                side=Side.BUY,
                quantity=qty,
                limit_price=sig.target_price * 1.005,
                reason="ENTRY_BREAKOUT",
                ctx=ctx,
            )

    def _post_market(self, today: date) -> None:
        balance = self.broker.balance()
        with self.db.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO equity_snapshots
                   (snapshot_date, mode, cash, positions_value, total_equity, daily_pnl, drawdown_from_peak)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (today.isoformat(), self.mode.value, balance.cash, balance.positions_value,
                 balance.total_equity, None,
                 (balance.total_equity - (self._peak_equity or balance.total_equity))
                 / (self._peak_equity or 1)),
            )

        # 일봉 캐시 갱신
        snapshot = univ.load_snapshot(today, settings.cache_dir_universe)
        if snapshot is not None:
            for sym in snapshot["symbol"].head(50):  # 비용 절약
                try:
                    update_history_cache(sym, settings.cache_dir_ohlcv, today)
                except Exception as e:
                    log.warning("history_update_failed", symbol=sym, error=str(e))

    def _sleep_until(self, today: date, target: dtime) -> None:
        now = datetime.now()
        target_dt = datetime.combine(today, target)
        secs = (target_dt - now).total_seconds()
        if secs > 0:
            log.info("sleep_until", target=target_dt.isoformat(), seconds=int(secs))
            time.sleep(min(secs, 600))

    def _sleep_until_next_session(self) -> None:
        nxt = cal.next_session(date.today())
        target = datetime.combine(nxt, dtime(8, 30))
        secs = (target - datetime.now()).total_seconds()
        if secs > 0:
            log.info("sleep_until_next_session", target=target.isoformat())
            time.sleep(min(secs, 3600))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=[m.value for m in RunMode], required=True)
    args = parser.parse_args()
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.JSONRenderer()],
    )
    loop = TradingLoop(RunMode(args.mode))
    try:
        loop.run()
    except KeyboardInterrupt:
        loop.request_stop()
    sys.exit(0)


if __name__ == "__main__":
    main()
