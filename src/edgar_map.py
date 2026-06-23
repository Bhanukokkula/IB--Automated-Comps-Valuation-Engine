"""Ticker -> CIK resolution using SEC's company_tickers.json map."""
import json
import time
from pathlib import Path

import requests

USER_AGENT = "comps-engine contact@example.com"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
CACHE_PATH = Path(__file__).parent.parent / "data" / "snapshot" / "raw_ticker_map.json"


def fetch_ticker_map(force: bool = False) -> dict:
    """Return {ticker: {cik_str, ticker, title}}, cached to disk."""
    if CACHE_PATH.exists() and not force:
        return json.loads(CACHE_PATH.read_text())

    resp = requests.get(TICKER_MAP_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    raw = resp.json()
    by_ticker = {v["ticker"]: v for v in raw.values()}
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(by_ticker))
    return by_ticker


def cik_for_ticker(ticker: str, ticker_map: dict) -> str | None:
    """Return zero-padded 10-digit CIK string, or None if not found."""
    entry = ticker_map.get(ticker.upper())
    if entry is None:
        return None
    return str(entry["cik_str"]).zfill(10)


def fetch_sic(cik10: str, session: requests.Session, sleep: float = 0.11) -> dict:
    """Fetch SIC code/description for a CIK from the submissions endpoint."""
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    time.sleep(sleep)  # stay under SEC's ~10 req/sec guidance
    if resp.status_code != 200:
        return {"sic": None, "sicDescription": None}
    d = resp.json()
    return {"sic": d.get("sic"), "sicDescription": d.get("sicDescription")}
