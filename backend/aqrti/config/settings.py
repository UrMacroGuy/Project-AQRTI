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
    universe: str = Field(
        default=(
            # Original 20
            "RELIANCE.NS,TCS.NS,INFY.NS,HDFCBANK.NS,ICICIBANK.NS,"
            "WIPRO.NS,AXISBANK.NS,NESTLEIND.NS,BAJFINANCE.NS,"
            "MARUTI.NS,SUNPHARMA.NS,TATASTEEL.NS,"
            "KOTAKBANK.NS,TITAN.NS,ONGC.NS,HINDALCO.NS,SBIN.NS,BHARTIARTL.NS,"
            # Expanded 30
            "HCLTECH.NS,ITC.NS,LT.NS,HINDUNILVR.NS,ULTRACEMCO.NS,"
            "BAJAJFINSV.NS,NTPC.NS,ADANIENT.NS,ADANIPORTS.NS,JSWSTEEL.NS,"
            "TECHM.NS,COALINDIA.NS,BPCL.NS,HDFCLIFE.NS,SBILIFE.NS,"
            "INDUSINDBK.NS,M&M.NS,DIVISLAB.NS,DRREDDY.NS,EICHERMOT.NS,"
            "HEROMOTOCO.NS,CIPLA.NS,BRITANNIA.NS,APOLLOHOSP.NS,TRENT.NS,"
            "GRASIM.NS,SHREECEM.NS,BEL.NS,POWERGRID.NS,ASIANPAINT.NS,"
            # NSE Extended Universe (from global_universe.py NSE section)
            "MPHASIS.NS,PERSISTENT.NS,COFORGE.NS,LTTS.NS,"
            "BAJAJ-AUTO.NS,TVSMOTOR.NS,BOSCHLTD.NS,MOTHERSON.NS,"
            "BANDHANBNK.NS,FEDERALBNK.NS,IDFCFIRSTB.NS,"
            "BANKBARODA.NS,PNB.NS,CANBK.NS,UNIONBANK.NS,"
            "CHOLAFIN.NS,MUTHOOTFIN.NS,"
            "AUROPHARMA.NS,LUPIN.NS,TORNTPHARM.NS,ALKEM.NS,"
            "DABUR.NS,MARICO.NS,COLPAL.NS,GODREJCP.NS,EMAMILTD.NS,TATACONSUM.NS,"
            "VEDL.NS,NATIONALUM.NS,SAIL.NS,HINDCOPPER.NS,"
            "IOC.NS,GAIL.NS,ADANIPOWER.NS,ADANIGREEN.NS,"
            "DMART.NS,NYKAA.NS,ETERNAL.NS,PAYTM.NS,POLICYBZR.NS,"
            "IRCTC.NS,INDHOTEL.NS,"
            "HAL.NS,BHEL.NS,SIEMENS.NS,ABB.NS,AIAENG.NS,GRINDWELL.NS,"
            "PIIND.NS,UPL.NS,SRF.NS,AARTIIND.NS,DEEPAKNTR.NS,NAVINFLUOR.NS,"
            "PHOENIXLTD.NS,OBEROIRLTY.NS,GODREJPROP.NS,PRESTIGE.NS,DLF.NS"
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
