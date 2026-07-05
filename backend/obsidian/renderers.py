"""
Obsidian note renderers — Daily, Stock, Lesson, Home, Algo, Report.
Spec: docs/OBSIDIAN_INTEGRATION_PLAN.md §3.

Every renderer is a pure function: DB rows in, markdown-with-frontmatter
out. No renderer performs I/O — vault_exporter.py handles paths/writes.
Missing data renders nothing (no-placeholder rule) rather than filler text.
"""
from __future__ import annotations

import json
import re
from datetime import date

from obsidian.vault_writer import wikilink


def _safe_json_list(raw) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _slug(text: str) -> str:
    """Filesystem-safe note filename stem."""
    cleaned = re.sub(r"[\\/:*?\"<>|]", "", text).strip()
    return cleaned or "untitled"


def _frontmatter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        elif isinstance(value, list):
            if value:
                lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
            else:
                lines.append(f"{key}: []")
        elif value is None:
            lines.append(f"{key}:")
        else:
            escaped = str(value).replace('"', '\\"')
            lines.append(f'{key}: "{escaped}"')
    lines.append("---")
    return "\n".join(lines)


# ── Daily note ──────────────────────────────────────────────────────
def render_daily_note(
    brief_date: date,
    brief,
    knowledge_score,
    regime,
    top_predictions: list,
    trades_opened: list,
    trades_closed: list,
    lessons_today: list,
) -> str:
    fm = _frontmatter({
        "aqrti_generated": True,
        "type": "daily",
        "date": brief_date.isoformat(),
        "regime": regime or None,
        "knowledge_score": knowledge_score,
        "trades_opened": len(trades_opened),
        "trades_closed": len(trades_closed),
        "tags": ["aqrti/daily"],
    })

    body = [f"\n# AQRTI Daily — {brief_date.isoformat()}\n"]

    if brief and brief.market_summary:
        body.append("## Market summary")
        body.append(brief.market_summary)
        body.append("")

    if top_predictions:
        body.append("## Top opportunities")
        for p in top_predictions:
            symbol = p.get("symbol")
            direction = p.get("direction", "")
            confidence = p.get("confidence")
            expected_return = p.get("expected_return")
            conf_str = f"{confidence:.0f}% confidence" if confidence is not None else ""
            ret_str = f"{expected_return:+.1f}% expected" if expected_return is not None else ""
            parts = [x for x in [direction, conf_str, ret_str] if x]
            suffix = f" — {', '.join(parts)}" if parts else ""
            body.append(f"- {wikilink(symbol)}{suffix}")
        body.append("")

    if trades_opened or trades_closed:
        body.append("## Trades")
        for t in trades_opened:
            algo = f" (algo {wikilink(t['strategy_id'])})" if t.get("strategy_id") else ""
            body.append(
                f"- Opened: {wikilink(t['symbol'])} ×{t['shares']:g} @ ₹{t['entry_price']:,.2f}{algo}"
            )
        for t in trades_closed:
            ret = t.get("actual_return")
            ret_str = f"{ret:+.1f}%" if ret is not None else t.get("exit_reason", "closed")
            body.append(f"- Closed: {wikilink(t['symbol'])} {ret_str}")
        body.append("")

    if lessons_today:
        body.append("## Risks / Lessons today")
        for lesson_link in lessons_today:
            body.append(f"- {wikilink(lesson_link)}")
        body.append("")

    if brief:
        action_items = _safe_json_list(brief.action_items)
        if action_items:
            body.append("## Action items")
            for item in action_items:
                body.append(f"- {item}")
            body.append("")

    if not brief and not top_predictions and not trades_opened and not trades_closed:
        body.append("_No pipeline run recorded for this day._")
        body.append("")

    return fm + "\n" + "\n".join(body)


