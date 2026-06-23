"""Benchmark the target against its peer set and produce an implied
valuation range. Peer aggregation uses the MEDIAN (not mean) specifically
because comps sets routinely contain a few extreme multiples (a richly
priced grower, a distressed name) that would distort a mean."""

import statistics

MULTIPLE_DENOMINATORS = {
    "ev_revenue": "revenue",
    "ev_ebitda": "ebitda",
    "ev_ebit": "operating_income",
    "pe": "net_income",
    "pb": "book_equity",
}

# multiples expressed on an enterprise-value basis need net debt subtracted
# back out to get to equity value; pe/pb are already equity-value multiples
EV_BASED = {"ev_revenue", "ev_ebitda", "ev_ebit"}


def winsorize(values: list[float], pct: float = 0.05) -> list[float]:
    """Clip the bottom/top pct of a sorted list to the nearest retained value."""
    if len(values) < 4:
        return values
    s = sorted(values)
    k = max(1, int(len(s) * pct))
    lo, hi = s[k], s[-(k + 1)]
    return [min(max(v, lo), hi) for v in s]


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in [0, 1]) over an already-sorted list."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = pct * (len(sorted_vals) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def peer_multiple_distribution(peer_multiples: list[float | None], winsorize_pct: float = 0.05) -> dict:
    clean = [v for v in peer_multiples if v is not None]
    n_excluded = len(peer_multiples) - len(clean)
    if not clean:
        return {"n": 0, "n_excluded": n_excluded, "min": None, "p25": None, "median": None, "p75": None, "max": None}

    wins = winsorize(clean, winsorize_pct) if len(clean) >= 4 else clean
    s = sorted(wins)
    return {
        "n": len(clean),
        "n_excluded": n_excluded,
        "min": s[0],
        "p25": _percentile(s, 0.25),
        "median": statistics.median(s),
        "p75": _percentile(s, 0.75),
        "max": s[-1],
    }


def percentile_rank(value: float | None, peer_values: list[float | None]) -> float | None:
    """Where does the target's own multiple fall within the peer distribution, 0-100."""
    clean = sorted(v for v in peer_values if v is not None)
    if value is None or not clean:
        return None
    below = sum(1 for v in clean if v < value)
    equal = sum(1 for v in clean if v == value)
    return 100.0 * (below + 0.5 * equal) / len(clean)


def implied_valuation(
    target: dict,
    target_multiples: dict,
    peer_distributions: dict[str, dict],
) -> dict:
    """Apply peer-median (and p25/p75) multiples to the target's own metrics
    to produce an implied enterprise/equity value range per multiple."""
    results = {}
    net_debt = target.get("net_debt")

    for mult_name, denom_field in MULTIPLE_DENOMINATORS.items():
        dist = peer_distributions.get(mult_name, {})
        denom_value = target.get(denom_field)
        if denom_value is None or denom_value <= 0 or dist.get("median") is None:
            results[mult_name] = {"implied_low": None, "implied_mid": None, "implied_high": None, "basis": denom_field, "note": "unavailable: missing target denominator or empty peer distribution"}
            continue

        low_mult, mid_mult, high_mult = dist["p25"], dist["median"], dist["p75"]
        implied = {}
        for label, m in (("implied_low", low_mult), ("implied_mid", mid_mult), ("implied_high", high_mult)):
            if m is None:
                implied[label] = None
                continue
            raw_value = m * denom_value
            if mult_name in EV_BASED:
                if net_debt is None:
                    implied[label] = None
                    continue
                implied[label] = raw_value - net_debt  # EV -> equity value
            else:
                implied[label] = raw_value  # already equity value (PE, PB)
        implied["basis"] = denom_field
        results[mult_name] = implied

    return {"implied_equity_value_by_multiple": results}
