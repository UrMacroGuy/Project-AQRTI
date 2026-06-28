"""
AQRTI → TradingView Paper Trading Automator
============================================
Reads open positions from AQRTI backend and places them as paper trades
on tradingview.com, with Stop Loss and Take Profit set on each order.

Usage:
    python place_trades_tradingview.py

Requirements:
    - pip install playwright
    - playwright install chromium
    - AQRTI backend running on localhost:8000
    - You will be prompted to log in to TradingView manually
      (the script pauses for 60s to let you log in)
"""

import json
import time
import sys
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

AQRTI_API = "http://localhost:8000/api/v1"
TV_URL     = "https://www.tradingview.com/chart/?symbol=NSE%3ANIFTY"

# How long (seconds) to wait for you to log in before starting
LOGIN_WAIT_SECS = 60


def fetch_positions() -> list[dict]:
    """Fetch open positions with SL/TP from AQRTI."""
    try:
        r = requests.get(f"{AQRTI_API}/paper-portfolio/positions", timeout=10)
        r.raise_for_status()
        data = r.json()
        # API returns list directly
        if isinstance(data, list):
            return data
        return data.get("positions", [])
    except Exception as e:
        print(f"[ERROR] Could not fetch positions from AQRTI: {e}")
        sys.exit(1)


def wait_and_click(page, selector, timeout=15000, description="element"):
    """Wait for selector then click it."""
    try:
        page.wait_for_selector(selector, timeout=timeout, state="visible")
        page.click(selector)
        return True
    except PWTimeout:
        print(f"  [WARN] Could not find {description} ({selector})")
        return False


def clear_and_type(page, selector, value, timeout=10000):
    """Clear an input and type a value."""
    page.wait_for_selector(selector, timeout=timeout, state="visible")
    page.triple_click(selector)
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    page.type(selector, str(value), delay=50)


def place_order(page, position: dict, index: int, total: int):
    symbol = position["symbol"]
    entry  = position["entryPrice"]
    sl     = round(position.get("stopLoss") or entry * 0.92, 2)
    tp     = round(position.get("target")   or entry * 1.15, 2)
    qty    = max(1, round(position["shares"]))

    print(f"\n[{index}/{total}] {symbol} — qty={qty} entry={entry} SL={sl} TP={tp}")

    # ── 1. Navigate chart to this symbol ──────────────────────────
    # Click the symbol search box at top left
    try:
        page.click("div[data-name='legend-source-item'] span.tv-symbol-header", timeout=5000)
    except Exception:
        try:
            # Fallback: click the symbol box in the top toolbar
            page.click("#header-toolbar-symbol-search", timeout=5000)
        except Exception:
            try:
                page.keyboard.press("Control+k")
            except Exception:
                pass

    time.sleep(0.5)
    page.keyboard.press("Control+a")
    page.keyboard.type(f"NSE:{symbol}", delay=60)
    time.sleep(1.5)

    # Select the first result
    try:
        page.wait_for_selector("div[data-name='symbol-list-item']", timeout=8000)
        page.click("div[data-name='symbol-list-item']:first-child")
        time.sleep(1.5)
    except PWTimeout:
        # Try pressing Enter to accept suggestion
        page.keyboard.press("Enter")
        time.sleep(1.5)

    # ── 2. Open the order panel ────────────────────────────────────
    # Click BUY button in the paper trading toolbar
    try:
        # Look for the Buy/Sell button in the trading panel
        page.wait_for_selector("button[data-name='buy-button'], .buy-btn-JvOkBsCS, button.buy", timeout=8000, state="visible")
        page.click("button[data-name='buy-button'], .buy-btn-JvOkBsCS, button.buy")
        time.sleep(0.8)
    except PWTimeout:
        # Try clicking the trade button from the left side panel
        print(f"  [INFO] Trying alternate buy button selector...")
        try:
            page.click("text=Buy", timeout=5000)
            time.sleep(0.8)
        except Exception:
            print(f"  [SKIP] Could not open order form for {symbol}")
            return False

    # ── 3. Set order type to Limit ────────────────────────────────
    try:
        # Click the order type dropdown
        page.click("[data-name='order-type-switcher'], .order-type-selector", timeout=5000)
        time.sleep(0.5)
        page.click("text=Limit", timeout=5000)
        time.sleep(0.4)
    except Exception:
        print(f"  [INFO] Couldn't set Limit order type, continuing with market order")

    # ── 4. Set quantity ───────────────────────────────────────────
    try:
        qty_selectors = [
            "input[data-name='qty-input']",
            "input[placeholder='Qty']",
            "input[name='qty']",
            ".qty-input input",
            "input.input-qty",
        ]
        qty_set = False
        for sel in qty_selectors:
            try:
                clear_and_type(page, sel, qty, timeout=3000)
                qty_set = True
                break
            except Exception:
                continue
        if not qty_set:
            print(f"  [WARN] Could not set quantity for {symbol}")
    except Exception as e:
        print(f"  [WARN] Qty error: {e}")

    # ── 5. Set limit price ────────────────────────────────────────
    try:
        price_selectors = [
            "input[data-name='price-input']",
            "input[placeholder='Price']",
            "input[name='price']",
            ".price-input input",
        ]
        for sel in price_selectors:
            try:
                clear_and_type(page, sel, entry, timeout=3000)
                break
            except Exception:
                continue
    except Exception as e:
        print(f"  [WARN] Price error: {e}")

    # ── 6. Set Stop Loss ──────────────────────────────────────────
    try:
        # Toggle SL on if not already
        sl_toggle_selectors = [
            "input[data-name='sl-toggle']",
            "[data-name='stop-loss-toggle']",
            "input[id*='stop-loss']",
        ]
        for sel in sl_toggle_selectors:
            try:
                el = page.query_selector(sel)
                if el and not el.is_checked():
                    el.click()
                    time.sleep(0.3)
                break
            except Exception:
                continue

        sl_selectors = [
            "input[data-name='sl-input']",
            "input[placeholder='Stop loss']",
            "input[name='stop-loss']",
            ".stop-loss-input input",
        ]
        for sel in sl_selectors:
            try:
                clear_and_type(page, sel, sl, timeout=3000)
                break
            except Exception:
                continue
    except Exception as e:
        print(f"  [WARN] SL error: {e}")

    # ── 7. Set Take Profit ────────────────────────────────────────
    try:
        tp_toggle_selectors = [
            "input[data-name='tp-toggle']",
            "[data-name='take-profit-toggle']",
            "input[id*='take-profit']",
        ]
        for sel in tp_toggle_selectors:
            try:
                el = page.query_selector(sel)
                if el and not el.is_checked():
                    el.click()
                    time.sleep(0.3)
                break
            except Exception:
                continue

        tp_selectors = [
            "input[data-name='tp-input']",
            "input[placeholder='Take profit']",
            "input[name='take-profit']",
            ".take-profit-input input",
        ]
        for sel in tp_selectors:
            try:
                clear_and_type(page, sel, tp, timeout=3000)
                break
            except Exception:
                continue
    except Exception as e:
        print(f"  [WARN] TP error: {e}")

    time.sleep(0.5)

    # ── 8. Submit the order ───────────────────────────────────────
    try:
        submit_selectors = [
            "button[data-name='submit-order']",
            "button[data-name='place-order-button']",
            "button.submit-button",
            "button:has-text('Buy')",
            "button:has-text('Place order')",
        ]
        submitted = False
        for sel in submit_selectors:
            try:
                page.click(sel, timeout=4000)
                submitted = True
                break
            except Exception:
                continue

        if not submitted:
            print(f"  [WARN] Could not find submit button for {symbol}")
            return False

        time.sleep(1.0)

        # Confirm dialog if it appears
        try:
            confirm_selectors = [
                "button[data-name='confirm']",
                "button:has-text('Confirm')",
                "button:has-text('OK')",
            ]
            for sel in confirm_selectors:
                try:
                    page.click(sel, timeout=3000)
                    break
                except Exception:
                    continue
        except Exception:
            pass

        time.sleep(1.2)
        print(f"  [OK] Order placed for {symbol}")
        return True

    except Exception as e:
        print(f"  [ERROR] Submit failed for {symbol}: {e}")
        return False


