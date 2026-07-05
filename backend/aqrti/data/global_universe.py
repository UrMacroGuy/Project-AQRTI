"""
AQRTI Global Stock Universe
Downloads 3yr OHLCV for top ~1000 world stocks via yfinance.
Stores to same DailyPrice + Stock tables as market_data.py.
"""

from __future__ import annotations

from contextlib import redirect_stderr
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from io import StringIO
from typing import Optional

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from aqrti.database.engine import get_session_factory
from aqrti.database.models import DailyPrice, Stock
from aqrti.utils.logger import data_logger

_YF_DOWNLOAD_LOCK = threading.Lock()

# ── Global Universe Definition ────────────────────────────────
# Format: ticker_as_yfinance -> {name, sector, industry, exchange, currency, region}

GLOBAL_UNIVERSE: dict[str, dict] = {

    # ══════════ UNITED STATES — S&P 500 + Russell 1000 ══════════
    "AAPL":  {"name": "Apple Inc",                          "sector": "Technology",          "industry": "Consumer Electronics",     "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "MSFT":  {"name": "Microsoft Corporation",              "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "NVDA":  {"name": "NVIDIA Corporation",                 "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "AMZN":  {"name": "Amazon.com Inc",                     "sector": "Consumer Cyclical",   "industry": "Internet Retail",          "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "META":  {"name": "Meta Platforms Inc",                 "sector": "Technology",          "industry": "Internet Content",         "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "GOOGL": {"name": "Alphabet Inc Class A",               "sector": "Technology",          "industry": "Internet Content",         "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "GOOG":  {"name": "Alphabet Inc Class C",               "sector": "Technology",          "industry": "Internet Content",         "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "BRK-B": {"name": "Berkshire Hathaway Inc Class B",     "sector": "Financial Services",  "industry": "Insurance",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "LLY":   {"name": "Eli Lilly and Company",              "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "JPM":   {"name": "JPMorgan Chase & Co",                "sector": "Financial Services",  "industry": "Banks",                    "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "V":     {"name": "Visa Inc",                           "sector": "Financial Services",  "industry": "Credit Services",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "TSLA":  {"name": "Tesla Inc",                          "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "UNH":   {"name": "UnitedHealth Group Incorporated",    "sector": "Healthcare",          "industry": "Healthcare Plans",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "XOM":   {"name": "Exxon Mobil Corporation",            "sector": "Energy",              "industry": "Oil & Gas",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "MA":    {"name": "Mastercard Incorporated",            "sector": "Financial Services",  "industry": "Credit Services",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "PG":    {"name": "Procter & Gamble Company",           "sector": "Consumer Defensive",  "industry": "Household Products",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "COST":  {"name": "Costco Wholesale Corporation",       "sector": "Consumer Defensive",  "industry": "Discount Stores",          "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "HD":    {"name": "Home Depot Inc",                     "sector": "Consumer Cyclical",   "industry": "Home Improvement Retail",  "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "JNJ":   {"name": "Johnson & Johnson",                  "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ABBV":  {"name": "AbbVie Inc",                         "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "BAC":   {"name": "Bank of America Corporation",        "sector": "Financial Services",  "industry": "Banks",                    "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "KO":    {"name": "Coca-Cola Company",                  "sector": "Consumer Defensive",  "industry": "Beverages",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "WMT":   {"name": "Walmart Inc",                        "sector": "Consumer Defensive",  "industry": "Discount Stores",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ORCL":  {"name": "Oracle Corporation",                 "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "MRK":   {"name": "Merck & Co Inc",                     "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "CVX":   {"name": "Chevron Corporation",                "sector": "Energy",              "industry": "Oil & Gas",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "NFLX":  {"name": "Netflix Inc",                        "sector": "Communication",       "industry": "Entertainment",            "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "CRM":   {"name": "Salesforce Inc",                     "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "AMD":   {"name": "Advanced Micro Devices Inc",         "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "CSCO":  {"name": "Cisco Systems Inc",                  "sector": "Technology",          "industry": "Communication Equipment",  "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "ACN":   {"name": "Accenture plc",                      "sector": "Technology",          "industry": "IT Services",              "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ADBE":  {"name": "Adobe Inc",                          "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "WFC":   {"name": "Wells Fargo & Company",              "sector": "Financial Services",  "industry": "Banks",                    "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "MCD":   {"name": "McDonald's Corporation",             "sector": "Consumer Cyclical",   "industry": "Restaurants",              "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ABT":   {"name": "Abbott Laboratories",                "sector": "Healthcare",          "industry": "Medical Devices",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "IBM":   {"name": "International Business Machines",    "sector": "Technology",          "industry": "IT Services",              "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "TMO":   {"name": "Thermo Fisher Scientific Inc",       "sector": "Healthcare",          "industry": "Diagnostics & Research",   "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "GS":    {"name": "Goldman Sachs Group Inc",            "sector": "Financial Services",  "industry": "Capital Markets",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "MS":    {"name": "Morgan Stanley",                     "sector": "Financial Services",  "industry": "Capital Markets",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "CAT":   {"name": "Caterpillar Inc",                    "sector": "Industrials",         "industry": "Farm & Heavy Construction", "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "NOW":   {"name": "ServiceNow Inc",                     "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "RTX":   {"name": "RTX Corporation",                    "sector": "Industrials",         "industry": "Aerospace & Defense",      "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "INTU":  {"name": "Intuit Inc",                         "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "QCOM":  {"name": "QUALCOMM Incorporated",              "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "T":     {"name": "AT&T Inc",                           "sector": "Communication",       "industry": "Telecom Services",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "VZ":    {"name": "Verizon Communications Inc",         "sector": "Communication",       "industry": "Telecom Services",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "AMGN":  {"name": "Amgen Inc",                          "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "HON":   {"name": "Honeywell International Inc",        "sector": "Industrials",         "industry": "Conglomerates",            "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "UNP":   {"name": "Union Pacific Corporation",          "sector": "Industrials",         "industry": "Railroads",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "AXP":   {"name": "American Express Company",           "sector": "Financial Services",  "industry": "Credit Services",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "LOW":   {"name": "Lowe's Companies Inc",               "sector": "Consumer Cyclical",   "industry": "Home Improvement Retail",  "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "SPGI":  {"name": "S&P Global Inc",                     "sector": "Financial Services",  "industry": "Financial Data",           "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "BMY":   {"name": "Bristol-Myers Squibb Company",       "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "BLK":   {"name": "BlackRock Inc",                      "sector": "Financial Services",  "industry": "Asset Management",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "SYK":   {"name": "Stryker Corporation",                "sector": "Healthcare",          "industry": "Medical Devices",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "DE":    {"name": "Deere & Company",                    "sector": "Industrials",         "industry": "Farm & Heavy Construction", "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SBUX":  {"name": "Starbucks Corporation",              "sector": "Consumer Cyclical",   "industry": "Restaurants",              "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "AMAT":  {"name": "Applied Materials Inc",              "sector": "Technology",          "industry": "Semiconductor Equipment",  "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "TJX":   {"name": "TJX Companies Inc",                  "sector": "Consumer Cyclical",   "industry": "Apparel Retail",           "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "GILD":  {"name": "Gilead Sciences Inc",                "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "PLD":   {"name": "Prologis Inc",                       "sector": "Real Estate",         "industry": "REIT Industrial",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ADP":   {"name": "Automatic Data Processing Inc",      "sector": "Technology",          "industry": "Staffing & Employment",    "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "MMC":   {"name": "Marsh & McLennan Companies Inc",     "sector": "Financial Services",  "industry": "Insurance",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "LRCX":  {"name": "Lam Research Corporation",           "sector": "Technology",          "industry": "Semiconductor Equipment",  "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "MDLZ":  {"name": "Mondelez International Inc",         "sector": "Consumer Defensive",  "industry": "Packaged Foods",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "ISRG":  {"name": "Intuitive Surgical Inc",             "sector": "Healthcare",          "industry": "Medical Devices",          "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "PGR":   {"name": "Progressive Corporation",            "sector": "Financial Services",  "industry": "Insurance",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "BKNG":  {"name": "Booking Holdings Inc",               "sector": "Consumer Cyclical",   "industry": "Travel Services",          "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "ADI":   {"name": "Analog Devices Inc",                 "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "REGN":  {"name": "Regeneron Pharmaceuticals Inc",      "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "CB":    {"name": "Chubb Limited",                      "sector": "Financial Services",  "industry": "Insurance",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "MU":    {"name": "Micron Technology Inc",              "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "CI":    {"name": "Cigna Group",                        "sector": "Healthcare",          "industry": "Healthcare Plans",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "DUK":   {"name": "Duke Energy Corporation",            "sector": "Utilities",           "industry": "Utilities Regulated",      "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "SO":    {"name": "Southern Company",                   "sector": "Utilities",           "industry": "Utilities Regulated",      "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "PFE":   {"name": "Pfizer Inc",                         "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "NEE":   {"name": "NextEra Energy Inc",                 "sector": "Utilities",           "industry": "Utilities Regulated",      "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "INTC":  {"name": "Intel Corporation",                  "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "MO":    {"name": "Altria Group Inc",                   "sector": "Consumer Defensive",  "industry": "Tobacco",                  "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "USB":   {"name": "U.S. Bancorp",                       "sector": "Financial Services",  "industry": "Banks",                    "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "TGT":   {"name": "Target Corporation",                 "sector": "Consumer Defensive",  "industry": "Discount Stores",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "COP":   {"name": "ConocoPhillips",                     "sector": "Energy",              "industry": "Oil & Gas",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "EOG":   {"name": "EOG Resources Inc",                  "sector": "Energy",              "industry": "Oil & Gas",                "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "SLB":   {"name": "SLB (Schlumberger)",                 "sector": "Energy",              "industry": "Oil & Gas Equipment",      "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ETN":   {"name": "Eaton Corporation plc",              "sector": "Industrials",         "industry": "Electrical Equipment",     "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "EMR":   {"name": "Emerson Electric Company",           "sector": "Industrials",         "industry": "Diversified Industrials",  "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "NOC":   {"name": "Northrop Grumman Corporation",       "sector": "Industrials",         "industry": "Aerospace & Defense",      "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "LMT":   {"name": "Lockheed Martin Corporation",        "sector": "Industrials",         "industry": "Aerospace & Defense",      "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "BA":    {"name": "Boeing Company",                     "sector": "Industrials",         "industry": "Aerospace & Defense",      "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "GE":    {"name": "GE Aerospace",                       "sector": "Industrials",         "industry": "Aerospace & Defense",      "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "UPS":   {"name": "United Parcel Service Inc",          "sector": "Industrials",         "industry": "Integrated Freight",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "FDX":   {"name": "FedEx Corporation",                  "sector": "Industrials",         "industry": "Integrated Freight",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "MMM":   {"name": "3M Company",                         "sector": "Industrials",         "industry": "Diversified Industrials",  "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "GM":    {"name": "General Motors Company",             "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "F":     {"name": "Ford Motor Company",                 "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "UBER":  {"name": "Uber Technologies Inc",              "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "LYFT":  {"name": "Lyft Inc",                           "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "ABNB":  {"name": "Airbnb Inc",                         "sector": "Consumer Cyclical",   "industry": "Travel Services",          "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "SHOP":  {"name": "Shopify Inc",                        "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "SQ":    {"name": "Block Inc",                          "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "PYPL":  {"name": "PayPal Holdings Inc",                "sector": "Financial Services",  "industry": "Credit Services",         "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "SNOW":  {"name": "Snowflake Inc",                      "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "COIN":  {"name": "Coinbase Global Inc",                "sector": "Financial Services",  "industry": "Capital Markets",          "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "ROKU":  {"name": "Roku Inc",                           "sector": "Technology",          "industry": "Consumer Electronics",     "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "SPOT":  {"name": "Spotify Technology SA",              "sector": "Communication",       "industry": "Entertainment",            "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ZM":    {"name": "Zoom Video Communications Inc",      "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "PLTR":  {"name": "Palantir Technologies Inc",          "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "PATH":  {"name": "UiPath Inc",                         "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "NET":   {"name": "Cloudflare Inc",                     "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "DDOG":  {"name": "Datadog Inc",                        "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "MDB":   {"name": "MongoDB Inc",                        "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "CRWD":  {"name": "CrowdStrike Holdings Inc",           "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "PANW":  {"name": "Palo Alto Networks Inc",             "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "ZS":    {"name": "Zscaler Inc",                        "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "OKTA":  {"name": "Okta Inc",                           "sector": "Technology",          "industry": "Software",                 "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "TWLO":  {"name": "Twilio Inc",                         "sector": "Technology",          "industry": "Software",                 "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "RBLX":  {"name": "Roblox Corporation",                 "sector": "Technology",          "industry": "Electronic Games",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "RIVN":  {"name": "Rivian Automotive Inc",              "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "LCID":  {"name": "Lucid Group Inc",                    "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "NIO":   {"name": "NIO Inc",                            "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "LI":    {"name": "Li Auto Inc",                        "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "WBD":   {"name": "Warner Bros. Discovery Inc",         "sector": "Communication",       "industry": "Entertainment",            "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "DIS":   {"name": "Walt Disney Company",                "sector": "Communication",       "industry": "Entertainment",            "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "CMCSA": {"name": "Comcast Corporation",                "sector": "Communication",       "industry": "Pay TV",                   "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "CHTR":  {"name": "Charter Communications Inc",         "sector": "Communication",       "industry": "Pay TV",                   "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "EA":    {"name": "Electronic Arts Inc",                "sector": "Communication",       "industry": "Electronic Games",         "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "TTWO":  {"name": "Take-Two Interactive Software",      "sector": "Communication",       "industry": "Electronic Games",         "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "ATVI":  {"name": "Activision Blizzard Inc",            "sector": "Communication",       "industry": "Electronic Games",         "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "AMD":   {"name": "Advanced Micro Devices Inc",         "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "TXN":   {"name": "Texas Instruments Incorporated",     "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "KLAC":  {"name": "KLA Corporation",                    "sector": "Technology",          "industry": "Semiconductor Equipment",  "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "MCHP":  {"name": "Microchip Technology Incorporated",  "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "NXPI":  {"name": "NXP Semiconductors NV",             "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "ON":    {"name": "ON Semiconductor Corporation",       "sector": "Technology",          "industry": "Semiconductors",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "ENPH":  {"name": "Enphase Energy Inc",                 "sector": "Technology",          "industry": "Solar",                    "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "FSLR":  {"name": "First Solar Inc",                    "sector": "Technology",          "industry": "Solar",                    "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "SEDG":  {"name": "SolarEdge Technologies Inc",         "sector": "Technology",          "industry": "Solar",                    "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "CVS":   {"name": "CVS Health Corporation",             "sector": "Healthcare",          "industry": "Healthcare Plans",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "HCA":   {"name": "HCA Healthcare Inc",                 "sector": "Healthcare",          "industry": "Medical Care Facilities",  "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "DHR":   {"name": "Danaher Corporation",                "sector": "Healthcare",          "industry": "Diagnostics & Research",   "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "BSX":   {"name": "Boston Scientific Corporation",      "sector": "Healthcare",          "industry": "Medical Devices",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "MDT":   {"name": "Medtronic plc",                      "sector": "Healthcare",          "industry": "Medical Devices",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ELV":   {"name": "Elevance Health Inc",                "sector": "Healthcare",          "industry": "Healthcare Plans",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "HUM":   {"name": "Humana Inc",                         "sector": "Healthcare",          "industry": "Healthcare Plans",         "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "VRTX":  {"name": "Vertex Pharmaceuticals Incorporated","sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "BIIB":  {"name": "Biogen Inc",                         "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "MRNA":  {"name": "Moderna Inc",                        "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "BNTX":  {"name": "BioNTech SE",                        "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "IQV":   {"name": "IQVIA Holdings Inc",                 "sector": "Healthcare",          "industry": "Diagnostics & Research",   "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ZBH":   {"name": "Zimmer Biomet Holdings Inc",         "sector": "Healthcare",          "industry": "Medical Devices",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "IDXX":  {"name": "IDEXX Laboratories Inc",             "sector": "Healthcare",          "industry": "Diagnostics & Research",   "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "EW":    {"name": "Edwards Lifesciences Corporation",   "sector": "Healthcare",          "industry": "Medical Devices",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "BAX":   {"name": "Baxter International Inc",           "sector": "Healthcare",          "industry": "Medical Devices",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "BDX":   {"name": "Becton Dickinson and Company",       "sector": "Healthcare",          "industry": "Medical Devices",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "ZTS":   {"name": "Zoetis Inc",                         "sector": "Healthcare",          "industry": "Drug Manufacturers",       "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "MCK":   {"name": "McKesson Corporation",               "sector": "Healthcare",          "industry": "Healthcare Distribution",  "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "CAH":   {"name": "Cardinal Health Inc",                "sector": "Healthcare",          "industry": "Healthcare Distribution",  "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "AMT":   {"name": "American Tower Corporation",         "sector": "Real Estate",         "industry": "REIT Specialty",           "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "EQIX":  {"name": "Equinix Inc",                        "sector": "Real Estate",         "industry": "REIT Specialty",           "exchange": "NASDAQ", "currency": "USD", "region": "US"},
    "SPG":   {"name": "Simon Property Group Inc",           "sector": "Real Estate",         "industry": "REIT Retail",              "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "PSA":   {"name": "Public Storage",                     "sector": "Real Estate",         "industry": "REIT Industrial",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "WY":    {"name": "Weyerhaeuser Company",               "sector": "Real Estate",         "industry": "REIT Specialty",           "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "O":     {"name": "Realty Income Corporation",          "sector": "Real Estate",         "industry": "REIT Retail",              "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "WELL":  {"name": "Welltower Inc",                      "sector": "Real Estate",         "industry": "REIT Healthcare",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "DLR":   {"name": "Digital Realty Trust Inc",           "sector": "Real Estate",         "industry": "REIT Specialty",           "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "VTR":   {"name": "Ventas Inc",                         "sector": "Real Estate",         "industry": "REIT Healthcare",          "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "CBRE":  {"name": "CBRE Group Inc",                     "sector": "Real Estate",         "industry": "Real Estate Services",     "exchange": "NYSE",   "currency": "USD", "region": "US"},
    "BXP":   {"name": "BXP Inc",                            "sector": "Real Estate",         "industry": "REIT Office",              "exchange": "NYSE",   "currency": "USD", "region": "US"},

    # ══════════ INDIA NSE — Nifty 500 Core ══════════
    "RELIANCE.NS":    {"name": "Reliance Industries",          "sector": "Energy",           "industry": "Oil & Gas",              "exchange": "NSE", "currency": "INR", "region": "IN"},
    "TCS.NS":         {"name": "Tata Consultancy Services",    "sector": "Technology",       "industry": "IT Services",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "INFY.NS":        {"name": "Infosys Ltd",                  "sector": "Technology",       "industry": "IT Services",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "HDFCBANK.NS":    {"name": "HDFC Bank",                    "sector": "Banking",          "industry": "Private Bank",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ICICIBANK.NS":   {"name": "ICICI Bank",                   "sector": "Banking",          "industry": "Private Bank",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "WIPRO.NS":       {"name": "Wipro Ltd",                    "sector": "Technology",       "industry": "IT Services",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "AXISBANK.NS":    {"name": "Axis Bank",                    "sector": "Banking",          "industry": "Private Bank",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "SBIN.NS":        {"name": "State Bank of India",          "sector": "Banking",          "industry": "PSU Bank",               "exchange": "NSE", "currency": "INR", "region": "IN"},
    "KOTAKBANK.NS":   {"name": "Kotak Mahindra Bank",          "sector": "Banking",          "industry": "Private Bank",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "HCLTECH.NS":     {"name": "HCL Technologies",             "sector": "Technology",       "industry": "IT Services",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "TECHM.NS":       {"name": "Tech Mahindra",                "sector": "Technology",       "industry": "IT Services",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "MPHASIS.NS":     {"name": "Mphasis",                      "sector": "Technology",       "industry": "IT Services",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "PERSISTENT.NS":  {"name": "Persistent Systems",           "sector": "Technology",       "industry": "IT Services",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "COFORGE.NS":     {"name": "Coforge",                      "sector": "Technology",       "industry": "IT Services",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "MARUTI.NS":      {"name": "Maruti Suzuki India",          "sector": "Auto",             "industry": "Automobiles",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "M&M.NS":         {"name": "Mahindra & Mahindra",          "sector": "Auto",             "industry": "Automobiles",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BAJAJ-AUTO.NS":  {"name": "Bajaj Auto",                   "sector": "Auto",             "industry": "Two Wheelers",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "HEROMOTOCO.NS":  {"name": "Hero MotoCorp",                "sector": "Auto",             "industry": "Two Wheelers",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "EICHERMOT.NS":   {"name": "Eicher Motors",                "sector": "Auto",             "industry": "Two Wheelers",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "TVSMOTOR.NS":    {"name": "TVS Motor Company",            "sector": "Auto",             "industry": "Two Wheelers",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BOSCHLTD.NS":    {"name": "Bosch Ltd",                    "sector": "Auto",             "industry": "Auto Components",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "MOTHERSON.NS":   {"name": "Samvardhana Motherson",        "sector": "Auto",             "industry": "Auto Components",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BHARTIARTL.NS":  {"name": "Bharti Airtel",                "sector": "Telecom",          "industry": "Telecom",                "exchange": "NSE", "currency": "INR", "region": "IN"},
    "INDUSINDBK.NS":  {"name": "IndusInd Bank",                "sector": "Banking",          "industry": "Private Bank",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BANDHANBNK.NS":  {"name": "Bandhan Bank",                 "sector": "Banking",          "industry": "Private Bank",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "FEDERALBNK.NS":  {"name": "Federal Bank",                 "sector": "Banking",          "industry": "Private Bank",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "IDFCFIRSTB.NS":  {"name": "IDFC First Bank",              "sector": "Banking",          "industry": "Private Bank",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BAJFINANCE.NS":  {"name": "Bajaj Finance",                "sector": "NBFC",             "industry": "Finance",                "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BAJAJFINSV.NS":  {"name": "Bajaj Finserv",                "sector": "NBFC",             "industry": "Finance",                "exchange": "NSE", "currency": "INR", "region": "IN"},
    "CHOLAFIN.NS":    {"name": "Cholamandalam Investment",     "sector": "NBFC",             "industry": "Finance",                "exchange": "NSE", "currency": "INR", "region": "IN"},
    "MUTHOOTFIN.NS":  {"name": "Muthoot Finance",              "sector": "NBFC",             "industry": "Finance",                "exchange": "NSE", "currency": "INR", "region": "IN"},
    "SUNPHARMA.NS":   {"name": "Sun Pharmaceutical",           "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "DRREDDY.NS":     {"name": "Dr Reddys Laboratories",       "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "CIPLA.NS":       {"name": "Cipla",                        "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "DIVISLAB.NS":    {"name": "Divis Laboratories",           "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "AUROPHARMA.NS":  {"name": "Aurobindo Pharma",             "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "LUPIN.NS":       {"name": "Lupin",                        "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "TORNTPHARM.NS":  {"name": "Torrent Pharmaceuticals",      "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ALKEM.NS":       {"name": "Alkem Laboratories",           "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "NSE", "currency": "INR", "region": "IN"},
    "HINDUNILVR.NS":  {"name": "Hindustan Unilever",           "sector": "FMCG",             "industry": "FMCG",                   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "NESTLEIND.NS":   {"name": "Nestle India",                 "sector": "FMCG",             "industry": "Food Products",          "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ITC.NS":         {"name": "ITC Ltd",                      "sector": "FMCG",             "industry": "FMCG",                   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BRITANNIA.NS":   {"name": "Britannia Industries",         "sector": "FMCG",             "industry": "Food Products",          "exchange": "NSE", "currency": "INR", "region": "IN"},
    "DABUR.NS":       {"name": "Dabur India",                  "sector": "FMCG",             "industry": "FMCG",                   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "MARICO.NS":      {"name": "Marico",                       "sector": "FMCG",             "industry": "FMCG",                   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "COLPAL.NS":      {"name": "Colgate-Palmolive India",      "sector": "FMCG",             "industry": "FMCG",                   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "GODREJCP.NS":    {"name": "Godrej Consumer Products",     "sector": "FMCG",             "industry": "FMCG",                   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "EMAMILTD.NS":    {"name": "Emami",                        "sector": "FMCG",             "industry": "FMCG",                   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "TATASTEEL.NS":   {"name": "Tata Steel",                   "sector": "Metal",            "industry": "Steel",                  "exchange": "NSE", "currency": "INR", "region": "IN"},
    "JSWSTEEL.NS":    {"name": "JSW Steel",                    "sector": "Metal",            "industry": "Steel",                  "exchange": "NSE", "currency": "INR", "region": "IN"},
    "HINDALCO.NS":    {"name": "Hindalco Industries",          "sector": "Metal",            "industry": "Aluminium",              "exchange": "NSE", "currency": "INR", "region": "IN"},
    "VEDL.NS":        {"name": "Vedanta",                      "sector": "Metal",            "industry": "Diversified Metals",     "exchange": "NSE", "currency": "INR", "region": "IN"},
    "NATIONALUM.NS":  {"name": "National Aluminium Company",   "sector": "Metal",            "industry": "Aluminium",              "exchange": "NSE", "currency": "INR", "region": "IN"},
    "SAIL.NS":        {"name": "Steel Authority of India",     "sector": "Metal",            "industry": "Steel",                  "exchange": "NSE", "currency": "INR", "region": "IN"},
    "HINDCOPPER.NS":  {"name": "Hindustan Copper",             "sector": "Metal",            "industry": "Copper",                 "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ONGC.NS":        {"name": "Oil & Natural Gas Corporation","sector": "Energy",           "industry": "Oil & Gas",              "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BPCL.NS":        {"name": "Bharat Petroleum",             "sector": "Energy",           "industry": "Oil & Gas",              "exchange": "NSE", "currency": "INR", "region": "IN"},
    "IOC.NS":         {"name": "Indian Oil Corporation",       "sector": "Energy",           "industry": "Oil & Gas",              "exchange": "NSE", "currency": "INR", "region": "IN"},
    "GAIL.NS":        {"name": "GAIL India",                   "sector": "Energy",           "industry": "Gas Distribution",       "exchange": "NSE", "currency": "INR", "region": "IN"},
    "POWERGRID.NS":   {"name": "Power Grid Corporation",       "sector": "Utilities",        "industry": "Power Transmission",     "exchange": "NSE", "currency": "INR", "region": "IN"},
    "NTPC.NS":        {"name": "NTPC",                         "sector": "Utilities",        "industry": "Power Generation",       "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ADANIPOWER.NS":  {"name": "Adani Power",                  "sector": "Utilities",        "industry": "Power Generation",       "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ADANIENT.NS":    {"name": "Adani Enterprises",            "sector": "Conglomerate",     "industry": "Diversified",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ADANIPORTS.NS":  {"name": "Adani Ports & SEZ",            "sector": "Industrials",      "industry": "Ports",                  "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ADANIGREEN.NS":  {"name": "Adani Green Energy",           "sector": "Utilities",        "industry": "Solar",                  "exchange": "NSE", "currency": "INR", "region": "IN"},
    "TITAN.NS":       {"name": "Titan Company",                "sector": "Consumer",         "industry": "Consumer Durables",      "exchange": "NSE", "currency": "INR", "region": "IN"},
    "TATACONSUM.NS":  {"name": "Tata Consumer Products",       "sector": "FMCG",             "industry": "Food Products",          "exchange": "NSE", "currency": "INR", "region": "IN"},
    "TRENT.NS":       {"name": "Trent",                        "sector": "Retail",           "industry": "Retail",                 "exchange": "NSE", "currency": "INR", "region": "IN"},
    "DMART.NS":       {"name": "Avenue Supermarts (D-Mart)",   "sector": "Retail",           "industry": "Supermarkets",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "NYKAA.NS":       {"name": "FSN E-Commerce (Nykaa)",       "sector": "Retail",           "industry": "Online Retail",          "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ZOMATO.NS":      {"name": "Zomato",                       "sector": "Technology",       "industry": "Internet Services",      "exchange": "NSE", "currency": "INR", "region": "IN"},
    "PAYTM.NS":       {"name": "One 97 Communications (Paytm)","sector": "Fintech",          "industry": "Digital Payments",       "exchange": "NSE", "currency": "INR", "region": "IN"},
    "POLICYBZR.NS":   {"name": "PB Fintech (PolicyBazaar)",    "sector": "Fintech",          "industry": "Insurance Tech",         "exchange": "NSE", "currency": "INR", "region": "IN"},
    "IRCTC.NS":       {"name": "Indian Railway Catering & Tourism","sector": "Services",     "industry": "Travel",                 "exchange": "NSE", "currency": "INR", "region": "IN"},
    "INDHOTEL.NS":    {"name": "Indian Hotels",                "sector": "Services",         "industry": "Hotels",                 "exchange": "NSE", "currency": "INR", "region": "IN"},
    "LTTS.NS":        {"name": "L&T Technology Services",      "sector": "Technology",       "industry": "IT Services",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "LT.NS":          {"name": "Larsen & Toubro",              "sector": "Industrials",      "industry": "Engineering",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "HAL.NS":         {"name": "Hindustan Aeronautics",        "sector": "Industrials",      "industry": "Aerospace & Defense",    "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BEL.NS":         {"name": "Bharat Electronics",           "sector": "Industrials",      "industry": "Electronics",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BHEL.NS":        {"name": "Bharat Heavy Electricals",     "sector": "Industrials",      "industry": "Heavy Engineering",      "exchange": "NSE", "currency": "INR", "region": "IN"},
    "SIEMENS.NS":     {"name": "Siemens India",                "sector": "Industrials",      "industry": "Electrical Equipment",   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "ABB.NS":         {"name": "ABB India",                    "sector": "Industrials",      "industry": "Electrical Equipment",   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "AIAENG.NS":      {"name": "AIA Engineering",              "sector": "Industrials",      "industry": "Industrial Machinery",   "exchange": "NSE", "currency": "INR", "region": "IN"},
    "GRINDWELL.NS":   {"name": "Grindwell Norton",             "sector": "Industrials",      "industry": "Abrasives",              "exchange": "NSE", "currency": "INR", "region": "IN"},
    "PIIND.NS":       {"name": "PI Industries",                "sector": "Chemicals",        "industry": "Agrochemicals",          "exchange": "NSE", "currency": "INR", "region": "IN"},
    "UPL.NS":         {"name": "UPL Ltd",                      "sector": "Chemicals",        "industry": "Agrochemicals",          "exchange": "NSE", "currency": "INR", "region": "IN"},
    "SRF.NS":         {"name": "SRF Ltd",                      "sector": "Chemicals",        "industry": "Specialty Chemicals",    "exchange": "NSE", "currency": "INR", "region": "IN"},
    "AARTIIND.NS":    {"name": "Aarti Industries",             "sector": "Chemicals",        "industry": "Specialty Chemicals",    "exchange": "NSE", "currency": "INR", "region": "IN"},
    "DEEPAKNTR.NS":   {"name": "Deepak Nitrite",               "sector": "Chemicals",        "industry": "Specialty Chemicals",    "exchange": "NSE", "currency": "INR", "region": "IN"},
    "NAVINFLUOR.NS":  {"name": "Navin Fluorine International", "sector": "Chemicals",        "industry": "Specialty Chemicals",    "exchange": "NSE", "currency": "INR", "region": "IN"},
    "PHOENIXLTD.NS":  {"name": "Phoenix Mills",                "sector": "Real Estate",      "industry": "Retail REITs",           "exchange": "NSE", "currency": "INR", "region": "IN"},
    "OBEROIRLTY.NS":  {"name": "Oberoi Realty",                "sector": "Real Estate",      "industry": "Real Estate",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "GODREJPROP.NS":  {"name": "Godrej Properties",            "sector": "Real Estate",      "industry": "Real Estate",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "PRESTIGE.NS":    {"name": "Prestige Estates Projects",    "sector": "Real Estate",      "industry": "Real Estate",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "DLF.NS":         {"name": "DLF",                          "sector": "Real Estate",      "industry": "Real Estate",            "exchange": "NSE", "currency": "INR", "region": "IN"},
    "BANKBARODA.NS":  {"name": "Bank of Baroda",               "sector": "Banking",          "industry": "PSU Bank",               "exchange": "NSE", "currency": "INR", "region": "IN"},
    "PNB.NS":         {"name": "Punjab National Bank",         "sector": "Banking",          "industry": "PSU Bank",               "exchange": "NSE", "currency": "INR", "region": "IN"},
    "CANBK.NS":       {"name": "Canara Bank",                  "sector": "Banking",          "industry": "PSU Bank",               "exchange": "NSE", "currency": "INR", "region": "IN"},
    "UNIONBANK.NS":   {"name": "Union Bank of India",          "sector": "Banking",          "industry": "PSU Bank",               "exchange": "NSE", "currency": "INR", "region": "IN"},

    # ══════════ UNITED KINGDOM — FTSE 100 ══════════
    "SHEL.L":  {"name": "Shell plc",                     "sector": "Energy",             "industry": "Oil & Gas",              "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "AZN.L":   {"name": "AstraZeneca plc",               "sector": "Healthcare",         "industry": "Drug Manufacturers",     "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "HSBA.L":  {"name": "HSBC Holdings plc",             "sector": "Financial Services", "industry": "Banks",                  "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "ULVR.L":  {"name": "Unilever plc",                  "sector": "Consumer Defensive", "industry": "Household Products",     "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "GSK.L":   {"name": "GSK plc",                       "sector": "Healthcare",         "industry": "Drug Manufacturers",     "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "BP.L":    {"name": "BP plc",                        "sector": "Energy",             "industry": "Oil & Gas",              "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "RIO.L":   {"name": "Rio Tinto plc",                 "sector": "Basic Materials",    "industry": "Other Industrial Metals","exchange": "LSE", "currency": "GBP", "region": "UK"},
    "VOD.L":   {"name": "Vodafone Group plc",            "sector": "Communication",      "industry": "Telecom Services",       "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "BARC.L":  {"name": "Barclays plc",                  "sector": "Financial Services", "industry": "Banks",                  "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "LLOY.L":  {"name": "Lloyds Banking Group plc",      "sector": "Financial Services", "industry": "Banks",                  "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "NWG.L":   {"name": "NatWest Group plc",             "sector": "Financial Services", "industry": "Banks",                  "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "BT-A.L":  {"name": "BT Group plc",                  "sector": "Communication",      "industry": "Telecom Services",       "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "STAN.L":  {"name": "Standard Chartered plc",        "sector": "Financial Services", "industry": "Banks",                  "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "AAL.L":   {"name": "Anglo American plc",            "sector": "Basic Materials",    "industry": "Other Industrial Metals","exchange": "LSE", "currency": "GBP", "region": "UK"},
    "GLEN.L":  {"name": "Glencore plc",                  "sector": "Basic Materials",    "industry": "Other Industrial Metals","exchange": "LSE", "currency": "GBP", "region": "UK"},
    "EXPN.L":  {"name": "Experian plc",                  "sector": "Industrials",        "industry": "Staffing & Employment",  "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "REL.L":   {"name": "RELX plc",                      "sector": "Communication",      "industry": "Publishing",             "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "LSEG.L":  {"name": "London Stock Exchange Group",   "sector": "Financial Services", "industry": "Financial Data",         "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "SGRO.L":  {"name": "Segro plc",                     "sector": "Real Estate",        "industry": "REIT Industrial",        "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "DGE.L":   {"name": "Diageo plc",                    "sector": "Consumer Defensive", "industry": "Beverages",              "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "BA.L":    {"name": "BAE Systems plc",               "sector": "Industrials",        "industry": "Aerospace & Defense",    "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "RR.L":    {"name": "Rolls-Royce Holdings plc",      "sector": "Industrials",        "industry": "Aerospace & Defense",    "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "IMB.L":   {"name": "Imperial Brands plc",           "sector": "Consumer Defensive", "industry": "Tobacco",                "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "BATS.L":  {"name": "British American Tobacco plc",  "sector": "Consumer Defensive", "industry": "Tobacco",                "exchange": "LSE", "currency": "GBP", "region": "UK"},
    "MNG.L":   {"name": "M&G plc",                       "sector": "Financial Services", "industry": "Asset Management",       "exchange": "LSE", "currency": "GBP", "region": "UK"},

    # ══════════ GERMANY — DAX 40 ══════════
    "SAP.DE":   {"name": "SAP SE",                       "sector": "Technology",          "industry": "Software",               "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "SIE.DE":   {"name": "Siemens AG",                   "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "ALV.DE":   {"name": "Allianz SE",                   "sector": "Financial Services",  "industry": "Insurance",              "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "MBG.DE":   {"name": "Mercedes-Benz Group AG",       "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "BMW.DE":   {"name": "Bayerische Motoren Werke AG",  "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "VOW3.DE":  {"name": "Volkswagen AG",                "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "BAYN.DE":  {"name": "Bayer AG",                     "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "BASF.DE":  {"name": "BASF SE",                      "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "MRK.DE":   {"name": "Merck KGaA",                   "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "ADS.DE":   {"name": "adidas AG",                    "sector": "Consumer Cyclical",   "industry": "Footwear & Accessories", "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "DTE.DE":   {"name": "Deutsche Telekom AG",          "sector": "Communication",       "industry": "Telecom Services",       "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "DBK.DE":   {"name": "Deutsche Bank AG",             "sector": "Financial Services",  "industry": "Banks",                  "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "HEI.DE":   {"name": "HeidelbergCement AG",          "sector": "Basic Materials",     "industry": "Building Materials",     "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "HEN3.DE":  {"name": "Henkel AG & Co KGaA",         "sector": "Consumer Defensive",  "industry": "Household Products",     "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "RWE.DE":   {"name": "RWE AG",                       "sector": "Utilities",           "industry": "Utilities Diversified",  "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "BAS.DE":   {"name": "BASF SE (alt ticker)",         "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "ENR.DE":   {"name": "Siemens Energy AG",            "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "DHER.DE":  {"name": "Delivery Hero SE",             "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "ZAL.DE":   {"name": "Zalando SE",                   "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "XETRA", "currency": "EUR", "region": "DE"},
    "IFX.DE":   {"name": "Infineon Technologies AG",     "sector": "Technology",          "industry": "Semiconductors",         "exchange": "XETRA", "currency": "EUR", "region": "DE"},

    # ══════════ FRANCE — CAC 40 ══════════
    "MC.PA":    {"name": "LVMH Moet Hennessy Louis Vuitton","sector": "Consumer Cyclical", "industry": "Luxury Goods",          "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "OR.PA":    {"name": "L'Oreal SA",                   "sector": "Consumer Defensive",  "industry": "Household Products",     "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "SAN.PA":   {"name": "Sanofi SA",                    "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "TTE.PA":   {"name": "TotalEnergies SE",             "sector": "Energy",              "industry": "Oil & Gas",              "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "BNP.PA":   {"name": "BNP Paribas SA",               "sector": "Financial Services",  "industry": "Banks",                  "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "AIR.PA":   {"name": "Airbus SE",                    "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "KER.PA":   {"name": "Kering SA",                    "sector": "Consumer Cyclical",   "industry": "Luxury Goods",           "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "RI.PA":    {"name": "Pernod Ricard SA",             "sector": "Consumer Defensive",  "industry": "Beverages",              "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "DG.PA":    {"name": "Vinci SA",                     "sector": "Industrials",         "industry": "Engineering & Construction","exchange": "EPA","currency": "EUR", "region": "FR"},
    "CS.PA":    {"name": "AXA SA",                       "sector": "Financial Services",  "industry": "Insurance",              "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "ENGI.PA":  {"name": "Engie SA",                     "sector": "Utilities",           "industry": "Utilities Diversified",  "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "SU.PA":    {"name": "Schneider Electric SE",        "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "CAP.PA":   {"name": "Capgemini SE",                 "sector": "Technology",          "industry": "IT Services",            "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "STM.PA":   {"name": "STMicroelectronics NV",        "sector": "Technology",          "industry": "Semiconductors",         "exchange": "EPA", "currency": "EUR", "region": "FR"},
    "HO.PA":    {"name": "Thales SA",                    "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "EPA", "currency": "EUR", "region": "FR"},

    # ══════════ JAPAN — Nikkei 225 majors ══════════
    "7203.T":  {"name": "Toyota Motor Corporation",      "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "6758.T":  {"name": "Sony Group Corporation",        "sector": "Technology",          "industry": "Consumer Electronics",   "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "6861.T":  {"name": "Keyence Corporation",           "sector": "Technology",          "industry": "Electronic Components",  "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "9432.T":  {"name": "NTT Nippon Telegraph & Telephone","sector": "Communication",     "industry": "Telecom Services",       "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "7974.T":  {"name": "Nintendo Co Ltd",               "sector": "Technology",          "industry": "Electronic Games",       "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "4063.T":  {"name": "Shin-Etsu Chemical",            "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "8306.T":  {"name": "Mitsubishi UFJ Financial Group","sector": "Financial Services",  "industry": "Banks",                  "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "8316.T":  {"name": "Sumitomo Mitsui Financial Group","sector": "Financial Services", "industry": "Banks",                  "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "8411.T":  {"name": "Mizuho Financial Group",        "sector": "Financial Services",  "industry": "Banks",                  "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "9984.T":  {"name": "SoftBank Group Corp",           "sector": "Technology",          "industry": "Telecom Services",       "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "6098.T":  {"name": "Recruit Holdings Co Ltd",       "sector": "Industrials",         "industry": "Staffing & Employment",  "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "4502.T":  {"name": "Takeda Pharmaceutical",         "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "6367.T":  {"name": "Daikin Industries",             "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "7267.T":  {"name": "Honda Motor Co Ltd",            "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "6954.T":  {"name": "Fanuc Corporation",             "sector": "Technology",          "industry": "Industrial Machinery",   "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "4519.T":  {"name": "Chugai Pharmaceutical",         "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "6762.T":  {"name": "TDK Corporation",               "sector": "Technology",          "industry": "Electronic Components",  "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "3382.T":  {"name": "Seven & i Holdings",            "sector": "Consumer Defensive",  "industry": "Grocery Stores",         "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "9433.T":  {"name": "KDDI Corporation",              "sector": "Communication",       "industry": "Telecom Services",       "exchange": "TSE", "currency": "JPY", "region": "JP"},
    "8035.T":  {"name": "Tokyo Electron",                "sector": "Technology",          "industry": "Semiconductor Equipment","exchange": "TSE", "currency": "JPY", "region": "JP"},
    "6501.T":  {"name": "Hitachi Ltd",                   "sector": "Industrials",         "industry": "Diversified Industrials","exchange": "TSE", "currency": "JPY", "region": "JP"},

    # ══════════ HONG KONG / CHINA ══════════
    "0700.HK": {"name": "Tencent Holdings",              "sector": "Technology",          "industry": "Internet Content",       "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "9988.HK": {"name": "Alibaba Group Holding",         "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "3690.HK": {"name": "Meituan",                       "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "9999.HK": {"name": "NetEase Inc",                   "sector": "Technology",          "industry": "Electronic Games",       "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "1299.HK": {"name": "AIA Group",                     "sector": "Financial Services",  "industry": "Insurance",              "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "0005.HK": {"name": "HSBC Holdings plc (HK)",        "sector": "Financial Services",  "industry": "Banks",                  "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "0941.HK": {"name": "China Mobile",                  "sector": "Communication",       "industry": "Telecom Services",       "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "2318.HK": {"name": "Ping An Insurance",             "sector": "Financial Services",  "industry": "Insurance",              "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "0883.HK": {"name": "CNOOC Ltd",                     "sector": "Energy",              "industry": "Oil & Gas",              "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "1398.HK": {"name": "Industrial & Commercial Bank of China","sector": "Financial Services","industry": "Banks",             "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "0388.HK": {"name": "Hong Kong Exchanges and Clearing","sector": "Financial Services","industry": "Financial Exchanges",    "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "2020.HK": {"name": "ANTA Sports Products",          "sector": "Consumer Cyclical",   "industry": "Footwear & Accessories", "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "9618.HK": {"name": "JD.com Inc",                    "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "HKEX", "currency": "HKD", "region": "HK"},
    "BABA":    {"name": "Alibaba Group (US ADR)",         "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "NYSE",  "currency": "USD", "region": "CN"},
    "JD":      {"name": "JD.com Inc (US ADR)",            "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "NASDAQ","currency": "USD", "region": "CN"},
    "PDD":     {"name": "PDD Holdings Inc (Pinduoduo)",   "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "NASDAQ","currency": "USD", "region": "CN"},
    "BIDU":    {"name": "Baidu Inc",                      "sector": "Technology",          "industry": "Internet Content",       "exchange": "NASDAQ","currency": "USD", "region": "CN"},
    "NTES":    {"name": "NetEase Inc (US ADR)",            "sector": "Technology",          "industry": "Electronic Games",       "exchange": "NASDAQ","currency": "USD", "region": "CN"},

    # ══════════ TAIWAN ══════════
    "TSM":     {"name": "Taiwan Semiconductor (ADR)",    "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NYSE",  "currency": "USD", "region": "TW"},
    "UMC":     {"name": "United Microelectronics (ADR)", "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NYSE",  "currency": "USD", "region": "TW"},
    "ASX":     {"name": "ASE Technology Holding (ADR)",  "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NYSE",  "currency": "USD", "region": "TW"},

    # ══════════ SOUTH KOREA ══════════
    "005930.KS": {"name": "Samsung Electronics",         "sector": "Technology",          "industry": "Consumer Electronics",   "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "000660.KS": {"name": "SK Hynix",                    "sector": "Technology",          "industry": "Semiconductors",         "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "005380.KS": {"name": "Hyundai Motor",               "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "051910.KS": {"name": "LG Chem",                     "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "035420.KS": {"name": "NAVER Corporation",           "sector": "Technology",          "industry": "Internet Content",       "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "035720.KS": {"name": "Kakao Corp",                  "sector": "Technology",          "industry": "Internet Content",       "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "006400.KS": {"name": "Samsung SDI",                 "sector": "Technology",          "industry": "Electronic Components",  "exchange": "KRX",  "currency": "KRW", "region": "KR"},

    # ══════════ AUSTRALIA — ASX 200 ══════════
    "BHP.AX":  {"name": "BHP Group",                     "sector": "Basic Materials",     "industry": "Other Industrial Metals","exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "CBA.AX":  {"name": "Commonwealth Bank of Australia","sector": "Financial Services",  "industry": "Banks",                  "exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "CSL.AX":  {"name": "CSL Limited",                   "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "NAB.AX":  {"name": "National Australia Bank",       "sector": "Financial Services",  "industry": "Banks",                  "exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "WBC.AX":  {"name": "Westpac Banking Corporation",   "sector": "Financial Services",  "industry": "Banks",                  "exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "ANZ.AX":  {"name": "ANZ Group Holdings",            "sector": "Financial Services",  "industry": "Banks",                  "exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "WES.AX":  {"name": "Wesfarmers",                    "sector": "Consumer Cyclical",   "industry": "Specialty Retail",       "exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "WOW.AX":  {"name": "Woolworths Group",              "sector": "Consumer Defensive",  "industry": "Grocery Stores",         "exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "RIO.AX":  {"name": "Rio Tinto Group",               "sector": "Basic Materials",     "industry": "Other Industrial Metals","exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "FMG.AX":  {"name": "Fortescue Metals Group",        "sector": "Basic Materials",     "industry": "Steel",                  "exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "MQG.AX":  {"name": "Macquarie Group",               "sector": "Financial Services",  "industry": "Capital Markets",        "exchange": "ASX",  "currency": "AUD", "region": "AU"},
    "TLS.AX":  {"name": "Telstra Group",                 "sector": "Communication",       "industry": "Telecom Services",       "exchange": "ASX",  "currency": "AUD", "region": "AU"},

    # ══════════ CANADA — TSX 60 ══════════
    "RY.TO":   {"name": "Royal Bank of Canada",          "sector": "Financial Services",  "industry": "Banks",                  "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "TD.TO":   {"name": "Toronto-Dominion Bank",         "sector": "Financial Services",  "industry": "Banks",                  "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "ENB.TO":  {"name": "Enbridge Inc",                  "sector": "Energy",              "industry": "Oil & Gas Midstream",    "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "CNR.TO":  {"name": "Canadian National Railway",     "sector": "Industrials",         "industry": "Railroads",              "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "CP.TO":   {"name": "Canadian Pacific Kansas City",  "sector": "Industrials",         "industry": "Railroads",              "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "SU.TO":   {"name": "Suncor Energy",                 "sector": "Energy",              "industry": "Oil & Gas",              "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "CNQ.TO":  {"name": "Canadian Natural Resources",    "sector": "Energy",              "industry": "Oil & Gas",              "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "BMO.TO":  {"name": "Bank of Montreal",              "sector": "Financial Services",  "industry": "Banks",                  "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "BNS.TO":  {"name": "Bank of Nova Scotia",           "sector": "Financial Services",  "industry": "Banks",                  "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "MFC.TO":  {"name": "Manulife Financial",            "sector": "Financial Services",  "industry": "Insurance",              "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "SHOP.TO": {"name": "Shopify Inc",                   "sector": "Technology",          "industry": "Software",               "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "TRI.TO":  {"name": "Thomson Reuters Corporation",   "sector": "Industrials",         "industry": "Publishing",             "exchange": "TSX",  "currency": "CAD", "region": "CA"},
    "BCE.TO":  {"name": "BCE Inc",                       "sector": "Communication",       "industry": "Telecom Services",       "exchange": "TSX",  "currency": "CAD", "region": "CA"},

    # ══════════ SWITZERLAND ══════════
    "NESN.SW": {"name": "Nestle SA",                     "sector": "Consumer Defensive",  "industry": "Packaged Foods",         "exchange": "SIX",  "currency": "CHF", "region": "CH"},
    "ROG.SW":  {"name": "Roche Holding AG",              "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "SIX",  "currency": "CHF", "region": "CH"},
    "NOVN.SW": {"name": "Novartis AG",                   "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "SIX",  "currency": "CHF", "region": "CH"},
    "ABBN.SW": {"name": "ABB Ltd",                       "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "SIX",  "currency": "CHF", "region": "CH"},
    "UBSG.SW": {"name": "UBS Group AG",                  "sector": "Financial Services",  "industry": "Banks",                  "exchange": "SIX",  "currency": "CHF", "region": "CH"},
    "ZURN.SW": {"name": "Zurich Insurance Group AG",     "sector": "Financial Services",  "industry": "Insurance",              "exchange": "SIX",  "currency": "CHF", "region": "CH"},
    "SREN.SW": {"name": "Swiss Re AG",                   "sector": "Financial Services",  "industry": "Insurance",              "exchange": "SIX",  "currency": "CHF", "region": "CH"},
    "LONN.SW": {"name": "Lonza Group AG",                "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "SIX",  "currency": "CHF", "region": "CH"},

    # ══════════ NETHERLANDS / OTHER EU ══════════
    "ASML.AS": {"name": "ASML Holding NV",               "sector": "Technology",          "industry": "Semiconductor Equipment","exchange": "AEX",  "currency": "EUR", "region": "NL"},
    "INGA.AS": {"name": "ING Groep NV",                  "sector": "Financial Services",  "industry": "Banks",                  "exchange": "AEX",  "currency": "EUR", "region": "NL"},
    "HEIA.AS": {"name": "Heineken NV",                   "sector": "Consumer Defensive",  "industry": "Beverages",              "exchange": "AEX",  "currency": "EUR", "region": "NL"},
    "PHIA.AS": {"name": "Philips NV",                    "sector": "Healthcare",          "industry": "Medical Devices",        "exchange": "AEX",  "currency": "EUR", "region": "NL"},
    "ENEL.MI": {"name": "Enel SpA",                      "sector": "Utilities",           "industry": "Utilities Regulated",   "exchange": "BIT",  "currency": "EUR", "region": "IT"},
    "ISP.MI":  {"name": "Intesa Sanpaolo SpA",           "sector": "Financial Services",  "industry": "Banks",                  "exchange": "BIT",  "currency": "EUR", "region": "IT"},
    "UCG.MI":  {"name": "UniCredit SpA",                 "sector": "Financial Services",  "industry": "Banks",                  "exchange": "BIT",  "currency": "EUR", "region": "IT"},
    "ENI.MI":  {"name": "Eni SpA",                       "sector": "Energy",              "industry": "Oil & Gas",              "exchange": "BIT",  "currency": "EUR", "region": "IT"},
    "SAN.MC":  {"name": "Banco Santander SA",            "sector": "Financial Services",  "industry": "Banks",                  "exchange": "BME",  "currency": "EUR", "region": "ES"},
    "BBVA.MC": {"name": "Banco Bilbao Vizcaya Argentaria","sector": "Financial Services", "industry": "Banks",                  "exchange": "BME",  "currency": "EUR", "region": "ES"},
    "IBE.MC":  {"name": "Iberdrola SA",                  "sector": "Utilities",           "industry": "Utilities Regulated",   "exchange": "BME",  "currency": "EUR", "region": "ES"},
    "TEF.MC":  {"name": "Telefonica SA",                 "sector": "Communication",       "industry": "Telecom Services",       "exchange": "BME",  "currency": "EUR", "region": "ES"},

    # ══════════ BRAZIL ══════════
    "VALE3.SA": {"name": "Vale SA",                      "sector": "Basic Materials",     "industry": "Other Industrial Metals","exchange": "B3",   "currency": "BRL", "region": "BR"},
    "PETR4.SA": {"name": "Petroleo Brasileiro (Petrobras)","sector": "Energy",            "industry": "Oil & Gas",              "exchange": "B3",   "currency": "BRL", "region": "BR"},
    "ITUB4.SA": {"name": "Itau Unibanco Holding SA",     "sector": "Financial Services",  "industry": "Banks",                  "exchange": "B3",   "currency": "BRL", "region": "BR"},
    "BBDC4.SA": {"name": "Banco Bradesco SA",            "sector": "Financial Services",  "industry": "Banks",                  "exchange": "B3",   "currency": "BRL", "region": "BR"},
    "ABEV3.SA": {"name": "Ambev SA",                     "sector": "Consumer Defensive",  "industry": "Beverages",              "exchange": "B3",   "currency": "BRL", "region": "BR"},
    "WEGE3.SA": {"name": "WEG SA",                       "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "B3",   "currency": "BRL", "region": "BR"},
    "MGLU3.SA": {"name": "Magazine Luiza SA",            "sector": "Consumer Cyclical",   "industry": "Specialty Retail",       "exchange": "B3",   "currency": "BRL", "region": "BR"},

    # ══════════ US ADRs for major EM companies ══════════
    "VALE":    {"name": "Vale SA (ADR)",                  "sector": "Basic Materials",     "industry": "Other Industrial Metals","exchange": "NYSE",  "currency": "USD", "region": "BR"},
    "PBR":     {"name": "Petrobras (ADR)",                "sector": "Energy",              "industry": "Oil & Gas",              "exchange": "NYSE",  "currency": "USD", "region": "BR"},
    "ITUB":    {"name": "Itau Unibanco (ADR)",            "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NYSE",  "currency": "USD", "region": "BR"},
    "HDB":     {"name": "HDFC Bank (ADR)",                "sector": "Banking",             "industry": "Private Bank",           "exchange": "NYSE",  "currency": "USD", "region": "IN"},
    "INFY":    {"name": "Infosys (ADR)",                  "sector": "Technology",          "industry": "IT Services",            "exchange": "NYSE",  "currency": "USD", "region": "IN"},
    "WIT":     {"name": "Wipro (ADR)",                    "sector": "Technology",          "industry": "IT Services",            "exchange": "NYSE",  "currency": "USD", "region": "IN"},
    "IBN":     {"name": "ICICI Bank (ADR)",               "sector": "Banking",             "industry": "Private Bank",           "exchange": "NYSE",  "currency": "USD", "region": "IN"},
    "RELX":    {"name": "RELX plc (ADR)",                 "sector": "Communication",       "industry": "Publishing",             "exchange": "NYSE",  "currency": "USD", "region": "UK"},
    "AZN":     {"name": "AstraZeneca plc (ADR)",          "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NASDAQ","currency": "USD", "region": "UK"},
    "NVS":     {"name": "Novartis AG (ADR)",              "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "CH"},
    "SNY":     {"name": "Sanofi SA (ADR)",                "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NASDAQ","currency": "USD", "region": "FR"},
    "SAP":     {"name": "SAP SE (ADR)",                   "sector": "Technology",          "industry": "Software",               "exchange": "NYSE",  "currency": "USD", "region": "DE"},
    "TM":      {"name": "Toyota Motor (ADR)",             "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "JP"},
    "HMC":     {"name": "Honda Motor (ADR)",              "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "JP"},
    "SONY":    {"name": "Sony Group (ADR)",               "sector": "Technology",          "industry": "Consumer Electronics",   "exchange": "NYSE",  "currency": "USD", "region": "JP"},
    "NTDOY":   {"name": "Nintendo (ADR)",                 "sector": "Technology",          "industry": "Electronic Games",       "exchange": "OTC",   "currency": "USD", "region": "JP"},
    "MUFG":    {"name": "Mitsubishi UFJ Financial (ADR)", "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NYSE",  "currency": "USD", "region": "JP"},
    "SMFG":    {"name": "Sumitomo Mitsui Financial (ADR)","sector": "Financial Services",  "industry": "Banks",                  "exchange": "NYSE",  "currency": "USD", "region": "JP"},

    # ══════════ UNITED STATES — S&P 500 expansion batch 2 ══════════
    "GE":     {"name": "GE Aerospace",                   "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "GEV":    {"name": "GE Vernova",                     "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CAT":    {"name": "Caterpillar Inc",                 "sector": "Industrials",         "industry": "Farm & Heavy Machinery", "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "UPS":    {"name": "United Parcel Service",           "sector": "Industrials",         "industry": "Integrated Freight",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "HON":    {"name": "Honeywell International",         "sector": "Industrials",         "industry": "Conglomerates",          "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "DE":     {"name": "Deere & Company",                 "sector": "Industrials",         "industry": "Farm & Heavy Machinery", "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "BA":     {"name": "Boeing Company",                  "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "RTX":    {"name": "RTX Corporation",                 "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "LMT":    {"name": "Lockheed Martin",                 "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "NOC":    {"name": "Northrop Grumman",                "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MMM":    {"name": "3M Company",                      "sector": "Industrials",         "industry": "Conglomerates",          "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "ETN":    {"name": "Eaton Corporation",               "sector": "Industrials",         "industry": "Specialty Industrial",   "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "EMR":    {"name": "Emerson Electric",                "sector": "Industrials",         "industry": "Specialty Industrial",   "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "FDX":    {"name": "FedEx Corporation",               "sector": "Industrials",         "industry": "Integrated Freight",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "WM":     {"name": "Waste Management Inc",            "sector": "Industrials",         "industry": "Waste Management",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PLD":    {"name": "Prologis Inc",                    "sector": "Real Estate",         "industry": "REIT Industrial",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "AMT":    {"name": "American Tower Corporation",      "sector": "Real Estate",         "industry": "REIT Specialty",         "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "EQIX":   {"name": "Equinix Inc",                     "sector": "Real Estate",         "industry": "REIT Specialty",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "SPG":    {"name": "Simon Property Group",            "sector": "Real Estate",         "industry": "REIT Retail",            "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "O":      {"name": "Realty Income Corporation",       "sector": "Real Estate",         "industry": "REIT Retail",            "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "NEE":    {"name": "NextEra Energy Inc",              "sector": "Utilities",           "industry": "Utilities Regulated",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "DUK":    {"name": "Duke Energy Corporation",         "sector": "Utilities",           "industry": "Utilities Regulated",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SO":     {"name": "Southern Company",                "sector": "Utilities",           "industry": "Utilities Regulated",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "D":      {"name": "Dominion Energy Inc",             "sector": "Utilities",           "industry": "Utilities Regulated",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "AEP":    {"name": "American Electric Power",         "sector": "Utilities",           "industry": "Utilities Regulated",    "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "EXC":    {"name": "Exelon Corporation",              "sector": "Utilities",           "industry": "Utilities Regulated",    "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "F":      {"name": "Ford Motor Company",              "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "GM":     {"name": "General Motors Company",          "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CMG":    {"name": "Chipotle Mexican Grill",          "sector": "Consumer Cyclical",   "industry": "Restaurants",            "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SBUX":   {"name": "Starbucks Corporation",           "sector": "Consumer Cyclical",   "industry": "Restaurants",            "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "YUM":    {"name": "Yum! Brands Inc",                 "sector": "Consumer Cyclical",   "industry": "Restaurants",            "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MCD":    {"name": "McDonald's Corporation",          "sector": "Consumer Cyclical",   "industry": "Restaurants",            "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "NKE":    {"name": "Nike Inc",                        "sector": "Consumer Cyclical",   "industry": "Footwear & Accessories", "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "TJX":    {"name": "TJX Companies Inc",               "sector": "Consumer Cyclical",   "industry": "Apparel Retail",         "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "LOW":    {"name": "Lowe's Companies Inc",            "sector": "Consumer Cyclical",   "industry": "Home Improvement Retail","exchange": "NYSE",  "currency": "USD", "region": "US"},
    "TGT":    {"name": "Target Corporation",              "sector": "Consumer Defensive",  "industry": "Discount Stores",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CVS":    {"name": "CVS Health Corporation",          "sector": "Healthcare",          "industry": "Healthcare Plans",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CI":     {"name": "Cigna Group",                     "sector": "Healthcare",          "industry": "Healthcare Plans",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "ELV":    {"name": "Elevance Health Inc",             "sector": "Healthcare",          "industry": "Healthcare Plans",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "HCA":    {"name": "HCA Healthcare Inc",              "sector": "Healthcare",          "industry": "Medical Care Facilities","exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MDT":    {"name": "Medtronic plc",                   "sector": "Healthcare",          "industry": "Medical Devices",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SYK":    {"name": "Stryker Corporation",             "sector": "Healthcare",          "industry": "Medical Devices",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "BSX":    {"name": "Boston Scientific Corporation",   "sector": "Healthcare",          "industry": "Medical Devices",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "EW":     {"name": "Edwards Lifesciences",            "sector": "Healthcare",          "industry": "Medical Devices",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "ISRG":   {"name": "Intuitive Surgical Inc",          "sector": "Healthcare",          "industry": "Medical Devices",        "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "ZTS":    {"name": "Zoetis Inc",                      "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MCK":    {"name": "McKesson Corporation",            "sector": "Healthcare",          "industry": "Healthcare Distribution","exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CAH":    {"name": "Cardinal Health Inc",             "sector": "Healthcare",          "industry": "Healthcare Distribution","exchange": "NYSE",  "currency": "USD", "region": "US"},
    "BDX":    {"name": "Becton Dickinson and Company",    "sector": "Healthcare",          "industry": "Medical Instruments",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "GILD":   {"name": "Gilead Sciences Inc",             "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "REGN":   {"name": "Regeneron Pharmaceuticals",       "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "VRTX":   {"name": "Vertex Pharmaceuticals",          "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "BIIB":   {"name": "Biogen Inc",                      "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "AMGN":   {"name": "Amgen Inc",                       "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "MRNA":   {"name": "Moderna Inc",                     "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "PFE":    {"name": "Pfizer Inc",                      "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "BMY":    {"name": "Bristol-Myers Squibb Company",    "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SCHW":   {"name": "Charles Schwab Corporation",      "sector": "Financial Services",  "industry": "Capital Markets",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "GS":     {"name": "Goldman Sachs Group Inc",         "sector": "Financial Services",  "industry": "Capital Markets",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MS":     {"name": "Morgan Stanley",                  "sector": "Financial Services",  "industry": "Capital Markets",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "WFC":    {"name": "Wells Fargo & Company",           "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "C":      {"name": "Citigroup Inc",                   "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "USB":    {"name": "U.S. Bancorp",                    "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PNC":    {"name": "PNC Financial Services",          "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "TFC":    {"name": "Truist Financial Corporation",    "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "COF":    {"name": "Capital One Financial",           "sector": "Financial Services",  "industry": "Credit Services",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SYF":    {"name": "Synchrony Financial",             "sector": "Financial Services",  "industry": "Credit Services",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "ICE":    {"name": "Intercontinental Exchange",       "sector": "Financial Services",  "industry": "Financial Data Services","exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CME":    {"name": "CME Group Inc",                   "sector": "Financial Services",  "industry": "Financial Data Services","exchange": "NASDAQ","currency": "USD", "region": "US"},
    "SPGI":   {"name": "S&P Global Inc",                  "sector": "Financial Services",  "industry": "Financial Data Services","exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MCO":    {"name": "Moody's Corporation",             "sector": "Financial Services",  "industry": "Financial Data Services","exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MSCI":   {"name": "MSCI Inc",                        "sector": "Financial Services",  "industry": "Financial Data Services","exchange": "NYSE",  "currency": "USD", "region": "US"},
    "AXP":    {"name": "American Express Company",        "sector": "Financial Services",  "industry": "Credit Services",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "BLK":    {"name": "BlackRock Inc",                   "sector": "Financial Services",  "industry": "Asset Management",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "BX":     {"name": "Blackstone Inc",                  "sector": "Financial Services",  "industry": "Asset Management",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "KKR":    {"name": "KKR & Co Inc",                    "sector": "Financial Services",  "industry": "Asset Management",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "APO":    {"name": "Apollo Global Management",        "sector": "Financial Services",  "industry": "Asset Management",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MET":    {"name": "MetLife Inc",                     "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PRU":    {"name": "Prudential Financial Inc",        "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "AFL":    {"name": "Aflac Incorporated",              "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "ALL":    {"name": "Allstate Corporation",            "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "TRV":    {"name": "Travelers Companies Inc",         "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PGR":    {"name": "Progressive Corporation",         "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CB":     {"name": "Chubb Limited",                   "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "ADBE":   {"name": "Adobe Inc",                       "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "NOW":    {"name": "ServiceNow Inc",                  "sector": "Technology",          "industry": "Software",               "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CRM":    {"name": "Salesforce Inc",                  "sector": "Technology",          "industry": "Software",               "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "INTU":   {"name": "Intuit Inc",                      "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "PANW":   {"name": "Palo Alto Networks Inc",          "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "CRWD":   {"name": "CrowdStrike Holdings Inc",        "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "SNOW":   {"name": "Snowflake Inc",                   "sector": "Technology",          "industry": "Software",               "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PLTR":   {"name": "Palantir Technologies Inc",       "sector": "Technology",          "industry": "Software",               "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MDB":    {"name": "MongoDB Inc",                     "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "DDOG":   {"name": "Datadog Inc",                     "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "ZS":     {"name": "Zscaler Inc",                     "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "FTNT":   {"name": "Fortinet Inc",                    "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "OKTA":   {"name": "Okta Inc",                        "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "TTD":    {"name": "Trade Desk Inc",                  "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "SHOP":   {"name": "Shopify Inc",                     "sector": "Technology",          "industry": "Internet Retail",        "exchange": "NYSE",  "currency": "USD", "region": "CA"},
    "UBER":   {"name": "Uber Technologies Inc",           "sector": "Technology",          "industry": "Software",               "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "LYFT":   {"name": "Lyft Inc",                        "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "ABNB":   {"name": "Airbnb Inc",                      "sector": "Technology",          "industry": "Travel Services",        "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "DASH":   {"name": "DoorDash Inc",                    "sector": "Technology",          "industry": "Software",               "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "RBLX":   {"name": "Roblox Corporation",              "sector": "Technology",          "industry": "Electronic Games",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SNAP":   {"name": "Snap Inc",                        "sector": "Technology",          "industry": "Internet Content",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PINS":   {"name": "Pinterest Inc",                   "sector": "Technology",          "industry": "Internet Content",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SPOT":   {"name": "Spotify Technology SA",           "sector": "Technology",          "industry": "Internet Content",       "exchange": "NYSE",  "currency": "USD", "region": "SE"},
    "NTNX":   {"name": "Nutanix Inc",                     "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "HPE":    {"name": "Hewlett Packard Enterprise",      "sector": "Technology",          "industry": "Computer Hardware",      "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "HPQ":    {"name": "HP Inc",                          "sector": "Technology",          "industry": "Computer Hardware",      "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "DELL":   {"name": "Dell Technologies Inc",           "sector": "Technology",          "industry": "Computer Hardware",      "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "WDC":    {"name": "Western Digital Corporation",     "sector": "Technology",          "industry": "Computer Hardware",      "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "STX":    {"name": "Seagate Technology Holdings",     "sector": "Technology",          "industry": "Computer Hardware",      "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "ON":     {"name": "ON Semiconductor Corporation",    "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "MCHP":   {"name": "Microchip Technology Incorporated","sector": "Technology",         "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "TXN":    {"name": "Texas Instruments Incorporated",  "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "INTC":   {"name": "Intel Corporation",               "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "KLAC":   {"name": "KLA Corporation",                 "sector": "Technology",          "industry": "Semiconductor Equipment","exchange": "NASDAQ","currency": "USD", "region": "US"},
    "LRCX":   {"name": "Lam Research Corporation",        "sector": "Technology",          "industry": "Semiconductor Equipment","exchange": "NASDAQ","currency": "USD", "region": "US"},
    "AMAT":   {"name": "Applied Materials Inc",           "sector": "Technology",          "industry": "Semiconductor Equipment","exchange": "NASDAQ","currency": "USD", "region": "US"},
    "MRVL":   {"name": "Marvell Technology Inc",          "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "CDNS":   {"name": "Cadence Design Systems Inc",      "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "SNPS":   {"name": "Synopsys Inc",                    "sector": "Technology",          "industry": "Software",               "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "EPAM":   {"name": "EPAM Systems Inc",                 "sector": "Technology",          "industry": "IT Services",            "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "GPN":    {"name": "Global Payments Inc",             "sector": "Technology",          "industry": "Information Technology Services","exchange": "NYSE","currency": "USD", "region": "US"},
    "FISV":   {"name": "Fiserv Inc",                      "sector": "Technology",          "industry": "Information Technology Services","exchange": "NASDAQ","currency": "USD", "region": "US"},
    "FIS":    {"name": "Fidelity National Information Services","sector": "Technology",   "industry": "Information Technology Services","exchange": "NYSE","currency": "USD", "region": "US"},
    "PAYX":   {"name": "Paychex Inc",                     "sector": "Technology",          "industry": "Staffing & Employment",  "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "ADP":    {"name": "Automatic Data Processing Inc",   "sector": "Technology",          "industry": "Staffing & Employment",  "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "ACN":    {"name": "Accenture plc",                   "sector": "Technology",          "industry": "IT Services",            "exchange": "NYSE",  "currency": "USD", "region": "IE"},
    "IBM":    {"name": "International Business Machines", "sector": "Technology",          "industry": "IT Services",            "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CSCO":   {"name": "Cisco Systems Inc",               "sector": "Technology",          "industry": "Communication Equipment","exchange": "NASDAQ","currency": "USD", "region": "US"},
    "QCOM":   {"name": "QUALCOMM Incorporated",           "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "NXPI":   {"name": "NXP Semiconductors NV",           "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "NL"},
    "AVGO":   {"name": "Broadcom Inc",                    "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "STM":    {"name": "STMicroelectronics NV",           "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NYSE",  "currency": "USD", "region": "CH"},
    "SWKS":   {"name": "Skyworks Solutions Inc",          "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "QRVO":   {"name": "Qorvo Inc",                       "sector": "Technology",          "industry": "Semiconductors",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "VZ":     {"name": "Verizon Communications Inc",      "sector": "Communication",       "industry": "Telecom Services",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "T":      {"name": "AT&T Inc",                        "sector": "Communication",       "industry": "Telecom Services",       "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "TMUS":   {"name": "T-Mobile US Inc",                 "sector": "Communication",       "industry": "Telecom Services",       "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "CMCSA":  {"name": "Comcast Corporation",             "sector": "Communication",       "industry": "Entertainment",          "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "CHTR":   {"name": "Charter Communications Inc",      "sector": "Communication",       "industry": "Entertainment",          "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "WBD":    {"name": "Warner Bros Discovery Inc",       "sector": "Communication",       "industry": "Entertainment",          "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "DIS":    {"name": "Walt Disney Company",             "sector": "Communication",       "industry": "Entertainment",          "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "NFLX":   {"name": "Netflix Inc",                     "sector": "Communication",       "industry": "Entertainment",          "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "FOX":    {"name": "Fox Corporation",                 "sector": "Communication",       "industry": "Entertainment",          "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "EA":     {"name": "Electronic Arts Inc",             "sector": "Communication",       "industry": "Electronic Games",       "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "TTWO":   {"name": "Take-Two Interactive Software",   "sector": "Communication",       "industry": "Electronic Games",       "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "NDAQ":   {"name": "Nasdaq Inc",                      "sector": "Financial Services",  "industry": "Financial Data Services","exchange": "NASDAQ","currency": "USD", "region": "US"},
    "CBOE":   {"name": "Cboe Global Markets Inc",         "sector": "Financial Services",  "industry": "Financial Data Services","exchange": "CBOE",  "currency": "USD", "region": "US"},
    "MKL":    {"name": "Markel Group Inc",                 "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "AJG":    {"name": "Arthur J. Gallagher & Co",        "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SHW":    {"name": "Sherwin-Williams Company",        "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "APD":    {"name": "Air Products and Chemicals",      "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "DD":     {"name": "DuPont de Nemours Inc",           "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "LIN":    {"name": "Linde plc",                       "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "NYSE",  "currency": "USD", "region": "IE"},
    "FCX":    {"name": "Freeport-McMoRan Inc",            "sector": "Basic Materials",     "industry": "Copper",                 "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "NEM":    {"name": "Newmont Corporation",             "sector": "Basic Materials",     "industry": "Gold",                   "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "NUE":    {"name": "Nucor Corporation",               "sector": "Basic Materials",     "industry": "Steel",                  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CLF":    {"name": "Cleveland-Cliffs Inc",            "sector": "Basic Materials",     "industry": "Steel",                  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MOS":    {"name": "Mosaic Company",                  "sector": "Basic Materials",     "industry": "Agricultural Inputs",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CF":     {"name": "CF Industries Holdings Inc",      "sector": "Basic Materials",     "industry": "Agricultural Inputs",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PSX":    {"name": "Phillips 66",                     "sector": "Energy",              "industry": "Oil & Gas Refining",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "VLO":    {"name": "Valero Energy Corporation",       "sector": "Energy",              "industry": "Oil & Gas Refining",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MPC":    {"name": "Marathon Petroleum Corporation",  "sector": "Energy",              "industry": "Oil & Gas Refining",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "COP":    {"name": "ConocoPhillips",                  "sector": "Energy",              "industry": "Oil & Gas Exploration",  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "OXY":    {"name": "Occidental Petroleum Corporation","sector": "Energy",              "industry": "Oil & Gas Exploration",  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PXD":    {"name": "Pioneer Natural Resources",       "sector": "Energy",              "industry": "Oil & Gas Exploration",  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "EOG":    {"name": "EOG Resources Inc",               "sector": "Energy",              "industry": "Oil & Gas Exploration",  "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SLB":    {"name": "SLB (Schlumberger)",              "sector": "Energy",              "industry": "Oil & Gas Equipment",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "HAL":    {"name": "Halliburton Company",             "sector": "Energy",              "industry": "Oil & Gas Equipment",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "BKR":    {"name": "Baker Hughes Company",            "sector": "Energy",              "industry": "Oil & Gas Equipment",    "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "KMI":    {"name": "Kinder Morgan Inc",               "sector": "Energy",              "industry": "Oil & Gas Midstream",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "WMB":    {"name": "Williams Companies Inc",          "sector": "Energy",              "industry": "Oil & Gas Midstream",    "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PM":     {"name": "Philip Morris International",     "sector": "Consumer Defensive",  "industry": "Tobacco",                "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MO":     {"name": "Altria Group Inc",                "sector": "Consumer Defensive",  "industry": "Tobacco",                "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CL":     {"name": "Colgate-Palmolive Company",       "sector": "Consumer Defensive",  "industry": "Household Products",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "KMB":    {"name": "Kimberly-Clark Corporation",      "sector": "Consumer Defensive",  "industry": "Household Products",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "CHD":    {"name": "Church & Dwight Co Inc",          "sector": "Consumer Defensive",  "industry": "Household Products",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "EL":     {"name": "Estee Lauder Companies Inc",      "sector": "Consumer Defensive",  "industry": "Household Products",     "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "MDLZ":   {"name": "Mondelez International Inc",      "sector": "Consumer Defensive",  "industry": "Packaged Foods",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "GIS":    {"name": "General Mills Inc",               "sector": "Consumer Defensive",  "industry": "Packaged Foods",         "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "KHC":    {"name": "Kraft Heinz Company",              "sector": "Consumer Defensive",  "industry": "Packaged Foods",         "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "CPB":    {"name": "Campbell Soup Company",           "sector": "Consumer Defensive",  "industry": "Packaged Foods",         "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "HRL":    {"name": "Hormel Foods Corporation",        "sector": "Consumer Defensive",  "industry": "Packaged Foods",         "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "TSN":    {"name": "Tyson Foods Inc",                 "sector": "Consumer Defensive",  "industry": "Packaged Foods",         "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "PEP":    {"name": "PepsiCo Inc",                     "sector": "Consumer Defensive",  "industry": "Beverages",              "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "BF-B":   {"name": "Brown-Forman Corporation",        "sector": "Consumer Defensive",  "industry": "Beverages",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "STZ":    {"name": "Constellation Brands Inc",        "sector": "Consumer Defensive",  "industry": "Beverages",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "TAP":    {"name": "Molson Coors Beverage Company",   "sector": "Consumer Defensive",  "industry": "Beverages",              "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "DG":     {"name": "Dollar General Corporation",      "sector": "Consumer Defensive",  "industry": "Discount Stores",        "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "DLTR":   {"name": "Dollar Tree Inc",                 "sector": "Consumer Defensive",  "industry": "Discount Stores",        "exchange": "NASDAQ","currency": "USD", "region": "US"},
    "KR":     {"name": "Kroger Co",                       "sector": "Consumer Defensive",  "industry": "Grocery Stores",         "exchange": "NYSE",  "currency": "USD", "region": "US"},
    "SYY":    {"name": "Sysco Corporation",               "sector": "Consumer Defensive",  "industry": "Food Distribution",      "exchange": "NYSE",  "currency": "USD", "region": "US"},

    # ══════════ TAIWAN ══════════
    "TSM":    {"name": "Taiwan Semiconductor Manufacturing (ADR)","sector": "Technology","industry": "Semiconductors",          "exchange": "NYSE",  "currency": "USD", "region": "TW"},
    "UMC":    {"name": "United Microelectronics Corp (ADR)","sector": "Technology",      "industry": "Semiconductors",          "exchange": "NYSE",  "currency": "USD", "region": "TW"},
    "ASX":    {"name": "Advanced Semiconductor Engineering (ADR)","sector": "Technology","industry": "Semiconductors",          "exchange": "NYSE",  "currency": "USD", "region": "TW"},

    # ══════════ CHINA — via US-listed ADRs ══════════
    "BABA":   {"name": "Alibaba Group Holding (ADR)",     "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "NYSE",  "currency": "USD", "region": "CN"},
    "JD":     {"name": "JD.com Inc (ADR)",                "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "NASDAQ","currency": "USD", "region": "CN"},
    "PDD":    {"name": "PDD Holdings Inc (ADR)",          "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "NASDAQ","currency": "USD", "region": "CN"},
    "BIDU":   {"name": "Baidu Inc (ADR)",                 "sector": "Technology",          "industry": "Internet Content",       "exchange": "NASDAQ","currency": "USD", "region": "CN"},
    "NTES":   {"name": "NetEase Inc (ADR)",               "sector": "Technology",          "industry": "Electronic Games",       "exchange": "NASDAQ","currency": "USD", "region": "CN"},
    "BILI":   {"name": "Bilibili Inc (ADR)",              "sector": "Communication",       "industry": "Internet Content",       "exchange": "NASDAQ","currency": "USD", "region": "CN"},
    "LI":     {"name": "Li Auto Inc (ADR)",               "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "NASDAQ","currency": "USD", "region": "CN"},
    "NIO":    {"name": "NIO Inc (ADR)",                   "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "CN"},
    "XPEV":   {"name": "XPeng Inc (ADR)",                 "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "NYSE",  "currency": "USD", "region": "CN"},
    "TME":    {"name": "Tencent Music Entertainment (ADR)","sector": "Communication",      "industry": "Internet Content",       "exchange": "NYSE",  "currency": "USD", "region": "CN"},

    # ══════════ INDIA NSE EXPANSION — Nifty 500 additions ══════════
    "ZOMATO.NS":    {"name": "Zomato Limited",            "sector": "Consumer Cyclical",   "industry": "Internet Retail",        "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "PAYTM.NS":     {"name": "One97 Communications (Paytm)","sector": "Technology",       "industry": "FinTech",                "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "NYKAA.NS":     {"name": "FSN E-Commerce Ventures (Nykaa)","sector": "Consumer Cyclical","industry": "Internet Retail",    "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "POLICYBZR.NS": {"name": "PB Fintech (PolicyBazaar)", "sector": "Financial Services",  "industry": "Insurance",              "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "DELHIVERY.NS": {"name": "Delhivery Limited",         "sector": "Industrials",         "industry": "Integrated Freight",     "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "INDIGO.NS":    {"name": "InterGlobe Aviation (IndiGo)","sector": "Industrials",       "industry": "Airlines",               "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "IRCTC.NS":     {"name": "Indian Railway Catering and Tourism","sector": "Consumer Cyclical","industry": "Travel Services",  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "IRFC.NS":      {"name": "Indian Railway Finance Corporation","sector": "Financial Services","industry": "Capital Markets",  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "HAL.NS":       {"name": "Hindustan Aeronautics Limited","sector": "Industrials",      "industry": "Aerospace & Defense",    "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "BEL.NS":       {"name": "Bharat Electronics Limited","sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "BHEL.NS":      {"name": "Bharat Heavy Electricals Limited","sector": "Industrials",   "industry": "Electrical Equipment",   "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "RECLTD.NS":    {"name": "REC Limited",               "sector": "Financial Services",  "industry": "Capital Markets",        "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "PFC.NS":       {"name": "Power Finance Corporation", "sector": "Financial Services",  "industry": "Capital Markets",        "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "CANBK.NS":     {"name": "Canara Bank",               "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "BANKBARODA.NS":{"name": "Bank of Baroda",            "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "UNIONBANK.NS": {"name": "Union Bank of India",       "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "PNB.NS":       {"name": "Punjab National Bank",      "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "MAHABANK.NS":  {"name": "Bank of Maharashtra",       "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "IDFCFIRSTB.NS":{"name": "IDFC First Bank Limited",  "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "FEDERALBNK.NS":{"name": "Federal Bank Limited",     "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "BANDHANBNK.NS":{"name": "Bandhan Bank Limited",     "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "RBLBANK.NS":   {"name": "RBL Bank Limited",          "sector": "Financial Services",  "industry": "Banks",                  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "MANAPPURAM.NS":{"name": "Manappuram Finance Limited","sector": "Financial Services",  "industry": "Capital Markets",        "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "MUTHOOTFIN.NS":{"name": "Muthoot Finance Limited",  "sector": "Financial Services",  "industry": "Capital Markets",        "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "CHOLAFIN.NS":  {"name": "Cholamandalam Investment", "sector": "Financial Services",  "industry": "Capital Markets",        "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "SBICARD.NS":   {"name": "SBI Cards and Payment Services","sector": "Financial Services","industry": "Credit Services",     "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "HDFCAMC.NS":   {"name": "HDFC Asset Management Company","sector": "Financial Services","industry": "Asset Management",    "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "NIPPOBATRY.NS":{"name": "Nippon India Battery",     "sector": "Technology",          "industry": "Electronic Components",  "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "STAR.NS":      {"name": "Star Health and Allied Insurance","sector": "Financial Services","industry": "Insurance",          "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "MAXHEALTH.NS": {"name": "Max Healthcare Institute", "sector": "Healthcare",          "industry": "Medical Care Facilities","exchange": "NSE",  "currency": "INR", "region": "IN"},
    "FORTIS.NS":    {"name": "Fortis Healthcare Limited","sector": "Healthcare",          "industry": "Medical Care Facilities","exchange": "NSE",  "currency": "INR", "region": "IN"},
    "KIMS.NS":      {"name": "Krishna Institute of Medical Sciences","sector": "Healthcare","industry": "Medical Care Facilities","exchange": "NSE","currency": "INR", "region": "IN"},
    "LUPIN.NS":     {"name": "Lupin Limited",             "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "GLAND.NS":     {"name": "Gland Pharma Limited",     "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "NATCOPHARM.NS":{"name": "Natco Pharma Limited",     "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "IPCALAB.NS":   {"name": "Ipca Laboratories Limited","sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "LALPATHLAB.NS":{"name": "Dr Lal PathLabs Limited",  "sector": "Healthcare",          "industry": "Diagnostics & Research","exchange": "NSE",  "currency": "INR", "region": "IN"},
    "METROPOLIS.NS":{"name": "Metropolis Healthcare Limited","sector": "Healthcare",      "industry": "Diagnostics & Research","exchange": "NSE",  "currency": "INR", "region": "IN"},
    "LTIMINDTEC.NS":{"name": "LTIMindtree Limited",      "sector": "Technology",          "industry": "IT Services",            "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "PERSISTENT.NS":{"name": "Persistent Systems Limited","sector": "Technology",         "industry": "IT Services",            "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "COFORGE.NS":   {"name": "Coforge Limited",          "sector": "Technology",          "industry": "IT Services",            "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "KPITTECH.NS":  {"name": "KPIT Technologies Limited","sector": "Technology",          "industry": "IT Services",            "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "MPHASIS.NS":   {"name": "Mphasis Limited",           "sector": "Technology",          "industry": "IT Services",            "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "HAPPSTMNDS.NS":{"name": "Happiest Minds Technologies","sector": "Technology",        "industry": "IT Services",            "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "TANLA.NS":     {"name": "Tanla Platforms Limited",  "sector": "Technology",          "industry": "Software",               "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "MAPMYINDIA.NS":{"name": "CE Info Systems (MapMyIndia)","sector": "Technology",      "industry": "Software",               "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "DIXON.NS":     {"name": "Dixon Technologies",       "sector": "Technology",          "industry": "Consumer Electronics",   "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "AMBER.NS":     {"name": "Amber Enterprises India",  "sector": "Consumer Cyclical",   "industry": "Consumer Electronics",   "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "POLYCAB.NS":   {"name": "Polycab India Limited",    "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "KEI.NS":       {"name": "KEI Industries Limited",   "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "VOLTAMP.NS":   {"name": "Voltamp Transformers",     "sector": "Industrials",         "industry": "Electrical Equipment",   "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "GRINDWELL.NS": {"name": "Grindwell Norton Limited", "sector": "Industrials",         "industry": "Specialty Industrial",   "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "SOLARINDS.NS": {"name": "Solar Industries India",  "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "SUPREMEIND.NS":{"name": "Supreme Industries Limited","sector": "Basic Materials",   "industry": "Specialty Chemicals",    "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "PIDILITIND.NS":{"name": "Pidilite Industries Limited","sector": "Basic Materials",  "industry": "Specialty Chemicals",    "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "TATACOMM.NS":  {"name": "Tata Communications Limited","sector": "Communication",    "industry": "Telecom Services",       "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "INDUSTOWER.NS":{"name": "Indus Towers Limited",    "sector": "Communication",       "industry": "Telecom Services",       "exchange": "NSE",  "currency": "INR", "region": "IN"},
    "HFCL.NS":      {"name": "HFCL Limited",             "sector": "Communication",       "industry": "Telecom Services",       "exchange": "NSE",  "currency": "INR", "region": "IN"},

    # ══════════ INDIA BSE — Sensex 30 + BSE 500 Core ══════════
    "RELIANCE.BO":    {"name": "Reliance Industries",          "sector": "Energy",           "industry": "Oil & Gas",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TCS.BO":         {"name": "Tata Consultancy Services",    "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HDFCBANK.BO":    {"name": "HDFC Bank",                    "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ICICIBANK.BO":   {"name": "ICICI Bank",                   "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "INFY.BO":        {"name": "Infosys Ltd",                  "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SBIN.BO":        {"name": "State Bank of India",          "sector": "Banking",          "industry": "PSU Bank",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BAJFINANCE.BO":  {"name": "Bajaj Finance",                "sector": "NBFC",             "industry": "Finance",                "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HINDUNILVR.BO":  {"name": "Hindustan Unilever",           "sector": "FMCG",             "industry": "Personal Products",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BHARTIARTL.BO":  {"name": "Bharti Airtel",                "sector": "Telecom",          "industry": "Telecom Services",       "exchange": "BSE", "currency": "INR", "region": "IN"},
    "KOTAKBANK.BO":   {"name": "Kotak Mahindra Bank",          "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "LT.BO":          {"name": "Larsen & Toubro",              "sector": "Industrials",      "industry": "Engineering",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ITC.BO":         {"name": "ITC Ltd",                      "sector": "FMCG",             "industry": "Cigarettes & FMCG",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "AXISBANK.BO":    {"name": "Axis Bank",                    "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "MARUTI.BO":      {"name": "Maruti Suzuki India",          "sector": "Auto",             "industry": "Automobiles",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TITAN.BO":       {"name": "Titan Company",                "sector": "Consumer",         "industry": "Consumer Durables",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ULTRACEMCO.BO":  {"name": "UltraTech Cement",             "sector": "Cement",           "industry": "Cement",                 "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SUNPHARMA.BO":   {"name": "Sun Pharmaceutical Industries","sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "WIPRO.BO":       {"name": "Wipro Ltd",                    "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HCLTECH.BO":     {"name": "HCL Technologies",             "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "NTPC.BO":        {"name": "NTPC Ltd",                     "sector": "Power",            "industry": "Power Generation",       "exchange": "BSE", "currency": "INR", "region": "IN"},
    "POWERGRID.BO":   {"name": "Power Grid Corporation",       "sector": "Power",            "industry": "Power Transmission",     "exchange": "BSE", "currency": "INR", "region": "IN"},
    "M&M.BO":         {"name": "Mahindra & Mahindra",          "sector": "Auto",             "industry": "Automobiles",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TATAMOTORS.BO":  {"name": "Tata Motors Ltd",              "sector": "Auto",             "industry": "Automobiles",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "JSWSTEEL.BO":    {"name": "JSW Steel",                    "sector": "Metal",            "industry": "Steel",                  "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TATASTEEL.BO":   {"name": "Tata Steel",                   "sector": "Metal",            "industry": "Steel",                  "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ADANIENT.BO":    {"name": "Adani Enterprises",            "sector": "Conglomerate",     "industry": "Diversified",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ADANIPORTS.BO":  {"name": "Adani Ports & SEZ",            "sector": "Industrials",      "industry": "Ports",                  "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ASIANPAINT.BO":  {"name": "Asian Paints",                 "sector": "Consumer",         "industry": "Paints",                 "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BAJAJFINSV.BO":  {"name": "Bajaj Finserv",                "sector": "NBFC",             "industry": "Insurance",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "INDUSINDBK.BO":  {"name": "IndusInd Bank",                "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    # BSE 500 — additional large caps unique to BSE focus
    "ONGC.BO":        {"name": "Oil & Natural Gas Corporation","sector": "Energy",           "industry": "Oil & Gas",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BPCL.BO":        {"name": "Bharat Petroleum Corp",        "sector": "Energy",           "industry": "Oil & Gas",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "COALINDIA.BO":   {"name": "Coal India",                   "sector": "Energy",           "industry": "Coal",                   "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HINDALCO.BO":    {"name": "Hindalco Industries",          "sector": "Metal",            "industry": "Aluminium",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "DRREDDY.BO":     {"name": "Dr Reddy's Laboratories",      "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "CIPLA.BO":       {"name": "Cipla Ltd",                    "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "DIVISLAB.BO":    {"name": "Divi's Laboratories",          "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "APOLLOHOSP.BO":  {"name": "Apollo Hospitals Enterprise",  "sector": "Healthcare",       "industry": "Hospitals",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "EICHERMOT.BO":   {"name": "Eicher Motors",                "sector": "Auto",             "industry": "Motorcycles",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HEROMOTOCO.BO":  {"name": "Hero MotoCorp",                "sector": "Auto",             "industry": "Motorcycles",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BAJAJ-AUTO.BO":  {"name": "Bajaj Auto",                   "sector": "Auto",             "industry": "Motorcycles",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BRITANNIA.BO":   {"name": "Britannia Industries",         "sector": "FMCG",             "industry": "Food Products",          "exchange": "BSE", "currency": "INR", "region": "IN"},
    "NESTLEIND.BO":   {"name": "Nestle India",                 "sector": "FMCG",             "industry": "Food Products",          "exchange": "BSE", "currency": "INR", "region": "IN"},
    "DABUR.BO":       {"name": "Dabur India",                  "sector": "FMCG",             "industry": "Personal Products",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "MARICO.BO":      {"name": "Marico Ltd",                   "sector": "FMCG",             "industry": "Personal Products",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "GODREJCP.BO":    {"name": "Godrej Consumer Products",     "sector": "FMCG",             "industry": "Personal Products",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "EMAMILTD.BO":    {"name": "Emami Ltd",                    "sector": "FMCG",             "industry": "Personal Products",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "COLPAL.BO":      {"name": "Colgate-Palmolive India",      "sector": "FMCG",             "industry": "Personal Products",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TRENT.BO":       {"name": "Trent Ltd",                    "sector": "Consumer",         "industry": "Retail",                 "exchange": "BSE", "currency": "INR", "region": "IN"},
    "NYKAA.BO":       {"name": "FSN E-Commerce (Nykaa)",       "sector": "Consumer",         "industry": "E-Commerce",             "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ZOMATO.BO":      {"name": "Zomato Ltd",                   "sector": "Consumer",         "industry": "Food Delivery",          "exchange": "BSE", "currency": "INR", "region": "IN"},
    "PAYTM.BO":       {"name": "One97 Communications (Paytm)", "sector": "Technology",       "industry": "FinTech",                "exchange": "BSE", "currency": "INR", "region": "IN"},
    "POLICYBZR.BO":   {"name": "PB Fintech (PolicyBazaar)",    "sector": "Technology",       "industry": "InsurTech",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "DELHIVERY.BO":   {"name": "Delhivery Ltd",                "sector": "Industrials",      "industry": "Logistics",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "IRCTC.BO":       {"name": "Indian Railway Catering",      "sector": "Consumer",         "industry": "Travel Services",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "DIXON.BO":       {"name": "Dixon Technologies",           "sector": "Technology",       "industry": "Electronics Manufacturing","exchange": "BSE","currency": "INR", "region": "IN"},
    "AMBER.BO":       {"name": "Amber Enterprises India",      "sector": "Consumer",         "industry": "Consumer Durables",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "KAYNES.BO":      {"name": "Kaynes Technology India",      "sector": "Technology",       "industry": "Electronics",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TATAPOWER.BO":   {"name": "Tata Power Company",           "sector": "Power",            "industry": "Power Generation",       "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ADANIGREEN.BO":  {"name": "Adani Green Energy",           "sector": "Power",            "industry": "Renewable Energy",       "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TORNTPOWER.BO":  {"name": "Torrent Power",                "sector": "Power",            "industry": "Power Generation",       "exchange": "BSE", "currency": "INR", "region": "IN"},
    "CESC.BO":        {"name": "CESC Ltd",                     "sector": "Power",            "industry": "Power Generation",       "exchange": "BSE", "currency": "INR", "region": "IN"},
    "GAIL.BO":        {"name": "GAIL India",                   "sector": "Energy",           "industry": "Gas Distribution",       "exchange": "BSE", "currency": "INR", "region": "IN"},
    "IOC.BO":         {"name": "Indian Oil Corporation",       "sector": "Energy",           "industry": "Oil & Gas",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HPCL.BO":        {"name": "Hindustan Petroleum Corp",     "sector": "Energy",           "industry": "Oil & Gas",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SHREECEM.BO":    {"name": "Shree Cement",                 "sector": "Cement",           "industry": "Cement",                 "exchange": "BSE", "currency": "INR", "region": "IN"},
    "GRASIM.BO":      {"name": "Grasim Industries",            "sector": "Cement",           "industry": "Diversified",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "AMBUJACEM.BO":   {"name": "Ambuja Cements",               "sector": "Cement",           "industry": "Cement",                 "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ACC.BO":         {"name": "ACC Ltd",                      "sector": "Cement",           "industry": "Cement",                 "exchange": "BSE", "currency": "INR", "region": "IN"},
    "RAMCOCEM.BO":    {"name": "The Ramco Cements",            "sector": "Cement",           "industry": "Cement",                 "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HDFCLIFE.BO":    {"name": "HDFC Life Insurance",          "sector": "Insurance",        "industry": "Life Insurance",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SBILIFE.BO":     {"name": "SBI Life Insurance",           "sector": "Insurance",        "industry": "Life Insurance",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "LICI.BO":        {"name": "Life Insurance Corporation",   "sector": "Insurance",        "industry": "Life Insurance",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ICICIPRULI.BO":  {"name": "ICICI Prudential Life",        "sector": "Insurance",        "industry": "Life Insurance",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ICICIGI.BO":     {"name": "ICICI Lombard General Insurance","sector": "Insurance",      "industry": "General Insurance",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "STARHEALTH.BO":  {"name": "Star Health & Allied Insurance","sector": "Insurance",       "industry": "Health Insurance",       "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BAJAJHFL.BO":    {"name": "Bajaj Housing Finance",        "sector": "NBFC",             "industry": "Housing Finance",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "CHOLAFIN.BO":    {"name": "Cholamandalam Investment",     "sector": "NBFC",             "industry": "Finance",                "exchange": "BSE", "currency": "INR", "region": "IN"},
    "MUTHOOTFIN.BO":  {"name": "Muthoot Finance",              "sector": "NBFC",             "industry": "Gold Loans",             "exchange": "BSE", "currency": "INR", "region": "IN"},
    "MANAPPURAM.BO":  {"name": "Manappuram Finance",           "sector": "NBFC",             "industry": "Gold Loans",             "exchange": "BSE", "currency": "INR", "region": "IN"},
    "LICHSGFIN.BO":   {"name": "LIC Housing Finance",          "sector": "NBFC",             "industry": "Housing Finance",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "PNBHOUSING.BO":  {"name": "PNB Housing Finance",          "sector": "NBFC",             "industry": "Housing Finance",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "PNCINFRA.BO":    {"name": "PNC Infratech",                "sector": "Industrials",      "industry": "Infrastructure",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "IRB.BO":         {"name": "IRB Infrastructure Developers","sector": "Industrials",      "industry": "Infrastructure",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ASHOKLEY.BO":    {"name": "Ashok Leyland",                "sector": "Auto",             "industry": "Commercial Vehicles",    "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TIINDIA.BO":     {"name": "Tube Investments of India",    "sector": "Auto",             "industry": "Auto Components",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "MOTHERSON.BO":   {"name": "Samvardhana Motherson",        "sector": "Auto",             "industry": "Auto Components",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BOSCHLTD.BO":    {"name": "Bosch Ltd",                    "sector": "Auto",             "industry": "Auto Components",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TATAELXSI.BO":   {"name": "Tata Elxsi",                   "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "KPITTECH.BO":    {"name": "KPIT Technologies",            "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "LTTS.BO":        {"name": "L&T Technology Services",      "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "MPHASIS.BO":     {"name": "Mphasis Ltd",                  "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "PERSISTENT.BO":  {"name": "Persistent Systems",           "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "COFORGE.BO":     {"name": "Coforge Ltd",                  "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HAPPSTMNDS.BO":  {"name": "Happiest Minds Technologies",  "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ZENSARTECH.BO":  {"name": "Zensar Technologies",          "sector": "Technology",       "industry": "IT Services",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ASTRAL.BO":      {"name": "Astral Ltd",                   "sector": "Industrials",      "industry": "Pipes & Fittings",       "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SUPREMEIND.BO":  {"name": "Supreme Industries",           "sector": "Industrials",      "industry": "Plastics",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "POLYCAB.BO":     {"name": "Polycab India",                "sector": "Industrials",      "industry": "Cables & Wires",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "KEI.BO":         {"name": "KEI Industries",               "sector": "Industrials",      "industry": "Cables & Wires",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HAVELLS.BO":     {"name": "Havells India",                "sector": "Industrials",      "industry": "Electrical Equipment",   "exchange": "BSE", "currency": "INR", "region": "IN"},
    "CROMPTON.BO":    {"name": "Crompton Greaves Consumer",    "sector": "Consumer",         "industry": "Consumer Durables",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "VOLTAS.BO":      {"name": "Voltas Ltd",                   "sector": "Consumer",         "industry": "Consumer Durables",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "WHIRLPOOL.BO":   {"name": "Whirlpool of India",           "sector": "Consumer",         "industry": "Consumer Durables",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BLUESTARCO.BO":  {"name": "Blue Star Ltd",                "sector": "Consumer",         "industry": "Consumer Durables",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "KAJARIACER.BO":  {"name": "Kajaria Ceramics",             "sector": "Industrials",      "industry": "Ceramics",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "CUMMINSIND.BO":  {"name": "Cummins India",                "sector": "Industrials",      "industry": "Industrial Machinery",   "exchange": "BSE", "currency": "INR", "region": "IN"},
    "THERMAX.BO":     {"name": "Thermax Ltd",                  "sector": "Industrials",      "industry": "Industrial Machinery",   "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SIEMENS.BO":     {"name": "Siemens India",                "sector": "Industrials",      "industry": "Industrial Machinery",   "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ABB.BO":         {"name": "ABB India",                    "sector": "Industrials",      "industry": "Electrical Equipment",   "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BHEL.BO":        {"name": "Bharat Heavy Electricals",     "sector": "Industrials",      "industry": "Heavy Engineering",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BEL.BO":         {"name": "Bharat Electronics",           "sector": "Defence",          "industry": "Electronics",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HAL.BO":         {"name": "Hindustan Aeronautics",        "sector": "Defence",          "industry": "Aerospace & Defence",    "exchange": "BSE", "currency": "INR", "region": "IN"},
    "COCHINSHIP.BO":  {"name": "Cochin Shipyard",              "sector": "Industrials",      "industry": "Shipbuilding",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "MAZAGON.BO":     {"name": "Mazagon Dock Shipbuilders",    "sector": "Defence",          "industry": "Shipbuilding",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "DRONEACHARYA.BO":{"name": "Droneacharya Aerial Innovations","sector": "Technology",    "industry": "Drones",                 "exchange": "BSE", "currency": "INR", "region": "IN"},
    "IDEAFORGE.BO":   {"name": "ideaForge Technology",         "sector": "Technology",       "industry": "Drones",                 "exchange": "BSE", "currency": "INR", "region": "IN"},
    "RAILVIKAS.BO":   {"name": "Rail Vikas Nigam",             "sector": "Industrials",      "industry": "Infrastructure",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "RVNL.BO":        {"name": "Rail Vikas Nigam (RVNL)",      "sector": "Industrials",      "industry": "Infrastructure",         "exchange": "BSE", "currency": "INR", "region": "IN"},
    "IRFC.BO":        {"name": "Indian Railway Finance Corp",  "sector": "NBFC",             "industry": "Finance",                "exchange": "BSE", "currency": "INR", "region": "IN"},
    "PFC.BO":         {"name": "Power Finance Corporation",    "sector": "NBFC",             "industry": "Finance",                "exchange": "BSE", "currency": "INR", "region": "IN"},
    "RECLTD.BO":      {"name": "REC Ltd",                      "sector": "NBFC",             "industry": "Finance",                "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BANKBARODA.BO":  {"name": "Bank of Baroda",               "sector": "Banking",          "industry": "PSU Bank",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "PNB.BO":         {"name": "Punjab National Bank",         "sector": "Banking",          "industry": "PSU Bank",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "CANBK.BO":       {"name": "Canara Bank",                  "sector": "Banking",          "industry": "PSU Bank",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "UNIONBANK.BO":   {"name": "Union Bank of India",          "sector": "Banking",          "industry": "PSU Bank",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "FEDERALBNK.BO":  {"name": "Federal Bank",                 "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "IDFCFIRSTB.BO":  {"name": "IDFC First Bank",              "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "RBLBANK.BO":     {"name": "RBL Bank",                     "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "YESBANK.BO":     {"name": "Yes Bank",                     "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "KARURVYSYA.BO":  {"name": "Karur Vysya Bank",             "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SOUTHBANK.BO":   {"name": "South Indian Bank",            "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "DCBBANK.BO":     {"name": "DCB Bank",                     "sector": "Banking",          "industry": "Private Bank",           "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TORNTPHARM.BO":  {"name": "Torrent Pharmaceuticals",      "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "AUROPHARMA.BO":  {"name": "Aurobindo Pharma",             "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "LUPIN.BO":       {"name": "Lupin Ltd",                    "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ALKEM.BO":       {"name": "Alkem Laboratories",           "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "IPCALAB.BO":     {"name": "IPCA Laboratories",            "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "GLAXO.BO":       {"name": "GlaxoSmithKline Pharma",       "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ZYDUSLIFE.BO":   {"name": "Zydus Lifesciences",           "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "GRANULES.BO":    {"name": "Granules India",               "sector": "Pharma",           "industry": "Pharmaceuticals",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SYNGENE.BO":     {"name": "Syngene International",        "sector": "Pharma",           "industry": "Biotech",                "exchange": "BSE", "currency": "INR", "region": "IN"},
    "LALPATHLAB.BO":  {"name": "Dr Lal PathLabs",              "sector": "Healthcare",       "industry": "Diagnostics",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "METROPOLIS.BO":  {"name": "Metropolis Healthcare",        "sector": "Healthcare",       "industry": "Diagnostics",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "MAXHEALTH.BO":   {"name": "Max Healthcare Institute",     "sector": "Healthcare",       "industry": "Hospitals",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "NH.BO":          {"name": "Narayana Hrudayalaya",         "sector": "Healthcare",       "industry": "Hospitals",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "TATACONSUM.BO":  {"name": "Tata Consumer Products",       "sector": "FMCG",             "industry": "Food Products",          "exchange": "BSE", "currency": "INR", "region": "IN"},
    "VARUN.BO":       {"name": "Varun Beverages",              "sector": "FMCG",             "industry": "Beverages",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "UBL.BO":         {"name": "United Breweries",             "sector": "FMCG",             "industry": "Beverages",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "VBL.BO":         {"name": "Varun Beverages Ltd",          "sector": "FMCG",             "industry": "Beverages",              "exchange": "BSE", "currency": "INR", "region": "IN"},
    "JUBLFOOD.BO":    {"name": "Jubilant FoodWorks",           "sector": "Consumer",         "industry": "QSR / Restaurants",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "DEVYANI.BO":     {"name": "Devyani International",        "sector": "Consumer",         "industry": "QSR / Restaurants",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SAPPHIRE.BO":    {"name": "Sapphire Foods India",         "sector": "Consumer",         "industry": "QSR / Restaurants",      "exchange": "BSE", "currency": "INR", "region": "IN"},
    "RELAXO.BO":      {"name": "Relaxo Footwears",             "sector": "Consumer",         "industry": "Footwear",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "BATAINDIA.BO":   {"name": "Bata India",                   "sector": "Consumer",         "industry": "Footwear",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "VEDL.BO":        {"name": "Vedanta Ltd",                  "sector": "Metal",            "industry": "Diversified Metals",     "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HINDZINC.BO":    {"name": "Hindustan Zinc",               "sector": "Metal",            "industry": "Zinc",                   "exchange": "BSE", "currency": "INR", "region": "IN"},
    "NMDC.BO":        {"name": "NMDC Ltd",                     "sector": "Metal",            "industry": "Iron Ore",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "SAIL.BO":        {"name": "Steel Authority of India",     "sector": "Metal",            "industry": "Steel",                  "exchange": "BSE", "currency": "INR", "region": "IN"},
    "JINDALSTEL.BO":  {"name": "Jindal Steel & Power",         "sector": "Metal",            "industry": "Steel",                  "exchange": "BSE", "currency": "INR", "region": "IN"},
    "APLAPOLLO.BO":   {"name": "APL Apollo Tubes",             "sector": "Metal",            "industry": "Steel",                  "exchange": "BSE", "currency": "INR", "region": "IN"},
    "PIIND.BO":       {"name": "PI Industries",                "sector": "Basic Materials",  "industry": "Agrochemicals",          "exchange": "BSE", "currency": "INR", "region": "IN"},
    "UPL.BO":         {"name": "UPL Ltd",                      "sector": "Basic Materials",  "industry": "Agrochemicals",          "exchange": "BSE", "currency": "INR", "region": "IN"},
    "COROMANDEL.BO":  {"name": "Coromandel International",     "sector": "Basic Materials",  "industry": "Fertilizers",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "CHAMBLFERT.BO":  {"name": "Chambal Fertilisers",          "sector": "Basic Materials",  "industry": "Fertilizers",            "exchange": "BSE", "currency": "INR", "region": "IN"},
    "DEEPAKNTR.BO":   {"name": "Deepak Nitrite",               "sector": "Basic Materials",  "industry": "Specialty Chemicals",    "exchange": "BSE", "currency": "INR", "region": "IN"},
    "AAVAS.BO":       {"name": "Aavas Financiers",             "sector": "NBFC",             "industry": "Housing Finance",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "HOMEFIRST.BO":   {"name": "Home First Finance Company",   "sector": "NBFC",             "industry": "Housing Finance",        "exchange": "BSE", "currency": "INR", "region": "IN"},
    "ANGELONE.BO":    {"name": "Angel One Ltd",                "sector": "Financial Services","industry": "Broking",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "5PAISA.BO":      {"name": "5Paisa Capital",               "sector": "Financial Services","industry": "Broking",               "exchange": "BSE", "currency": "INR", "region": "IN"},
    "IIFL.BO":        {"name": "IIFL Finance",                 "sector": "NBFC",             "industry": "Finance",                "exchange": "BSE", "currency": "INR", "region": "IN"},
    "MOTILALOFS.BO":  {"name": "Motilal Oswal Financial",      "sector": "Financial Services","industry": "Broking",               "exchange": "BSE", "currency": "INR", "region": "IN"},

    # ══════════ ADDITIONAL EUROPE — STOXX 600 ══════════
    "RMS.PA":  {"name": "Hermes International SA",       "sector": "Consumer Cyclical",   "industry": "Luxury Goods",           "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "MC.PA":   {"name": "LVMH Moet Hennessy Louis Vuitton","sector": "Consumer Cyclical","industry": "Luxury Goods",           "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "KER.PA":  {"name": "Kering SA",                     "sector": "Consumer Cyclical",   "industry": "Luxury Goods",           "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "BNP.PA":  {"name": "BNP Paribas SA",                "sector": "Financial Services",  "industry": "Banks",                  "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "GLE.PA":  {"name": "Societe Generale SA",           "sector": "Financial Services",  "industry": "Banks",                  "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "CS.PA":   {"name": "AXA SA",                        "sector": "Financial Services",  "industry": "Insurance",              "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "OR.PA":   {"name": "L'Oreal SA",                    "sector": "Consumer Defensive",  "industry": "Household Products",     "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "DSY.PA":  {"name": "Dassault Systemes SE",          "sector": "Technology",          "industry": "Software",               "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "CAP.PA":  {"name": "Capgemini SE",                  "sector": "Technology",          "industry": "IT Services",            "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "AIR.PA":  {"name": "Airbus SE",                     "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "EPA",  "currency": "EUR", "region": "FR"},
    "SIE.DE":  {"name": "Siemens AG",                    "sector": "Industrials",         "industry": "Specialty Industrial",   "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "MUV2.DE": {"name": "Munich Re AG",                  "sector": "Financial Services",  "industry": "Insurance",              "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "DBK.DE":  {"name": "Deutsche Bank AG",              "sector": "Financial Services",  "industry": "Banks",                  "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "DTE.DE":  {"name": "Deutsche Telekom AG",           "sector": "Communication",       "industry": "Telecom Services",       "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "BMW.DE":  {"name": "Bayerische Motoren Werke AG",   "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "MBG.DE":  {"name": "Mercedes-Benz Group AG",        "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "VOW3.DE": {"name": "Volkswagen AG",                 "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "RWE.DE":  {"name": "RWE AG",                        "sector": "Utilities",           "industry": "Utilities Regulated",    "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "ADS.DE":  {"name": "adidas AG",                     "sector": "Consumer Cyclical",   "industry": "Footwear & Accessories","exchange": "XETRA","currency": "EUR", "region": "DE"},
    "BAYN.DE": {"name": "Bayer AG",                      "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "MRK.DE":  {"name": "Merck KGaA",                   "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "DHL.DE":  {"name": "Deutsche Post DHL Group",       "sector": "Industrials",         "industry": "Integrated Freight",     "exchange": "XETRA","currency": "EUR", "region": "DE"},
    "IMCD.AS": {"name": "IMCD NV",                       "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "AEX",  "currency": "EUR", "region": "NL"},
    "WKL.AS":  {"name": "Wolters Kluwer NV",             "sector": "Technology",          "industry": "Software",               "exchange": "AEX",  "currency": "EUR", "region": "NL"},
    "ADYEN.AS":{"name": "Adyen NV",                      "sector": "Technology",          "industry": "Information Technology Services","exchange": "AEX","currency": "EUR", "region": "NL"},
    "PRX.AS":  {"name": "Prosus NV",                     "sector": "Technology",          "industry": "Internet Content",       "exchange": "AEX",  "currency": "EUR", "region": "NL"},
    "GSK.L":   {"name": "GSK plc",                       "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "RIO.L":   {"name": "Rio Tinto Group",               "sector": "Basic Materials",     "industry": "Diversified Metals",     "exchange": "LSE",  "currency": "GBP", "region": "AU"},
    "BHP.L":   {"name": "BHP Group",                     "sector": "Basic Materials",     "industry": "Diversified Metals",     "exchange": "LSE",  "currency": "GBP", "region": "AU"},
    "AAL.L":   {"name": "Anglo American plc",            "sector": "Basic Materials",     "industry": "Diversified Metals",     "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "VOD.L":   {"name": "Vodafone Group plc",            "sector": "Communication",       "industry": "Telecom Services",       "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "BT-A.L":  {"name": "BT Group plc",                  "sector": "Communication",       "industry": "Telecom Services",       "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "LGEN.L":  {"name": "Legal & General Group plc",     "sector": "Financial Services",  "industry": "Insurance",              "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "BATS.L":  {"name": "British American Tobacco plc",  "sector": "Consumer Defensive",  "industry": "Tobacco",                "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "IMB.L":   {"name": "Imperial Brands plc",           "sector": "Consumer Defensive",  "industry": "Tobacco",                "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "DGE.L":   {"name": "Diageo plc",                    "sector": "Consumer Defensive",  "industry": "Beverages",              "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "CCH.L":   {"name": "Coca-Cola HBC AG",              "sector": "Consumer Defensive",  "industry": "Beverages",              "exchange": "LSE",  "currency": "GBP", "region": "CH"},
    "SGRO.L":  {"name": "Segro plc",                     "sector": "Real Estate",         "industry": "REIT Industrial",        "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "LAND.L":  {"name": "Land Securities Group plc",     "sector": "Real Estate",         "industry": "REIT Office",            "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "RR.L":    {"name": "Rolls-Royce Holdings plc",      "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "BA.L":    {"name": "BAE Systems plc",               "sector": "Industrials",         "industry": "Aerospace & Defense",    "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "EZJ.L":   {"name": "easyJet plc",                   "sector": "Industrials",         "industry": "Airlines",               "exchange": "LSE",  "currency": "GBP", "region": "UK"},
    "IAG.L":   {"name": "International Consolidated Airlines","sector": "Industrials",    "industry": "Airlines",               "exchange": "LSE",  "currency": "GBP", "region": "UK"},

    # ══════════ SOUTH KOREA ══════════
    "005930.KS":{"name": "Samsung Electronics Co Ltd",   "sector": "Technology",          "industry": "Consumer Electronics",   "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "000660.KS":{"name": "SK Hynix Inc",                 "sector": "Technology",          "industry": "Semiconductors",         "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "207940.KS":{"name": "Samsung Biologics Co Ltd",     "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "051910.KS":{"name": "LG Chem Ltd",                  "sector": "Basic Materials",     "industry": "Specialty Chemicals",    "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "005380.KS":{"name": "Hyundai Motor Company",        "sector": "Consumer Cyclical",   "industry": "Auto Manufacturers",     "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "035420.KS":{"name": "NAVER Corporation",            "sector": "Technology",          "industry": "Internet Content",       "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "035720.KS":{"name": "Kakao Corp",                   "sector": "Technology",          "industry": "Internet Content",       "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "373220.KS":{"name": "LG Energy Solution Ltd",       "sector": "Technology",          "industry": "Electronic Components",  "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "006400.KS":{"name": "Samsung SDI Co Ltd",           "sector": "Technology",          "industry": "Electronic Components",  "exchange": "KRX",  "currency": "KRW", "region": "KR"},
    "003550.KS":{"name": "LG Corp",                      "sector": "Industrials",         "industry": "Conglomerates",          "exchange": "KRX",  "currency": "KRW", "region": "KR"},

    # ══════════ SINGAPORE ══════════
    "D05.SI":  {"name": "DBS Group Holdings Ltd",        "sector": "Financial Services",  "industry": "Banks",                  "exchange": "SGX",  "currency": "SGD", "region": "SG"},
    "O39.SI":  {"name": "Oversea-Chinese Banking Corporation","sector": "Financial Services","industry": "Banks",               "exchange": "SGX",  "currency": "SGD", "region": "SG"},
    "U11.SI":  {"name": "United Overseas Bank Limited",  "sector": "Financial Services",  "industry": "Banks",                  "exchange": "SGX",  "currency": "SGD", "region": "SG"},
    "C6L.SI":  {"name": "Singapore Airlines Limited",   "sector": "Industrials",         "industry": "Airlines",               "exchange": "SGX",  "currency": "SGD", "region": "SG"},
    "Z74.SI":  {"name": "Singapore Telecommunications", "sector": "Communication",       "industry": "Telecom Services",       "exchange": "SGX",  "currency": "SGD", "region": "SG"},

    # ══════════ SCANDINAVIA ══════════
    "NOVO-B.CO":{"name": "Novo Nordisk A/S",             "sector": "Healthcare",          "industry": "Drug Manufacturers",     "exchange": "CPH",  "currency": "DKK", "region": "DK"},
    "NESTE.HE": {"name": "Neste Oyj",                    "sector": "Energy",              "industry": "Oil & Gas Refining",     "exchange": "HSE",  "currency": "EUR", "region": "FI"},
    "NOKIA.HE": {"name": "Nokia Oyj",                    "sector": "Technology",          "industry": "Communication Equipment","exchange": "HSE",  "currency": "EUR", "region": "FI"},
    "VOLV-B.ST":{"name": "Volvo AB",                     "sector": "Industrials",         "industry": "Farm & Heavy Machinery", "exchange": "STO",  "currency": "SEK", "region": "SE"},
    "ERIC-B.ST":{"name": "Ericsson",                     "sector": "Technology",          "industry": "Communication Equipment","exchange": "STO",  "currency": "SEK", "region": "SE"},
    "ATCO-A.ST":{"name": "Atlas Copco AB",               "sector": "Industrials",         "industry": "Specialty Industrial",   "exchange": "STO",  "currency": "SEK", "region": "SE"},
}


def ticker_to_symbol(ticker: str) -> str:
    """
    Convert a yfinance ticker to a unique DB symbol key.
    US tickers have no suffix → keep as-is.
    Indian tickers (.NS/.BO) are canonicalized to the suffix-less form used
    by market_data.py (e.g. RELIANCE.NS → RELIANCE) so the same company is
    never stored under two different keys.
    Other non-US tickers keep their exchange suffix to avoid collisions
    (e.g. BA vs BA.L, SAN.PA vs SAN.MC).
    """
    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        return ticker.rsplit(".", 1)[0]
    return ticker


def seed_global_universe(db: Session) -> dict:
    """
    Upsert all GLOBAL_UNIVERSE entries into Stock table.

    GLOBAL_UNIVERSE has some duplicate underlying-company entries under
    different exchange-suffixed keys (e.g. "DELHIVERY.NS" and
    "DELHIVERY.BO" both collapse to symbol="DELHIVERY" via
    ticker_to_symbol) -- track symbols added within this same call so the
    second one updates in-memory instead of hitting the DB's UNIQUE
    constraint before the first insert has even committed (found 2026-07-05:
    this crashed the whole seed on every run once GLOBAL_UNIVERSE grew to
    include cross-listed tickers).
    """
    added = 0
    updated = 0
    seen_this_call: dict[str, Stock] = {}
    for ticker, meta in GLOBAL_UNIVERSE.items():
        symbol   = ticker_to_symbol(ticker)
        exchange = meta.get("exchange", "")
        region   = meta.get("region", "")
        industry = f"{meta['industry']} [{exchange}/{region}]"

        if symbol in seen_this_call:
            # Duplicate underlying company under a different exchange suffix
            # — keep the first entry as-is, don't insert/update again.
            continue

        existing = db.query(Stock).filter_by(symbol=symbol).first()
        if existing:
            existing.name     = meta["name"]
            existing.sector   = meta["sector"]
            existing.industry = industry
            existing.active   = True
            seen_this_call[symbol] = existing
            updated += 1
        else:
            new_stock = Stock(
                symbol       = symbol,
                name         = meta["name"],
                sector       = meta["sector"],
                industry     = industry,
                nifty_member = (meta.get("exchange") == "NSE"),
                active       = True,
            )
            db.add(new_stock)
            seen_this_call[symbol] = new_stock
            added += 1
    db.commit()
    data_logger.info("Global universe seeded: %d added, %d updated", added, updated)
    return {"added": added, "updated": updated, "total": len(GLOBAL_UNIVERSE)}


def _latest_date_for_symbol(db: Session, ticker: str):
    """Check latest date stored for a ticker (using full ticker as symbol key)."""
    from aqrti.database.models import DailyPrice
    symbol = ticker_to_symbol(ticker)
    row = (
        db.query(DailyPrice.date)
        .filter(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return row[0] if row else None


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return None if (f != f) else f  # NaN check
    except Exception:
        return None


def _extract_ticker_df(batch_df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """Extract a single ticker's OHLCV from a yfinance batch result."""
    if batch_df is None or batch_df.empty:
        return None

    # yfinance with group_by='ticker': MultiIndex columns (ticker, field)
    if isinstance(batch_df.columns, pd.MultiIndex):
        lvl0 = batch_df.columns.get_level_values(0)
        lvl1 = batch_df.columns.get_level_values(1)
        # group_by='ticker' → level 0 = ticker, level 1 = field (Open/Close/...)
        if ticker in lvl0:
            df = batch_df[ticker].copy()
            df.index.name = "Date"
            return df.reset_index()
        # fallback: level 1 = ticker, level 0 = field (no group_by)
        if ticker in lvl1:
            df = batch_df.xs(ticker, axis=1, level=1).copy()
            df.index.name = "Date"
            return df.reset_index()
        return None

    # Single ticker — flat DataFrame
    df = batch_df.copy()
    if df.index.name == "Date" or "Date" not in df.columns:
        df = df.reset_index()
    return df


def _store_batch_df(db: Session, batch_df: pd.DataFrame, tickers: list[str]) -> dict[str, int]:
    """Parse yfinance batch download result and upsert into DailyPrice."""
    counts: dict[str, int] = {}
    for ticker in tickers:
        symbol = ticker_to_symbol(ticker)
        try:
            df = _extract_ticker_df(batch_df, ticker)
            if df is None or df.empty:
                counts[symbol] = 0
                continue

            # Normalise column names
            df.columns = [str(c).strip() for c in df.columns]
            if "Date" not in df.columns:
                # try Datetime or first column
                for candidate in ["Datetime", "index"]:
                    if candidate in df.columns:
                        df = df.rename(columns={candidate: "Date"})
                        break

            if "Close" not in df.columns:
                counts[symbol] = 0
                continue

            df = df.sort_values("Date")
            df["daily_return"] = df["Close"].pct_change(fill_method=None) * 100

            rows_inserted = 0
            for _, row in df.iterrows():
                close_val = _safe_float(row.get("Close"))
                if close_val is None:
                    continue
                row_date = row["Date"]
                if hasattr(row_date, "date"):
                    row_date = row_date.date()
                stmt = sqlite_insert(DailyPrice).values(
                    symbol       = symbol,
                    date         = row_date,
                    open         = _safe_float(row.get("Open")),
                    high         = _safe_float(row.get("High")),
                    low          = _safe_float(row.get("Low")),
                    close        = close_val,
                    adj_close    = close_val,
                    volume       = _safe_float(row.get("Volume")),
                    daily_return = _safe_float(row.get("daily_return")),
                ).on_conflict_do_update(
                    index_elements=["symbol", "date"],
                    set_={
                        "open":         _safe_float(row.get("Open")),
                        "high":         _safe_float(row.get("High")),
                        "low":          _safe_float(row.get("Low")),
                        "close":        close_val,
                        "adj_close":    close_val,
                        "volume":       _safe_float(row.get("Volume")),
                        "daily_return": _safe_float(row.get("daily_return")),
                    }
                )
                db.execute(stmt)
                rows_inserted += 1

            db.commit()
            counts[symbol] = rows_inserted
        except Exception as exc:
            db.rollback()
            data_logger.warning("Store failed for %s: %s", ticker, exc)
            counts[symbol] = -1

    return counts


def _download_batch(tickers: list[str], start_date: date, end_date: date) -> Optional[pd.DataFrame]:
    """Download a batch of tickers from yfinance."""
    try:
        tickers_str = " ".join(tickers)
        yf_stderr = StringIO()
        with _YF_DOWNLOAD_LOCK, redirect_stderr(yf_stderr):
            df = yf.download(
                tickers_str,
                start=str(start_date),
                end=str(end_date),
                progress=False,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
            )
        yf_noise = yf_stderr.getvalue().strip()
        if yf_noise:
            data_logger.debug("Batch yfinance detail for %s: %s", tickers[:3], yf_noise)
        return df
    except Exception as exc:
        data_logger.error("Batch download failed for %s: %s", tickers[:3], exc)
        return None


def download_global_universe(
    db: Session,
    symbols: Optional[list[str]] = None,
    start_date: Optional[date] = None,
    workers: int = 4,
    batch_size: int = 20,
) -> dict:
    """
    Download 3yr OHLCV for all (or specified) global universe tickers.
    Uses ThreadPoolExecutor for parallel batch downloads.
    Incremental: skips dates already in DB.
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=3 * 365)
    end_date = date.today() + timedelta(days=1)

    all_tickers = symbols or list(GLOBAL_UNIVERSE.keys())
    total = len(all_tickers)

    # Filter tickers that are already fully up to date (within 1 day)
    tickers_to_download = []
    skipped = 0
    for ticker in all_tickers:
        latest = _latest_date_for_symbol(db, ticker)
        if latest and (date.today() - latest).days <= 1:
            skipped += 1
        else:
            tickers_to_download.append(ticker)

    data_logger.info("Global universe: %d total, %d to download, %d already current",
                     total, len(tickers_to_download), skipped)

    # Split into batches
    batches = [
        tickers_to_download[i:i + batch_size]
        for i in range(0, len(tickers_to_download), batch_size)
    ]

    downloaded = 0
    errors = 0
    total_rows = 0
    processed = 0

    def _process_batch(batch: list[str]) -> dict[str, int]:
        # Each thread gets its own DB session
        _db = get_session_factory()()
        try:
            df = _download_batch(batch, start_date, end_date)
            if df is None or df.empty:
                return {t: -1 for t in batch}
            return _store_batch_df(_db, df, batch)
        finally:
            _db.close()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_process_batch, batch): batch for batch in batches}
        for future in as_completed(futures):
            batch = futures[future]
            processed += len(batch)
            try:
                result = future.result()
                for sym, count in result.items():
                    if count >= 0:
                        downloaded += 1
                        total_rows += count
                    else:
                        errors += 1
            except Exception as exc:
                data_logger.error("Batch future error: %s", exc)
                errors += len(batch)

            if processed % 50 == 0 or processed == len(tickers_to_download):
                data_logger.info("Global download progress: %d/%d processed",
                                 processed, len(tickers_to_download))
            # Small delay between batches to respect rate limits
            time.sleep(0.5)

    summary = {
        "total":       total,
        "downloaded":  downloaded,
        "skipped":     skipped,
        "errors":      errors,
        "total_rows":  total_rows,
        "start_date":  str(start_date),
    }
    data_logger.info("Global download complete: %s", summary)
    return summary


def get_universe_summary(db: Session) -> dict:
    """Count stocks by region and sector."""
    from aqrti.database.models import DailyPrice
    from sqlalchemy import func

    stock_rows = db.query(Stock).filter_by(active=True).all()
    price_counts = dict(
        db.query(DailyPrice.symbol, func.count(DailyPrice.id))
        .group_by(DailyPrice.symbol)
        .all()
    )

    by_region: dict[str, int] = {}
    by_sector: dict[str, int] = {}
    for ticker, meta in GLOBAL_UNIVERSE.items():
        r = meta.get("region", "Unknown")
        s = meta.get("sector", "Unknown")
        by_region[r] = by_region.get(r, 0) + 1
        by_sector[s] = by_sector.get(s, 0) + 1

    symbols_with_data = len([s for s in price_counts if price_counts[s] > 0])

    return {
        "universe_size":     len(GLOBAL_UNIVERSE),
        "stocks_in_db":      len(stock_rows),
        "symbols_with_data": symbols_with_data,
        "total_price_rows":  sum(price_counts.values()),
        "by_region":         dict(sorted(by_region.items(), key=lambda x: -x[1])),
        "by_sector":         dict(sorted(by_sector.items(), key=lambda x: -x[1])),
    }