# ── Stock note ──────────────────────────────────────────────────────
def render_stock_note(
    symbol: str,
    stock,
    exchange_meta: dict | None,
    last_prediction,
    sentiment_score,
    open_position,
    recent_trades: list,
    trade_stats: dict,
) -> str:
    """
    exchange_meta: {"exchange", "currency", "region"} from GLOBAL_UNIVERSE,
    or None if the symbol isn't in that table (never guessed from the
    bare ticker string — that was the old bug, e.g. AAPL mislabeled NSE).
    trade_stats: {"closed", "wins", "losses", "win_rate", "avg_return_pct",
    "total_pnl"} computed over ALL closed trades for the symbol, not just
    the last 10 shown in the table.
    """
    currency_symbol = "$" if exchange_meta and exchange_meta.get("currency") == "USD" else "₹"

    fm = _frontmatter({
        "aqrti_generated": True,
        "type": "stock",
        "symbol": symbol,
        "sector": stock.sector if stock else None,
        "exchange": exchange_meta.get("exchange") if exchange_meta else None,
        "region": exchange_meta.get("region") if exchange_meta else None,
        "last_prediction": last_prediction.direction if last_prediction else None,
        "last_confidence": last_prediction.confidence if last_prediction else None,
        "sentiment_score": sentiment_score,
        "in_portfolio": bool(open_position),
        "closed_trades": trade_stats.get("closed", 0),
        "win_rate": trade_stats.get("win_rate"),
        "tags": ["aqrti/stock"],
    })

    body = [f"\n# {symbol}\n"]

    if last_prediction:
        conf = last_prediction.confidence
        conf_str = f", {conf:.0f}% confidence" if conf is not None else ""
        body.append(
            f"AQRTI view: **{last_prediction.direction or 'Neutral'}**{conf_str} "
            f"as of {last_prediction.date.isoformat() if last_prediction.date else 'unknown date'}."
        )
        body.append("")

    if open_position:
        body.append("## Open position")
        body.append(
            f"- {open_position['shares']:g} shares @ {currency_symbol}{open_position['entry_price']:,.2f} "
            f"(opened {open_position['entry_date']})"
        )
        body.append("")

    if trade_stats.get("closed"):
        body.append("## Trade record")
        body.append(
            f"- **{trade_stats['closed']} closed trades** — "
            f"{trade_stats['wins']} wins / {trade_stats['losses']} losses "
            f"({trade_stats['win_rate']:.0f}% win rate)"
        )
        body.append(f"- Average return per trade: {trade_stats['avg_return_pct']:+.2f}%")
        body.append(f"- Total realized P&L: {currency_symbol}{trade_stats['total_pnl']:+,.2f}")
        body.append("")

    if recent_trades:
        body.append("## Recent trades (last 10)")
        body.append("| Entry | Exit | Return | Reason |")
        body.append("|---|---|---|---|")
        for t in recent_trades:
            exit_date = t.get("exit_date") or "open"
            ret = t.get("return_pct")
            ret_str = f"{ret:+.2f}%" if ret is not None else "—"
            body.append(f"| {t['entry_date']} | {exit_date} | {ret_str} | {t.get('exit_reason') or '—'} |")
        body.append("")

    if not last_prediction and not open_position and not recent_trades:
        body.append("_No AQRTI activity recorded for this symbol yet._")
        body.append("")

    return fm + "\n" + "\n".join(body)


# ── Lesson note ───────────────────────────────────────────────────
def render_lesson_note(lesson) -> str:
    fm = _frontmatter({
        "aqrti_generated": True,
        "type": "lesson",
        "category": lesson.category,
        "severity": lesson.severity,
        "regime": lesson.regime,
        "applied": bool(lesson.applied),
        "date": lesson.lesson_date.isoformat() if lesson.lesson_date else None,
        "tags": ["aqrti/lesson"],
    })

    body = [f"\n# {lesson.title}\n"]

    if lesson.what_happened:
        body.append("## What happened")
        body.append(lesson.what_happened)
        if lesson.symbol:
            body.append(f"\nSymbol: {wikilink(lesson.symbol)}")
        body.append("")

    if lesson.why_it_happened:
        body.append("## Why")
        body.append(lesson.why_it_happened)
        body.append("")

    if lesson.recommendation:
        body.append("## Recommendation")
        body.append(lesson.recommendation)
        body.append("")

    if lesson.lesson_date:
        body.append(f"Related: {wikilink('Daily/' + lesson.lesson_date.isoformat())}")
        body.append("")

    return fm + "\n" + "\n".join(body)


# ── Home note ─────────────────────────────────────────────────────
def render_home_note(
    latest_daily_date,
    knowledge_score_trend: list,
    recent_lessons: list,
    promoted_algos: list | None = None,
) -> str:
    """
    Dashboard hub. Static summary (computed at export time, always
    correct even without Dataview) plus embedded Dataview queries for
    live drill-down (require the Dataview plugin — degrade to plain
    fenced code blocks if it isn't installed, never break the page).
    """
    fm = _frontmatter({
        "aqrti_generated": True,
        "type": "home",
        "tags": ["aqrti/home"],
    })

    body = ["\n# AQRTI Vault\n"]

    if latest_daily_date:
        body.append(f"Latest: {wikilink('Daily/' + latest_daily_date.isoformat())}")
        body.append("")

    body.append(
        "Jump to an index: [[Daily/_index|Daily]] · [[Stocks/_index|Stocks]] · "
        "[[Lessons/_index|Lessons]] · [[Algos/_index|Algos]]"
    )
    body.append("")

    if knowledge_score_trend:
        body.append("## Knowledge score (last 7 days)")
        for d, score in knowledge_score_trend:
            body.append(f"- {d.isoformat()}: {score:.1f}")
        body.append("")

    if promoted_algos:
        body.append("## Promoted algos")
        for algo_link in promoted_algos:
            body.append(f"- {wikilink(algo_link)}")
        body.append("")
    else:
        body.append("## Promoted algos")
        body.append(
            "_None yet — honest baseline, not a bug. See [[Algos/_index]] once one clears "
            "the full gate chain (backtest + OOS + benchmark + duplicate + quarantine)._"
        )
        body.append("")

    if recent_lessons:
        body.append("## Recent lessons")
        for title in recent_lessons:
            body.append(f"- {wikilink(title)}")
        body.append("")

    body.append("## Live: knowledge score trend")
    body.append("```dataview")
    body.append("TABLE knowledge_score, regime, trades_opened, trades_closed")
    body.append('FROM "Daily"')
    body.append('WHERE type = "daily"')
    body.append("SORT date DESC")
    body.append("LIMIT 10")
    body.append("```")
    body.append("")

    if not latest_daily_date and not knowledge_score_trend and not recent_lessons and not promoted_algos:
        body.append("_No AQRTI data exported yet._")
        body.append("")

    return fm + "\n" + "\n".join(body)


