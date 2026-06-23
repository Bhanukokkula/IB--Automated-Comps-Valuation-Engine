import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from peers import sector_for, build_feature_vector, rank_peers


def make_company(ticker, sic, revenue, market_cap, total_assets, ebitda_margin, net_margin, cagr=0.05, leverage=1.0):
    c = {
        "ticker": ticker,
        "title": ticker,
        "revenue": revenue,
        "market_cap": market_cap,
        "total_assets": total_assets,
        "ebitda_margin": ebitda_margin,
        "net_margin": net_margin,
        "revenue_cagr": cagr,
        "net_debt_to_ebitda": leverage,
    }
    c["sector"] = sector_for(sic)
    c["features"] = build_feature_vector(c)
    return c


def test_sector_hard_filter():
    assert sector_for(3674) == "Tech Hardware & Semis"
    assert sector_for(6021) == "Banks"
    assert sector_for(9999) == "Unclassified"
    assert sector_for(None) == "Unclassified"


def test_rank_peers_only_returns_same_sector():
    companies = [
        make_company("A", 3674, 1e9, 5e9, 2e9, 0.3, 0.15),
        make_company("B", 3674, 1.1e9, 5.2e9, 2.1e9, 0.31, 0.16),
        make_company("C", 6021, 1e9, 5e9, 2e9, 0.3, 0.15),  # different sector
    ]
    result = rank_peers("A", companies)
    tickers = [p["ticker"] for p in result["peers"]]
    assert "B" in tickers
    assert "C" not in tickers


def test_rank_peers_closer_company_ranked_first():
    companies = [
        make_company("TARGET", 3674, 1e9, 5e9, 2e9, 0.30, 0.15),
        make_company("CLOSE", 3674, 1.05e9, 5.1e9, 2.05e9, 0.31, 0.16),
        make_company("FAR", 3674, 50e9, 200e9, 80e9, 0.05, -0.10),
    ]
    result = rank_peers("TARGET", companies)
    assert result["peers"][0]["ticker"] == "CLOSE"


def test_missing_features_excluded_from_distance_not_zero_filled():
    companies = [
        make_company("TARGET", 3674, 1e9, 5e9, 2e9, 0.30, 0.15),
        make_company("PARTIAL", 3674, 1e9, 5e9, 2e9, 0.30, 0.15),
    ]
    companies[1]["features"]["revenue_cagr"] = None
    result = rank_peers("TARGET", companies)
    peer = result["peers"][0]
    assert "revenue_cagr" in peer["features_missing"]


def test_no_peers_in_sector_returns_warning():
    companies = [make_company("LONELY", 3674, 1e9, 5e9, 2e9, 0.3, 0.15)]
    result = rank_peers("LONELY", companies)
    assert result["peers"] == []
    assert "warning" in result


def test_thin_data_peer_ranked_after_fully_compared_peer():
    # THIN has only one comparable feature (huge market cap, like a real
    # foreign-issuer case with no EDGAR fundamentals) which would otherwise
    # look deceptively "close" on that single dimension alone.
    target = make_company("TARGET", 3674, 1e9, 5e9, 2e9, 0.30, 0.15)
    full_peer = make_company("FULL", 3674, 1.2e9, 5.5e9, 2.2e9, 0.25, 0.12)
    thin_peer = make_company("THIN", 3674, 1e9, 5.01e9, 2e9, 0.30, 0.15)
    for feat in ["log_revenue", "log_total_assets", "ebitda_margin", "net_margin", "revenue_cagr", "net_debt_to_ebitda"]:
        thin_peer["features"][feat] = None
    companies = [target, full_peer, thin_peer]
    result = rank_peers("TARGET", companies)
    tickers_in_order = [p["ticker"] for p in result["peers"]]
    assert tickers_in_order == ["FULL", "THIN"]
    assert result["peers"][1]["thin_data"] is True


def test_unknown_target_raises():
    companies = [make_company("A", 3674, 1e9, 5e9, 2e9, 0.3, 0.15)]
    try:
        rank_peers("NOTFOUND", companies)
        assert False, "expected ValueError"
    except ValueError:
        pass
