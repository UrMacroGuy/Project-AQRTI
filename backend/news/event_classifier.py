"""
AQRTI Event Classifier
Maps a parsed news headline + summary to a structured event_type.

Event Types (9 + General):
  Earnings        — quarterly/annual results, revenue, profit, EPS
  Acquisition     — acquisition, takeover, buyout, stake purchase
  Merger          — merger, amalgamation, consolidation
  Buyback         — share buyback, share repurchase
  Dividend        — dividend, interim dividend, final dividend
  ManagementChange — CEO, MD, CFO appointment/resignation
  RegulatoryAction — SEBI, RBI, CCI, penalty, fine, notice, order
  LargeOrder      — order win, contract, deal award, LoI
  LegalEvent      — court, litigation, lawsuit, arbitration
  General         — fallthrough for anything else

Classification is rule-based via ordered keyword patterns.
Most specific patterns are checked first.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class EventType(str, Enum):
    EARNINGS          = "Earnings"
    ACQUISITION       = "Acquisition"
    MERGER            = "Merger"
    BUYBACK           = "Buyback"
    DIVIDEND          = "Dividend"
    MANAGEMENT_CHANGE = "ManagementChange"
    REGULATORY_ACTION = "RegulatoryAction"
    LARGE_ORDER       = "LargeOrder"
    LEGAL_EVENT       = "LegalEvent"
    GENERAL           = "General"


# ══════════════════════════════════════════════════════════════
# CLASSIFICATION RULES
# Ordered: first match wins. More specific patterns first.
# ══════════════════════════════════════════════════════════════
_RULES: list[tuple[EventType, list[str]]] = [
    (EventType.EARNINGS, [
        r"\bq[1-4]\s*(fy|result|profit|revenue|net\s+profit|earnings)\b",
        r"\b(quarterly|annual|q1|q2|q3|q4|fy\d{2,4})\s*(result|earning|profit|revenue|loss)\b",
        r"\b(net\s+profit|operating\s+profit|ebitda|revenue|eps)\s*(up|down|rises?|falls?|jumps?|slips?|surges?|drops?)\b",
        r"\b(results?|earnings?)\s+(beat|miss|inline|in.?line|disappoint)\b",
        r"\b(profit|loss|revenue|income)\s*(up|down|rises?|falls?|jumps?|slips?)\s+\d+",
        r"\bfinancial\s+results?\b",
    ]),
    (EventType.BUYBACK, [
        r"\bbuyback\b",
        r"\bshare\s+repurchase\b",
        r"\bbuy.?back\b",
    ]),
    (EventType.DIVIDEND, [
        r"\b(interim|final|special|bonus)\s+dividend\b",
        r"\bdividend\s+(declared?|announced?|recommended?|approved?)\b",
        r"\bdividend\s+of\s+(?:rs|₹|inr)?\s*\d+\b",
    ]),
    (EventType.ACQUISITION, [
        r"\b(acquires?|acquisition|buyout|stake\s+purchase|buys?\s+\d+%)\b",
        r"\b(acquiring|purchased?\s+stake|takeover|acquired)\b",
    ]),
    (EventType.MERGER, [
        r"\b(merger|amalgamation|merges?\s+with|merging\s+with|consolidation)\b",
        r"\bmerger\s+(agreement|deal|ratio|swap)\b",
    ]),
    (EventType.MANAGEMENT_CHANGE, [
        r"\b(ceo|md|cfo|coo|chairman|director)\s+(resigns?|quits?|steps?\s+down|appointed?|joins?|elevated?)\b",
        r"\b(appoints?|names?|elevates?)\s+new\s+(ceo|cfo|md|coo|chairman)\b",
        r"\b(resignation|appointment)\s+of\s+(ceo|md|cfo|chairman|director)\b",
    ]),
    (EventType.REGULATORY_ACTION, [
        r"\b(sebi|rbi|cci|nclt|ed|cbi|income\s+tax)\s*(order|notice|penalty|fine|probe|investigation|approval|approval)\b",
        r"\b(penali[sz]es?|fined?|notice|show.?cause|enforcement)\b",
        r"\bregulatory\s+(approval|clearance|order|action|compliance)\b",
        r"\b(rbi|sebi)\s+(bans?|bars?|suspends?|approves?|rejects?)\b",
    ]),
    (EventType.LARGE_ORDER, [
        r"\b(wins?\s+order|order\s+win|bags?\s+order|receives?\s+order|secures?\s+order)\b",
        r"\b(contract\s+(win|award|valued?|worth)|deal\s+(win|award|signed?))\b",
        r"\b(loi|letter\s+of\s+intent)\s+(received?|issued?|awarded?)\b",
        r"\border\s+(worth|valued?\s+at|of)\s+(?:rs|₹|inr)?\s*\d+",
    ]),
    (EventType.LEGAL_EVENT, [
        r"\b(court|tribunal|arbitration|lawsuit|litigation|legal\s+challenge)\b",
        r"\b(files?\s+suit|sued|injunction|stay\s+order|contempt)\b",
        r"\b(supreme\s+court|high\s+court|nclt|nclat)\s+(ruling|order|verdict|judgment)\b",
    ]),
]


def classify_event(headline: str, summary: Optional[str] = None) -> EventType:
    """
    Return the most specific matching EventType.
    Checks headline first (higher weight), then summary.
    Falls back to General if no pattern matches.
    """
    text = (headline + " " + (summary or "")).lower()

    for event_type, patterns in _RULES:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return event_type

    return EventType.GENERAL


def classify_event_str(headline: str, summary: Optional[str] = None) -> str:
    return classify_event(headline, summary).value
