"""
AQRTI Configuration System
Single source of truth for all runtime settings.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


BASE_DIR = Path(__file__).resolve().parent.parent.parent

_ENV_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_PATH,
        env_prefix="AQRTI_",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **kwargs):
        if not _ENV_PATH.exists():
            warnings.warn(
                f"Missing .env file at {_ENV_PATH} — all settings will use defaults. "
                "Create a .env file to configure AQRTI_AUTH_TOKEN, AQRTI_TELEGRAM_*, etc."
            )
        super().__init__(**kwargs)

    # ── Server ──────────────────────────────────────────────────
    host: str = Field(default="127.0.0.1")   # ARCH-8: localhost-only; override via AQRTI_HOST for LAN after enabling auth
    port: int = Field(default=8000)
    reload: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # ── ARCH-8: Admin token (optional but required for any non-localhost access) ─
    # Set AQRTI_ADMIN_TOKEN in .env. When empty, /admin/* routes accept all
    # requests — localhost-only binding ensures this is safe without the token.
    admin_token: str = Field(default="")

    # ── Database ─────────────────────────────────────────────────
    db_path: str = Field(default="./aqrti.db")

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    # ── Paper Trading ────────────────────────────────────────────
    paper_capital: float = Field(default=100_000.0)

    # ── Universe ─────────────────────────────────────────────────
    # Curated 12-symbol real-money-adjacent universe per the research-driven
    # re-architecture (docs/RESEARCH_DRIVEN_REARCHITECTURE.md). NSE-scrapable
    # symbols only — VOO/QQQ (US, no NSE feed) and NIFTY 50 (lives in
    # index_data, not the stocks table) are handled outside this list.
    universe: str = Field(
        default=(
            # Tier 1 (owned)
            "BEL.NS,HDFCBANK.NS,NTPC.NS,"
            # Tier 2 (bench)
            "ICICIBANK.NS,INFY.NS,CDSL.NS,DRREDDY.NS,LT.NS,HAL.NS"
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

    # ── Obsidian Vault Export ──────────────────────────────────────
    # Absolute path to the Obsidian vault folder. Export is disabled
    # entirely when unset (no-placeholder rule: no vault, no writes).
    obsidian_vault_path: str = Field(default="")

    # ── GO-4: Telegram Alerts ─────────────────────────────────────
    # Set AQRTI_TELEGRAM_BOT_TOKEN and AQRTI_TELEGRAM_CHAT_ID in .env
    # to enable out-of-dashboard alerts. Alerts are silently skipped
    # when either is unset — no crash, no fake messages.
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    # ── Finnhub Real-Time Data ─────────────────────────────────────
    # Set AQRTI_FINNHUB_API_KEY in .env for real-time NSE quotes and
    # news feeds. Falls back to yfinance when unset or on error.
    # Free tier: 60 API calls/minute — sufficient for the 5-min monitor loop.
    finnhub_api_key: str = Field(default="")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
