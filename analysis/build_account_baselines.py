"""
Build per-account baselines from scraped recent posts.

Takes analysis/account_baselines_raw.csv (from scrape_account_baselines.py),
excludes any posts that are part of the pilot (by shortcode), and computes
per-account medians and means for views / likes / comments.

Writes: analysis/account_baselines.csv (one row per handle)

Downstream: the dashboard joins on `profile` and shows
    (pilot_median_views / baseline_median_views)
so each account's pilot videos can be benchmarked against that creator's
own usual performance, not against cross-account averages.
"""

import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = REPO_ROOT / "analysis"
CLIPS_CSV = REPO_ROOT / "data" / "raw" / "Viral_Micro_Dramas_campaign_report_2026-04-13.xlsx - All Clips.csv"
RAW_CSV = ANALYSIS_DIR / "account_baselines_raw.csv"
OUT_CSV = ANALYSIS_DIR / "account_baselines.csv"


def extract_shortcode(url: str | float) -> str | None:
    if pd.isna(url):
        return None
    m = re.search(r"(?:reel|p|tv)/([^/?#]+)", str(url))
    return m.group(1) if m else None


def main() -> None:
    raw = pd.read_csv(RAW_CSV)
    pilot_clips = pd.read_csv(CLIPS_CSV)

    pilot_shortcodes = set(
        pilot_clips["URL"].dropna().map(extract_shortcode).dropna()
    )
    print(f"Pilot shortcodes to exclude: {len(pilot_shortcodes)}")

    before = len(raw)
    raw = raw[~raw["shortcode"].isin(pilot_shortcodes)].copy()
    print(f"Dropped {before - len(raw)} posts that were pilot videos")

    # Only videos — this is what we care about for views comparison. IG
    # profile grids can include photo posts which have no view count.
    raw = raw[raw["is_video"].astype(str).str.lower() == "true"].copy()
    print(f"After is_video filter: {len(raw)} posts")

    # Exclude pinned posts too — those are creator-curated hero content
    # and distort medians upward. Baseline should reflect typical posts.
    raw = raw[raw["is_pinned"].astype(str).str.lower() != "true"].copy()
    print(f"After excluding pinned: {len(raw)} posts")

    raw["views"] = pd.to_numeric(raw["views"], errors="coerce")
    raw["likes"] = pd.to_numeric(raw["likes"], errors="coerce")
    raw["comments"] = pd.to_numeric(raw["comments"], errors="coerce")

    baselines = (
        raw.groupby("requested_handle", dropna=True)
        .agg(
            baseline_n_posts=("shortcode", "count"),
            baseline_median_views=("views", "median"),
            baseline_mean_views=("views", "mean"),
            baseline_median_likes=("likes", "median"),
            baseline_median_comments=("comments", "median"),
            baseline_follower_count=("owner_follower_count", "max"),
            baseline_post_count=("owner_post_count", "max"),
            baseline_earliest=("created_at", "min"),
            baseline_latest=("created_at", "max"),
        )
        .reset_index()
        .rename(columns={"requested_handle": "profile"})
    )

    # Strip leading @ for consistency with rollup/v_videos
    baselines["profile"] = baselines["profile"].str.lstrip("@")
    baselines = baselines.sort_values("baseline_median_views", ascending=False)

    baselines.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV} ({len(baselines)} accounts)")
    print("\nTop 10 by baseline median views:")
    print(baselines[["profile", "baseline_n_posts", "baseline_median_views", "baseline_follower_count"]].head(10).to_string(index=False))
    print("\nAccounts with zero video posts (no baseline):")
    requested = set(raw["requested_handle"].dropna()) | set(pd.read_csv(RAW_CSV)["requested_handle"].dropna())
    no_baseline = requested - set(baselines["profile"])
    if no_baseline:
        print(f"  {sorted(no_baseline)}")


if __name__ == "__main__":
    main()
