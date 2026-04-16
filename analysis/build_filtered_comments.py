"""Filter contaminated comments from the labeled NLP output.

The original `comment_audience_analysis.py` pipeline did not use the Apify
`is_created_by_media_owner` flag or the commenter `username` when labeling.
As a result, creator-posted SEO/promo spam got labeled as high-intent
audience reactions. This script joins the labeled output back to the raw
Apify scrape on (input_url, text) to recover those fields, then filters
per three rules:

    rule_1: drop rows where any raw occurrence was is_created_by_media_owner
    rule_3: drop rows whose text is duplicated as a long comment (>80 chars)
            across 2+ distinct videos (cross-video spam)
    rule_4: drop rows whose commenter username matches any known creator
            account in All Clips (cross-creator promo)

Writes:
    analysis/analysis_comment_level_filtered.csv
    analysis/filter_report.md  (counts, rule breakdown, sample drops)

Run from project root:  python analysis/build_filtered_comments.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = Path(__file__).resolve().parent

LABELED_PATH = PROJECT_ROOT / "analysis_comment_level.csv"
RAW_PATH = PROJECT_ROOT / "apify_full_results_datadoping.json"
CLIPS_PATH = PROJECT_ROOT / (
    "Viral_Micro_Dramas_campaign_report_2026-04-13.xlsx - All Clips.csv"
)

OUT_PATH = ANALYSIS_DIR / "analysis_comment_level_filtered.csv"
REPORT_PATH = ANALYSIS_DIR / "filter_report.md"
OWNERS_PATH = ANALYSIS_DIR / "apify_post_owners.csv"

LONG_COMMENT_CHARS = 80


def load_raw_aggregated() -> pd.DataFrame:
    """Raw Apify comments collapsed to one row per (input_url, text).

    Aggregates the per-row fields we need: any_owner (True if *any* occurrence
    of that text on that post is flagged as owner), usernames (sorted unique).
    """
    with RAW_PATH.open("r", encoding="cp1252") as f:
        raw = json.load(f)
    raw_df = pd.DataFrame(raw)
    raw_df = raw_df[raw_df["content_type"].isin(["comment", "reply"])].copy()
    return (
        raw_df.groupby(["input_url", "text"], dropna=False)
        .agg(
            any_owner=(
                "is_created_by_media_owner",
                lambda s: bool(s.fillna(False).any()),
            ),
            usernames=(
                "username",
                lambda s: sorted(set(s.dropna().astype(str))),
            ),
            n_raw_occurrences=("comment_id", "size"),
        )
        .reset_index()
    )


def load_creator_handles() -> set[str]:
    """Lowercased handles of every account that posted a video.

    Union of (a) the registered roster in All Clips, (b) any poster username
    discovered from the Apify caption/owner rows. Rule 4 (commenter matches
    creator handle) should apply to both — both groups are paid creators in
    the campaign, just tracked in different spreadsheets.
    """
    clips = pd.read_csv(CLIPS_PATH)
    roster = (
        clips["Profile"]
        .dropna()
        .str.extract(r"/([^/]+)/?$")[0]
        .str.lower()
        .dropna()
    )
    apify_owners = load_apify_post_owners()
    return set(roster).union(
        apify_owners["username"].dropna().str.lower()
    )


def load_apify_post_owners() -> pd.DataFrame:
    """One row per post: who posted it, per the raw Apify caption data.

    Instagram's caption row has is_created_by_media_owner=True and names the
    poster's username — authoritative source for the post owner. Also writes
    the result to apify_post_owners.csv so build_workspace.sql can read it
    and backfill profiles that are missing from All Clips.
    """
    with RAW_PATH.open("r", encoding="cp1252") as f:
        raw = json.load(f)
    rows = []
    for r in raw:
        if r.get("content_type") != "caption":
            continue
        url = r.get("input_url")
        username = r.get("username")
        full_name = (r.get("user") or {}).get("full_name")
        if url and username:
            rows.append(
                {"input_url": url, "username": username, "full_name": full_name}
            )
    df = pd.DataFrame(rows).drop_duplicates(subset=["input_url"])
    df.to_csv(OWNERS_PATH, index=False)
    return df


def first_username(usernames) -> str | None:
    if isinstance(usernames, list) and usernames:
        return usernames[0]
    return None


def main() -> None:
    labels = pd.read_csv(LABELED_PATH)
    raw_agg = load_raw_aggregated()
    creators = load_creator_handles()

    merged = labels.merge(
        raw_agg,
        left_on=["input_url", "text_raw"],
        right_on=["input_url", "text"],
        how="left",
    )
    merged = merged.drop(columns=["text"], errors="ignore")

    # Rule 1: owner-posted.
    merged["rule_1_owner"] = merged["any_owner"].fillna(False).astype(bool)

    # Rule 3: text appears as a long comment on >= 2 distinct videos.
    text_col = merged["text_raw"].fillna("")
    long_mask = text_col.str.len() >= LONG_COMMENT_CHARS
    spread = (
        merged.loc[long_mask]
        .groupby("text_raw")["input_url"]
        .nunique()
        .rename("n_videos_for_long_text")
    )
    cross_video_long_texts = set(spread[spread >= 2].index)
    merged["rule_3_cross_video_long_dup"] = (
        long_mask & text_col.isin(cross_video_long_texts)
    )

    # Rule 4: commenter username matches a known creator handle.
    merged["primary_username"] = (
        merged["usernames"].apply(first_username).astype("string").str.lower()
    )
    merged["rule_4_creator_commenter"] = (
        merged["primary_username"].fillna("").isin(creators)
    )

    merged["drop_any"] = (
        merged["rule_1_owner"]
        | merged["rule_3_cross_video_long_dup"]
        | merged["rule_4_creator_commenter"]
    )

    filtered = merged[~merged["drop_any"]].copy()

    # Write filtered labeled output (preserve original label columns).
    label_cols = list(labels.columns)
    extra_cols = [
        "primary_username",
        "any_owner",
        "rule_1_owner",
        "rule_3_cross_video_long_dup",
        "rule_4_creator_commenter",
    ]
    out = filtered[label_cols + extra_cols]
    out.to_csv(OUT_PATH, index=False)

    # Report.
    def count(mask: pd.Series) -> int:
        return int(mask.sum())

    lines = [
        "# Comment filter report",
        "",
        f"- Input labeled rows: **{len(labels)}**",
        f"- Rows matched to raw Apify scrape: **{int(merged['any_owner'].notna().sum())}**",
        f"- Rows with no raw match (mostly empty text): "
        f"**{int(merged['any_owner'].isna().sum())}**",
        "",
        "## Rule hits (non-exclusive — a single row can match multiple rules)",
        f"- Rule 1 (`is_created_by_media_owner=True`): **{count(merged['rule_1_owner'])}**",
        f"- Rule 3 (long text duplicated across ≥2 videos, ≥{LONG_COMMENT_CHARS} chars): **{count(merged['rule_3_cross_video_long_dup'])}**",
        f"- Rule 4 (commenter username matches a known creator handle): **{count(merged['rule_4_creator_commenter'])}**",
        f"- Any rule: **{count(merged['drop_any'])}**",
        "",
        f"- Surviving rows after filter: **{len(filtered)}** "
        f"({len(filtered) / len(labels) * 100:.1f}% of input)",
        "",
        "## Top offender accounts (by rows dropped under any rule)",
    ]
    top_offenders = (
        merged[merged["drop_any"]]
        .groupby("primary_username", dropna=False)
        .size()
        .sort_values(ascending=False)
        .head(15)
    )
    for user, n in top_offenders.items():
        lines.append(f"- @{user}: {n}")

    lines.extend(
        [
            "",
            "## Sample dropped rows",
            "",
            "| user | rule(s) | input_url | text (first 80 chars) |",
            "| --- | --- | --- | --- |",
        ]
    )
    sample = merged[merged["drop_any"]].head(15)
    for _, r in sample.iterrows():
        rules = []
        if r["rule_1_owner"]:
            rules.append("1")
        if r["rule_3_cross_video_long_dup"]:
            rules.append("3")
        if r["rule_4_creator_commenter"]:
            rules.append("4")
        txt = (str(r["text_raw"])[:80] or "").replace("|", "\\|").replace(
            "\n", " "
        )
        lines.append(
            f"| @{r['primary_username']} | {','.join(rules)} | "
            f"{r['input_url']} | {txt} |"
        )

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ok] wrote {OUT_PATH.relative_to(PROJECT_ROOT)}  "
          f"({len(filtered)} rows, dropped {count(merged['drop_any'])})")
    print(f"[ok] wrote {REPORT_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
