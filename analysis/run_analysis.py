"""Pilot-campaigns analysis orchestrator.

Builds the DuckDB workspace over the project-root CSVs, then produces:
  - account_rollup.csv
  - theme_rollup.csv
  - video_clusters.csv
  - cluster_profile.md
  - theme_intent_vs_viewlift.svg
  - account_winner_scores.svg

Run from project root:  python analysis/run_analysis.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import subprocess

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = Path(__file__).resolve().parent
DB_PATH = ANALYSIS_DIR / "pilot.duckdb"
SQL_PATH = ANALYSIS_DIR / "build_workspace.sql"
FILTER_SCRIPT = ANALYSIS_DIR / "build_filtered_comments.py"
FILTERED_CSV = ANALYSIS_DIR / "analysis_comment_level_filtered.csv"


def ensure_filtered_comments() -> None:
    """Regenerate the filtered comment CSV before every run.

    Cheap (runs in ~1s) and guarantees the workspace is consistent with the
    current filter rules if build_filtered_comments.py is edited.
    """
    result = subprocess.run(
        [sys.executable, str(FILTER_SCRIPT)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    # Forward the one-line summary the filter prints.
    for line in result.stdout.splitlines():
        if line.strip():
            print(line)


def build_workspace() -> duckdb.DuckDBPyConnection:
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = duckdb.connect(str(DB_PATH))
    # DuckDB's read_csv_auto resolves paths relative to the process CWD.
    con.execute(f"SET FILE_SEARCH_PATH = '{PROJECT_ROOT.as_posix()}'")
    con.execute(SQL_PATH.read_text(encoding="utf-8"))
    return con


def report_join_gaps(con: duckdb.DuckDBPyConnection) -> None:
    gaps = con.execute(
        "SELECT COUNT(*) FROM v_videos WHERE profile IS NULL"
    ).fetchone()[0]
    if gaps:
        print(
            f"[warn] {gaps} analyzed videos have no profile "
            f"(not in All Clips CSV). They'll appear with profile=NULL.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Empirical-Bayes shrinkage for per-video high-intent rate
# ---------------------------------------------------------------------------
#
# Most videos have 1-3 analyzed comments, so raw high-intent rates swing
# between 0 and 1. We fit a Beta(alpha, beta) prior to the observed rates
# via method-of-moments on videos with n >= SHRINK_MIN_N, then post-shrink
# every video to (k + alpha) / (n + alpha + beta). Videos with n=0 get the
# prior mean. The prior strength alpha+beta sets the "effective sample size"
# we're borrowing from other videos.

SHRINK_MIN_N = 3  # videos with at least this many comments inform the prior


def fit_beta_prior(rates: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    """Method-of-moments fit. Returns (alpha, beta)."""
    if rates.size < 2:
        return 1.0, 1.0  # uninformative fallback
    # Weighted mean/variance over videos that have enough comments.
    w = weights / weights.sum()
    mean = float((rates * w).sum())
    var = float((w * (rates - mean) ** 2).sum())
    if var <= 0 or mean <= 0 or mean >= 1:
        return 1.0, 1.0
    # Method-of-moments for Beta.
    common = mean * (1 - mean) / var - 1
    if common <= 0:
        return 1.0, 1.0
    alpha = mean * common
    beta = (1 - mean) * common
    # Floor the prior strength so single-comment videos don't get dominated.
    if alpha + beta < 4:
        scale = 4 / (alpha + beta)
        alpha *= scale
        beta *= scale
    return float(alpha), float(beta)


def add_shrunk_intent(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Compute empirical-Bayes-shrunk high_intent_rate per video.

    Returns a DataFrame with (post_id, n_labeled, k_high, raw_rate,
    shrunk_rate) and persists it as table `video_intent_shrunk`.
    """
    rows = con.execute(
        """
        SELECT post_id,
               SUM(CASE WHEN watch_intent_label IS NOT NULL
                             AND watch_intent_label <> '' THEN 1 ELSE 0 END) AS n_labeled,
               SUM(CASE WHEN lower(watch_intent_label) = 'high' THEN 1 ELSE 0 END) AS k_high
        FROM raw_comments
        GROUP BY post_id
        """
    ).fetchdf()

    # Include videos with 0 analyzed comments so downstream joins are clean.
    all_posts = con.execute("SELECT post_id FROM v_videos").fetchdf()
    rows = all_posts.merge(rows, on="post_id", how="left").fillna(
        {"n_labeled": 0, "k_high": 0}
    )
    rows["n_labeled"] = rows["n_labeled"].astype(int)
    rows["k_high"] = rows["k_high"].astype(int)

    # Fit the prior on videos with enough data to inform it.
    informative = rows[rows["n_labeled"] >= SHRINK_MIN_N].copy()
    informative["raw_rate"] = informative["k_high"] / informative["n_labeled"]
    alpha, beta = fit_beta_prior(
        informative["raw_rate"].values,
        informative["n_labeled"].values.astype(float),
    )
    prior_mean = alpha / (alpha + beta)
    print(
        f"[ok] intent prior Beta(alpha={alpha:.2f}, beta={beta:.2f})  "
        f"prior_mean={prior_mean:.3f}  prior_strength={alpha + beta:.2f}"
    )

    rows["raw_rate"] = np.where(
        rows["n_labeled"] > 0, rows["k_high"] / rows["n_labeled"], np.nan
    )
    rows["shrunk_rate"] = (rows["k_high"] + alpha) / (
        rows["n_labeled"] + alpha + beta
    )

    con.execute("DROP TABLE IF EXISTS video_intent_shrunk")
    con.execute("CREATE TABLE video_intent_shrunk AS SELECT * FROM rows")

    # Also stash prior params so downstream code / re-runs can reuse.
    con.execute("DROP TABLE IF EXISTS intent_prior")
    con.execute(
        "CREATE TABLE intent_prior AS "
        "SELECT ? AS alpha, ? AS beta, ? AS prior_mean",
        [alpha, beta, prior_mean],
    )
    return rows


