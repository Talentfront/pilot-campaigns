"""Apply the theme relabel mapping produced by relabel_themes.py.

What this rewrites:
  - analysis/analysis_comment_level_filtered.csv: theme_human_label column
  - analysis_post_level.csv: top_theme_1/2/3 columns
  - analysis/pilot.duckdb: rebuilt from the CSVs via build_workspace.sql so
    v_videos.top_theme_* and raw_comments.theme_human_label stay consistent
  - analysis/theme_rollup.csv: regenerated inline so downstream charts pick up
    the new labels without running the full NLP pipeline

Back-ups are written next to each overwritten file with a .prerelabel suffix
so the old labels are recoverable.

Usage:
  python analysis/apply_theme_relabel.py            # interactive confirm
  python analysis/apply_theme_relabel.py --yes      # non-interactive
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = Path(__file__).resolve().parent

MAPPING_PATH = ANALYSIS_DIR / "theme_relabel_mapping.csv"
COMMENT_CSV = ANALYSIS_DIR / "analysis_comment_level_filtered.csv"
POST_CSV = PROJECT_ROOT / "analysis_post_level.csv"
DB_PATH = ANALYSIS_DIR / "pilot.duckdb"
BUILD_SQL = ANALYSIS_DIR / "build_workspace.sql"
ROLLUP_PATH = ANALYSIS_DIR / "theme_rollup.csv"


def load_mapping() -> pd.DataFrame:
    if not MAPPING_PATH.exists():
        sys.exit(f"ERROR: {MAPPING_PATH} not found. Run relabel_themes.py first.")
    m = pd.read_csv(MAPPING_PATH)
    required = {"current_label", "new_label", "is_mixed"}
    if not required.issubset(m.columns):
        sys.exit(f"ERROR: mapping missing columns {required - set(m.columns)}")
    m["new_label"] = m["new_label"].fillna("").astype(str).str.strip()
    m["current_label"] = m["current_label"].astype(str).str.strip()
    # Empty new_label means "keep current"
    m.loc[m["new_label"] == "", "new_label"] = m.loc[m["new_label"] == "", "current_label"]
    return m


def build_rename(mapping: pd.DataFrame) -> dict[str, str]:
    rename = {}
    for _, r in mapping.iterrows():
        old, new = r["current_label"], r["new_label"]
        if old and new and old != new:
            rename[old] = new
    return rename


def back_up(path: Path) -> None:
    if path.exists():
        bak = path.with_suffix(path.suffix + ".prerelabel")
        shutil.copy2(path, bak)
        print(f"  backup ->{bak.name}")


def rewrite_comment_csv(rename: dict[str, str]) -> int:
    print(f"Rewriting {COMMENT_CSV.name} …")
    back_up(COMMENT_CSV)
    df = pd.read_csv(COMMENT_CSV, dtype=str, keep_default_na=False)
    before = df["theme_human_label"].value_counts().to_dict()
    df["theme_human_label"] = df["theme_human_label"].replace(rename)
    after = df["theme_human_label"].value_counts().to_dict()
    n_changed = sum(
        before.get(k, 0) for k in rename if k in before
    )
    df.to_csv(COMMENT_CSV, index=False)
    print(f"  touched {n_changed} comment-level rows")
    # Report any labels that disappeared / appeared
    gone = set(before) - set(after)
    new = set(after) - set(before)
    if gone:
        print(f"  labels retired: {sorted(gone)}")
    if new:
        print(f"  labels introduced: {sorted(new)}")
    return n_changed


def rewrite_post_csv(rename: dict[str, str]) -> int:
    print(f"Rewriting {POST_CSV.name} …")
    back_up(POST_CSV)
    df = pd.read_csv(POST_CSV, dtype=str, keep_default_na=False)
    n_changed = 0
    for col in ("top_theme_1", "top_theme_2", "top_theme_3"):
        if col not in df.columns:
            continue
        mask = df[col].isin(rename)
        n_changed += int(mask.sum())
        df.loc[mask, col] = df.loc[mask, col].map(rename)
    df.to_csv(POST_CSV, index=False)
    print(f"  touched {n_changed} post-level theme cells")
    return n_changed


def rebuild_duckdb() -> None:
    print(f"Rebuilding {DB_PATH.name} from CSVs …")
    if DB_PATH.exists():
        back_up(DB_PATH)
        DB_PATH.unlink()
    sql = BUILD_SQL.read_text(encoding="utf-8")
    con = duckdb.connect(str(DB_PATH))
    # build_workspace.sql uses relative paths from project root.
    import os
    cwd = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        con.execute(sql)
    finally:
        os.chdir(cwd)
        con.close()
    print("  rebuilt.")


def regenerate_theme_rollup() -> None:
    """Mirror theme_rollup() in run_analysis.py so downstream charts/dashboard
    read fresh labels without paying for a full NLP re-run."""
    print(f"Regenerating {ROLLUP_PATH.name} …")
    back_up(ROLLUP_PATH)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    comments = con.execute(
        """
        SELECT post_id, theme_human_label AS theme,
               watch_intent_label, confusion_flag
        FROM raw_comments
        WHERE theme_human_label IS NOT NULL AND theme_human_label <> ''
        """
    ).fetchdf()
    videos = con.execute(
        "SELECT post_id, profile, views, payout_usd FROM v_videos"
    ).fetchdf()

    comments["is_high"] = (
        comments["watch_intent_label"].str.lower() == "high"
    ).astype(int)
    comments["is_neg_or_conf"] = (
        comments["confusion_flag"].astype(bool)
        | (comments["watch_intent_label"].str.lower() == "low")
    ).astype(int)

    agg = (
        comments.groupby("theme")
        .agg(
            n_comments=("post_id", "size"),
            n_videos_appearing_in=("post_id", "nunique"),
            high_intent_rate=("is_high", "mean"),
            neg_or_conf_rate=("is_neg_or_conf", "mean"),
        )
        .reset_index()
    )

    theme_video = (
        comments[["theme", "post_id"]]
        .drop_duplicates()
        .merge(videos[["post_id", "profile"]], on="post_id", how="left")
    )
    theme_video["profile"] = theme_video["profile"].fillna("(unknown)")

    def hhi(profiles: pd.Series) -> float:
        shares = profiles.value_counts(normalize=True)
        return float((shares ** 2).sum())

    hhi_per_theme = (
        theme_video.groupby("theme")["profile"]
        .apply(hhi)
        .rename("account_concentration_hhi")
        .reset_index()
    )
    agg = agg.merge(hhi_per_theme, on="theme", how="left")

    post_themes_df = con.execute(
        """
        SELECT post_id, theme
        FROM (
            SELECT post_id, top_theme_1 AS theme FROM v_videos
            UNION ALL
            SELECT post_id, top_theme_2 FROM v_videos
            UNION ALL
            SELECT post_id, top_theme_3 FROM v_videos
        ) WHERE theme IS NOT NULL AND theme <> ''
        """
    ).fetchdf()

    base_views = videos["views"].median()
    base_payout = videos["payout_usd"].median()

    def lift(theme: str, col: str, baseline: float) -> float:
        pids = post_themes_df.loc[post_themes_df["theme"] == theme, "post_id"]
        vals = videos.loc[videos["post_id"].isin(pids), col].dropna()
        if vals.empty or not baseline or np.isnan(baseline):
            return np.nan
        return float(vals.median() / baseline)

    agg["view_lift"] = agg["theme"].apply(lambda t: lift(t, "views", base_views))
    agg["payout_lift"] = agg["theme"].apply(
        lambda t: lift(t, "payout_usd", base_payout)
    )
    agg = agg.sort_values("n_comments", ascending=False)
    agg.to_csv(ROLLUP_PATH, index=False)
    print(f"  rewrote with {len(agg)} themes.")
    con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true",
                        help="Skip interactive confirmation.")
    args = parser.parse_args()

    mapping = load_mapping()
    rename = build_rename(mapping)
    mixed = mapping[mapping["is_mixed"].astype(str).isin(["1", "True", "true"])]

    print("Relabel plan:")
    if rename:
        for old, new in rename.items():
            print(f"  {old!r:38s} ->{new!r}")
    else:
        print("  (no labels will change)")
    if not mixed.empty:
        print("\nThemes flagged MIXED:")
        for _, r in mixed.iterrows():
            print(f"  - {r['current_label']!r} ->"
                  f"{r['new_label']!r} ({r.get('description','')})")

    if not rename and mixed.empty:
        print("\nNothing to apply. Exiting.")
        return 0

    if not args.yes:
        resp = input("\nApply these changes? [y/N] ").strip().lower()
        if resp not in {"y", "yes"}:
            print("Aborted.")
            return 1

    rewrite_comment_csv(rename)
    rewrite_post_csv(rename)
    rebuild_duckdb()
    regenerate_theme_rollup()
    print("\nDone. Dashboard will pick up new labels on next reload.")
    print("Originals saved with .prerelabel suffix; delete them once verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
