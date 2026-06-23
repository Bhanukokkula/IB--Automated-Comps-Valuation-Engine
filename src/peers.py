"""Peer-similarity model — the intellectual core of the engine.

Method:
  1. Sector is a HARD constraint. SIC codes are far more granular than a
     banker's mental model of "sector" (e.g. 3571 Electronic Computers and
     3674 Semiconductors are different SIC codes but often comped together),
     so SIC codes are bucketed into ~14 broad sector groups below. This
     mapping is curated by hand against the SIC codes actually present in
     data/universe.csv — it is a judgment call, not an official taxonomy,
     and is the single biggest lever on peer quality. Document disagreements
     openly rather than pretending this is objective.
  2. Within a sector bucket, peers are ranked by a weighted Euclidean
     distance over a standardized (z-scored within the sector bucket)
     feature vector: size, profitability, growth, leverage. Every distance
     and every feature value is inspectable — nothing is hidden inside a
     black-box score.

Known failure modes (be honest about these, don't bury them):
  - Conglomerates and multi-segment companies get one SIC code for their
    whole business, so a company that's 40% of its revenue in an unrelated
    segment will still be bucketed (and possibly comped) on its primary SIC.
  - Companies mid-transformation (a "growth" name with collapsing margins,
    or a legacy name pivoting business mix) will look like statistical
    outliers within their own sector bucket and get ranked as poor peers
    even though qualitatively they belong there.
  - Size outliers inside a sector (e.g. the one $3T company in a bucket of
    $50B companies) will dominate the standardization and can make every
    other company in the bucket look artificially "similar" to each other
    and "dissimilar" to the giant, even if all of them are legitimate
    peers from a business standpoint.
"""
import math

SIC_TO_SECTOR = {
    # Energy
    1311: "Energy", 1389: "Energy", 2911: "Energy",
    # Materials
    1000: "Materials", 1040: "Materials", 2670: "Materials",
    2810: "Materials", 2821: "Materials", 2860: "Materials",
    2851: "Materials", 3312: "Materials",
    # Consumer Staples
    2000: "Consumer Staples", 2040: "Consumer Staples", 2060: "Consumer Staples",
    2080: "Consumer Staples", 2111: "Consumer Staples", 2840: "Consumer Staples",
    2842: "Consumer Staples", 2844: "Consumer Staples", 5140: "Consumer Staples",
    5411: "Consumer Staples",
    # Consumer Discretionary, split into finer sub-buckets — an earlier
    # single "Consumer Discretionary" bucket lumped apparel makers,
    # restaurants, hotels, and general retail together and scored badly on
    # validation (NKE 0% agreement, MCD 25%) against hand-labeled peer sets
    # because a restaurant chain and a sneaker maker are not real comps.
    # Apparel & Footwear
    2300: "Apparel & Footwear", 2320: "Apparel & Footwear",
    3021: "Apparel & Footwear", 5651: "Apparel & Footwear",
    # Restaurants & Leisure
    5810: "Restaurants & Leisure", 5812: "Restaurants & Leisure",
    7011: "Restaurants & Leisure", 7841: "Restaurants & Leisure",
    7990: "Restaurants & Leisure",
    # General & Specialty Retail
    5200: "General & Specialty Retail", 5211: "General & Specialty Retail",
    5331: "General & Specialty Retail", 5731: "General & Specialty Retail",
    5912: "General & Specialty Retail", 5961: "General & Specialty Retail",
    5990: "General & Specialty Retail",
    # Health Care (pharma/biotech/devices)
    2834: "Health Care", 2836: "Health Care", 3841: "Health Care",
    # Health Care Payers (insurance-like, kept distinct from pharma)
    6324: "Health Care Payers",
    # Automotive
    3711: "Automotive",
    # Aerospace & Defense
    3721: "Aerospace & Defense", 3724: "Aerospace & Defense",
    3730: "Aerospace & Defense", 3760: "Aerospace & Defense",
    3812: "Aerospace & Defense",
    # Industrials / Capital Goods
    3490: "Industrials", 3523: "Industrials", 3531: "Industrials",
    3559: "Industrials", 3560: "Industrials", 3590: "Industrials",
    3600: "Industrials", 3663: "Industrials", 3827: "Industrials",
    # Transportation
    4011: "Transportation", 4210: "Transportation", 4512: "Transportation",
    4513: "Transportation", 4700: "Transportation",
    # Technology Hardware & Semiconductors
    3570: "Tech Hardware & Semis", 3571: "Tech Hardware & Semis",
    3576: "Tech Hardware & Semis", 3577: "Tech Hardware & Semis",
    3674: "Tech Hardware & Semis",
    # Software & IT Services
    7370: "Software & IT Services", 7371: "Software & IT Services",
    7372: "Software & IT Services", 7373: "Software & IT Services",
    7374: "Software & IT Services", 7380: "Software & IT Services",
    7389: "Software & IT Services",
    # Telecom & Media
    4812: "Telecom & Media", 4813: "Telecom & Media",
    4832: "Telecom & Media", 4841: "Telecom & Media",
    # Utilities
    4911: "Utilities", 4931: "Utilities",
    # Financials - Banks
    6021: "Banks", 6022: "Banks",
    # Financials - Capital Markets
    6199: "Capital Markets", 6200: "Capital Markets", 6211: "Capital Markets",
    # Real Estate
    6798: "Real Estate", 7340: "Real Estate",
    # Services - Consumer Credit
    7320: "Business Services",
}

