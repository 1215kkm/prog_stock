"""KOSPI200 지수 백필 (시장 필터 'M' 판정용).

사용:
  python -m prog_stock.tools.backfill_market_index --years 3
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import pandas as pd
import structlog

from prog_stock.config import settings

log = structlog.get_logger(__name__)


def fetch_kospi200_index(start: date, end: date) -> pd.DataFrame:
    from pykrx import stock

    df = stock.get_index_ohlcv(
        start.isoformat().replace("-", ""),
        end.isoformat().replace("-", ""),
        "1028",  # 코스피200
    )
    df = df.reset_index().rename(
        columns={"날짜": "date", "시가": "open", "고가": "high", "저가": "low",
                 "종가": "close", "거래량": "volume"}
    )
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["date", "open", "high", "low", "close", "volume"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=3)
    args = parser.parse_args()

    settings.ensure_dirs()
    end = date.today()
    start = end - timedelta(days=args.years * 365)

    log.info("market_index_backfill_start", start=start.isoformat(), end=end.isoformat())
    df = fetch_kospi200_index(start, end)
    path = settings.cache_dir_market / "kospi200_index.parquet"
    df.to_parquet(path, index=False)
    log.info("market_index_backfill_complete", rows=len(df), path=str(path))


if __name__ == "__main__":
    main()
