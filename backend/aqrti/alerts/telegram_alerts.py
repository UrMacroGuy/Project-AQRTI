"""
GO-4: Telegram alert channel.

Sends critical events outside the dashboard so the user doesn't need to
have AQRTI open to learn something urgent.

Covered events:
  - Pipeline failure (GO-3 health check fails)
  - Circuit breaker triggered
  - Algo promoted (first to pass all gates)
  - Algo completes quarantine (ready for human review)
  - Portfolio drawdown < -15%

Configuration (in backend/.env):
  AQRTI_TELEGRAM_BOT_TOKEN=<your bot token from @BotFather>
  AQRTI_TELEGRAM_CHAT_ID=<your personal chat or group chat ID>

Alerts are silently skipped when either setting is unset — no crash,
no fake messages, no errors in logs beyond a single INFO note.
"""

from __future__ import annotations

import urllib.request
import urllib.parse
import json
import logging
from datetime import datetime

log = logging.getLogger("aqrti.alerts.telegram")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _send(token: str, chat_id: str, text: str) -> bool:
    """Low-level Telegram send — returns True on success, False on any failure."""
    url = _TELEGRAM_API.format(token=token)
    payload = json.dumps({
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        log.warning("Telegram send failed: %s", exc)
        return False


def _get_config() -> tuple[str, str] | tuple[None, None]:
    """Return (token, chat_id) or (None, None) if not configured."""
    try:
        from aqrti.config.settings import get_settings
        s = get_settings()
        if s.telegram_bot_token and s.telegram_chat_id:
            return s.telegram_bot_token, s.telegram_chat_id
    except Exception:
        pass
    return None, None


def _ts() -> str:
    return datetime.now().strftime("%d %b %Y %H:%M IST")


def alert_pipeline_failure(failures: list[str]) -> None:
    """GO-3 integration — called when the 16:30 health check finds failures."""
    token, chat_id = _get_config()
    if not token:
        log.info("GO-4 Telegram not configured — skipping pipeline failure alert")
        return
    text = (
        f"⛔ <b>AQRTI — Pipeline Failure</b>\n"
        f"<i>{_ts()}</i>\n\n"
        f"Daily self-check failed:\n"
        + "\n".join(f"• {f}" for f in failures)
        + "\n\nCheck backend logs."
    )
    _send(token, chat_id, text)


def alert_circuit_breaker(reason: str) -> None:
    """Called when the circuit breaker trips."""
    token, chat_id = _get_config()
    if not token:
        return
    text = (
        f"🔴 <b>AQRTI — Circuit Breaker Triggered</b>\n"
        f"<i>{_ts()}</i>\n\n"
        f"Reason: {reason}\n"
        "Paper trading halted. Review in dashboard."
    )
    _send(token, chat_id, text)


def alert_algo_promoted(strategy_id: str, sharpe: float, wr: float) -> None:
    """Called when an algo passes all gates and is promoted."""
    token, chat_id = _get_config()
    if not token:
        return
    text = (
        f"🟢 <b>AQRTI — Algo Promoted!</b>\n"
        f"<i>{_ts()}</i>\n\n"
        f"Strategy: <code>{strategy_id}</code>\n"
        f"Sharpe: {sharpe:.2f}  |  Win Rate: {wr:.1f}%\n\n"
        "Now in quarantine. 60 days + 20 shadow trades required before human approval."
    )
    _send(token, chat_id, text)


def alert_quarantine_complete(strategy_id: str, days: int, shadow_wr: float, net_pnl: float) -> None:
    """Called when an algo completes quarantine — ready for human review."""
    token, chat_id = _get_config()
    if not token:
        return
    text = (
        f"✅ <b>AQRTI — Quarantine Complete</b>\n"
        f"<i>{_ts()}</i>\n\n"
        f"Strategy: <code>{strategy_id}</code>\n"
        f"Days in quarantine: {days}  |  Shadow WR: {shadow_wr:.1f}%  |  Net P&L: ₹{net_pnl:,.0f}\n\n"
        "Open dashboard → Paper Trading to review and approve."
    )
    _send(token, chat_id, text)


def alert_drawdown(drawdown_pct: float, portfolio_value: float) -> None:
    """Called when portfolio drawdown exceeds -15%."""
    token, chat_id = _get_config()
    if not token:
        return
    text = (
        f"⚠️ <b>AQRTI — Drawdown Alert</b>\n"
        f"<i>{_ts()}</i>\n\n"
        f"Current drawdown: <b>{drawdown_pct:.1f}%</b>\n"
        f"Portfolio value: ₹{portfolio_value:,.0f}\n\n"
        "Review paper positions. If real money: consider halting per GO-10 rules."
    )
    _send(token, chat_id, text)
