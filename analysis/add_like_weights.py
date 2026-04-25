"""Join Apify `like_count` onto the filtered comment CSV and compute weights.

Writes analysis_comment_level_filtered_weighted.csv — same schema as the
filtered CSV plus two columns:

- like_count: raw int from Apify (0 for null-likes are DROPPED, per policy)
- weight:     log1p(like_count) + 1, halved for replies

Policy decisions (confirmed 2026-04-23):
- Weighting function: log1p(likes) + 1
- Time normalization: none (all videos scraped within a narrow window)
- Null likes: drop the row
- Replies: half weight (reply-as-attention is weaker signal than top-comment)

This script does NOT modify the source filtered CSV or any downstream tables.
It's an additive experiment artifact for compare_weighted_vs_unweighted.py.

Usage:
  python analysis/add_like_weights.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = Path(__file__).resolve().parent
APIFY_JSON = PROJECT_ROOT / "apify_full_results_datadoping.json"
FILTERED_CSV = ANALYSIS_DIR / "analysis_comment_level_filtered.csv"
OUT_CSV = ANALYSIS_DIR / "analysis_comment_level_filtered_weighted.csv"


def load_apify_like_counts() -> dict[int, int | None]:
    """Map Apify array index → like_count (or None when missing)."""
    with APIFY_JSON.open("r", encoding="utf-8", errors="replace") as f:
        data = json.load(f)
    return {i: r.get("like_count") for i, r in enumerate(data)}


def main() -> int:
    likes_by_idx = load_apify_like_counts()
    print(f"Loaded {len(likes_by_idx)} Apify records.")

    df = pd.read_csv(FILTERED_CSV, dtype=str, keep_default_na=False)
    n_in = len(df)
    print(f"Filtered rows: {n_in}")

    # row_id = f"r{idx}" from comment_audience_analysis.filter_rows
    df["apify_idx"] = df["row_id"].str.slice(1).astype(int)
    df["like_count"] = df["apify_idx"].map(likes_by_idx)

    # Policy: drop rows with null like_count.
    n_null = int(df["like_count"].isna().sum())
    df = df[df["like_count"].notna()].copy()
    df["like_count"] = df["like_count"].astype(int)
    print(f"Dropped {n_null} rows with null like_count "
          f"({n_null / n_in * 100:.1f}%). Remaining: {len(df)}.")

    # Base weight: log1p(likes) + 1. Then half-weight replies.
    base = df["like_count"].apply(lambda x: math.log1p(x) + 1.0)
    is_reply = df["content_type"] == "reply"
    df["weight"] = base.where(~is_reply, base * 0.5)

    # Report
    print()
    print("Weight distribution:")
    print(df["weight"].describe().to_string())
    print()
    print("Rows by content type:")
    print(df.groupby("content_type")["weight"].agg(["count", "sum", "mean"]).to_string())
    print()
    top = df.nlargest(10, "weight")[["like_count", "content_type",
                                     "text_raw", "weight"]]
    print("Top 10 by weight:")
    for _, r in top.iterrows():
        txt = str(r["text_raw"])[:70]
        print(f"  likes={r['like_count']:>4}  w={r['weight']:5.2f}  "
              f"[{r['content_type']}]  {txt!r}")

    df = df.drop(columns=["apify_idx"])
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\nWrote {OUT_CSV.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