# A distance computed over only 1-2 of 7 features can look deceptively
# small (e.g. two huge-market-cap companies will look "close" on
# log_market_cap alone even with zero other data in common). Require at
# least this many features present on both sides before a company is
# allowed to rank ahead of peers with fuller data -- thin-data candidates
# are still returned, just sorted after fully-compared ones and flagged.
MIN_FEATURES_FOR_FULL_RANKING = 4

FEATURES = [
    "log_revenue",
    "log_market_cap",
    "log_total_assets",
    "ebitda_margin",
    "net_margin",
    "revenue_cagr",
    "net_debt_to_ebitda",
]

DEFAULT_WEIGHTS = {
    "log_revenue": 1.5,
    "log_market_cap": 1.5,
    "log_total_assets": 1.0,
    "ebitda_margin": 1.0,
    "net_margin": 1.0,
    "revenue_cagr": 0.75,
    "net_debt_to_ebitda": 0.75,
}


def sector_for(sic: int | str | None) -> str:
    if sic is None:
        return "Unclassified"
    try:
        sic_int = int(sic)
    except (ValueError, TypeError):
        return "Unclassified"
    return SIC_TO_SECTOR.get(sic_int, "Unclassified")


def _safe_log(x: float | None) -> float | None:
    if x is None or x <= 0:
        return None
    return math.log(x)


def build_feature_vector(company: dict) -> dict:
    return {
        "log_revenue": _safe_log(company.get("revenue")),
        "log_market_cap": _safe_log(company.get("market_cap")),
        "log_total_assets": _safe_log(company.get("total_assets")),
        "ebitda_margin": company.get("ebitda_margin"),
        "net_margin": company.get("net_margin"),
        "revenue_cagr": company.get("revenue_cagr"),
        "net_debt_to_ebitda": company.get("net_debt_to_ebitda"),
    }


def _zscore_sector(companies: list[dict]) -> dict[str, dict[str, tuple[float, float]]]:
    """Compute per-feature (mean, std) within each sector bucket, ignoring Nones."""
    stats: dict[str, dict[str, tuple[float, float]]] = {}
    by_sector: dict[str, list[dict]] = {}
    for c in companies:
        by_sector.setdefault(c["sector"], []).append(c["features"])

    for sector, feats_list in by_sector.items():
        stats[sector] = {}
        for feat in FEATURES:
            vals = [f[feat] for f in feats_list if f.get(feat) is not None]
            if len(vals) < 2:
                stats[sector][feat] = (0.0, 1.0)  # degenerate: no standardization possible
                continue
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = math.sqrt(var) if var > 0 else 1.0
            stats[sector][feat] = (mean, std)
    return stats


def rank_peers(
    target_ticker: str,
    companies: list[dict],
    weights: dict[str, float] | None = None,
    top_n: int = 10,
) -> dict:
    """Return ranked peers for target_ticker within its sector bucket.

    Each company dict must already have 'sector' and 'features' keys
    (see build_feature_vector / sector_for).
    """
    weights = weights or DEFAULT_WEIGHTS
    by_ticker = {c["ticker"]: c for c in companies}
    target = by_ticker.get(target_ticker)
    if target is None:
        raise ValueError(f"{target_ticker} not found in company universe")

    sector = target["sector"]
    candidates = [c for c in companies if c["sector"] == sector and c["ticker"] != target_ticker]

    if not candidates:
        return {
            "target": target_ticker,
            "sector": sector,
            "peers": [],
            "warning": f"no other companies found in sector bucket '{sector}'",
        }

    stats = _zscore_sector(companies)[sector]
    target_z = _standardize(target["features"], stats)

    scored = []
    for c in candidates:
        c_z = _standardize(c["features"], stats)
        dist, n_used, missing = _weighted_distance(target_z, c_z, weights)
        scored.append(
            {
                "ticker": c["ticker"],
                "title": c.get("title"),
                "distance": dist,
                "features_compared": n_used,
                "features_missing": missing,
                "thin_data": n_used < MIN_FEATURES_FOR_FULL_RANKING,
                "feature_values": c["features"],
            }
        )

    # thin-data candidates (too few comparable features) are sorted after
    # fully-compared ones regardless of how small their raw distance looks
    scored.sort(key=lambda r: (r["thin_data"], r["distance"] is None, r["distance"] if r["distance"] is not None else 0))
    return {
        "target": target_ticker,
        "sector": sector,
        "sector_size": len(candidates) + 1,
        "peers": scored[:top_n],
    }


def _standardize(features: dict, stats: dict) -> dict:
    z = {}
    for feat in FEATURES:
        val = features.get(feat)
        if val is None:
            z[feat] = None
            continue
        mean, std = stats[feat]
        z[feat] = (val - mean) / std if std else 0.0
    return z


def _weighted_distance(z1: dict, z2: dict, weights: dict) -> tuple[float | None, int, list[str]]:
    """Weighted Euclidean distance over features present in BOTH vectors.
    Missing features are excluded from the distance (not zero-filled) and
    listed so a peer pick can be audited for how much data backed it."""
    sq_sum = 0.0
    weight_sum = 0.0
    n_used = 0
    missing = []
    for feat in FEATURES:
        v1, v2 = z1.get(feat), z2.get(feat)
        if v1 is None or v2 is None:
            missing.append(feat)
            continue
        w = weights.get(feat, 1.0)
        sq_sum += w * (v1 - v2) ** 2
        weight_sum += w
        n_used += 1
    if n_used == 0:
        return None, 0, missing
    return math.sqrt(sq_sum / weight_sum), n_used, missing
