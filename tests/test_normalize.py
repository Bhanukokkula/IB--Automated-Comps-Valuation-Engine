import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from normalize import normalize_company


def field(value, tag="SomeTag", fy_end="2024-12-31"):
    return {"value": value, "tag_used": tag if value is not None else None, "fy_end": fy_end if value is not None else None, "found": value is not None}


def base_raw(**overrides):
    raw = {
        "revenue": field(1_000_000),
        "net_income": field(100_000),
        "operating_income": field(150_000),
        "depreciation_amortization": field(50_000),
        "total_assets": field(2_000_000),
        "book_equity": field(800_000),
        "cash": field(200_000),
        "long_term_debt": field(400_000),
        "current_debt": field(50_000),
        "shares_outstanding": field(10_000),
        "revenue_history": [
            {"fy_end": "2024-12-31", "value": 1_000_000, "tag_used": "Revenues"},
            {"fy_end": "2023-12-31", "value": 900_000, "tag_used": "Revenues"},
        ],
    }
    raw.update(overrides)
    return raw


def base_price(**overrides):
    p = {"price": 50.0, "market_cap": 500_000, "found": True}
    p.update(overrides)
    return p


def test_ebitda_reconstruction():
    c = normalize_company("T", "0000000001", "Test Co", "1234", "Test SIC", base_raw(), base_price(), date(2025, 6, 1))
    assert c["ebitda"] == 200_000  # 150,000 operating income + 50,000 D&A
    assert "ebitda_missing_components" not in c["flags"]


def test_ebitda_missing_component_flagged_not_zero_filled():
    raw = base_raw(depreciation_amortization=field(None))
    c = normalize_company("T", "0000000001", "Test Co", "1234", "Test SIC", raw, base_price(), date(2025, 6, 1))
    assert c["ebitda"] is None
    assert "ebitda_missing_components" in c["flags"]


def test_negative_ebitda_not_clipped():
    raw = base_raw(operating_income=field(-300_000))
    c = normalize_company("T", "0000000001", "Test Co", "1234", "Test SIC", raw, base_price(), date(2025, 6, 1))
    assert c["ebitda"] == -250_000  # -300,000 + 50,000, left negative on purpose


def test_partial_debt_data_flagged():
    raw = base_raw(current_debt=field(None))
    c = normalize_company("T", "0000000001", "Test Co", "1234", "Test SIC", raw, base_price(), date(2025, 6, 1))
    assert c["total_debt"] == 400_000  # only long-term debt found
    assert "debt_data_partial" in c["flags"]


def test_all_debt_missing_flagged():
    raw = base_raw(long_term_debt=field(None), current_debt=field(None))
    c = normalize_company("T", "0000000001", "Test Co", "1234", "Test SIC", raw, base_price(), date(2025, 6, 1))
    assert c["total_debt"] is None
    assert "debt_data_missing" in c["flags"]


def test_stale_filing_flagged():
    raw = base_raw(revenue=field(1_000_000, fy_end="2020-01-01"))
    c = normalize_company("T", "0000000001", "Test Co", "1234", "Test SIC", raw, base_price(), date(2025, 6, 1))
    assert "stale_filing" in c["flags"]


def test_mismatched_fiscal_year_not_silently_treated_as_comparable():
    # two companies with very different fy_end dates both compute, but the
    # fy_end is preserved on the record so a caller can compare and flag
    raw_a = base_raw(revenue=field(1_000_000, fy_end="2024-12-31"))
    raw_b = base_raw(revenue=field(1_000_000, fy_end="2024-06-30"))
    a = normalize_company("A", "1", "A Co", "1", "x", raw_a, base_price(), date(2025, 6, 1))
    b = normalize_company("B", "2", "B Co", "1", "x", raw_b, base_price(), date(2025, 6, 1))
    assert a["fy_end"] != b["fy_end"]


def test_revenue_cagr_computed_from_history():
    c = normalize_company("T", "0000000001", "Test Co", "1234", "Test SIC", base_raw(), base_price(), date(2025, 6, 1))
    expected = (1_000_000 / 900_000) ** (1 / 1) - 1
    assert abs(c["revenue_cagr"] - expected) < 1e-9


def test_revenue_cagr_insufficient_history_flagged():
    raw = base_raw(revenue_history=[{"fy_end": "2024-12-31", "value": 1_000_000, "tag_used": "Revenues"}])
    c = normalize_company("T", "0000000001", "Test Co", "1234", "Test SIC", raw, base_price(), date(2025, 6, 1))
    assert c["revenue_cagr"] is None
    assert "revenue_cagr_insufficient_history" in c["flags"]


def test_no_10k_data_flagged_as_likely_foreign_private_issuer():
    raw = base_raw(
        revenue=field(None), net_income=field(None), operating_income=field(None)
    )
    c = normalize_company("T", "0000000001", "Test Co", "1234", "Test SIC", raw, base_price(), date(2025, 6, 1))
    assert "no_10k_data_likely_foreign_private_issuer_or_ifrs" in c["flags"]
