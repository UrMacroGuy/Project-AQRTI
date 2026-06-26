"""Watchlist API — /api/v1/watchlist"""
from __future__ import annotations
from fastapi import APIRouter

router = APIRouter()

_watchlist: list[str] = ["RELIANCE", "HDFCBANK", "INFY", "TCS"]

@router.get("")
def get_watchlist():
    return {"symbols": _watchlist}

@router.post("/add")
def add_to_watchlist(symbol: str):
    sym = symbol.upper().strip()
    if sym not in _watchlist:
        _watchlist.append(sym)
    return {"symbols": _watchlist}

@router.post("/remove")
def remove_from_watchlist(symbol: str):
    sym = symbol.upper().strip()
    if sym in _watchlist:
        _watchlist.remove(sym)
    return {"symbols": _watchlist}
