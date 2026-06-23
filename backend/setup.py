"""
AQRTI First-Run Setup
Run once: python setup.py
- Creates the SQLite database
- Seeds the stock universe
- Downloads 1 year of historical data
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from aqrti.database.engine import init_db
from aqrti.database.engine import get_db
from aqrti.data.market_data import seed_stock_universe, run_daily_ingestion
from aqrti.utils.logger import get_logger
from datetime import date, timedelta

log = get_logger("setup")


def main():
    log.info("=== AQRTI FIRST-RUN SETUP ===")

    # Step 1: Create all tables
    log.info("Step 1: Initializing database ...")
    init_db()

    # Step 2: Seed stock universe
    log.info("Step 2: Seeding stock universe ...")
    with get_db() as db:
        seed_stock_universe(db)

    # Step 3: Download 1 year of historical data
    log.info("Step 3: Downloading 1 year of historical data (this takes ~2 minutes) ...")
    start = date.today() - timedelta(days=365)
    report = run_daily_ingestion(start_override=start)

    log.info("Setup complete.")
    log.info("Stocks updated:  %d rows", report["stocks_updated"])
    log.info("Indices updated: %d rows", report["indices_updated"])
    if report["errors"]:
        log.warning("Errors: %s", report["errors"])

    log.info("")
    log.info("Next steps:")
    log.info("  1. python main.py          — start the API server")
    log.info("  2. Open ui/index.html      — open the terminal")
    log.info("  3. In api.js set USE_MOCK = false to use live data")


if __name__ == "__main__":
    main()
