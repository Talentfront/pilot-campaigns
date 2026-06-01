"""Regenerate analysis_summary_filtered.md from the post-filter, post-relabel data.

The original data/processed/analysis_summary.md was written by
comment_audience_analysis.py on the raw Apify scrape, before the spam
filter was built. This script produces a replacement that:
  - reads the filtered comment CSV (821 surviving rows)
  - applies the theme relabel mapping (junk themes -> MIXED bucket)
  - joins the recluster audit for per-theme cohesion
  - recomputes Run Metrics, Winners, Laggards, Top Themes

Writes to analysis/analysis_summary_filtered.md so the original stays
on disk as an audit trail of how the spam was discovered.

Run from project root:  python analysis/write_filtered_summary.py
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = Path(__file__).resolve().parent

FILTERED_PATH = ANALYSIS_DIR / "analysis_comment_level_filtered.csv"
RELABEL_PATH = ANALYSIS_DIR / "theme_relabel_mapping.csv"
RECLUSTER_PATH = ANALYSIS_DIR / "canonical_reclustered.csv"
ORIGINAL_LABELED_PATH = PROJECT_ROOT / "data" / "processed" / "analysis_comment_level.csv"
OUT_PATH = ANALYSIS_DIR / "reports" / "analysis_summary_filtered.md"

MIN_ROWS_PER_POST = 5
QUOTES_PER_THEME = 5
MIN_COMMENTS_FOR_CONCENTRATION = 3
MIXED_LABEL = "Unlabeled / mixed reactions"


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def safe_div(n: float, d: float) -> float:
    return (n / d) if d else 0.0


def load_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    filtered = pd.read_csv(FILTERED_PATH)
    relabel = pd.read_csv(RELABEL_PATH)
    recluster = pd.read_csv(RECLUSTER_PATH)
    return filtered, relabel, recluster


def apply_relabel(filtered: pd.DataFrame, relabel: pd.DataFrame) -> pd.DataFrame:
    """Attach effective_theme per row using the audit's relabel decisions.

    Rows whose theme got marked MIXED (low-coherence junk clusters) all
    collapse into one bucket so they can be reported together instead of
    inflating the top-themes list.
    """
    mapping = relabel.set_index("theme_id")[["new_label", "is_mixed"]]
    out = filtered.merge(mapping, how="left", left_on="theme_id", right_index=True)
    out["effective_theme"] = out.apply(
        lambda r: (
            MIXED_LABEL
            if (pd.notna(r.get("is_mixed")) and int(r["is_mixed"]) == 1)
            else (r["new_label"] if pd.notna(r.get("new_label")) else r["theme_human_label"])
        ),
        axis=1,
    )
    return out


def cohesion_by_theme(
    filtered: pd.DataFrame, recluster: pd.DataFrame
) -> dict[str, tuple[float, int, int]]:
    """Mean audit coherence over the canonical texts in each theme, with coverage.

    The audit's HDBSCAN pass labels most canonicals as *noise* (coherence
    stored as 0.0), because the pilot's embeddings only formed 3 tight
    clusters. Averaging raw coherence would drag everything toward zero.
    Instead we average over canonicals that *did* land in an HDBSCAN
    cluster (coherence > 0) and report (mean, n_clustered, n_total) so
    coverage is visible. Themes with zero clustered canonicals get a
    neutral (nan, 0, n) sentinel.
    """
    if "canonical_id" not in recluster.columns:
        return {}
    canon = (
        recluster[["canonical_id", "coherence"]]
        .dropna(subset=["canonical_id"])
    )
    canon = canon[canon["canonical_id"].astype(str).str.strip() != ""]
    # One canonical_id can repeat in recluster; dedupe to the first row.
    canon = canon.drop_duplicates(subset=["canonical_id"])

    canonical_by_theme = (
        filtered.dropna(subset=["canonical_id"])
        .drop_duplicates(subset=["canonical_id"])
        [["canonical_id", "effective_theme"]]
    )
    joined = canonical_by_theme.merge(canon, on="canonical_id", how="left")
    joined["coherence"] = pd.to_numeric(joined["coherence"], errors="coerce")

    out: dict[str, tuple[float, int, int]] = {}
    for theme, sub in joined.groupby("effective_theme"):
        clustered = sub[sub["coherence"].fillna(0) > 0]
        n_total = int(len(sub))
        n_clustered = int(len(clustered))
        mean = float(clustered["coherence"].mean()) if n_clustered else float("nan")
        out[theme] = (mean, n_clustered, n_total)
    return out


def pick_quotes(
    rows: pd.DataFrame, k: int
) -> list[tuple[str, str]]:
    """k quotes per theme, diversified across source videos, preferring
    high theme_confidence so representative text sits on top."""
    rows = rows.dropna(subset=["text_raw"])
    rows = rows[rows["text_raw"].astype(str).str.strip() != ""]
    rows = rows.sort_values("theme_confidence", ascending=False, na_position="last")
    picked: list[tuple[str, str]] = []
    seen_posts: set[str] = set()
    for _, r in rows.iterrows():
        post = r["input_url"]
        if post in seen_posts:
            continue
        picked.append((str(r["text_raw"]), post))
        seen_posts.add(post)
        if len(picked) >= k:
            break
    if len(picked) < k:
        for _, r in rows.iterrows():
            pair = (str(r["text_raw"]), r["input_url"])
            if pair in picked:
                continue
            picked.append(pair)
            if len(picked) >= k:
                break
    return picked


def per_theme_stats(
    rows: pd.DataFrame, cohesion_lookup: dict[str, float]
) -> list[dict]:
    out = []
    for theme, sub in rows.groupby("effective_theme"):
        video_counts = sub["input_url"].value_counts()
        n_rows = int(len(sub))
        total_videos = int(video_counts.size)
        top_share = float(video_counts.iloc[0] / n_rows) if n_rows else 0.0

        # Concentration restricted to videos that contributed >=3 rows —
        # suppresses the long tail of 1-comment videos.
        substantive = video_counts[video_counts >= MIN_COMMENTS_FOR_CONCENTRATION]
        if substantive.sum() >= MIN_COMMENTS_FOR_CONCENTRATION:
            top_share_ge3 = float(substantive.iloc[0] / substantive.sum())
            ge3_videos = int(substantive.size)
            ge3_total = int(substantive.sum())
        else:
            top_share_ge3 = float("nan")
            ge3_videos = 0
            ge3_total = 0

        out.append(
            {
                "theme": theme,
                "n_rows": n_rows,
                "n_videos": total_videos,
                "top_post_share": top_share,
                "top_post_share_ge3": top_share_ge3,
                "ge3_videos": ge3_videos,
                "ge3_total": ge3_total,
                "cohesion": cohesion_lookup.get(theme, (float("nan"), 0, 0)),
                "quotes": pick_quotes(sub, QUOTES_PER_THEME),
            }
        )
    # Real themes first (most comments first), MIXED bucket always last.
    out.sort(
        key=lambda d: (d["theme"] == MIXED_LABEL, -d["n_rows"])
    )
    return out


def per_post_stats(rows: pd.DataFrame) -> pd.DataFrame:
    """Per-video high_rate, neg_or_conf_rate, winner_score from the filtered
    comment set. Matches the original summary's guardrail (n>=5)."""
    rows = rows.copy()
    rows["is_high"] = (rows["watch_intent_label"].astype(str).str.lower() == "high").astype(int)
    rows["is_low"] = (rows["watch_intent_label"].astype(str).str.lower() == "low").astype(int)
    rows["is_neg"] = (rows["sentiment_label"].astype(str).str.lower() == "neg").astype(int)
    rows["is_conf"] = pd.to_numeric(rows["confusion_flag"], errors="coerce").fillna(0).astype(int)
    # confusion_flag stored as 0/1; combine neg OR confusion for the old rubric.
    rows["is_neg_or_conf"] = (
        (rows["is_neg"] == 1) | (rows["is_conf"] == 1)
    ).astype(int)

    labeled = rows[rows["watch_intent_label"].astype(str).str.strip().ne("")]

    per_post = labeled.groupby("input_url").agg(
        n_total_text_rows=("row_id", "size"),
        n_high=("is_high", "sum"),
        n_neg_or_conf=("is_neg_or_conf", "sum"),
    ).reset_index()

    per_post["high_rate"] = per_post.apply(
        lambda r: safe_div(r["n_high"], r["n_total_text_rows"]), axis=1
    )
    per_post["neg_or_conf_rate"] = per_post.apply(
        lambda r: safe_div(r["n_neg_or_conf"], r["n_total_text_rows"]), axis=1
    )
    # Depth = replies / comments.
    rows_c = rows[rows["content_type"] == "comment"].groupby("input_url").size()
    rows_r = rows[rows["content_type"] == "reply"].groupby("input_url").size()
    depth = (rows_r / rows_c).rename("depth")
    per_post = per_post.merge(depth, on="input_url", how="left")
    per_post["depth"] = per_post["depth"].fillna(0.0)
    per_post["winner_score"] = per_post["high_rate"] - 0.5 * per_post["neg_or_conf_rate"]
    return per_post


