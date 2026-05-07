"""일봉 시세 백필.

사용:
  python -m prog_stock.tools.backfill_history --years 5
  python -m prog_stock.tools.backfill_history --symbols 005930,000660 --years 3

페이퍼 트레이딩 시작 전 1회 실행 권장. 매일 16:00 운영 루프가 갱신.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import structlog

from prog_stock.config import settings
from prog_stock.data import universe as univ
from prog_stock.data.history import update_cache

log = structlog.get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="", help="comma-separated; empty = today's universe")
    parser.add_argument("--years", type=int, default=5)
    args = parser.parse_args()

    settings.ensure_dirs()
    today = date.today()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        log.info("building_universe_for_backfill", date=today.isoformat())
        df = univ.build_universe(today, settings.min_market_cap_krw)
        univ.save_snapshot(df, today, settings.cache_dir_universe)
        symbols = df["symbol"].tolist()

    log.info("backfill_start", count=len(symbols), years=args.years)

    failures: list[tuple[str, str]] = []
    for i, sym in enumerate(symbols, 1):
        try:
            df = update_cache(sym, settings.cache_dir_ohlcv, today=today)
            log.info("backfill_ok", symbol=sym, rows=len(df), pct=f"{i}/{len(symbols)}")
        except Exception as e:
            log.warning("backfill_failed", symbol=sym, error=str(e))
            failures.append((sym, str(e)))

    log.info("backfill_complete", ok=len(symbols) - len(failures), failed=len(failures))
    if failures:
        for sym, err in failures[:20]:
            print(f"FAIL {sym}: {err}")


if __name__ == "__main__":
    main()
