"""백테스트 러너 — 전략 시그널을 과거 시계열에 적용해 성과 산출.

구현 노트:
- vectorbt가 ideal이지만 무거운 의존성 → 자체 이벤트 기반 simulator로 시작.
- 수수료(0.015%) + 매도 거래세(0.18%) + 슬리피지(0.1%) 반영.
- 룩어헤드 방지: 시그널 생성 시점에 그 날짜까지의 데이터만 사용.
- vectorbt 통합은 추후 CanslimSepaStrategy 신호 벡터화 후 추가.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import structlog

from prog_stock.config import settings
from prog_stock.data.history import load_history
from prog_stock.strategies.base import Action, Signal
from prog_stock.strategies.canslim_sepa import CanslimSepaConfig, CanslimSepaStrategy

log = structlog.get_logger(__name__)


@dataclass
class BacktestConfig:
    starting_cash: float = 10_000_000.0
    max_positions: int = 5
    risk_per_trade: float = 0.015
    hard_stop_loss: float = -0.07
    max_position_pct: float = 0.25
    commission: float = 0.00015
    sell_tax: float = 0.0018
    slippage: float = 0.001
    cooldown_days: int = 30


@dataclass
class BacktestState:
    cash: float
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    positions: dict[str, dict] = field(default_factory=dict)  # sym -> {qty, avg_price, opened, peak}
    trades: list[dict] = field(default_factory=list)
    cooldowns: dict[str, date] = field(default_factory=dict)  # sym -> until


def _equity(state: BacktestState, prices: dict[str, float]) -> float:
    pos_value = sum(p["qty"] * prices.get(s, p["avg_price"]) for s, p in state.positions.items())
    return state.cash + pos_value


def _execute_buy(state: BacktestState, sym: str, price: float, cfg: BacktestConfig, today: date,
                 equity: float) -> bool:
    if sym in state.positions or len(state.positions) >= cfg.max_positions:
        return False
    if sym in state.cooldowns and state.cooldowns[sym] >= today:
        return False
    fill = price * (1 + cfg.slippage)
    risk_based = (equity * cfg.risk_per_trade) / abs(cfg.hard_stop_loss)
    cap = equity * cfg.max_position_pct
    target = min(risk_based, cap, state.cash)
    qty = int(target // fill)
    if qty <= 0:
        return False
    cost = fill * qty * (1 + cfg.commission)
    if cost > state.cash:
        return False
    state.cash -= cost
    state.positions[sym] = {"qty": qty, "avg_price": fill, "opened": today, "peak": fill}
    return True


def _execute_sell(state: BacktestState, sym: str, price: float, cfg: BacktestConfig, today: date,
                  reason: str) -> None:
    pos = state.positions.pop(sym, None)
    if pos is None:
        return
    fill = price * (1 - cfg.slippage)
    notional = fill * pos["qty"]
    commission = notional * cfg.commission
    tax = notional * cfg.sell_tax
    proceeds = notional - commission - tax
    state.cash += proceeds
    gross = (fill - pos["avg_price"]) * pos["qty"]
    net = gross - commission - tax - (pos["avg_price"] * pos["qty"] * cfg.commission)
    state.trades.append({
        "symbol": sym,
        "entry_at": pos["opened"],
        "entry_price": pos["avg_price"],
        "exit_at": today,
        "exit_price": fill,
        "qty": pos["qty"],
        "gross_pnl": gross,
        "net_pnl": net,
        "return_pct": (fill - pos["avg_price"]) / pos["avg_price"],
        "holding_days": (today - pos["opened"]).days,
        "exit_reason": reason,
    })
    if reason == "STOP_LOSS":
        state.cooldowns[sym] = today + timedelta(days=cfg.cooldown_days)


def run_backtest(
    start: date,
    end: date,
    universe_symbols: list[str],
    fundamentals: pd.DataFrame,
    market_index: pd.DataFrame,
    cache_dir: Path,
    cfg: BacktestConfig | None = None,
    strategy: CanslimSepaStrategy | None = None,
) -> dict:
    cfg = cfg or BacktestConfig()
    strat = strategy or CanslimSepaStrategy(CanslimSepaConfig())

    state = BacktestState(cash=cfg.starting_cash)
    history_loader = lambda sym: load_history(sym, cache_dir)

    universe_df = pd.DataFrame({"symbol": universe_symbols})

    sessions = pd.date_range(start, end, freq="B").date  # 영업일 근사

    for today in sessions:
        # 보유 종목 평가 (청산)
        from prog_stock.brokers.port import Position
        held = []
        for sym, p in state.positions.items():
            df = history_loader(sym)
            if df.empty:
                continue
            df = df[df["date"] <= today]
            if df.empty:
                continue
            last_price = float(df.iloc[-1]["close"])
            held.append(Position(symbol=sym, quantity=p["qty"], avg_price=p["avg_price"], current_price=last_price))
            p["peak"] = max(p["peak"], last_price)

        signals = strat.evaluate_holdings(today, held, history_loader, fundamentals)
        for s in signals:
            if s.action == Action.SELL:
                df = history_loader(s.symbol)
                df = df[df["date"] <= today]
                if not df.empty:
                    _execute_sell(state, s.symbol, float(df.iloc[-1]["close"]), cfg, today, s.reason)

        # 신규 매수 후보
        buy_signals = strat.select_candidates(today, universe_df, history_loader, fundamentals, market_index)
        prices_today = {}
        for sig in buy_signals:
            df = history_loader(sig.symbol)
            df = df[df["date"] <= today]
            if df.empty:
                continue
            prices_today[sig.symbol] = float(df.iloc[-1]["close"])

        eq = _equity(state, prices_today | {s: state.positions[s]["avg_price"] for s in state.positions})
        for sig in buy_signals:
            if sig.action == Action.BUY and sig.symbol in prices_today:
                _execute_buy(state, sig.symbol, prices_today[sig.symbol], cfg, today, eq)

        # equity 스냅샷
        all_prices = {}
        for s in state.positions:
            df = history_loader(s)
            df = df[df["date"] <= today]
            if not df.empty:
                all_prices[s] = float(df.iloc[-1]["close"])
        state.equity_curve.append((today, _equity(state, all_prices)))

    return _summarize(state, cfg)


def _summarize(state: BacktestState, cfg: BacktestConfig) -> dict:
    if not state.equity_curve:
        return {"trades": 0, "final_equity": cfg.starting_cash}
    eq_df = pd.DataFrame(state.equity_curve, columns=["date", "equity"])
    eq_df["return"] = eq_df["equity"].pct_change().fillna(0)
    final = float(eq_df["equity"].iloc[-1])
    cagr = (final / cfg.starting_cash) ** (252 / max(len(eq_df), 1)) - 1
    rolling_max = eq_df["equity"].cummax()
    mdd = float(((eq_df["equity"] - rolling_max) / rolling_max).min())
    sharpe = float(eq_df["return"].mean() / eq_df["return"].std() * (252 ** 0.5)) if eq_df["return"].std() > 0 else 0.0

    trades = pd.DataFrame(state.trades)
    win_rate = float((trades["net_pnl"] > 0).mean()) if not trades.empty else 0.0
    avg_win = float(trades.loc[trades["net_pnl"] > 0, "net_pnl"].mean()) if (trades["net_pnl"] > 0).any() else 0.0
    avg_loss = float(trades.loc[trades["net_pnl"] < 0, "net_pnl"].mean()) if (trades["net_pnl"] < 0).any() else 0.0
    pf = float(trades.loc[trades["net_pnl"] > 0, "net_pnl"].sum() / abs(trades.loc[trades["net_pnl"] < 0, "net_pnl"].sum())) if avg_loss < 0 else float("inf")

    return {
        "trades": len(trades),
        "final_equity": final,
        "cagr": cagr,
        "mdd": mdd,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": pf,
        "equity_curve": state.equity_curve,
        "trades_df": trades,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="canslim_sepa")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--symbols", type=str, default="", help="comma-separated, default = read snapshot")
    args = parser.parse_args()

    settings.ensure_dirs()
    end = date.today()
    start = end.replace(year=end.year - args.years)
    if not args.symbols:
        log.warning("no_symbols_given_use_universe_snapshot")
        symbols: list[str] = []
    else:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    fundamentals = pd.read_parquet(settings.fundamentals_path) if settings.fundamentals_path.exists() else pd.DataFrame()
    market_index_path = settings.cache_dir_market / "kospi200_index.parquet"
    market_index = pd.read_parquet(market_index_path) if market_index_path.exists() else pd.DataFrame()

    summary = run_backtest(
        start=start,
        end=end,
        universe_symbols=symbols,
        fundamentals=fundamentals,
        market_index=market_index,
        cache_dir=settings.cache_dir_ohlcv,
    )
    print({k: v for k, v in summary.items() if k not in ("equity_curve", "trades_df")})


if __name__ == "__main__":
    main()