def header_note() -> list[str]:
    return [
        "# Datadoping Comment-Level Audience Analysis — filtered rebuild",
        "",
        "> **Provenance.** Regenerated from `analysis_comment_level_filtered.csv` "
        "(post-spam-filter) and `theme_relabel_mapping.csv` (post-audit). "
        "No new embeddings, no new LLM calls. The original pre-filter "
        "`data/processed/analysis_summary.md` is retained as an audit "
        "trail of how the creator-self-spam contamination was discovered.",
        "",
        "> **What changed vs the original.** "
        "(1) Winners / Laggards / theme counts recomputed on the 821-row "
        "filtered corpus, not the 923-row raw corpus. "
        "(2) Themes renamed per the audit — e.g. 'Media Identification' → "
        "'Movie Name Requests'. "
        "(3) Three original themes (`Exclamations and Questions`, "
        "`Step-by-Step Instructions`, `Personal Statements`) reviewed as "
        "low-coherence junk clusters and collapsed into a single "
        "'unlabeled / mixed reactions' bucket at the bottom. "
        "(4) Added `top_post_share_ge3` — concentration restricted to videos "
        "contributing ≥3 comments to the theme, to suppress long tails of "
        "single-comment videos inflating the headline concentration number.",
        "",
    ]


def run_metrics_section(
    filtered: pd.DataFrame, relabeled: pd.DataFrame
) -> list[str]:
    non_empty = filtered["text_norm"].astype(str).str.strip().ne("").sum()
    canonical_ids = filtered["canonical_id"].dropna().astype(str)
    canonical_ids = canonical_ids[canonical_ids.str.strip() != ""]
    n_canonical = int(canonical_ids.nunique())
    dedupe_savings = safe_div(int(non_empty) - n_canonical, int(non_empty)) if non_empty else 0.0

    label_src = filtered["label_source"].astype(str).str.lower()
    n_llm = int((label_src == "llm").sum())
    n_model = int((label_src == "model").sum())
    n_labeled = int(filtered["watch_intent_label"].astype(str).str.strip().ne("").sum())

    # Compare input count vs current.
    try:
        orig = pd.read_csv(ORIGINAL_LABELED_PATH)
        orig_rows = len(orig)
    except FileNotFoundError:
        orig_rows = None

    lines = [
        "## Run Metrics",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if orig_rows is not None:
        lines.append(
            f"- Original labeled rows (pre-filter): {orig_rows}"
        )
    lines += [
        f"- Filtered comment/reply rows: {len(filtered)}",
        f"- Non-empty text rows: {int(non_empty)}",
        f"- Unique canonical texts surviving filter: {n_canonical}",
        f"- Dedupe savings: {fmt_pct(dedupe_savings)}",
        f"- Labeled rows (watch-intent assigned): {n_labeled}",
        f"- Label source breakdown: model={n_model}, llm={n_llm}",
        "",
    ]
    return lines


def winners_laggards_section(per_post: pd.DataFrame) -> list[str]:
    eligible = per_post[per_post["n_total_text_rows"] >= MIN_ROWS_PER_POST].copy()
    eligible = eligible.sort_values("winner_score", ascending=False)
    winners = eligible.head(5)
    laggards = eligible.tail(5).iloc[::-1]

    def format_row(r) -> str:
        return (
            f"- {r['input_url']} | n={int(r['n_total_text_rows'])}, "
            f"high_intent={fmt_pct(r['high_rate'])}, "
            f"neg_or_conf={fmt_pct(r['neg_or_conf_rate'])}, "
            f"depth={r['depth']:.2f}, "
            f"winner_score={r['winner_score']:.4f}"
        )

    lines = [
        f"## Winners (min n={MIN_ROWS_PER_POST} comments)",
    ]
    if winners.empty:
        lines.append("- No eligible winners.")
    else:
        lines += [format_row(r) for _, r in winners.iterrows()]

    lines += [
        "",
        f"## Laggards (min n={MIN_ROWS_PER_POST} comments)",
    ]
    if laggards.empty:
        lines.append("- No eligible laggards.")
    else:
        lines += [format_row(r) for _, r in laggards.iterrows()]
    lines.append("")
    return lines


def themes_section(stats: list[dict]) -> list[str]:
    lines = [
        "## Top Themes + Representative Quotes",
        "",
        "_Counts reflect the filtered corpus. `top_post_share` = fraction "
        "of the theme's rows from its most-represented video. "
        "`top_post_share_ge3` = same metric restricted to videos that "
        "contributed at least 3 rows to the theme (more honest when the "
        "theme has a long tail of single-comment videos). `cohesion` = "
        "mean HDBSCAN audit coherence over canonicals that landed in an "
        "audit cluster (not all canonicals did — HDBSCAN marked most as "
        "noise — so coverage is shown alongside the mean)._",
        "",
    ]
    for row in stats:
        theme = row["theme"]
        coh_mean, n_clustered, n_total = row["cohesion"]
        if n_clustered and pd.notna(coh_mean):
            coh_str = (
                f"{coh_mean:.2f} "
                f"(over {n_clustered}/{n_total} canonicals with audit coverage)"
            )
        else:
            coh_str = f"n/a (0/{n_total} canonicals in audit clusters)"
        tps = row["top_post_share"]
        if row["ge3_total"]:
            ge3 = (
                f"{row['top_post_share_ge3']:.2f} "
                f"(across {row['ge3_videos']} videos with ≥3 rows)"
            )
        else:
            ge3 = "n/a (no video contributed ≥3 rows)"
        header = (
            f"### {theme}  ·  {row['n_rows']} rows across {row['n_videos']} videos"
        )
        if theme == MIXED_LABEL:
            header += "  _(audit: low-coherence / no shared topic)_"
        lines.append(header)
        lines.append(
            f"- cohesion: **{coh_str}**  |  "
            f"top_post_share: **{tps:.2f}**  |  "
            f"top_post_share_ge3: **{ge3}**"
        )
        if row["quotes"]:
            lines.append("- Representative quotes:")
            for text, post in row["quotes"]:
                snippet = text.replace("\n", " ").strip()
                if len(snippet) > 140:
                    snippet = snippet[:137] + "..."
                lines.append(f"    - \"{snippet}\" ({post})")
        lines.append("")
    return lines


def notes_section() -> list[str]:
    return [
        "## Notes",
        "- Three themes were collapsed into the MIXED bucket because the "
        "audit ([analysis/theme_relabel_mapping.csv](theme_relabel_mapping.csv)) "
        "scored their shared-topic coherence at ≤0.20: `t8 Exclamations and "
        "Questions` (229 rows → mostly '??' punctuation), `t2 Step-by-Step "
        "Instructions` (76 rows → scattered spam-adjacent reactions), `t0 "
        "Personal Statements` (51 rows → no unifying topic).",
        "- Filter rules (applied in `build_filtered_comments.py`): "
        "(1) `is_created_by_media_owner=True`; "
        "(3) long text (≥80 chars) duplicated across ≥2 videos; "
        "(4) commenter username matches a known creator handle.",
        "- Watch-intent rubric: broad curiosity intent.",
        "- Non-English handling: as-is (no translation pass).",
    ]


def main() -> None:
    filtered, relabel, recluster = load_frames()
    relabeled = apply_relabel(filtered, relabel)
    cohesion_lookup = cohesion_by_theme(relabeled, recluster)
    theme_stats = per_theme_stats(relabeled, cohesion_lookup)
    post_stats = per_post_stats(relabeled)

    sections: list[str] = []
    sections += header_note()
    sections += run_metrics_section(filtered, relabeled)
    sections += winners_laggards_section(post_stats)
    sections += themes_section(theme_stats)
    sections += notes_section()

    OUT_PATH.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"[ok] wrote {OUT_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