# ---------------------------------------------------------------------------
# 1. Account rollup
# ---------------------------------------------------------------------------

ACCOUNT_ROLLUP_SQL = """
WITH per_video AS (
    SELECT
        coalesce(v.profile, '(unknown)') AS profile,
        v.post_id,
        v.views,
        v.payout_usd,
        v.n_comments_analyzed,
        v.high_rate,
        s.shrunk_rate                          AS shrunk_high_rate,
        s.n_labeled                            AS n_labeled_intent,
        s.k_high                               AS k_high_intent,
        v.negative_or_confusion_rate,
        v.winner_score
    FROM v_videos v
    LEFT JOIN video_intent_shrunk s USING (post_id)
),
themed AS (
    SELECT coalesce(profile, '(unknown)') AS profile, theme, share
    FROM v_video_themes
),
theme_mix AS (
    SELECT profile,
           string_agg(theme || ' (' || round(share*100,0) || '%)', ', '
                      ORDER BY share DESC) AS theme_mix_top3
    FROM (
        SELECT profile, theme,
               avg(share) AS share,
               row_number() OVER (
                   PARTITION BY profile ORDER BY avg(share) DESC
               ) AS rn
        FROM themed
        GROUP BY profile, theme
    )
    WHERE rn <= 3
    GROUP BY profile
)
SELECT
    pv.profile,
    COUNT(*)                                            AS n_videos,
    SUM(coalesce(views,0))                              AS total_views,
    CAST(median(views) AS BIGINT)                       AS median_views,
    SUM(coalesce(payout_usd,0))                         AS total_payout_usd,
    SUM(n_comments_analyzed)                            AS total_comments_analyzed,
    SUM(coalesce(n_labeled_intent,0))                   AS total_labeled_intent,
    avg(winner_score)                                   AS mean_winner_score,
    avg(high_rate)                                      AS mean_high_intent_rate_raw,
    avg(shrunk_high_rate)                               AS mean_high_intent_rate_shrunk,
    -- Pooled rate: one rate across all this account's comments. Not
    -- susceptible to the per-video averaging skew at all.
    CASE WHEN SUM(coalesce(n_labeled_intent,0)) > 0
         THEN CAST(SUM(coalesce(k_high_intent,0)) AS DOUBLE)
              / SUM(coalesce(n_labeled_intent,0))
         ELSE NULL END                                  AS pooled_high_intent_rate,
    avg(negative_or_confusion_rate)                     AS mean_neg_or_conf_rate,
    CASE WHEN SUM(n_comments_analyzed) > 0
         THEN SUM(winner_score * n_comments_analyzed)
              / SUM(n_comments_analyzed)
         ELSE NULL END                                  AS weighted_winner_score,
    SUM(n_comments_analyzed) > 0                        AS has_nlp_data,
    tm.theme_mix_top3
FROM per_video pv
LEFT JOIN theme_mix tm USING (profile)
GROUP BY pv.profile, tm.theme_mix_top3
ORDER BY mean_high_intent_rate_shrunk DESC NULLS LAST, n_videos DESC
"""


