"""Valuation multiples for a single normalized company record.

EV = market_cap + net_debt (net_debt = total_debt - cash).

Negative or near-zero EBITDA makes EV/EBITDA meaningless (small denominator
blows up the ratio, sign flips are uninterpretable), so EV/EBITDA is
excluded — not zero-filled, not clipped — whenever EBITDA <= EBITDA_FLOOR.
Same logic applies to EV/EBIT, P/E (loss-making companies), and P/B
(negative book equity).
"""

EBITDA_FLOOR_RATIO = 0.005  # EBITDA must be >= 0.5% of revenue to be usable


def compute_multiples(company: dict) -> dict:
    ev = company["enterprise_value"]
    revenue = company["revenue"]
    ebitda = company["ebitda"]
    operating_income = company["operating_income"]
    net_income = company["net_income"]
    market_cap = company["market_cap"]
    book_equity = company["book_equity"]

    multiples: dict[str, float | None] = {
        "ev_revenue": None,
        "ev_ebitda": None,
        "ev_ebit": None,
        "pe": None,
        "pb": None,
    }
    excluded: list[str] = []

    if ev is not None and revenue is not None and revenue > 0:
        multiples["ev_revenue"] = ev / revenue
    else:
        excluded.append("ev_revenue: missing EV or non-positive revenue")

    ebitda_floor = (revenue * EBITDA_FLOOR_RATIO) if revenue else 0
    if ev is not None and ebitda is not None and ebitda > ebitda_floor:
        multiples["ev_ebitda"] = ev / ebitda
    else:
        excluded.append("ev_ebitda: missing EV or EBITDA non-positive/near-zero")

    if ev is not None and operating_income is not None and operating_income > 0:
        multiples["ev_ebit"] = ev / operating_income
    else:
        excluded.append("ev_ebit: missing EV or non-positive operating income (EBIT)")

    if market_cap is not None and net_income is not None and net_income > 0:
        multiples["pe"] = market_cap / net_income
    else:
        excluded.append("pe: missing market cap or non-positive net income")

    if market_cap is not None and book_equity is not None and book_equity > 0:
        multiples["pb"] = market_cap / book_equity
    else:
        excluded.append("pb: missing market cap or non-positive book equity")

    return {"multiples": multiples, "excluded": excluded}
