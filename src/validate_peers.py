"""Soft validation of the peer model against hand-labeled reference peer
sets for a handful of well-known names. There is no ground truth for "the
correct comp set" — this is a sanity check, not a benchmark, and the
agreement rate is reported honestly including the misses.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from peers import rank_peers  # noqa: E402

ROOT = Path(__file__).parent.parent

# Hand-picked by the author using general market knowledge of who's
# considered a "real" comp for each name, not derived from the model.
REFERENCE_PEER_SETS = {
    "JPM": {"BAC", "WFC", "C", "USB", "PNC", "TFC", "COF"},
    "XOM": {"CVX", "COP", "EOG", "OXY", "MPC", "PSX", "VLO", "SLB", "HAL"},
    "KO": {"PEP"},
    "NKE": {"LULU", "DECK", "VFC", "RL"},
    "MCD": {"SBUX", "YUM", "CMG", "DPZ"},
    "HD": {"LOW", "TGT", "TJX", "ROST"},
    "AAL": {"DAL", "UAL", "LUV"},
    "SO": {"DUK", "NEE", "AEP", "EXC", "D", "ED", "XEL", "WEC"},
}


def main():
    companies = json.loads((ROOT / "data" / "snapshot" / "companies.json").read_text())
    results = []
    for target, ref_set in REFERENCE_PEER_SETS.items():
        try:
            ranking = rank_peers(target, companies, top_n=10)
        except ValueError:
            results.append({"target": target, "error": "target not in snapshot"})
            continue
        model_peers = {p["ticker"] for p in ranking["peers"]}
        overlap = model_peers & ref_set
        agreement_rate = len(overlap) / len(ref_set) if ref_set else None
        results.append({
            "target": target,
            "sector": ranking["sector"],
            "reference_set": sorted(ref_set),
            "model_top10": sorted(model_peers),
            "overlap": sorted(overlap),
            "missed_by_model": sorted(ref_set - model_peers),
            "agreement_rate": agreement_rate,
        })

    overall = [r["agreement_rate"] for r in results if r.get("agreement_rate") is not None]
    summary = {"per_target": results, "mean_agreement_rate": sum(overall) / len(overall) if overall else None}
    print(json.dumps(summary, indent=2))

    out_path = ROOT / "data" / "snapshot" / "peer_validation.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
