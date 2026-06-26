"""Scenario Stress Test API — /api/v1/stress-test"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from aqrti.database.engine import get_db_dependency
from aqrti.database.models import PaperPosition, PaperPortfolio

router = APIRouter()

SECTOR_BETA = {
    "Banking": 1.3, "Finance": 1.2, "Technology": 0.8, "Auto": 1.1,
    "Energy": 0.9, "Pharma": 0.5, "FMCG": 0.6, "Metals": 1.4,
    "Telecom": 0.7, "Infrastructure": 1.1,
}

STOCK_SECTOR = {
    "RELIANCE": "Energy", "HDFCBANK": "Banking", "ICICIBANK": "Banking",
    "INFY": "Technology", "TCS": "Technology", "AXISBANK": "Banking",
    "SBIN": "Banking", "BAJFINANCE": "Finance", "MARUTI": "Auto",
    "TITAN": "FMCG", "WIPRO": "Technology", "ONGC": "Energy",
    "SUNPHARMA": "Pharma", "NESTLEIND": "FMCG", "BHARTIARTL": "Telecom",
    "KOTAKBANK": "Banking", "TATASTEEL": "Metals", "HINDALCO": "Metals",
}

@router.post("/run")
def run_stress_test(
    nifty_shock_pct: float = -10.0,
    sector_shock: str = None,
    sector_shock_pct: float = -15.0,
    db: Session = Depends(get_db_dependency),
):
    portfolio = db.query(PaperPortfolio).first()
    positions = db.query(PaperPosition).all()

    if not positions:
        return {
            "scenario": {"nifty_shock_pct": nifty_shock_pct, "sector_shock": sector_shock, "sector_shock_pct": sector_shock_pct},
            "total_pnl_impact": 0.0,
            "total_pnl_pct": 0.0,
            "portfolio_value": portfolio.total_value if portfolio else 100000,
            "new_portfolio_value": portfolio.total_value if portfolio else 100000,
            "positions": [],
            "message": "No open positions to stress test",
        }

    results = []
    total_impact = 0.0

    for pos in positions:
        sector = pos.sector or STOCK_SECTOR.get(pos.symbol, "Unknown")
        beta = SECTOR_BETA.get(sector, 1.0)

        stock_shock = nifty_shock_pct * beta

        if sector_shock and sector and sector.lower() == sector_shock.lower():
            stock_shock += sector_shock_pct

        current_val = pos.capital_deployed or (pos.entry_price * pos.shares)
        pnl_impact = current_val * (stock_shock / 100)
        new_price = pos.entry_price * (1 + stock_shock / 100)

        results.append({
            "symbol": pos.symbol,
            "sector": sector,
            "beta": round(beta, 2),
            "stock_shock_pct": round(stock_shock, 2),
            "current_value": round(current_val, 2),
            "pnl_impact": round(pnl_impact, 2),
            "new_price": round(new_price, 2),
            "entry_price": pos.entry_price,
        })
        total_impact += pnl_impact

    portfolio_value = (portfolio.total_value if portfolio else 100000) or 100000
    return {
        "scenario": {"nifty_shock_pct": nifty_shock_pct, "sector_shock": sector_shock, "sector_shock_pct": sector_shock_pct},
        "total_pnl_impact": round(total_impact, 2),
        "total_pnl_pct": round(total_impact / portfolio_value * 100, 2),
        "portfolio_value": portfolio_value,
        "new_portfolio_value": round(portfolio_value + total_impact, 2),
        "positions": results,
    }

@router.get("/presets")
def get_stress_presets():
    return {"presets": [
        {"name": "Bear Market",     "nifty_shock_pct": -20, "sector_shock": None,         "sector_shock_pct": 0},
        {"name": "Mild Correction", "nifty_shock_pct": -10, "sector_shock": None,         "sector_shock_pct": 0},
        {"name": "Banking Crisis",  "nifty_shock_pct": -8,  "sector_shock": "Banking",    "sector_shock_pct": -15},
        {"name": "IT Selloff",      "nifty_shock_pct": -5,  "sector_shock": "Technology", "sector_shock_pct": -12},
        {"name": "Metals Crash",    "nifty_shock_pct": -6,  "sector_shock": "Metals",     "sector_shock_pct": -18},
    ]}
