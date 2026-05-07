"""운영 CLI — status / halt / resume / kill / today.

DB의 system_events 테이블을 통해 런타임 루프와 통신.
loop.py가 매 분 이벤트를 폴링해 상태 변화에 반응.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from prog_stock.config import settings
from prog_stock.storage.db import Database


def _record_command(cmd: str, payload: dict | None = None) -> None:
    db = Database(settings.db_path)
    db.log_event("INFO", f"CMD_{cmd.upper()}", f"manual command: {cmd}", payload)


def cmd_status() -> int:
    db = Database(settings.db_path)
    with db.connect() as conn:
        latest_eq = conn.execute(
            "SELECT * FROM equity_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        positions = conn.execute(
            "SELECT * FROM positions WHERE quantity > 0"
        ).fetchall()
        recent_events = conn.execute(
            "SELECT * FROM system_events ORDER BY occurred_at DESC LIMIT 10"
        ).fetchall()
        recent_orders = conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT 5"
        ).fetchall()

    print(f"\n=== prog_stock status @ {datetime.now().isoformat(timespec='seconds')} ===\n")
    if latest_eq:
        print(f"Equity:      {latest_eq['total_equity']:,.0f}원 ({latest_eq['mode']})")
        print(f"Cash:        {latest_eq['cash']:,.0f}원")
        print(f"Drawdown:    {latest_eq['drawdown_from_peak']:.2%}")
        print(f"Snapshot:    {latest_eq['snapshot_date']}")
    else:
        print("(no equity snapshot yet)")

    print(f"\nPositions ({len(positions)}):")
    for p in positions:
        print(f"  {p['symbol']:>8}  qty={p['quantity']:>5}  avg={p['avg_price']:>10,.0f}  mode={p['mode']}")

    print(f"\nRecent orders:")
    for o in recent_orders:
        print(f"  [{o['submitted_at']}] {o['symbol']} {o['side']} {o['quantity']} "
              f"@{o['price'] or 'mkt'} status={o['status']} reason={o['reason']}")

    print(f"\nRecent events:")
    for e in recent_events:
        print(f"  [{e['occurred_at']}] {e['level']:5} {e['kind']}: {e['message'][:80]}")
    return 0


def cmd_halt() -> int:
    """신규 매수 잠금 (보유는 유지)."""
    _record_command("HALT")
    print("HALT recorded — runtime loop will block new buys at next tick.")
    return 0


def cmd_resume() -> int:
    _record_command("RESUME")
    print("RESUME recorded — new buys re-enabled at next tick.")
    return 0


def cmd_kill() -> int:
    """전 포지션 시장가 청산 + 시스템 정지. 수동 승인 필요."""
    confirm = input("KILL SWITCH: liquidate ALL and STOP system? (yes/no) ")
    if confirm.lower() != "yes":
        print("aborted")
        return 1
    _record_command("KILL_SWITCH")
    print("KILL recorded — runtime loop will liquidate and exit at next tick.")
    return 0


def cmd_today() -> int:
    """오늘 사전 점검 리포트 출력 (텍스트)."""
    from datetime import date

    from prog_stock.brokers.kis_adapter import KisAdapter
    from prog_stock.brokers.paper_adapter import PaperAdapter
    from prog_stock.monitoring.morning_report import build_report
    from prog_stock.strategies.canslim_sepa import CanslimSepaStrategy

    kis = KisAdapter(
        app_key=settings.kis_app_key,
        app_secret=settings.kis_app_secret,
        account_number=settings.kis_account_number,
        virtual=settings.kis_virtual,
    )
    broker = PaperAdapter(quote_source=kis)
    print(build_report(date.today(), broker, CanslimSepaStrategy()))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="prog_stock")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("halt")
    sub.add_parser("resume")
    sub.add_parser("kill")
    sub.add_parser("today")
    args = parser.parse_args()

    handler = {
        "status": cmd_status,
        "halt": cmd_halt,
        "resume": cmd_resume,
        "kill": cmd_kill,
        "today": cmd_today,
    }[args.cmd]
    raise SystemExit(handler())


if __name__ == "__main__":
    main()