def _render_condition(cond: dict, indent: int = 0) -> list[str]:
    """Render a Condition or ConditionGroup dict as plain-English bullet lines."""
    pad = "  " * indent
    lines = []
    if "logic" in cond:
        lines.append(f"{pad}- ({cond['logic']})")
        for sub in cond.get("conditions", []):
            lines.extend(_render_condition(sub, indent + 1))
    else:
        feature = cond.get("feature")
        operator = cond.get("operator")
        threshold = cond.get("threshold")
        lines.append(f"{pad}- `{feature}` {operator} {threshold}")
    return lines


# ── Algo note ─────────────────────────────────────────────────────
def render_algo_note(strategy, dsl: dict | None, shadow_trades: list) -> str:
    """
    strategy: StrategyV2 row (promoted/active/retired only — never a
    raw candidate, per spec §3.4).
    dsl: parsed dsl_json, or None if unparseable.
    shadow_trades: recent StrategyPerformance rows for the quarantine record.
    """
    fm = _frontmatter({
        "aqrti_generated": True,
        "type": "algo",
        "family": strategy.family,
        "status": strategy.status,
        "fitness": strategy.fitness_score,
        "sharpe": strategy.sharpe,
        "win_rate": strategy.win_rate,
        "oos_passed": strategy.oos_passed,
        "promoted_at": strategy.promoted_at.isoformat() if strategy.promoted_at else None,
        "tags": ["aqrti/algo"],
    })

    title = strategy.name or strategy.strategy_id
    body = [f"\n# {title}\n"]
    body.append(f"Family: **{strategy.family}** · Status: **{strategy.status}** · Generation: {strategy.generation}")
    body.append("")

    if dsl and dsl.get("entry_conditions"):
        body.append("## Entry rules")
        body.extend(_render_condition(dsl["entry_conditions"]))
        body.append("")

    if dsl and dsl.get("exit_conditions"):
        body.append("## Exit rules")
        body.extend(_render_condition(dsl["exit_conditions"]))
        body.append("")

    body.append("## Backtest gates")
    gate_lines = []
    if strategy.fitness_score is not None:
        gate_lines.append(f"- Fitness: {strategy.fitness_score:.1f}")
    if strategy.sharpe is not None:
        gate_lines.append(f"- Sharpe: {strategy.sharpe:.2f}")
    if strategy.win_rate is not None:
        gate_lines.append(f"- Win rate: {strategy.win_rate:.1f}%")
    if strategy.trade_count is not None:
        gate_lines.append(f"- Trade count: {strategy.trade_count}")
    if strategy.oos_passed is not None:
        gate_lines.append(f"- OOS gate: {'passed' if strategy.oos_passed else 'failed'}")
    if gate_lines:
        body.extend(gate_lines)
        body.append("")
    else:
        body.append("_No backtest metrics recorded._")
        body.append("")

    if shadow_trades:
        body.append("## Shadow-trade record (forward-paper quarantine)")
        body.append("| Date | Opened | Closed | Daily P&L |")
        body.append("|---|---|---|---|")
        for row in shadow_trades[:20]:
            pnl = f"{row['daily_pnl']:+.2f}" if row.get("daily_pnl") is not None else "—"
            body.append(f"| {row['date']} | {row['trades_opened']} | {row['trades_closed']} | {pnl} |")
        body.append("")

    return fm + "\n" + "\n".join(body)


