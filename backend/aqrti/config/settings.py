"""
AQRTI Configuration System
Single source of truth for all runtime settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_prefix="AQRTI_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Server ──────────────────────────────────────────────────
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    reload: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # ── Database ─────────────────────────────────────────────────
    db_path: str = Field(default="./aqrti.db")

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    # ── Paper Trading ────────────────────────────────────────────
    paper_capital: float = Field(default=100_000.0)

    # ── Universe ─────────────────────────────────────────────────
    universe: str = Field(
        default=(
            # Original 20
            "RELIANCE.NS,TCS.NS,INFY.NS,HDFCBANK.NS,ICICIBANK.NS,"
            "WIPRO.NS,AXISBANK.NS,LTIM.NS,NESTLEIND.NS,BAJFINANCE.NS,"
            "MARUTI.NS,SUNPHARMA.NS,TATASTEEL.NS,TATAMOTORS.NS,"
            "KOTAKBANK.NS,TITAN.NS,ONGC.NS,HINDALCO.NS,SBIN.NS,BHARTIARTL.NS,"
            # Expanded 30
            "HCLTECH.NS,ITC.NS,LT.NS,HINDUNILVR.NS,ULTRACEMCO.NS,"
            "BAJAJFINSV.NS,NTPC.NS,ADANIENT.NS,ADANIPORTS.NS,JSWSTEEL.NS,"
            "TECHM.NS,COALINDIA.NS,BPCL.NS,HDFCLIFE.NS,SBILIFE.NS,"
            "INDUSINDBK.NS,M&M.NS,DIVISLAB.NS,DRREDDY.NS,EICHERMOT.NS,"
            "HEROMOTOCO.NS,CIPLA.NS,BRITANNIA.NS,APOLLOHOSP.NS,TRENT.NS,"
            "GRASIM.NS,SHREECEM.NS,BEL.NS,POWERGRID.NS,ASIANPAINT.NS"
        )
    )

    @property
    def universe_list(self) -> list[str]:
        return [s.strip() for s in self.universe.split(",") if s.strip()]

    @property
    def universe_clean(self) -> list[str]:
        """Symbols without .NS suffix for display."""
        return [s.replace(".NS", "") for s in self.universe_list]

    indices: str = Field(default="^NSEI,^NSEBANK")

    @property
    def indices_list(self) -> list[str]:
        return [s.strip() for s in self.indices.split(",") if s.strip()]

    # ── Scheduler ────────────────────────────────────────────────
    ingest_cron: str = Field(default="30 15 * * 1-5")

    # ── Risk Limits ──────────────────────────────────────────────
    max_position_pct: float = Field(default=5.0)
    max_sector_pct: float = Field(default=25.0)
    max_portfolio_exposure: float = Field(default=80.0)
    min_confidence: float = Field(default=60.0)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
