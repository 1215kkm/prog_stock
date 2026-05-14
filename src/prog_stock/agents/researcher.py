"""Researcher Agent — 파라미터 그리드 백테스트.

매일 밤 (16:30) 실행:
1. 현재 운영 파라미터 vs N개 변형의 5년 백테스트
2. Sharpe·MDD·Profit Factor 모두 개선되는 후보만 의사결정으로 등록
3. 신규 후보 → 카나리(자본 1%, 30거래일)로 자동 진입
4. 모든 결과를 experiments 테이블에 저장
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import product
from pathlib import Path

import pandas as pd
import structlog

from prog_stock.agents.base import (
    Agent,
    Decision,
    DecisionStatus,
    DecisionType,
    record_decision,
)
from prog_stock.agents.bounds import PARAM_BOUNDS
from prog_stock.backtest.runner import BacktestConfig, run_backtest
from prog_stock.config import settings
from prog_stock.storage.db import Database
from prog_stock.strategies.canslim_sepa import CanslimSepaConfig, CanslimSepaStrategy

log = structlog.get_logger(__name__)


@dataclass
class ResearcherConfig:
    grid_per_param: int = 3              # 파라미터당 시도 값 개수
    min_improvement_sharpe: float = 0.1  # Sharpe 개선 최소치
    min_improvement_pf: float = 0.1      # Profit Factor 개선 최소치
    max_mdd_degradation: float = 0.02    # MDD 악화 허용 한도 (절댓값)
    lookback_years: int = 5
    max_candidates_per_run: int = 3      # 한 번에 제안하는 변경 수


class ResearcherAgent:
    name = "researcher"

    def __init__(self, db: Database, cfg: ResearcherConfig | None = None) -> None:
        self.db = db
        self.cfg = cfg or ResearcherConfig()

    def _baseline_summary(self, end: date) -> dict | None:
        """현재 운영 파라미터로 baseline 백테스트."""
        symbols = self._universe_symbols(end)
        if not symbols:
            return None
        return self._run_one(
            params={
                "hard_stop_loss": settings.hard_stop_loss,
                "max_positions": settings.max_positions,
                "min_op_income_yoy": settings.min_op_income_growth_yoy,
                "rs_top_pct": settings.rs_top_pct,
                "breakout_volume_ratio": settings.breakout_volume_ratio,
            },
            symbols=symbols,
            end=end,
        )

    def _universe_symbols(self, end: date) -> list[str]:
        from prog_stock.data import universe as univ
        df = univ.load_snapshot(end, settings.cache_dir_universe)
        if df is None or df.empty:
            return []
        return df["symbol"].head(50).tolist()  # 백테스트 비용 제어

    def _build_strategy(self, params: dict) -> CanslimSepaStrategy:
        cfg = CanslimSepaConfig(
            fundamental_quarters=4,
            min_op_income_yoy=params.get("min_op_income_yoy", settings.min_op_income_growth_yoy),
            rs_top_pct=params.get("rs_top_pct", settings.rs_top_pct),
            breakout_volume_ratio=params.get("breakout_volume_ratio", settings.breakout_volume_ratio),
            hard_stop_loss=params.get("hard_stop_loss", settings.hard_stop_loss),
        )
        return CanslimSepaStrategy(cfg)

    def _run_one(self, params: dict, symbols: list[str], end: date) -> dict | None:
        start = end - timedelta(days=self.cfg.lookback_years * 365)
        fundamentals = (
            pd.read_parquet(settings.fundamentals_path)
            if settings.fundamentals_path.exists() else pd.DataFrame()
        )
        market_idx_path = settings.cache_dir_market / "kospi200_index.parquet"
        market_idx = pd.read_parquet(market_idx_path) if market_idx_path.exists() else pd.DataFrame()

        bt_cfg = BacktestConfig(
            hard_stop_loss=params.get("hard_stop_loss", settings.hard_stop_loss),
            max_positions=params.get("max_positions", settings.max_positions),
        )
        strat = self._build_strategy(params)

        try:
            summary = run_backtest(
                start=start, end=end, universe_symbols=symbols,
                fundamentals=fundamentals, market_index=market_idx,
                cache_dir=settings.cache_dir_ohlcv, cfg=bt_cfg, strategy=strat,
            )
        except Exception as e:
            log.warning("backtest_failed", params=params, error=str(e))
            return None

        self._save_experiment(params, start, end, summary)
        return summary

    def _save_experiment(self, params: dict, start: date, end: date, summary: dict) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO experiments
                   (run_at, strategy, params_json, period_start, period_end,
                    cagr, sharpe, mdd, win_rate, profit_factor, trades)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (datetime.now().isoformat(timespec="seconds"), "canslim_sepa",
                 json.dumps(params, ensure_ascii=False),
                 start.isoformat(), end.isoformat(),
                 summary.get("cagr"), summary.get("sharpe"), summary.get("mdd"),
                 summary.get("win_rate"),
                 None if summary.get("profit_factor") in (float("inf"), None) else summary.get("profit_factor"),
                 summary.get("trades")),
            )

    def _enumerate_variants(self, baseline_params: dict) -> list[dict]:
        """Bounds 내에서 그리드 생성."""
        tunable = ["hard_stop_loss", "min_op_income_yoy", "rs_top_pct", "breakout_volume_ratio"]
        grids: dict[str, list[float]] = {}
        for p in tunable:
            b = PARAM_BOUNDS[p]
            assert b.min is not None and b.max is not None
            step = (b.max - b.min) / (self.cfg.grid_per_param - 1)
            grids[p] = [round(b.min + i * step, 4) for i in range(self.cfg.grid_per_param)]

        variants = []
        for hsl, oiy, rs, vol in product(grids["hard_stop_loss"], grids["min_op_income_yoy"],
                                          grids["rs_top_pct"], grids["breakout_volume_ratio"]):
            v = {
                "hard_stop_loss": hsl,
                "min_op_income_yoy": oiy,
                "rs_top_pct": rs,
                "breakout_volume_ratio": vol,
                "max_positions": baseline_params["max_positions"],
            }
            if v != baseline_params:
                variants.append(v)
        return variants

    def _is_strictly_better(self, candidate: dict, baseline: dict) -> bool:
        c_sharpe = candidate.get("sharpe") or 0
        b_sharpe = baseline.get("sharpe") or 0
        c_pf = candidate.get("profit_factor") or 0
        b_pf = baseline.get("profit_factor") or 0
        c_mdd = candidate.get("mdd") or 0
        b_mdd = baseline.get("mdd") or 0
        return (
            c_sharpe >= b_sharpe + self.cfg.min_improvement_sharpe
            and c_pf >= b_pf + self.cfg.min_improvement_pf
            and c_mdd >= b_mdd - self.cfg.max_mdd_degradation
        )

    def run(self) -> list[Decision]:
        end = date.today()
        baseline = self._baseline_summary(end)
        if baseline is None:
            log.warning("researcher_no_baseline_skip")
            return []

        symbols = self._universe_symbols(end)
        variants = self._enumerate_variants({"hard_stop_loss": settings.hard_stop_loss,
                                              "max_positions": settings.max_positions,
                                              "min_op_income_yoy": settings.min_op_income_growth_yoy,
                                              "rs_top_pct": settings.rs_top_pct,
                                              "breakout_volume_ratio": settings.breakout_volume_ratio})
        log.info("researcher_grid_size", n=len(variants))

        results = []
        for v in variants:
            r = self._run_one(v, symbols, end)
            if r is None:
                continue
            if self._is_strictly_better(r, baseline):
                results.append((v, r))

        # Sharpe 우월순 상위 K개 의사결정 등록
        results.sort(key=lambda x: x[1].get("sharpe") or 0, reverse=True)
        decisions: list[Decision] = []
        for v, r in results[: self.cfg.max_candidates_per_run]:
            change_keys = {k: v[k] for k in v if v[k] != baseline.get(k, settings.__dict__.get(k))}
            d = Decision(
                agent=self.name,
                type=DecisionType.PARAM_CHANGE,
                summary=(
                    f"파라미터 후보 발견 (Sharpe {r['sharpe']:.2f} vs "
                    f"{baseline['sharpe']:.2f}, PF {r['profit_factor']:.2f}): "
                    + ", ".join(f"{k}={vv}" for k, vv in change_keys.items())
                ),
                payload={"new_params": v, "metrics": {
                    "sharpe": r["sharpe"], "mdd": r["mdd"],
                    "profit_factor": r["profit_factor"], "win_rate": r["win_rate"],
                }},
                rationale=(
                    f"5년 백테스트 결과 baseline Sharpe={baseline['sharpe']:.2f} "
                    f"→ 후보 Sharpe={r['sharpe']:.2f}, "
                    f"MDD {baseline['mdd']:.2%} → {r['mdd']:.2%}"
                ),
                expected_impact=f"Sharpe +{r['sharpe'] - baseline['sharpe']:.2f}",
                status=DecisionStatus.CANARY,
                expires_at=(date.today() + timedelta(days=30)).isoformat(),
            )
            record_decision(self.db, d)
            decisions.append(d)
        return decisions