def main():
    positions = fetch_positions()
    # Only open positions (no exitDate)
    open_pos = [p for p in positions if p.get("entryPrice")]
    if not open_pos:
        print("No open positions found in AQRTI.")
        sys.exit(0)

    print(f"\n{'='*55}")
    print(f"  AQRTI → TradingView Paper Trading Automator")
    print(f"{'='*55}")
    print(f"  Found {len(open_pos)} open positions to place\n")
    for p in open_pos:
        sl_pct = abs(p.get('stopLoss', p['entryPrice']) - p['entryPrice']) / p['entryPrice'] * 100
        tp_pct = abs(p.get('target',   p['entryPrice']) - p['entryPrice']) / p['entryPrice'] * 100
        print(f"  {p['symbol']:<15} qty={round(p['shares'])} entry={p['entryPrice']} "
              f"SL=-{sl_pct:.1f}% TP=+{tp_pct:.1f}%")
    print()

    with sync_playwright() as pw:
        # Launch in headed mode so you can log in
        browser = pw.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        ctx  = browser.new_context(viewport=None)
        page = ctx.new_page()

        print(f"[*] Opening TradingView...")
        page.goto(TV_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # ── Wait for login ─────────────────────────────────────────
        print(f"\n[!] Please log in to TradingView in the browser window.")
        print(f"[!] Also make sure Paper Trading panel is open at the bottom.")
        print(f"[!] Script will start placing trades in {LOGIN_WAIT_SECS} seconds...\n")

        for remaining in range(LOGIN_WAIT_SECS, 0, -5):
            print(f"    Starting in {remaining}s... (log in now)", end="\r")
            time.sleep(5)
        print("\n")

        # ── Place each order ───────────────────────────────────────
        placed  = 0
        skipped = 0
        for i, pos in enumerate(open_pos, 1):
            ok = place_order(page, pos, i, len(open_pos))
            if ok:
                placed += 1
            else:
                skipped += 1
            time.sleep(1.5)

        print(f"\n{'='*55}")
        print(f"  Done! Placed: {placed} | Skipped: {skipped}")
        print(f"{'='*55}")
        print("\n[*] Browser will stay open for 60s so you can verify.")
        print("    Close it manually when done.\n")
        time.sleep(60)
        browser.close()


if __name__ == "__main__":
    main()
