import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

ROOT = Path(__file__).parent.parent
COMPANIES_PATH = ROOT / "data" / "snapshot" / "companies.json"
META_PATH = ROOT / "data" / "snapshot" / "meta.json"

REQUIRED_FIELDS = [
    "ticker", "cik", "title", "sic", "fy_end", "revenue", "net_income",
    "operating_income", "ebitda", "total_assets", "book_equity", "cash",
    "total_debt", "net_debt", "market_cap", "enterprise_value",
    "multiples", "multiples_excluded", "sector", "features", "flags",
]


def _load_companies():
    if not COMPANIES_PATH.exists():
        return None
    return json.loads(COMPANIES_PATH.read_text())


def test_snapshot_exists():
    assert COMPANIES_PATH.exists(), "run src/build_snapshot.py first"
    assert META_PATH.exists()


def test_every_company_has_required_fields_or_is_flagged():
    companies = _load_companies()
    for c in companies:
        for field in REQUIRED_FIELDS:
            assert field in c, f"{c.get('ticker')} missing field {field}"
        # a company with no usable financials must carry an explanatory flag
        if c["revenue"] is None and c["net_income"] is None:
            assert len(c["flags"]) > 0, f"{c['ticker']} has no data and no flags"


def test_no_duplicate_tickers():
    companies = _load_companies()
    tickers = [c["ticker"] for c in companies]
    assert len(tickers) == len(set(tickers))


def test_meta_counts_consistent():
    companies = _load_companies()
    meta = json.loads(META_PATH.read_text())
    assert meta["companies_built"] == len(companies)


def test_ebitda_never_silently_zero_filled():
    """If EBITDA components were missing, ebitda must be None, not 0."""
    companies = _load_companies()
    for c in companies:
        if "ebitda_missing_components" in c["flags"]:
            assert c["ebitda"] is None


def test_negative_ebitda_excluded_from_ev_ebitda():
    companies = _load_companies()
    for c in companies:
        if c["ebitda"] is not None and c["ebitda"] <= 0:
            assert c["multiples"]["ev_ebitda"] is None
