"""Compare multiple model cards and output a grid comparison artifact."""

import argparse
import json
from pathlib import Path
import pandas as pd

def parse_card(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Model card not found: {path}")
    card = json.loads(path.read_text())
    
    # Extract key metrics
    meta = card.get("meta", {}).get("split", {})
    agg = card.get("aggregate", {})
    sections = card.get("sections", {})
    
    # Section metrics
    b_metrics = {m["name"]: m["value"] for m in sections.get("B", {}).get("metrics", [])}
    c_metrics = {m["name"]: m["value"] for m in sections.get("C", {}).get("metrics", [])}
    e_metrics = {m["name"]: m["value"] for m in sections.get("E", {}).get("metrics", [])}
    
    d_metrics = {m["name"]: m["value"] for m in sections.get("D", {}).get("metrics", [])}
    
    # D subscores
    d_binary = sections.get("D", {}).get("rubric_scores", {}).get("D_binary", "N/A")
    d_mag = sections.get("D", {}).get("rubric_scores", {}).get("D_magnitude", "N/A")

    top10_lift = d_metrics.get("Abin_top10_lift", "N/A")
    if top10_lift != "N/A":
        top10_lift = round(top10_lift, 2)

    return {
        "Model ID": card.get("model_id", path.stem),
        "Score (out of 100)": agg.get("total", "N/A"),
        "AUC": round(b_metrics.get("roc_auc", 0), 3) if "roc_auc" in b_metrics else "N/A",
        "PR-AUC": round(b_metrics.get("pr_auc", 0), 3) if "pr_auc" in b_metrics else "N/A",
        "ECE (Calibration)": round(c_metrics.get("ece", 0), 4) if "ece" in c_metrics else "N/A",
        "Threshold Precision (T=0.6)": round(e_metrics.get("precision_at_t=0.6", 0), 3) if "precision_at_t=0.6" in e_metrics else "N/A",
        "Ranker Top-10 Lift": top10_lift,
        "Ranker Band (Bin/Mag)": f"{d_binary} / {d_mag}",
        "Val Prevalence": round(meta.get("prevalence", 0), 3) if "prevalence" in meta else "N/A"
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cards", nargs="+", required=True, help="Paths to model_card.json files")
    parser.add_argument("--output", default="grid_comparison.md", help="Output markdown artifact path")
    args = parser.parse_args()

    results = []
    for card_path in args.cards:
        results.append(parse_card(Path(card_path)))

    df = pd.DataFrame(results)
    
    md_table = df.to_markdown(index=False)
    
    out_path = Path(args.output)
    out_path.write_text(f"# Model Grid Comparison\n\n{md_table}\n")
    print(f"Wrote comparison to {out_path}")

if __name__ == "__main__":
    main()
