"""Pull fundamentals from SEC EDGAR companyfacts API and extract the latest
annual (10-K) value for each metric we need, with full tag provenance.

XBRL tags vary by filer, so each metric has a fallback list of synonym tags
tried in order. Whichever tag actually supplied the value is recorded in
'tag_used' so every number is auditable back to its source filing concept.
"""
import time
from dataclasses import dataclass, field

import requests

USER_AGENT = "comps-engine contact@example.com"

# Tag fallback chains, tried in order, per metric. us-gaap namespace unless noted.
DURATION_TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "Depreciation",
    ],
}

INSTANT_TAGS = {
    "total_assets": ["Assets"],
    "book_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsAtCarryingValueIncludingDiscontinuedOperations",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsAtCarryingValue",
    ],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "current_debt": ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings"],
    "shares_outstanding": ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
}


@dataclass
class FieldResult:
    value: float | None
    tag_used: str | None
    fy_end: str | None
    found: bool = field(init=False)

    def __post_init__(self):
        self.found = self.value is not None


def fetch_companyfacts(cik10: str, session: requests.Session, sleep: float = 0.11) -> dict | None:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
    resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    time.sleep(sleep)
    if resp.status_code != 200:
        return None
    return resp.json()


def _latest_duration_value(facts: dict, tags: list[str]) -> FieldResult:
    """Pick the most recent 10-K full-year (~365 day) value across a tag fallback list."""
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        tag_data = usgaap.get(tag)
        if not tag_data:
            continue
        candidates = []
        for unit, points in tag_data.get("units", {}).items():
            if unit != "USD":
                continue
            for p in points:
                if p.get("form") != "10-K" or p.get("fp") != "FY":
                    continue
                start, end = p.get("start"), p.get("end")
                if not start or not end:
                    continue
                days = (_date(end) - _date(start)).days
                if not (330 <= days <= 400):  # roughly one fiscal year
                    continue
                candidates.append(p)
        if candidates:
            best = max(candidates, key=lambda p: p["end"])
            return FieldResult(value=float(best["val"]), tag_used=tag, fy_end=best["end"])
    return FieldResult(value=None, tag_used=None, fy_end=None)


def revenue_history(facts: dict, n_years: int = 4) -> list[dict]:
    """Return up to n_years of annual revenue points (most recent first),
    using the same tag fallback chain as the latest-value extraction, so the
    growth feature (CAGR) is computed from a consistent tag where possible."""
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in DURATION_TAGS["revenue"]:
        tag_data = usgaap.get(tag)
        if not tag_data:
            continue
        candidates = []
        for unit, points in tag_data.get("units", {}).items():
            if unit != "USD":
                continue
            for p in points:
                if p.get("form") != "10-K" or p.get("fp") != "FY":
                    continue
                start, end = p.get("start"), p.get("end")
                if not start or not end:
                    continue
                days = (_date(end) - _date(start)).days
                if not (330 <= days <= 400):
                    continue
                candidates.append(p)
        if candidates:
            # de-dup by fiscal year-end, keep latest filed value per period
            by_end = {}
            for p in candidates:
                by_end[p["end"]] = p
            ordered = sorted(by_end.values(), key=lambda p: p["end"], reverse=True)
            return [
                {"fy_end": p["end"], "value": float(p["val"]), "tag_used": tag}
                for p in ordered[:n_years]
            ]
    return []


def _latest_instant_value(facts: dict, tags: list[str]) -> FieldResult:
    """Pick the most recent instant (point-in-time) value, preferring 10-K filings."""
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        tag_data = usgaap.get(tag)
        if not tag_data:
            continue
        candidates = []
        for unit, points in tag_data.get("units", {}).items():
            if unit not in ("USD", "shares"):
                continue
            for p in points:
                if p.get("form") != "10-K":
                    continue
                if not p.get("end"):
                    continue
                candidates.append(p)
        if candidates:
            best = max(candidates, key=lambda p: p["end"])
            return FieldResult(value=float(best["val"]), tag_used=tag, fy_end=best["end"])
    return FieldResult(value=None, tag_used=None, fy_end=None)


def _date(s: str):
    from datetime import date
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def extract_financials(facts: dict) -> dict:
    """Extract all required raw fields with provenance. Does NOT compute EBITDA
    or totals — that's normalize.py's job, so the reconstruction stays auditable
    and separate from raw extraction."""
    out = {}
    for metric, tags in DURATION_TAGS.items():
        r = _latest_duration_value(facts, tags)
        out[metric] = {"value": r.value, "tag_used": r.tag_used, "fy_end": r.fy_end, "found": r.found}
    for metric, tags in INSTANT_TAGS.items():
        r = _latest_instant_value(facts, tags)
        out[metric] = {"value": r.value, "tag_used": r.tag_used, "fy_end": r.fy_end, "found": r.found}
    out["revenue_history"] = revenue_history(facts)
    return out
