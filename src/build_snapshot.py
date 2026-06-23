"""Orchestrate: universe.csv -> EDGAR fundamentals + yfinance prices ->
normalize -> multiples -> static JSON snapshot.

Run once to (re)build the snapshot. The dashboard never calls this; it only
reads data/snapshot/companies.json and data/snapshot/meta.json, which is the
whole point — zero runtime API dependency, zero rate-limit fragility.

Peer ranking and implied valuation are NOT precomputed here. They're cheap,
pure functions over the snapshot (see peers.py / valuation.py) and depend on
which target the user picks, so the dashboard computes them on the fly from
the static company list. That keeps this script's only job as "build a
clean, normalized company table," which is also what keeps it testable.
"""
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))

from edgar_map import fetch_sic  # noqa: E402  (kept for potential re-resolution)
from ingest_edgar import fetch_companyfacts, extract_financials  # noqa: E402
from ingest_prices import fetch_price_data  # noqa: E402
from normalize import normalize_company  # noqa: E402
from multiples import compute_multiples  # noqa: E402
from peers import sector_for, build_feature_vector  # noqa: E402

ROOT = Path(__file__).parent.parent
UNIVERSE_CSV = ROOT / "data" / "universe.csv"
SNAPSHOT_DIR = ROOT / "data" / "snapshot"
RAW_CACHE_DIR = SNAPSHOT_DIR / "raw_facts"


def load_universe() -> list[dict]:
    with open(UNIVERSE_CSV) as f:
        return list(csv.DictReader(f))


def get_companyfacts_cached(ticker: str, cik: str, session: requests.Session) -> dict | None:
    RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_CACHE_DIR / f"{ticker}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    facts = fetch_companyfacts(cik, session)
    if facts is not None:
        cache_path.write_text(json.dumps(facts))
    return facts


def build(universe_rows: list[dict], snapshot_date: date, use_cache: bool = True) -> tuple[list[dict], dict]:
    session = requests.Session()
    companies = []
    n_no_facts = 0
    n_no_price = 0

    for i, row in enumerate(universe_rows):
        ticker, cik, title = row["ticker"], row["cik"], row["title"]
        sic, sic_desc = row.get("sic"), row.get("sic_description")

        if use_cache:
            facts = get_companyfacts_cached(ticker, cik, session)
        else:
            facts = fetch_companyfacts(cik, session)

        if facts is None:
            n_no_facts += 1
            print(f"  [{i+1}/{len(universe_rows)}] {ticker}: NO companyfacts data")
            continue

        raw = extract_financials(facts)
        price = fetch_price_data(ticker)
        if not price.get("found"):
            n_no_price += 1

        company = normalize_company(ticker, cik, title, sic, sic_desc, raw, price, snapshot_date)
        mult_result = compute_multiples(company)
        company["multiples"] = mult_result["multiples"]
        company["multiples_excluded"] = mult_result["excluded"]
        company["sector"] = sector_for(sic)
        company["features"] = build_feature_vector(company)

        companies.append(company)
        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(universe_rows)}] processed")

    meta = {
        "snapshot_date": snapshot_date.isoformat(),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "universe_requested": len(universe_rows),
        "companies_built": len(companies),
        "companies_missing_facts": n_no_facts,
        "companies_missing_price": n_no_price,
    }
    return companies, meta


def main():
    universe_rows = load_universe()
    snapshot_date = date.today()
    print(f"Building snapshot for {len(universe_rows)} companies, dated {snapshot_date.isoformat()}...")

    companies, meta = build(universe_rows, snapshot_date)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / "companies.json").write_text(json.dumps(companies, indent=2))
    (SNAPSHOT_DIR / "meta.json").write_text(json.dumps(meta, indent=2))

    print(json.dumps(meta, indent=2))
    print(f"Wrote {len(companies)} companies to {SNAPSHOT_DIR / 'companies.json'}")


if __name__ == "__main__":
    main()
