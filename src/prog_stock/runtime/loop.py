"""운영 이벤트 루프 — dry_run / paper / live 공통.

매일 06:00 데이터 갱신, 08:50 사전점검, 09:00 매매 시작, 16:00 일일 리포트.
상태(peak equity, daily start, halt flag)는 RuntimeState에 영속화.
CLI 명령(/halt /resume /kill)은 system_events 폴링으로 수신.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import date, datetime, time as dtime, timedelta

import pandas as pd
import structlog

from prog_stock.agents.orchestrator import Orchestrator
from prog_stock.agents.regime import RegimeDetectorAgent
from prog_stock.brokers.kis_adapter import KisAdapter
from prog_stock.brokers.paper_adapter import PaperAdapter
from prog_stock.brokers.port import BrokerPort, OrderType, Side
from prog_stock.config import RunMode, settings
from prog_stock.data import calendar as cal
from prog_stock.data import universe as univ
from prog_stock.data.history import load_history, update_cache as update_history_cache
from prog_stock.execution.order_manager import ManagerConfig, OrderManager
from prog_stock.monitoring.morning_report import build_report
from prog_stock.monitoring.telegram_bot import TelegramNotifier
from prog_stock.risk.guard import GuardConfig, GuardContext, RiskGuard
from prog_stock.risk.sizing import calc_quantity
from prog_stock.runtime.logging_config import configure as configure_logging
from prog_stock.runtime.state import RuntimeState, StateStore
from prog_stock.storage.db import Database
from prog_stock.strategies.base import Action
from prog_stock.strategies.canslim_sepa import CanslimSepaStrategy

log = structlog.get_logger(__name__)


class TradingLoop:
    def __init__(self, mode: RunMode) -> None:
        self.mode = mode
        settings.ensure_dirs()
        configure_logging(settings.cache_dir.parent / "logs", settings.log_level)
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
        self.state_store = StateStore(settings.cache_dir / "runtime_state.json")
        self.state: RuntimeState = self.state_store.load()
        self.notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
        self.orchestrator = Orchestrator(self.db, self.notifier, self.broker)
        self._kill = False
        self._last_event_id = self._latest_event_id()
        self._last_orchestrator_date: date | None = None

    def _build_broker(self) -> BrokerPort:
        if self.mode == RunMode.LIVE:
            return KisAdapter(
                app_key=settings.kis_app_key,
                app_secret=settings.kis_app_secret,
                account_number=settings.kis_account_number,
                virtual=False,
            )
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
            state_path=settings.cache_dir / f"paper_state_{self.mode.value}.json",
        )

    def request_stop(self) -> None:
        self._kill = True
        log.warning("kill_switch_requested")

    def _latest_event_id(self) -> int:
        with self.db.connect() as conn:
            row = conn.execute("SELECT MAX(id) AS mx FROM system_events").fetchone()
        return int(row["mx"] or 0)

    def _poll_commands(self) -> None:
        """CLI 명령(HALT/RESUME/KILL_SWITCH)을 system_events에서 폴링."""
        with self.db.connect() as conn:
            new = list(conn.execute(
                "SELECT id, kind FROM system_events WHERE id > ? AND kind LIKE 'CMD_%' ORDER BY id ASC",
                (self._last_event_id,),
            ))
        for row in new:
            self._last_event_id = max(self._last_event_id, int(row["id"]))
            kind = row["kind"]
            if kind == "CMD_KILL_SWITCH":
                self._kill = True
                self.notifier.send("🛑 KILL switch received — liquidating and stopping.")
            elif kind == "CMD_HALT":
                self.state.halt_engaged = True
                self.state_store.save(self.state)
                self.notifier.send("⏸️  HALT — new buys blocked. holdings remain.")
            elif kind == "CMD_RESUME":
                self.state.halt_engaged = False
                self.state_store.save(self.state)
                self.notifier.send("▶️  RESUME — new buys re-enabled.")

    def _market_filter_on(self, today: date) -> bool:
        """KOSPI200 > 200MA 캐시 (1일 1회)."""
        if self.state.last_market_filter_check == today.isoformat():
            return self.state.market_filter_on
        path = settings.cache_dir_market / "kospi200_index.parquet"
        if not path.exists():
            log.warning("market_index_missing_assume_on")
            return True
        df = pd.read_parquet(path).sort_values("date").copy()
        df["ma200"] = df["close"].rolling(200).mean()
        df = df[df["date"] <= today]
        if df.empty or pd.isna(df.iloc[-1]["ma200"]):
            on = True
        else:
            on = bool(df.iloc[-1]["close"] > df.iloc[-1]["ma200"])
        self.state.market_filter_on = on
        self.state.last_market_filter_check = today.isoformat()
        self.state_store.save(self.state)
        return on

    def _liquidate_all(self) -> None:
        positions = self.broker.positions()
        if not positions:
            return
        ctx = self._build_ctx(positions, self.broker.balance())
        for pos in positions:
            quote = self.broker.quote(pos.symbol)
            self.om.submit_with_market_fallback(
                symbol=pos.symbol,
                side=Side.SELL,
                quantity=pos.quantity,
                limit_price=quote.bid,
                reason="KILL_LIQUIDATE",
                ctx=ctx,
            )

    def _build_ctx(self, positions, balance) -> GuardContext:
        # peak equity 갱신
        if balance.total_equity > self.state.peak_equity:
            self.state.peak_equity = balance.total_equity
            self.state_store.save(self.state)

        drawdown = (
            (balance.total_equity - self.state.peak_equity) / self.state.peak_equity
            if self.state.peak_equity else 0.0
        )

        today = datetime.now().date()
        self.state = self.state_store.reset_daily(self.state, today, balance.total_equity)
        daily_pnl_pct = (
            (balance.total_equity - self.state.daily_start_equity) / self.state.daily_start_equity
            if self.state.daily_start_equity else 0.0
        )

        # 쿨다운 심볼 로드
        with self.db.connect() as conn:
            cooldowns = {
                row["symbol"] for row in conn.execute(
                    "SELECT symbol FROM cooldowns WHERE mode = ? AND until_date >= ?",
                    (self.mode.value, today.isoformat()),
                )
            }
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM orders WHERE status = 'PENDING' AND mode = ?",
                (self.mode.value,),
            ).fetchone()["n"]

        return GuardContext(
            now=datetime.now(),
            equity=balance.total_equity,
            cash=balance.cash,
            daily_pnl_pct=daily_pnl_pct,
            drawdown_from_peak=drawdown,
            open_positions_count=len(positions),
            pending_orders_count=int(pending),
            recent_balance_change_pct=0.0,
            market_filter_off=not self._market_filter_on(today) or self.state.halt_engaged,
            kill_switch_engaged=self._kill,
            in_call_auction=cal.in_call_auction(datetime.now()),
            cooldown_symbols=cooldowns,
        )

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self.request_stop())
        signal.signal(signal.SIGTERM, lambda *_: self.request_stop())
        log.info("loop_started", mode=self.mode.value)
        self.notifier.send(f"🚀 prog_stock started ({self.mode.value})")

        while not self._kill:
            now = datetime.now()
            today = now.date()
            if not cal.is_session(today):
                self._sleep_until_next_session()
                continue

            self._morning_prep(today)
            self._send_morning_report(today)

            if now.time() < dtime(9, 0):
                self._sleep_until(today, dtime(9, 0))

            self._intraday_loop(today)

            self._post_market(today)
            self._run_orchestrator_if_due(today)
            self._sleep_until_next_session()

        if self._kill:
            self._liquidate_all()
            self.notifier.send("✅ system stopped — all liquidated")
        log.info("loop_stopped")

    def _morning_prep(self, today: date) -> None:
        log.info("morning_prep", date=today.isoformat())
        try:
            df = univ.build_universe(today, settings.min_market_cap_krw)
            univ.save_snapshot(df, today, settings.cache_dir_universe)
        except Exception as e:
            log.error("universe_build_failed", error=str(e))

    def _send_morning_report(self, today: date) -> None:
        try:
            text = build_report(today, self.broker, self.strategy, self.db)
            self.notifier.send(text)
        except Exception as e:
            log.error("morning_report_failed", error=str(e))

    def _intraday_loop(self, today: date) -> None:
        end_time = dtime(15, 20)
        while datetime.now().time() < end_time and not self._kill:
            try:
                self._poll_commands()
                if self._kill:
                    break
                self._tick_iteration(today)
            except Exception as e:
                log.exception("tick_iteration_failed", error=str(e))
            time.sleep(60)

    def _tick_iteration(self, today: date) -> None:
        positions = self.broker.positions()
        balance = self.broker.balance()
        ctx = self._build_ctx(positions, balance)

        history_loader = lambda s: load_history(s, settings.cache_dir_ohlcv)
        fundamentals = (
            pd.read_parquet(settings.fundamentals_path)
            if settings.fundamentals_path.exists() else pd.DataFrame()
        )

        # 보유 종목 청산 평가
        if positions:
            sells = self.strategy.evaluate_holdings(today, positions, history_loader, fundamentals)
            for sig in sells:
                if sig.action == Action.SELL:
                    pos = next((p for p in positions if p.symbol == sig.symbol), None)
                    if pos is None:
                        continue
                    quote = self.broker.quote(sig.symbol)
                    gres, _ = self.om.submit_with_market_fallback(
                        symbol=sig.symbol, side=Side.SELL, quantity=pos.quantity,
                        limit_price=quote.bid, reason=sig.reason, ctx=ctx,
                    )
                    if gres.approved and sig.reason == "STOP_LOSS":
                        until = (today + timedelta(days=settings.cooldown_days)).isoformat()
                        self.db.add_cooldown(sig.symbol, self.mode.value, until, "STOP_LOSS")

        # 신규 매수 (장 초반 30분 회피)
        if datetime.now().time() < dtime(9, 30):
            return
        snapshot = univ.load_snapshot(today, settings.cache_dir_universe)
        if snapshot is None or snapshot.empty:
            return
        market_idx_path = settings.cache_dir_market / "kospi200_index.parquet"
        market_idx = pd.read_parquet(market_idx_path) if market_idx_path.exists() else pd.DataFrame()

        buys = self.strategy.select_candidates(today, snapshot, history_loader, fundamentals, market_idx)
        capital_scale = self._capital_scale()
        scaled_equity = balance.total_equity * capital_scale
        for sig in buys:
            if sig.action != Action.BUY or sig.target_price is None:
                continue
            qty = calc_quantity(
                equity=scaled_equity, price=sig.target_price,
                risk_per_trade=settings.risk_per_trade,
                stop_loss_pct=settings.hard_stop_loss,
                max_position_pct=settings.max_position_pct,
            )
            if qty <= 0:
                continue
            self.om.submit_with_market_fallback(
                symbol=sig.symbol, side=Side.BUY, quantity=qty,
                limit_price=sig.target_price * 1.005,
                reason="ENTRY_BREAKOUT", ctx=ctx,
            )

    def _run_orchestrator_if_due(self, today: date) -> None:
        """16:30 이후 에이전트 daily pipeline + 일요일이면 weekly."""
        if self._last_orchestrator_date == today:
            return
        try:
            self.orchestrator.daily_pipeline()
            if today.weekday() == 6:  # Sunday
                self.orchestrator.weekly_pipeline()
            self._last_orchestrator_date = today
        except Exception as e:
            log.exception("orchestrator_failed", error=str(e))

    def _capital_scale(self) -> float:
        """레짐 감지기가 결정한 자본 비중 (0.25 ~ 1.0)."""
        return RegimeDetectorAgent.current_capital_scale(self.db)

    def _post_market(self, today: date) -> None:
        balance = self.broker.balance()
        drawdown = (
            (balance.total_equity - self.state.peak_equity) / self.state.peak_equity
            if self.state.peak_equity else 0.0
        )
        daily_pnl = (
            balance.total_equity - self.state.daily_start_equity
            if self.state.daily_start_equity else 0.0
        )
        with self.db.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO equity_snapshots
                   (snapshot_date, mode, cash, positions_value, total_equity, daily_pnl, drawdown_from_peak)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (today.isoformat(), self.mode.value, balance.cash, balance.positions_value,
                 balance.total_equity, daily_pnl, drawdown),
            )

        # 일봉 캐시 갱신
        snapshot = univ.load_snapshot(today, settings.cache_dir_universe)
        if snapshot is not None:
            for sym in snapshot["symbol"].head(50):
                try:
                    update_history_cache(sym, settings.cache_dir_ohlcv, today)
                except Exception as e:
                    log.warning("history_update_failed", symbol=sym, error=str(e))

        self.notifier.send(
            f"📈 [{today}] 장마감\n"
            f"잔고: {balance.total_equity:,.0f}원\n"
            f"일일 P&L: {daily_pnl:+,.0f}원 ({daily_pnl / max(self.state.daily_start_equity, 1):+.2%})\n"
            f"낙폭(고점 대비): {drawdown:.2%}"
        )

    def _sleep_until(self, today: date, target: dtime) -> None:
        now = datetime.now()
        target_dt = datetime.combine(today, target)
        secs = (target_dt - now).total_seconds()
        if secs > 0:
            time.sleep(min(secs, 600))

    def _sleep_until_next_session(self) -> None:
        nxt = cal.next_session(date.today())
        target = datetime.combine(nxt, dtime(8, 30))
        secs = (target - datetime.now()).total_seconds()
        if secs > 0:
            time.sleep(min(secs, 3600))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=[m.value for m in RunMode], required=True)
    args = parser.parse_args()
    loop = TradingLoop(RunMode(args.mode))
    try:
        loop.run()
    except KeyboardInterrupt:
        loop.request_stop()
    sys.exit(0)


if __name__ == "__main__":
    main()
