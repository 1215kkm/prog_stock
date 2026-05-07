"""KIS 모의투자 잔고 조회 PoC."""
from __future__ import annotations

import sys

from prog_stock.brokers.kis_adapter import KisAdapter
from prog_stock.config import settings


def main() -> None:
    if not settings.kis_app_key or not settings.kis_account_number:
        print("ERROR: .env에 KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NUMBER 설정 필요", file=sys.stderr)
        sys.exit(1)

    kis = KisAdapter(
        app_key=settings.kis_app_key,
        app_secret=settings.kis_app_secret,
        account_number=settings.kis_account_number,
        virtual=settings.kis_virtual,
    )
    bal = kis.balance()
    print(f"모드: {'모의투자' if settings.kis_virtual else '실거래'}")
    print(f"현금: {bal.cash:,.0f}원")
    print(f"평가금액: {bal.positions_value:,.0f}원")
    print(f"총자산: {bal.total_equity:,.0f}원")
    print(f"보유 종목 수: {len(kis.positions())}")


if __name__ == "__main__":
    main()
