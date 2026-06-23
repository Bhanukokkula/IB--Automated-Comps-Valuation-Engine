"""Market price / shares-outstanding-implied market cap from yfinance.

EDGAR has fundamentals but no market prices, so this is a separate source
fetched at snapshot-build time. See LIMITATIONS.md: this makes the snapshot
go stale the moment prices move, by design (no live dependency in the demo).
"""
import time

import yfinance as yf


def fetch_price_data(ticker: str, sleep: float = 0.05) -> dict:
    """Return last close price and yfinance's own market cap for one ticker."""
    try:
        tk = yf.Ticker(ticker)
        info = tk.fast_info
        price = info.get("lastPrice")
        market_cap = info.get("marketCap")
        time.sleep(sleep)
        if price is None:
            return {"price": None, "market_cap": None, "found": False}
        return {"price": float(price), "market_cap": float(market_cap) if market_cap else None, "found": True}
    except Exception:
        return {"price": None, "market_cap": None, "found": False}
