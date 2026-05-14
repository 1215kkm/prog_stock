"""Target Searcher CLI — 사용자 목표 기반 파라미터 탐색.

사용:
  python -m prog_stock.tools.target plan --preset balanced --horizon 6m
  python -m prog_stock.tools.target apply --session 7 --candidate 2
  python -m prog_stock.tools.target status [--session 7]
  python -m prog_stock.tools.target cancel --session 7
"""
from __future__ import annotations

import argparse
import json
import sys

from prog_stock.agents.base import ensure_agent_schema
from prog_stock.agents.target_searcher import PRESETS, TargetSearcherAgent
from prog_stock.config import settings
from prog_stock.storage.db import Database


def _format_horizon(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("m"):
        return int(s[:-1])
    if s.endswith("y"):
        return int(s[:-1]) * 12
    return int(s)


def cmd_plan(args: argparse.Namespace) -> int:
    if args.preset not in PRESETS:
        print(f"unknown preset: {args.preset} (choose: conservative / balanced / aggressive)")
        return 1
    horizon = _format_horizon(args.horizon)
    settings.ensure_dirs()
    db = Database(settings.db_path)
    ensure_agent_schema(db)
    agent = TargetSearcherAgent(db)

    print(f"🎯 Target search starting: preset={args.preset}, horizon={horizon}m")
    result = agent.search(args.preset, horizon)

    print(f"\nSession ID: {result.session_id}")
    print(f"Status: {result.status}")
    print(f"Candidates: {len(result.candidates)}\n")

    if not result.candidates:
        print("⚠ 통과 후보 없음. 더 낮은 목표를 시도하거나, 데이터가 부족할 수 있습니다.")
        return 0

    print(f"{'Rank':<5} {'CAGR':<8} {'Sharpe':<8} {'MDD':<8} {'Trades':<8} Warning")
    print("-" * 70)
    for c in result.candidates:
        m = c["metrics"]
        warn = c["overfit_warning"] or "-"
        print(f"{c['rank']:<5} {m.get('cagr', 0):<+8.2%} {m.get('sharpe', 0):<8.2f} "
              f"{m.get('mdd', 0):<+8.2%} {m.get('trades', 0):<8} {warn}")

    print(f"\n승인하려면: python -m prog_stock.tools.target apply --session {result.session_id} --candidate <rank>")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    db = Database(settings.db_path)
    ensure_agent_schema(db)
    agent = TargetSearcherAgent(db)
    try:
        d = agent.apply(args.session, args.candidate)
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    print(f"✅ 카나리 시작: {d.summary}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    db = Database(settings.db_path)
    ensure_agent_schema(db)
    agent = TargetSearcherAgent(db)
    sessions = agent.status(args.session)
    if not sessions:
        print("no sessions yet")
        return 0
    for s in sessions:
        print(f"#{s['id']} {s['created_at']} preset={s['preset']} "
              f"target={s['target_annual_return']:.0%} status={s['status']} "
              f"candidates={s['candidates_found']}")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    db = Database(settings.db_path)
    ensure_agent_schema(db)
    agent = TargetSearcherAgent(db)
    agent.cancel(args.session)
    print(f"session {args.session} cancelled")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="target")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--preset", required=True, choices=list(PRESETS))
    p.add_argument("--horizon", default="6m", help="e.g. 3m, 6m, 1y")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("apply")
    p.add_argument("--session", type=int, required=True)
    p.add_argument("--candidate", type=int, required=True)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("status")
    p.add_argument("--session", type=int, default=None)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("cancel")
    p.add_argument("--session", type=int, required=True)
    p.set_defaults(func=cmd_cancel)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
