"""DART 분기 실적 백필.

사용:
  python -m prog_stock.tools.backfill_fundamentals --years 2024,2025
"""
from __future__ import annotations

import argparse
from datetime import date

import structlog

from prog_stock.config import settings
from prog_stock.data import universe as univ
from prog_stock.data.fundamentals import update_cache

log = structlog.get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="")
    parser.add_argument("--years", default=str(date.today().year))
    args = parser.parse_args()

    if not settings.dart_api_key:
        raise SystemExit("DART_API_KEY not set in .env")

    settings.ensure_dirs()
    years = [int(y) for y in args.years.split(",")]

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        df = univ.load_snapshot(date.today(), settings.cache_dir_universe)
        if df is None:
            df = univ.build_universe(date.today(), settings.min_market_cap_krw)
            univ.save_snapshot(df, date.today(), settings.cache_dir_universe)
        symbols = df["symbol"].tolist()

    log.info("dart_backfill_start", count=len(symbols), years=years)
    df = update_cache(
        api_key=settings.dart_api_key,
        symbols=symbols,
        cache_path=settings.fundamentals_path,
        years=years,
    )
    log.info("dart_backfill_complete", rows=len(df))


if __name__ == "__main__":
    main()