def account_rollup(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.execute(ACCOUNT_ROLLUP_SQL).fetchdf()
    df.to_csv(ANALYSIS_DIR / "account_rollup.csv", index=False)
    print(f"[ok] account_rollup.csv  ({len(df)} rows)")
    return df


# ---------------------------------------------------------------------------
# 2. Theme rollup
# ---------------------------------------------------------------------------

def theme_rollup(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # Per-theme aggregates from the comment-level table (more granular than
    # top_theme_N on the post-level, which only gives us the top 3 per video).
    comments = con.execute(
        """
        SELECT post_id, theme_human_label AS theme,
               watch_intent_label, confusion_flag
        FROM raw_comments
        WHERE theme_human_label IS NOT NULL
          AND theme_human_label <> ''
        """
    ).fetchdf()

    videos = con.execute(
        "SELECT post_id, profile, views, payout_usd FROM v_videos"
    ).fetchdf()

    # High-intent / neg-or-conf rate per theme.
    comments["is_high"] = (
        comments["watch_intent_label"].str.lower() == "high"
    ).astype(int)
    comments["is_neg_or_conf"] = (
        (comments["confusion_flag"].astype(bool))
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

    # Account concentration (HHI): sum of squared account shares for videos
    # where this theme appears. 1.0 = single account, 0 = evenly spread.
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

    # View/payout lift: median of videos where theme appears in top-3 (per
    # post_level table) divided by median across all analyzed videos.
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

    base_median_views = videos["views"].median()
    base_median_payout = videos["payout_usd"].median()

    def lift(theme: str, col: str, baseline: float) -> float:
        pids = post_themes_df.loc[post_themes_df["theme"] == theme, "post_id"]
        vals = videos.loc[videos["post_id"].isin(pids), col].dropna()
        if vals.empty or not baseline or np.isnan(baseline):
            return np.nan
        return float(vals.median() / baseline)

    agg["view_lift"] = agg["theme"].apply(
        lambda t: lift(t, "views", base_median_views)
    )
    agg["payout_lift"] = agg["theme"].apply(
        lambda t: lift(t, "payout_usd", base_median_payout)
    )

    agg = agg.sort_values("n_comments", ascending=False)
    agg.to_csv(ANALYSIS_DIR / "theme_rollup.csv", index=False)
    print(f"[ok] theme_rollup.csv    ({len(agg)} rows)")
    return agg


# ---------------------------------------------------------------------------
# 3. Latent video clustering on theme-share vectors
# ---------------------------------------------------------------------------

def cluster_videos(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # Build video × theme matrix from comment-level data (full distribution,
    # not just top-3). Values are per-video share of each theme.
    raw = con.execute(
        """
        SELECT post_id,
               theme_human_label AS theme,
               COUNT(*) AS n
        FROM raw_comments
        WHERE theme_human_label IS NOT NULL AND theme_human_label <> ''
        GROUP BY post_id, theme
        """
    ).fetchdf()

    # Share within each post.
    raw["share"] = raw.groupby("post_id")["n"].transform(
        lambda s: s / s.sum()
    )
    mat = raw.pivot_table(
        index="post_id", columns="theme", values="share", fill_value=0.0
    )

    if len(mat) < 6:
        print("[warn] too few videos for clustering", file=sys.stderr)
        return pd.DataFrame()

    # Sweep k, pick by silhouette.
    best_k, best_score, best_labels = None, -1.0, None
    for k in (3, 4, 5, 6):
        if k >= len(mat):
            continue
        km = KMeans(n_clusters=k, n_init=10, random_state=0)
        labels = km.fit_predict(mat.values)
        try:
            score = silhouette_score(mat.values, labels)
        except Exception:
            continue
        print(f"  k={k}  silhouette={score:.3f}")
        if score > best_score:
            best_k, best_score, best_labels = k, score, labels

    print(f"[ok] chose k={best_k} (silhouette={best_score:.3f})")
    clusters = pd.DataFrame(
        {"post_id": mat.index, "cluster_id": best_labels}
    )

    # Persist cluster assignment as a table so it can be joined in SQL.
    con.execute("DROP TABLE IF EXISTS video_clusters")
    con.execute(
        "CREATE TABLE video_clusters AS SELECT * FROM clusters"
    )

    # Attach metadata for the CSV export.
    videos = con.execute(
        """
        SELECT v.post_id, v.profile, v.input_url, v.views, v.winner_score,
               v.high_rate                AS high_rate_raw,
               s.shrunk_rate              AS high_rate_shrunk,
               s.n_labeled, s.k_high
        FROM v_videos v
        LEFT JOIN video_intent_shrunk s USING (post_id)
        """
    ).fetchdf()
    out = clusters.merge(videos, on="post_id", how="left")
    out.to_csv(ANALYSIS_DIR / "video_clusters.csv", index=False)
    print(f"[ok] video_clusters.csv  ({len(out)} rows)")

    # Human-readable cluster profile.
    write_cluster_profile(out, mat, best_labels)
    return out


def write_cluster_profile(
    clustered: pd.DataFrame, theme_matrix: pd.DataFrame, labels: np.ndarray
) -> None:
    lines = ["# Latent Video Clusters\n"]
    lines.append(
        "Clusters derived via k-means on per-video theme-share vectors "
        "(source: comment-level theme assignments).\n"
    )
    lines.append(
        "Three intent measurements per cluster:\n"
        "- **raw per-video mean**: average of per-video raw rates (inflated by tiny-n videos)\n"
        "- **shrunk per-video mean**: after empirical-Bayes shrinkage toward the global prior\n"
        "- **pooled rate**: one rate over *all comments in the cluster* (most stable)\n"
    )
    theme_matrix_with_cluster = theme_matrix.copy()
    theme_matrix_with_cluster["cluster_id"] = labels

    for cid in sorted(clustered["cluster_id"].unique()):
        sub = clustered[clustered["cluster_id"] == cid]
        lines.append(f"## Cluster {cid}  (n={len(sub)})")
        mean_views = sub["views"].mean()
        lines.append(
            f"- Mean views: {mean_views:.0f}"
            if pd.notna(mean_views)
            else "- Mean views: n/a"
        )
        lines.append(
            f"- Mean winner_score: {sub['winner_score'].mean():.3f}"
        )
        raw_mean = sub["high_rate_raw"].mean()
        shrunk_mean = sub["high_rate_shrunk"].mean()
        total_k = sub["k_high"].fillna(0).sum()
        total_n = sub["n_labeled"].fillna(0).sum()
        pooled = (total_k / total_n) if total_n > 0 else float("nan")
        lines.append(
            f"- High-intent rate: raw={raw_mean:.3f}  "
            f"shrunk={shrunk_mean:.3f}  "
            f"pooled={pooled:.3f} ({int(total_k)}/{int(total_n)} comments)"
        )
        top_profiles = (
            sub["profile"].fillna("(unknown)").value_counts().head(3)
        )
        lines.append(
            "- Top accounts: "
            + ", ".join(f"{p} ({n})" for p, n in top_profiles.items())
        )

        cluster_themes = (
            theme_matrix_with_cluster[
                theme_matrix_with_cluster["cluster_id"] == cid
            ]
            .drop(columns="cluster_id")
            .mean()
            .sort_values(ascending=False)
            .head(4)
        )
        lines.append("- Top themes (mean share):")
        for theme, share in cluster_themes.items():
            lines.append(f"    - {theme}: {share:.2f}")

        exemplars = sub.sort_values(
            "winner_score", ascending=False
        ).head(3)
        lines.append("- Exemplars (highest winner_score):")
        for _, row in exemplars.iterrows():
            lines.append(
                f"    - {row['input_url']}  "
                f"(winner={row['winner_score']:.2f}, "
                f"views={int(row['views']) if pd.notna(row['views']) else 'n/a'}, "
                f"profile={row['profile'] or '(unknown)'})"
            )
        lines.append("")

    (ANALYSIS_DIR / "cluster_profile.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print("[ok] cluster_profile.md")


# ---------------------------------------------------------------------------
# 4. Charts
# ---------------------------------------------------------------------------

def chart_account_winner_scores(df: pd.DataFrame) -> None:
    plot_df = df[df["has_nlp_data"]].copy()
    plot_df = plot_df.sort_values("weighted_winner_score")
    if plot_df.empty:
        return
    fig, ax = plt.subplots(figsize=(10, max(4, 0.3 * len(plot_df))))
    colors = [
        "#2a9d8f" if v >= 0 else "#e76f51"
        for v in plot_df["weighted_winner_score"]
    ]
    ax.barh(plot_df["profile"], plot_df["weighted_winner_score"], color=colors)
    ax.axvline(0, color="#333", linewidth=0.8)
    ax.set_xlabel("Weighted winner_score (comment-count weighted)")
    ax.set_title("Accounts by watch-intent signal")
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(ANALYSIS_DIR / "account_winner_scores.svg")
    plt.close(fig)
    print("[ok] account_winner_scores.svg")


def chart_account_intent_shrunk(df: pd.DataFrame, prior_mean: float) -> None:
    """Bar chart of accounts sorted by shrunk mean high-intent rate."""
    plot_df = df[df["has_nlp_data"]].copy()
    plot_df = plot_df.dropna(subset=["mean_high_intent_rate_shrunk"])
    plot_df = plot_df.sort_values("mean_high_intent_rate_shrunk")
    if plot_df.empty:
        return
    fig, ax = plt.subplots(figsize=(10, max(4, 0.3 * len(plot_df))))
    ax.barh(
        plot_df["profile"], plot_df["mean_high_intent_rate_shrunk"],
        color="#457b9d",
    )
    # Reference line: global prior mean.
    ax.axvline(
        prior_mean, color="#e63946", linestyle="--", linewidth=1.0,
        label=f"Prior mean ({prior_mean:.2f})",
    )
    ax.set_xlabel("Shrunk mean high-intent rate")
    ax.set_title("Accounts by high-intent rate (empirical-Bayes shrunk)")
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(ANALYSIS_DIR / "account_intent_shrunk.svg")
    plt.close(fig)
    print("[ok] account_intent_shrunk.svg")


def chart_intent_raw_vs_shrunk(con: duckdb.DuckDBPyConnection) -> None:
    """Scatter: raw rate vs shrunk rate per video, sized by n_labeled.

    Shows how dramatically tiny-n videos get pulled toward the prior mean.
    """
    df = con.execute(
        """
        SELECT post_id, n_labeled, raw_rate, shrunk_rate
        FROM video_intent_shrunk
        WHERE n_labeled > 0
        """
    ).fetchdf()
    if df.empty:
        return
    prior_mean = con.execute(
        "SELECT prior_mean FROM intent_prior"
    ).fetchone()[0]

    fig, ax = plt.subplots(figsize=(8, 7))
    sizes = 20 + df["n_labeled"].clip(upper=100) * 3
    ax.scatter(
        df["raw_rate"], df["shrunk_rate"],
        s=sizes, alpha=0.55, edgecolor="#333", linewidth=0.5,
        color="#2a9d8f",
    )
    ax.plot([0, 1], [0, 1], color="#888", linestyle=":", linewidth=0.8,
            label="y = x (no shrinkage)")
    ax.axhline(prior_mean, color="#e63946", linestyle="--", linewidth=0.8,
               label=f"Prior mean ({prior_mean:.2f})")
    ax.set_xlabel("Raw per-video high-intent rate")
    ax.set_ylabel("Shrunk rate (empirical Bayes)")
    ax.set_title("How much shrinkage moves each video (bubble = n comments)")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(ANALYSIS_DIR / "intent_raw_vs_shrunk.svg")
    plt.close(fig)
    print("[ok] intent_raw_vs_shrunk.svg")


def chart_theme_intent_vs_viewlift(df: pd.DataFrame) -> None:
    plot_df = df.dropna(subset=["view_lift", "high_intent_rate"]).copy()
    if plot_df.empty:
        return
    # Cap bubble sizes so one huge theme doesn't dominate.
    sizes = 30 + plot_df["n_comments"].clip(upper=300) * 2
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(
        plot_df["high_intent_rate"], plot_df["view_lift"],
        s=sizes, alpha=0.55, edgecolor="#333", linewidth=0.6,
        color="#1d3557",
    )
    ax.axhline(1.0, color="#888", linestyle="--", linewidth=0.8)
    for _, row in plot_df.iterrows():
        ax.annotate(
            row["theme"],
            (row["high_intent_rate"], row["view_lift"]),
            fontsize=8, alpha=0.8, xytext=(4, 2),
            textcoords="offset points",
        )
    ax.set_xlabel("High watch-intent rate")
    ax.set_ylabel("View lift vs median video (1.0 = baseline)")
    ax.set_title("Themes: intent-to-watch vs view-lift (bubble = n_comments)")
    ax.grid(True, linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(ANALYSIS_DIR / "theme_intent_vs_viewlift.svg")
    plt.close(fig)
    print("[ok] theme_intent_vs_viewlift.svg")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ensure_filtered_comments()
    con = build_workspace()
    report_join_gaps(con)

    # Must run before rollups so the shrunk-rate table exists.
    add_shrunk_intent(con)
    prior_mean = con.execute("SELECT prior_mean FROM intent_prior").fetchone()[0]

    accounts = account_rollup(con)
    themes = theme_rollup(con)
    cluster_videos(con)

    chart_account_winner_scores(accounts)
    chart_account_intent_shrunk(accounts, prior_mean)
    chart_theme_intent_vs_viewlift(themes)
    chart_intent_raw_vs_shrunk(con)

    con.close()
    print("\nDone. Outputs in analysis/.")


if __name__ == "__main__":
    main()
