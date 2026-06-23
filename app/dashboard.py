"""Streamlit dashboard for the comps & valuation engine. Reads only the
static snapshot in data/snapshot/ — no live API calls, ever."""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from peers import rank_peers, FEATURES  # noqa: E402
from valuation import peer_multiple_distribution, percentile_rank, implied_valuation  # noqa: E402

st.set_page_config(page_title="Comps & Valuation Engine", layout="wide")


@st.cache_data
def load_snapshot():
    companies = json.loads((ROOT / "data" / "snapshot" / "companies.json").read_text())
    meta = json.loads((ROOT / "data" / "snapshot" / "meta.json").read_text())
    return companies, meta


@st.cache_data
def load_limitations():
    path = ROOT / "LIMITATIONS.md"
    return path.read_text() if path.exists() else "LIMITATIONS.md not found."


companies, meta = load_snapshot()
by_ticker = {c["ticker"]: c for c in companies}

st.title("Automated Comps & Valuation Engine")
st.caption(f"Data as of {meta['snapshot_date']} — static snapshot, {meta['companies_built']} companies, zero live API calls.")

tab_comps, tab_limits = st.tabs(["Comps & Valuation", "Limitations"])

with tab_comps:
    col_select, _ = st.columns([1, 3])
    with col_select:
        tickers_sorted = sorted(by_ticker.keys())
        default_idx = tickers_sorted.index("AAPL") if "AAPL" in tickers_sorted else 0
        target_ticker = st.selectbox("Target company", tickers_sorted, index=default_idx)

    target = by_ticker[target_ticker]
    st.subheader(f"{target['title']} ({target_ticker}) — {target['sector']}")

    if target["flags"]:
        st.warning("Data flags for this company: " + ", ".join(target["flags"]))

    metric_cols = st.columns(5)
    metric_labels = [
        ("Revenue", target["revenue"]),
        ("EBITDA", target["ebitda"]),
        ("Market Cap", target["market_cap"]),
        ("Enterprise Value", target["enterprise_value"]),
        ("Net Debt / EBITDA", target["net_debt_to_ebitda"]),
    ]
    for col, (label, val) in zip(metric_cols, metric_labels):
        if val is None:
            col.metric(label, "n/a")
        elif label == "Net Debt / EBITDA":
            col.metric(label, f"{val:.2f}x")
        else:
            col.metric(label, f"${val/1e9:,.2f}B")

    st.markdown("### Peer set")
    ranking = rank_peers(target_ticker, companies, top_n=15)

    if ranking.get("warning"):
        st.error(ranking["warning"])
        peer_tickers_default = []
    else:
        peer_rows = []
        for p in ranking["peers"]:
            row = {
                "Ticker": p["ticker"],
                "Company": p["title"],
                "Distance": round(p["distance"], 3) if p["distance"] is not None else None,
                "Features compared": f"{p['features_compared']}/{len(FEATURES)}",
                "Thin data": p["thin_data"],
            }
            for feat in FEATURES:
                row[feat] = p["feature_values"].get(feat)
            peer_rows.append(row)
        peer_df = pd.DataFrame(peer_rows)
        st.caption(
            f"Sector bucket: **{ranking['sector']}** ({ranking['sector_size']} companies total in this snapshot). "
            "Ranked by standardized weighted distance — lower is more similar. "
            "Companies with too few comparable features (< 4 of 7) are pushed to the bottom and flagged "
            "'Thin data', since a distance computed from 1-2 features can look deceptively small."
        )
        st.dataframe(peer_df, use_container_width=True, hide_index=True)
        peer_tickers_default = [p["ticker"] for p in ranking["peers"][:8]]

    st.markdown("**Override the peer set** (analysts always have the final say — this is a credibility feature, not a gap):")
    same_sector_tickers = [c["ticker"] for c in companies if c["sector"] == target["sector"] and c["ticker"] != target_ticker]
    selected_peers = st.multiselect(
        "Peers used for valuation below",
        options=sorted(set(same_sector_tickers) | set(peer_tickers_default)),
        default=peer_tickers_default,
    )

    if not selected_peers:
        st.info("Select at least one peer to compute multiples and valuation.")
    else:
        peer_companies = [by_ticker[t] for t in selected_peers]

        st.markdown("### Multiples table")
        mult_names = ["ev_revenue", "ev_ebitda", "ev_ebit", "pe", "pb"]
        mult_rows = []
        for c in peer_companies + [target]:
            row = {"Ticker": c["ticker"], "Company": c["title"], "Is Target": c["ticker"] == target_ticker}
            for m in mult_names:
                row[m] = c["multiples"].get(m)
            mult_rows.append(row)
        mult_df = pd.DataFrame(mult_rows)

        def highlight_target(row):
            return ["background-color: #fff3cd" if row["Is Target"] else "" for _ in row]

        st.dataframe(
            mult_df.style.apply(highlight_target, axis=1),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### Peer distribution & target percentile")
        dist_rows = []
        peer_distributions = {}
        for m in mult_names:
            peer_vals = [c["multiples"].get(m) for c in peer_companies]
            dist = peer_multiple_distribution(peer_vals)
            peer_distributions[m] = dist
            pct = percentile_rank(target["multiples"].get(m), peer_vals)
            dist_rows.append({
                "Multiple": m,
                "Peer N (usable)": dist["n"],
                "Peer N (excluded)": dist["n_excluded"],
                "Min": dist["min"], "P25": dist["p25"], "Median": dist["median"],
                "P75": dist["p75"], "Max": dist["max"],
                "Target value": target["multiples"].get(m),
                "Target percentile": pct,
            })
        st.dataframe(pd.DataFrame(dist_rows), use_container_width=True, hide_index=True)

        st.markdown("### Implied valuation — football field")
        val_result = implied_valuation(target, target["multiples"], peer_distributions)
        ranges = val_result["implied_equity_value_by_multiple"]

        chart_rows = []
        for m, r in ranges.items():
            if r.get("implied_low") is None or r.get("implied_high") is None:
                continue
            chart_rows.append({
                "Multiple": m,
                "Low": r["implied_low"] / 1e9,
                "Mid": r["implied_mid"] / 1e9,
                "High": r["implied_high"] / 1e9,
            })

        if not chart_rows:
            st.warning("No implied valuation could be computed — peer distributions or target denominators are unavailable. See flags above.")
        else:
            import matplotlib.pyplot as plt

            chart_df = pd.DataFrame(chart_rows)
            fig, ax = plt.subplots(figsize=(8, 0.6 * len(chart_df) + 1))
            y_pos = range(len(chart_df))
            ax.barh(y_pos, chart_df["High"] - chart_df["Low"], left=chart_df["Low"], height=0.5, color="#4a90d9")
            ax.scatter(chart_df["Mid"], y_pos, color="black", zorder=3, s=40)
            ax.set_yticks(list(y_pos))
            ax.set_yticklabels(chart_df["Multiple"])
            ax.set_xlabel("Implied equity value ($B)")
            ax.invert_yaxis()
            fig.tight_layout()
            st.pyplot(fig)
            st.caption("Bar = P25–P75 of peer multiples applied to target metrics. Black dot = peer median (point estimate). EV-based multiples are converted to equity value by subtracting target net debt.")

        excluded = target.get("multiples_excluded", [])
        if excluded:
            st.caption("Multiples excluded for the target: " + "; ".join(excluded))

with tab_limits:
    st.markdown(load_limitations())
