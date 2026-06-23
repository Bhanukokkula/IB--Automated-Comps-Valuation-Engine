import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from multiples import compute_multiples


def base_company(**overrides):
    c = {
        "enterprise_value": 1_000_000,
        "revenue": 500_000,
        "ebitda": 100_000,
        "operating_income": 80_000,
        "net_income": 50_000,
        "market_cap": 900_000,
        "book_equity": 300_000,
    }
    c.update(overrides)
    return c


def test_known_ev_ebitda():
    # hand-checked: EV 1,000,000 / EBITDA 100,000 = 10.0x
    result = compute_multiples(base_company())
    assert result["multiples"]["ev_ebitda"] == 10.0


def test_known_ev_revenue():
    result = compute_multiples(base_company())
    assert result["multiples"]["ev_revenue"] == 2.0  # 1,000,000 / 500,000


def test_known_pe():
    result = compute_multiples(base_company())
    assert result["multiples"]["pe"] == 18.0  # 900,000 / 50,000


def test_known_pb():
    result = compute_multiples(base_company())
    assert abs(result["multiples"]["pb"] - 3.0) < 1e-9  # 900,000 / 300,000


def test_negative_ebitda_excluded():
    result = compute_multiples(base_company(ebitda=-50_000))
    assert result["multiples"]["ev_ebitda"] is None
    assert any("ev_ebitda" in e for e in result["excluded"])


def test_near_zero_ebitda_excluded():
    # EBITDA below 0.5% of revenue floor should be excluded as meaningless
    result = compute_multiples(base_company(ebitda=1_000, revenue=500_000))
    assert result["multiples"]["ev_ebitda"] is None


def test_negative_net_income_excludes_pe():
    result = compute_multiples(base_company(net_income=-10_000))
    assert result["multiples"]["pe"] is None


def test_negative_book_equity_excludes_pb():
    result = compute_multiples(base_company(book_equity=-5_000))
    assert result["multiples"]["pb"] is None


def test_missing_ev_excludes_ev_based_multiples():
    result = compute_multiples(base_company(enterprise_value=None))
    assert result["multiples"]["ev_revenue"] is None
    assert result["multiples"]["ev_ebitda"] is None
    assert result["multiples"]["ev_ebit"] is None
    # pe/pb don't depend on EV, should still compute
    assert result["multiples"]["pe"] is not None
    assert result["multiples"]["pb"] is not None
