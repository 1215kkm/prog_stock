"""중앙 설정. 환경변수 + YAML."""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunMode(str, Enum):
    BACKTEST = "backtest"
    DRY_RUN = "dry_run"
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # KIS
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_number: str = ""
    kis_virtual: bool = True

    # DART
    dart_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Storage
    db_path: Path = Path("./data/prog_stock.db")
    cache_dir: Path = Path("./data/cache")

    # Logging
    log_level: str = "INFO"

    # Strategy
    strategy_name: str = "canslim_sepa"
    run_mode: RunMode = RunMode.DRY_RUN

    # Risk parameters (defaults aligned with 04_risk_management.md)
    max_positions: int = 5
    risk_per_trade: float = 0.015  # 1.5% of equity per trade
    hard_stop_loss: float = -0.07  # -7%
    daily_loss_limit: float = -0.03  # -3%
    mdd_limit: float = -0.15  # -15%
    max_position_pct: float = 0.25  # single name cap
    cooldown_days: int = 30  # rebuy ban after stop-loss

    # Trade costs (Korean market)
    commission_rate: float = 0.00015
    sell_tax_rate: float = 0.0018
    slippage_rate: float = 0.001

    # Strategy params
    fundamental_growth_quarters: int = 4
    min_market_cap_krw: int = 100_000_000_000  # 1,000억
    min_op_income_growth_yoy: float = 0.25
    rs_top_pct: float = 0.30
    breakout_volume_ratio: float = 1.5
    trailing_stop_activate_pct: float = 0.20
    trailing_stop_drop_pct: float = 0.10

    @property
    def cache_dir_ohlcv(self) -> Path:
        return self.cache_dir / "ohlcv"

    @property
    def cache_dir_universe(self) -> Path:
        return self.cache_dir / "universe"

    @property
    def cache_dir_market(self) -> Path:
        return self.cache_dir / "market"

    @property
    def fundamentals_path(self) -> Path:
        return self.cache_dir / "fundamentals.parquet"

    def ensure_dirs(self) -> None:
        for p in (self.db_path.parent, self.cache_dir, self.cache_dir_ohlcv,
                  self.cache_dir_universe, self.cache_dir_market):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