# ── Report note (per-agent) ──────────────────────────────────────
def render_report_note(agent_id: str, report_date: date, findings: list) -> str:
    fm = _frontmatter({
        "aqrti_generated": True,
        "type": "report",
        "agent": agent_id,
        "date": report_date.isoformat(),
        "tags": ["aqrti/report"],
    })

    body = [f"\n# {agent_id} — {report_date.isoformat()}\n"]

    deduped = _dedupe_findings(findings)
    if len(findings) > len(deduped):
        body.append(
            f"_{len(findings)} raw findings this day, collapsed to {len(deduped)} distinct "
            f"(agents re-log unchanged status on every intra-day run)._\n"
        )

    for f, occurrences in deduped:
        urgency_tag = f" [{f.urgency.upper()}]" if f.urgency and f.urgency != "normal" else ""
        count_tag = f" (×{occurrences})" if occurrences > 1 else ""
        body.append(f"## {f.title}{urgency_tag}{count_tag}")
        if f.description:
            body.append(f.description)
        if f.symbol:
            body.append(f"\nSymbol: {wikilink(f.symbol)}")
        if f.implication:
            body.append(f"\n*Implication:* {f.implication}")
        body.append("")

    if not findings:
        body.append("_No findings recorded._")
        body.append("")

    return fm + "\n" + "\n".join(body)


def _dedupe_findings(findings: list) -> list[tuple]:
    """
    Agents log a running-status finding (data coverage, "daily brief
    issued" summary, "all systems normal") on *every* intra-day run —
    same title pattern, but description text keeps changing as counters
    grow (e.g. "strategies_v2=51" -> "156" -> "786"). A daily digest only
    needs the final state of each running status, not every intermediate
    tick. Group by title with digits stripped (so "Data Coverage: 3/5"
    and "Data Coverage: 5/5" fall in the same bucket) and keep only the
    LAST occurrence of each bucket plus how many times it fired that day.
    Findings whose title has no embedded counter (a genuinely distinct,
    one-off finding) naturally form their own singleton bucket and pass
    through unchanged.
    """
    groups: dict[str, dict] = {}
    order: list[str] = []
    for f in findings:
        key = re.sub(r"\d[\d,./]*", "#", f.title or "")
        if key not in groups:
            order.append(key)
            groups[key] = {"latest": f, "count": 0}
        groups[key]["count"] += 1
        groups[key]["latest"] = f  # findings are queried in date/agent order — last wins

    return [(groups[key]["latest"], groups[key]["count"]) for key in order]


# ── Dataview index notes ──────────────────────────────────────────
# These are pure organization: a sorted table over each folder's own
# frontmatter, so the flat file list becomes a queryable view without
# any change to how individual notes are written. Inert plain text if
# Dataview isn't installed — degrades gracefully, never breaks reading.
def render_algos_index() -> str:
    fm = _frontmatter({"aqrti_generated": True, "type": "index", "tags": ["aqrti/index"]})
    body = [
        "\n# Algos Index\n",
        "Promoted, active, and retired algos — sorted by fitness. "
        "Candidates never appear here (927+ of them would be graph noise); "
        "only algos that cleared the full backtest+OOS+benchmark+duplicate gate chain show up.\n",
        "```dataview",
        "TABLE status, family, fitness, sharpe, win_rate, oos_passed, promoted_at",
        'FROM "Algos"',
        "WHERE type = \"algo\"",
        "SORT fitness DESC",
        "```",
    ]
    return fm + "\n" + "\n".join(body)


def render_lessons_index() -> str:
    fm = _frontmatter({"aqrti_generated": True, "type": "index", "tags": ["aqrti/index"]})
    body = [
        "\n# Lessons Index\n",
        "All lessons learned, most severe and most recent first.\n",
        "```dataview",
        "TABLE severity, category, regime, applied, date",
        'FROM "Lessons"',
        "WHERE type = \"lesson\"",
        "SORT severity DESC, date DESC",
        "```",
    ]
    return fm + "\n" + "\n".join(body)


def render_stocks_index() -> str:
    fm = _frontmatter({"aqrti_generated": True, "type": "index", "tags": ["aqrti/index"]})
    body = [
        "\n# Stocks Index\n",
        "Every symbol AQRTI has an opinion on — sorted by last confidence.\n",
        "```dataview",
        "TABLE sector, last_prediction, last_confidence, sentiment_score, in_portfolio",
        'FROM "Stocks"',
        "WHERE type = \"stock\"",
        "SORT last_confidence DESC",
        "```",
    ]
    return fm + "\n" + "\n".join(body)


def render_daily_index() -> str:
    fm = _frontmatter({"aqrti_generated": True, "type": "index", "tags": ["aqrti/index"]})
    body = [
        "\n# Daily Index\n",
        "Every day AQRTI ran its pipeline — most recent first.\n",
        "```dataview",
        "TABLE regime, knowledge_score, trades_opened, trades_closed",
        'FROM "Daily"',
        "WHERE type = \"daily\"",
        "SORT date DESC",
        "```",
    ]
    return fm + "\n" + "\n".join(body)
