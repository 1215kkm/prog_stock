"""Target Searcher — 사용자 목표 수익률 기반 파라미터 탐색.

3개 프리셋 (안정 / 균형 / 공격), 항상 PARAM_BOUNDS 내에서만 탐색.
백테스트로 통과 후보 발견 시 사용자에게 제안 (PROPOSED). 사용자가 apply 하면 CANARY 30일.

⚠ 백테스트 통과 = 미래 수익 보장 아님. 과적합 휴리스틱으로 의심 후보 경고.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import product

import pandas as pd
import structlog

from prog_stock.agents.base import (
    Decision,
    DecisionStatus,
    DecisionType,
    record_decision,
)
from prog_stock.agents.bounds import PARAM_BOUNDS
from prog_stock.backtest.runner import BacktestConfig, run_backtest
from prog_stock.config import settings
from prog_stock.data import universe as univ
from prog_stock.storage.db import Database
from prog_stock.strategies.canslim_sepa import CanslimSepaConfig, CanslimSepaStrategy

log = structlog.get_logger(__name__)


PRESETS: dict[str, dict] = {
    "conservative": {"annual": 0.08, "mdd": -0.10, "sharpe": 0.8, "grid": 3},
    "balanced":     {"annual": 0.15, "mdd": -0.15, "sharpe": 1.0, "grid": 4},
    "aggressive":   {"annual": 0.25, "mdd": -0.20, "sharpe": 1.2, "grid": 5},
}


@dataclass
class TargetSearchResult:
    session_id: int
    status: str   # SEARCHING / FOUND / NOT_FOUND
    candidates: list[dict]


def _overfit_warning(metrics: dict) -> str | None:
    """후보가 너무 좋아 의심스러우면 사유 반환."""
    sharpe = metrics.get("sharpe") or 0
    trades = metrics.get("trades") or 0
    if sharpe > 3.0:
        return f"high_sharpe:{sharpe:.2f}_likely_overfit"
    if trades < 30:
        return f"low_sample:{trades}_trades"
    return None


class TargetSearcherAgent:
    name = "target_searcher"

    def __init__(self, db: Database) -> None:
        self.db = db

    def _universe_symbols(self, today: date, limit: int = 50) -> list[str]:
        df = univ.load_snapshot(today, settings.cache_dir_universe)
        if df is None or df.empty:
            return []
        return df["symbol"].head(limit).tolist()

    def _enumerate(self, grid: int) -> list[dict]:
        tunable = ["hard_stop_loss", "min_op_income_yoy", "rs_top_pct", "breakout_volume_ratio"]
        grids: dict[str, list[float]] = {}
        for p in tunable:
            b = PARAM_BOUNDS[p]
            assert b.min is not None and b.max is not None
            step = (b.max - b.min) / (grid - 1) if grid > 1 else 0
            grids[p] = [round(b.min + i * step, 4) for i in range(grid)]

        return [
            {"hard_stop_loss": hsl, "min_op_income_yoy": oiy,
             "rs_top_pct": rs, "breakout_volume_ratio": vol}
            for hsl, oiy, rs, vol in product(
                grids["hard_stop_loss"], grids["min_op_income_yoy"],
                grids["rs_top_pct"], grids["breakout_volume_ratio"],
            )
        ]

    def _run_one(self, params: dict, symbols: list[str], end: date,
                 lookback_years: int) -> dict | None:
        start = end - timedelta(days=lookback_years * 365)
        fundamentals = (
            pd.read_parquet(settings.fundamentals_path)
            if settings.fundamentals_path.exists() else pd.DataFrame()
        )
        market_idx_path = settings.cache_dir_market / "kospi200_index.parquet"
        market_idx = pd.read_parquet(market_idx_path) if market_idx_path.exists() else pd.DataFrame()

        bt_cfg = BacktestConfig(hard_stop_loss=params["hard_stop_loss"])
        strat = CanslimSepaStrategy(CanslimSepaConfig(
            min_op_income_yoy=params["min_op_income_yoy"],
            rs_top_pct=params["rs_top_pct"],
            breakout_volume_ratio=params["breakout_volume_ratio"],
            hard_stop_loss=params["hard_stop_loss"],
        ))

        try:
            summary = run_backtest(
                start=start, end=end, universe_symbols=symbols,
                fundamentals=fundamentals, market_index=market_idx,
                cache_dir=settings.cache_dir_ohlcv, cfg=bt_cfg, strategy=strat,
            )
        except Exception as e:
            log.warning("target_backtest_failed", params=params, error=str(e))
            return None
        return summary

    def _passes(self, summary: dict, criteria: dict) -> bool:
        cagr = summary.get("cagr") or 0
        mdd = summary.get("mdd") or 0
        sharpe = summary.get("sharpe") or 0
        return (
            cagr >= criteria["annual"]
            and mdd >= criteria["mdd"]
            and sharpe >= criteria["sharpe"]
        )

    def search(self, preset: str, horizon_months: int,
               lookback_years: int = 5) -> TargetSearchResult:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset: {preset}")
        criteria = PRESETS[preset]
        today = date.today()

        # 세션 생성
        with self.db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO target_sessions
                   (created_at, preset, target_annual_return, max_mdd, min_sharpe,
                    horizon_months, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'SEARCHING')""",
                (datetime.now().isoformat(timespec="seconds"),
                 preset, criteria["annual"], criteria["mdd"], criteria["sharpe"],
                 horizon_months),
            )
            session_id = int(cur.lastrowid)

        symbols = self._universe_symbols(today)
        if not symbols:
            self._mark_session(session_id, "NOT_FOUND", 0)
            return TargetSearchResult(session_id, "NOT_FOUND", [])

        variants = self._enumerate(criteria["grid"])
        log.info("target_search_start", preset=preset, variants=len(variants))

        candidates: list[tuple[dict, dict]] = []
        for v in variants:
            r = self._run_one(v, symbols, today, lookback_years)
            if r is None:
                continue
            if self._passes(r, criteria):
                candidates.append((v, r))

        # Sharpe 내림차순 + Overfit 페널티
        candidates.sort(key=lambda x: x[1].get("sharpe") or 0, reverse=True)

        top = candidates[:5]
        with self.db.connect() as conn:
            for rank, (v, r) in enumerate(top, start=1):
                warn = _overfit_warning(r)
                conn.execute(
                    """INSERT INTO target_candidates
                       (session_id, params_json, cagr, sharpe, mdd, profit_factor,
                        trades, rank, overfit_warning)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, json.dumps(v, ensure_ascii=False),
                     r.get("cagr"), r.get("sharpe"), r.get("mdd"),
                     None if r.get("profit_factor") in (float("inf"), None) else r.get("profit_factor"),
                     r.get("trades"), rank, warn),
                )

        status = "FOUND" if top else "NOT_FOUND"
        self._mark_session(session_id, status, len(top))

        result_candidates = [
            {"rank": rank, "params": v, "metrics": r, "overfit_warning": _overfit_warning(r)}
            for rank, (v, r) in enumerate(top, start=1)
        ]

        d = Decision(
            agent=self.name,
            type=DecisionType.PARAM_CHANGE,
            summary=(
                f"🎯 목표 탐색 [{preset}]: 후보 {len(top)}개 발견 (session={session_id})"
                if top else
                f"🎯 목표 탐색 [{preset}]: 통과 후보 없음 — 더 낮은 목표 검토 권장"
            ),
            payload={"session_id": session_id, "preset": preset, "candidates": result_candidates},
            rationale=f"5년 백테스트 그리드 {len(variants)}개 중 {len(candidates)}개 통과",
            status=DecisionStatus.PROPOSED,
        )
        record_decision(self.db, d)
        return TargetSearchResult(session_id, status, result_candidates)

    def _mark_session(self, session_id: int, status: str, found: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE target_sessions SET status = ?, candidates_found = ? WHERE id = ?",
                (status, found, session_id),
            )

    def apply(self, session_id: int, candidate_rank: int) -> Decision:
        """선택된 후보를 CANARY 모드로 활성화."""
        with self.db.connect() as conn:
            cand = conn.execute(
                "SELECT * FROM target_candidates WHERE session_id = ? AND rank = ?",
                (session_id, candidate_rank),
            ).fetchone()
            sess = conn.execute(
                "SELECT * FROM target_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if cand is None or sess is None:
            raise ValueError(f"candidate not found: session={session_id} rank={candidate_rank}")

        params = json.loads(cand["params_json"])

        # PARAM_BOUNDS 재검증 (절대 우회 X)
        from prog_stock.agents.orchestrator import Orchestrator
        if not all(PARAM_BOUNDS[k].valid(v) for k, v in params.items() if k in PARAM_BOUNDS):
            raise ValueError("param out of bounds, rejected")

        d = Decision(
            agent=self.name,
            type=DecisionType.PARAM_CHANGE,
            summary=f"🟢 목표 후보 적용: session={session_id} rank={candidate_rank} (카나리 30일)",
            payload={"new_params": params, "session_id": session_id, "rank": candidate_rank,
                     "metrics": {"cagr": cand["cagr"], "sharpe": cand["sharpe"],
                                 "mdd": cand["mdd"], "trades": cand["trades"]}},
            rationale=f"사용자 승인. Preset={sess['preset']}, 목표={sess['target_annual_return']:.0%}",
            expected_impact=f"카나리 자본 1%로 30거래일 검증",
            status=DecisionStatus.CANARY,
            activated_at=datetime.now().isoformat(timespec="seconds"),
            expires_at=(date.today() + timedelta(days=30)).isoformat(),
        )
        decision_id = record_decision(self.db, d)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE target_sessions SET status = 'APPLIED', applied_decision_id = ? WHERE id = ?",
                (decision_id, session_id),
            )
        return d

    def cancel(self, session_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE target_sessions SET status = 'EXPIRED' WHERE id = ? AND status IN ('FOUND', 'SEARCHING')",
                (session_id,),
            )

    def status(self, session_id: int | None = None) -> list[dict]:
        with self.db.connect() as conn:
            if session_id is None:
                rows = list(conn.execute(
                    "SELECT * FROM target_sessions ORDER BY id DESC LIMIT 20"
                ))
            else:
                rows = list(conn.execute(
                    "SELECT * FROM target_sessions WHERE id = ?", (session_id,)
                ))
        return [dict(r) for r in rows]
