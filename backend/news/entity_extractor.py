"""
AQRTI Entity Extractor
Identifies NSE stock symbols and sector names in news headlines/summaries.
Uses exact token matching with aliases — no NLP library required.
Returns: primary_symbol, all_symbols[], sector

Approach:
  1. Build a lookup table from symbol → set of name variants
  2. Tokenise headline + summary
  3. Match tokens against lookup (case-insensitive, whole-word)
  4. Classify as 'primary' (first/strongest match) vs 'secondary'
"""

from __future__ import annotations

import re
from typing import Optional

# ══════════════════════════════════════════════════════════════
# ENTITY MAP — symbol → (sector, [name variants])
# Variants are checked as case-insensitive substrings in headlines.
# ══════════════════════════════════════════════════════════════
ENTITY_MAP: dict[str, tuple[str, list[str]]] = {
    "RELIANCE":   ("Energy",    ["Reliance", "Reliance Industries", "RIL", "Jio"]),
    "TCS":        ("IT",        ["TCS", "Tata Consultancy", "Tata Consultancy Services"]),
    "INFY":       ("IT",        ["Infosys", "INFY"]),
    "HDFCBANK":   ("Banking",   ["HDFC Bank", "HDFCBank"]),
    "ICICIBANK":  ("Banking",   ["ICICI Bank", "ICICIBank", "ICICI"]),
    "WIPRO":      ("IT",        ["Wipro"]),
    "AXISBANK":   ("Banking",   ["Axis Bank", "AxisBank"]),
    "LTM":        ("IT",        ["LTM", "LTM Limited", "LTIMindtree", "LTI Mindtree", "LTIM"]),
    "NESTLEIND":  ("FMCG",      ["Nestle India", "Nestlé", "Nestle"]),
    "BAJFINANCE": ("NBFC",      ["Bajaj Finance", "BajFinance"]),
    "MARUTI":     ("Auto",      ["Maruti", "Maruti Suzuki", "MSIL"]),
    "SUNPHARMA":  ("Pharma",    ["Sun Pharma", "Sun Pharmaceutical", "SUNPHARMA"]),
    "TATASTEEL":  ("Metal",     ["Tata Steel", "TataSteel"]),
    "TMPV":       ("Auto",      ["TMPV", "Tata Motors", "TataMotors", "Tata Motors Passenger Vehicles"]),
    "KOTAKBANK":  ("Banking",   ["Kotak", "Kotak Mahindra", "Kotak Bank"]),
    "TITAN":      ("Consumer",  ["Titan"]),
    "ONGC":       ("Energy",    ["ONGC", "Oil and Natural Gas", "Oil & Natural Gas"]),
    "HINDALCO":   ("Metal",     ["Hindalco"]),
    "SBIN":       ("Banking",   ["SBI", "State Bank", "State Bank of India"]),
    "BHARTIARTL": ("Telecom",   ["Bharti Airtel", "Airtel", "Bharti"]),
    # Sector-level entities (mapped to a pseudo-symbol for aggregation)
    "__IT__":     ("IT",        ["IT sector", "tech sector", "information technology sector"]),
    "__BANKING__":("Banking",   ["banking sector", "bank stocks", "PSU banks", "private banks"]),
    "__PHARMA__": ("Pharma",    ["pharma sector", "pharmaceutical sector"]),
    "__AUTO__":   ("Auto",      ["auto sector", "automobile sector", "EV sector"]),
    "__FMCG__":   ("FMCG",      ["FMCG sector", "consumer staples"]),
    "__METAL__":  ("Metal",     ["metal sector", "steel sector"]),
    "__ENERGY__": ("Energy",    ["energy sector", "oil sector", "upstream oil"]),
}

# Pre-compile variant→symbol lookup for O(1) matching
_VARIANT_LOOKUP: dict[str, str] = {}
for _sym, (_sec, _variants) in ENTITY_MAP.items():
    for _v in _variants:
        _VARIANT_LOOKUP[_v.lower()] = _sym


def extract_entities(
    headline: str,
    summary: Optional[str] = None,
) -> dict:
    """
    Returns:
      {
        "symbols":        [list of matched symbols, most prominent first],
        "primary_symbol": str | None,
        "sector":         str | None,
        "mention_types":  {symbol: "primary"|"secondary"},
      }
    """
    text = headline + " " + (summary or "")
    text_lower = text.lower()

    matched: dict[str, int] = {}  # symbol → mention_count

    for variant, symbol in _VARIANT_LOOKUP.items():
        # Whole-word match: word boundary or surrounded by space/punctuation
        pattern = r"(?<![a-zA-Z])" + re.escape(variant) + r"(?![a-zA-Z])"
        count = len(re.findall(pattern, text_lower, re.IGNORECASE))
        if count > 0:
            matched[symbol] = matched.get(symbol, 0) + count

    if not matched:
        # Try exact uppercase ticker match (e.g., "RELIANCE fell 2%")
        tokens = re.findall(r"\b[A-Z]{2,15}\b", headline + " " + (summary or ""))
        for tok in tokens:
            if tok in ENTITY_MAP:
                matched[tok] = matched.get(tok, 0) + 1

    # Sort by mention count descending
    ranked = sorted(matched.items(), key=lambda x: x[1], reverse=True)

    # Filter out sector pseudo-symbols from the symbol list
    real_symbols  = [s for s, _ in ranked if not s.startswith("__")]
    sector_hits   = [s for s, _ in ranked if s.startswith("__")]

    primary_symbol = real_symbols[0] if real_symbols else None
    sector         = None

    if primary_symbol and primary_symbol in ENTITY_MAP:
        sector = ENTITY_MAP[primary_symbol][0]
    elif sector_hits:
        sector = ENTITY_MAP[sector_hits[0]][0]

    mention_types: dict[str, str] = {}
    for i, sym in enumerate(real_symbols):
        mention_types[sym] = "primary" if i == 0 else "secondary"

    return {
        "symbols":        real_symbols,
        "primary_symbol": primary_symbol,
        "sector":         sector,
        "mention_types":  mention_types,
    }
