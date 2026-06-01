"""
Scrape recent posts for each pilot IG handle via apidojo/instagram-scraper,
so we can later compute per-account baseline metrics (median views, etc.)
and compare our pilot videos against the creator's own norm.

Writes: analysis/account_baselines_raw.csv (one row per scraped post)

Cost: ~$0.0005/post * 30 posts * 55 handles = ~$0.83
"""

import os
import sys
import time
import re
import json
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = REPO_ROOT / "analysis"
CLIPS_CSV = REPO_ROOT / "data" / "raw" / "Viral_Micro_Dramas_campaign_report_2026-04-13.xlsx - All Clips.csv"
ROLLUP_CSV = ANALYSIS_DIR / "account_rollup.csv"
OUT_CSV = ANALYSIS_DIR / "account_baselines_raw.csv"

ACTOR_ID = "apidojo~instagram-scraper"
POSTS_PER_HANDLE = 30


def load_token() -> str:
    token = os.environ.get("APIFY_TOKEN")
    if token:
        return token
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("APIFY_TOKEN="):
                return line.split("=", 1)[1].strip()
    sys.exit("APIFY_TOKEN not found in env or .env file")


def gather_handles() -> list[str]:
    clips = pd.read_csv(CLIPS_CSV)
    clips["handle"] = (
        clips["Profile"]
        .str.extract(r"([^/]+)/?$")[0]
        .str.lower()
        .str.lstrip("@")
    )
    ig_handles = set(
        clips.loc[clips["Platform"] == "Instagram", "handle"].dropna()
    )

    rollup = pd.read_csv(ROLLUP_CSV)
    rollup_handles = set(
        rollup["profile"].dropna().str.lower().str.lstrip("@")
    )

    all_handles = sorted(ig_handles | rollup_handles)
    return all_handles


def run_actor(token: str, handles: list[str]) -> list[dict]:
    """Start an actor run synchronously and return dataset items."""
    # /reels URL targets video posts specifically — matches our pilot content
    # (all pilot videos are reels). Regular profile URL returns grid posts which
    # can include photos, which don't have the view-count field we need.
    profile_urls = [f"https://www.instagram.com/{h}/reels" for h in handles]
    payload = {
        "startUrls": profile_urls,
        "maxItems": len(handles) * POSTS_PER_HANDLE,
    }
    url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items?token={token}"
    total = len(handles) * POSTS_PER_HANDLE
    print(f"Starting actor run for {len(handles)} handles...")
    print(f"  maxItems={total}, budget ~${total * 0.0005:.2f}")
    t0 = time.time()
    resp = requests.post(url, json=payload, timeout=1800)
    elapsed = time.time() - t0
    print(f"  Finished in {elapsed:.0f}s, status {resp.status_code}")
    if resp.status_code >= 400:
        print(f"  Response body: {resp.text[:1000]}")
    resp.raise_for_status()
    return resp.json()


def normalize_rows(raw_items: list[dict]) -> pd.DataFrame:
    """Flatten the actor output to a consistent post-level CSV.

    Schema reference (apidojo/instagram-scraper, observed 2026-04-16):
      top-level: owner{username,fullName,followerCount,...}, code, url,
                 likeCount, commentCount, createdAt, isVideo, isPinned,
                 video{playCount,duration,...}, inputSource, caption
    """
    rows = []
    for item in raw_items:
        owner = item.get("owner") or {}
        video = item.get("video") or {}
        # inputSource lets us trace which profile URL this came from —
        # useful because IG posts can have multiple co-owners.
        input_src = (item.get("inputSource") or "")
        src_handle_match = re.search(r"instagram\.com/([^/?#]+)", input_src)
        src_handle = src_handle_match.group(1).lower() if src_handle_match else None

        rows.append({
            "requested_handle": src_handle,
            "owner_username": (owner.get("username") or "").lower() or None,
            "owner_full_name": owner.get("fullName"),
            "owner_follower_count": owner.get("followerCount"),
            "owner_post_count": owner.get("postCount"),
            "shortcode": item.get("code"),
            "url": item.get("url"),
            "type": item.get("type"),
            "created_at": item.get("createdAt"),
            "caption": (item.get("caption") or "")[:500],
            "likes": item.get("likeCount"),
            "comments": item.get("commentCount"),
            "views": video.get("playCount"),
            "duration": video.get("duration"),
            "is_video": item.get("isVideo"),
            "is_pinned": item.get("isPinned"),
            "is_carousel": item.get("isCarousel"),
            "is_paid_partnership": item.get("isPaidPartnership"),
        })
    return pd.DataFrame(rows)


def main() -> None:
    token = load_token()
    handles = gather_handles()
    print(f"Scraping {len(handles)} unique IG handles")

    items = run_actor(token, handles)
    print(f"Got {len(items)} items back")

    df = normalize_rows(items)
    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV} ({len(df)} rows, {df['owner_username'].nunique()} unique owners)")

    # Quick coverage report
    requested = set(handles)
    returned = set(df["owner_username"].dropna())
    missing = requested - returned
    extra = returned - requested
    print(f"\nCoverage:")
    print(f"  Requested handles: {len(requested)}")
    print(f"  Handles with posts returned: {len(returned & requested)}")
    print(f"  Missing (0 posts returned): {len(missing)}")
    if missing:
        print(f"    {sorted(missing)[:20]}")
    if extra:
        print(f"  Unexpected owners in output: {len(extra)}")


if __name__ == "__main__":
    main()
