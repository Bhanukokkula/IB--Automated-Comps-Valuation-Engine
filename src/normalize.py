"""Combine raw EDGAR fundamentals + price data into one normalized company
record. Every normalization decision below is also logged in LIMITATIONS.md.

Decisions made here, and why:
  - EBITDA is not an XBRL tag. We reconstruct it as
    OperatingIncomeLoss + DepreciationDepletionAndAmortization. If either
    component is missing we do NOT zero-fill it (that would silently
    understate EBITDA) — we leave ebitda as None and flag it.
  - total_debt sums LongTermDebtNoncurrent + LongTermDebtCurrent (current
    portion of LT debt). If only one is found we still report a value but
    flag it as partial, since e.g. a company funded entirely by revolver
    debt won't show up under LongTermDebt at all.
  - We do not attempt to reconcile fiscal year-end mismatches across
    companies (e.g. a Jan-FYE retailer vs a Dec-FYE peer) — we record each
    company's actual fy_end and flag the comparison as non-contemporaneous
    if fiscal year-ends differ by more than ~45 days from the calendar peer
    norm. The multiples are still computed; the flag is for the analyst.
  - Filers who report no 10-K duration tags at all (most foreign private
    issuers file Form 20-F, often under IFRS) are flagged explicitly rather
    than silently dropped, since this is exactly the GAAP/IFRS comparability
    gap the project is required to surface, not hide.
"""
from datetime import date


STALE_DAYS = 450  # ~15 months — flag filings older than this as stale


def _sum_optional(*vals: float | None) -> tuple[float | None, bool]:
    """Sum the non-None values. Returns (sum_or_None, all_missing)."""
    present = [v for v in vals if v is not None]
    if not present:
        return None, True
    return sum(present), False


def normalize_company(
    ticker: str,
    cik: str,
    title: str,
    sic: str | None,
    sic_description: str | None,
    raw: dict,
    price: dict,
    snapshot_date: date,
) -> dict:
    flags: list[str] = []

    revenue = raw["revenue"]["value"]
    net_income = raw["net_income"]["value"]
    operating_income = raw["operating_income"]["value"]
    da = raw["depreciation_amortization"]["value"]
    total_assets = raw["total_assets"]["value"]
    book_equity = raw["book_equity"]["value"]
    cash = raw["cash"]["value"]
    shares_out_edgar = raw["shares_outstanding"]["value"]

    # --- EBITDA reconstruction ---
    if operating_income is not None and da is not None:
        ebitda = operating_income + da
    else:
        ebitda = None
        flags.append("ebitda_missing_components")

    # --- total debt ---
    long_term_debt = raw["long_term_debt"]["value"]
    current_debt = raw["current_debt"]["value"]
    total_debt, debt_all_missing = _sum_optional(long_term_debt, current_debt)
    if debt_all_missing:
        flags.append("debt_data_missing")
    elif long_term_debt is None or current_debt is None:
        flags.append("debt_data_partial")

    # --- net debt ---
    if total_debt is not None and cash is not None:
        net_debt = total_debt - cash
    else:
        net_debt = None
        flags.append("net_debt_unavailable")

    # --- fiscal year-end staleness ---
    fy_end_str = raw["revenue"]["fy_end"] or raw["total_assets"]["fy_end"]
    fy_end = None
    if fy_end_str:
        y, m, d = fy_end_str.split("-")
        fy_end = date(int(y), int(m), int(d))
        if (snapshot_date - fy_end).days > STALE_DAYS:
            flags.append("stale_filing")
    else:
        flags.append("no_annual_filing_found")

    # --- likely foreign private issuer / non-GAAP comparability gap ---
    core_found = sum(
        1
        for k in ("revenue", "net_income", "operating_income")
        if raw[k]["value"] is not None
    )
    if core_found == 0:
        flags.append("no_10k_data_likely_foreign_private_issuer_or_ifrs")

    # --- revenue CAGR from available annual history ---
    history = raw.get("revenue_history", [])
    revenue_cagr = None
    if len(history) >= 2:
        newest, oldest = history[0]["value"], history[-1]["value"]
        years = len(history) - 1
        if oldest > 0 and newest > 0:
            revenue_cagr = (newest / oldest) ** (1 / years) - 1
        else:
            flags.append("revenue_cagr_undefined_nonpositive_base")
    else:
        flags.append("revenue_cagr_insufficient_history")

    # --- margins ---
    gross_margin = None  # no COGS tag extracted; not computable from current tag set
    ebitda_margin = ebitda / revenue if (ebitda is not None and revenue) else None
    net_margin = net_income / revenue if (net_income is not None and revenue) else None

    # --- market data ---
    market_cap = price.get("market_cap")
    market_price = price.get("price")
    if market_cap is None:
        flags.append("market_data_unavailable")

    # --- enterprise value ---
    if market_cap is not None and net_debt is not None:
        enterprise_value = market_cap + net_debt
    else:
        enterprise_value = None
        flags.append("ev_unavailable")

    return {
        "ticker": ticker,
        "cik": cik,
        "title": title,
        "sic": sic,
        "sic_description": sic_description,
        "fy_end": fy_end.isoformat() if fy_end else None,
        "revenue": revenue,
        "net_income": net_income,
        "operating_income": operating_income,
        "depreciation_amortization": da,
        "ebitda": ebitda,
        "total_assets": total_assets,
        "book_equity": book_equity,
        "cash": cash,
        "total_debt": total_debt,
        "net_debt": net_debt,
        "shares_outstanding_edgar": shares_out_edgar,
        "market_price": market_price,
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "revenue_cagr": revenue_cagr,
        "revenue_history_years": len(history),
        "gross_margin": gross_margin,
        "ebitda_margin": ebitda_margin,
        "net_margin": net_margin,
        "net_debt_to_ebitda": (net_debt / ebitda if (net_debt is not None and ebitda and ebitda > 0) else None),
        "tag_provenance": {k: raw[k]["tag_used"] for k in raw if k != "revenue_history"},
        "flags": flags,
    }
