"""Exec-facing dashboard for the Viral Micro Dramas pilot analysis.

Run:  streamlit run analysis/dashboard.py   (from the project root)

This dashboard is designed for non-technical readers. Every claim carries an
inline confidence/sample-size badge so findings can't be quoted without the
context behind them. The dashboard reads from analysis/pilot.duckdb, which is
produced by  python analysis/run_analysis.py  (must be run first).
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = Path(__file__).resolve().parent
DB_PATH = ANALYSIS_DIR / "pilot.duckdb"

# DuckDB resolves the CSV paths embedded in pilot.duckdb relative to the
# process cwd. Streamlit Cloud may launch this file from analysis/, so pin cwd.
os.chdir(PROJECT_ROOT)

# Shareability gate. Not cryptographically secure — just keeps the URL
# from being trivially scrapable when the dashboard is hosted.
DASHBOARD_PASSWORD = "dashboardisok"

st.set_page_config(
    page_title="Viral Micro Dramas — Pilot Insights",
    page_icon="📊",
    layout="wide",
)


def _auth_gate() -> bool:
    if st.session_state.get("_authed"):
        return True
    st.title("📊 Pilot Insights")
    st.caption("Enter password to view the dashboard.")
    pw = st.text_input("Password", type="password", label_visibility="collapsed")
    if pw == DASHBOARD_PASSWORD:
        st.session_state["_authed"] = True
        st.rerun()
    elif pw:
        st.error("Wrong password.")
    return False


if not _auth_gate():
    st.stop()


def _db_mtime() -> float:
    """Cache-busting key. When apply_theme_relabel.py rebuilds the DB,
    its mtime changes and the @st.cache_* entries below invalidate."""
    return DB_PATH.stat().st_mtime if DB_PATH.exists() else 0.0


@st.cache_resource
def get_connection(_mtime: float) -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        st.error(
            f"Workspace not built yet. Run `python analysis/run_analysis.py` "
            f"from the project root first (expected {DB_PATH})."
        )
        st.stop()
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data
def load_tables(_mtime: float) -> dict[str, pd.DataFrame]:
    con = get_connection(_mtime)
    return {
        "videos": con.execute("SELECT * FROM v_videos").fetchdf(),
        "comments": con.execute("SELECT * FROM raw_comments").fetchdf(),
        "clusters": con.execute(
            """
            SELECT vc.cluster_id, vc.post_id, v.profile, v.views,
                   v.winner_score, v.high_rate, v.high_rate_filtered,
                   v.n_total_text_rows AS n_comments_orig,
                   v.n_filtered_comments, v.input_url
            FROM video_clusters vc JOIN v_videos v USING (post_id)
            """
        ).fetchdf(),
        "themes_post": con.execute(
            """
            SELECT post_id, theme,
                   CAST(n AS DOUBLE) / SUM(n) OVER (PARTITION BY post_id) AS share
            FROM (
                SELECT post_id, theme_human_label AS theme, COUNT(*) AS n
                FROM raw_comments
                WHERE theme_human_label IS NOT NULL AND theme_human_label <> ''
                GROUP BY post_id, theme
            ) t
            """
        ).fetchdf(),
        "intent_prior": con.execute(
            "SELECT * FROM intent_prior"
        ).fetchdf(),
        "shrunk": con.execute(
            "SELECT * FROM video_intent_shrunk"
        ).fetchdf(),
    }


def load_account_rollup() -> pd.DataFrame:
    """Account rollup joined with own-baseline stats from the Apify scrape.

    The baseline columns let us show "pilot videos got Nx this account's
    usual views" instead of only cross-account comparisons. Missing baseline
    columns are fine — the baseline scrape only covers IG and skips handles
    with no recent video posts (private, deleted, photo-only).
    """
    path = ANALYSIS_DIR / "account_rollup.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["profile_norm"] = df["profile"].str.lower().str.lstrip("@")

    # Per-account pilot-video medians (for ratio numerator). Open our own
    # read-only connection rather than reaching into the cached one — this
    # loader runs once at startup before the cached connection is wired up.
    if DB_PATH.exists():
        con = duckdb.connect(str(DB_PATH), read_only=True)
        pilot_medians = con.execute("""
            SELECT
                lower(regexp_replace(profile, '^@', '')) AS profile_norm,
                median(views) AS pilot_median_views,
                count(*)      AS pilot_n_videos_with_views
            FROM v_videos
            WHERE views IS NOT NULL AND profile IS NOT NULL
            GROUP BY 1
        """).df()
        con.close()
        df = df.merge(pilot_medians, on="profile_norm", how="left")

    # Baselines from analysis/account_baselines.csv (built by
    # build_account_baselines.py from the Apify profile scrape)
    bpath = ANALYSIS_DIR / "account_baselines.csv"
    if bpath.exists():
        bdf = pd.read_csv(bpath)
        bdf["profile_norm"] = bdf["profile"].str.lower().str.lstrip("@")
        bdf = bdf.drop(columns=["profile"])
        df = df.merge(bdf, on="profile_norm", how="left")
        # vs-own-baseline ratio. Guard against div-by-zero.
        mv = pd.to_numeric(df.get("baseline_median_views"), errors="coerce")
        pv = pd.to_numeric(df.get("pilot_median_views"), errors="coerce")
        df["views_vs_baseline"] = pv / mv.where(mv > 0)
    return df


def load_theme_relabel_mapping() -> pd.DataFrame:
    """Produced by analysis/relabel_themes.py. Absent on fresh checkouts —
    in that case the Themes page just skips the audit-badge column."""
    path = ANALYSIS_DIR / "theme_relabel_mapping.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "is_mixed" in df.columns:
        df["is_mixed"] = df["is_mixed"].astype(str).isin(
            {"1", "True", "true"}
        )
    if "supports_share" in df.columns:
        df["supports_share"] = pd.to_numeric(
            df["supports_share"], errors="coerce"
        )
    return df


def load_filter_report_counts() -> dict[str, int] | None:
    """Parse filter_report.md for the headline counts."""
    path = ANALYSIS_DIR / "filter_report.md"
    if not path.exists():
        return None
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "Input labeled rows" in line:
            counts["input"] = int(line.split("**")[1])
        elif "Any rule" in line:
            counts["dropped"] = int(line.split("**")[1])
        elif "Surviving rows after filter" in line:
            counts["kept"] = int(line.split("**")[1])
    return counts or None


# ---------------------------------------------------------------------------
# Confidence / caveat badges
# ---------------------------------------------------------------------------

def confidence_badge(level: str) -> str:
    """Small inline confidence marker. Designed to be hard to miss."""
    styles = {
        "high": ("🟢 ROBUST", "#16a34a"),
        "medium": ("🟡 DIRECTIONAL", "#d97706"),
        "low": ("🔴 THIN — directional only", "#dc2626"),
        "dropped": ("⚫ SPAM-CONTAMINATED", "#525252"),
    }
    label, color = styles[level]
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:4px;font-size:0.75rem;font-weight:600;"
        f"margin-left:6px;white-space:nowrap;'>{label}</span>"
    )


def sample_badge(n: int, label: str = "n") -> str:
    color = "#16a34a" if n >= 30 else ("#d97706" if n >= 10 else "#dc2626")
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:4px;font-size:0.75rem;font-weight:600;"
        f"margin-left:6px;'>{label}={n}</span>"
    )


def pattern_badge(n_videos: int) -> str:
    """Second axis of confidence: how many videos back the claim.

    A high comment count on 1 video tells us about THAT video; it says
    little about whether the account/theme pattern repeats. Separates
    rate-precision from pattern-generalizability.
    """
    if n_videos >= 5:
        label, color = f"📊 BROAD ({n_videos} videos)", "#16a34a"
    elif n_videos >= 2:
        label, color = f"📊 NARROW ({n_videos} videos)", "#d97706"
    else:
        label, color = "📊 SINGLE-VIDEO", "#dc2626"
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:4px;font-size:0.75rem;font-weight:600;"
        f"margin-left:6px;white-space:nowrap;'>{label}</span>"
    )


# ---------------------------------------------------------------------------
# Links + stats utilities
# ---------------------------------------------------------------------------

def account_link(profile: str, platform: str | None = None) -> str:
    """Markdown link to a creator's profile. Everything in this pilot is
    Instagram; `platform` is accepted for future YT/TikTok support."""
    if not profile or pd.isna(profile):
        return "_unknown_"
    handle = str(profile).lstrip("@")
    plat = (platform or "instagram").lower()
    if "youtube" in plat:
        return f"[@{handle}](https://youtube.com/@{handle})"
    if "tiktok" in plat:
        return f"[@{handle}](https://tiktok.com/@{handle})"
    return f"[@{handle}](https://instagram.com/{handle}/)"


def video_link(url: str, label: str | None = None) -> str:
    if not url or pd.isna(url):
        return "_no url_"
    return f"[{label or 'open video ↗'}]({url})"


def selectable_plotly_chart(fig: go.Figure, key: str):
    """Render a Plotly chart with point-click support when available.

    Older Streamlit installs do not support `on_select`; falling back keeps
    the dashboard usable while newer installs get click-to-open behavior.
    """
    try:
        return st.plotly_chart(
            fig,
            width="stretch",
            key=key,
            on_select="rerun",
            selection_mode="points",
        )
    except TypeError:
        st.plotly_chart(fig, width="stretch")
        return None


def selected_plotly_point(event) -> dict | None:
    """Return the first clicked/selected Plotly point from Streamlit state."""
    if not event:
        return None
    try:
        points = event.selection.points
    except AttributeError:
        points = event.get("selection", {}).get("points", [])
    return points[0] if points else None


def wilson_halfwidth(p: float, n: int, z: float = 1.96) -> float:
    """Half-width of a Wilson 95% CI for a proportion.

    Uses the symmetric approximation (center-width), which is close
    enough for the precision-planning table. No scipy dependency.
    Returns 1.0 (maximum uncertainty) for missing/invalid inputs.
    """
    if n is None or pd.isna(n) or n <= 0 or p is None or pd.isna(p):
        return 1.0
    denom = 1 + z * z / n
    half = (z / denom) * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return half


def n_for_halfwidth(p: float, target_halfwidth: float, z: float = 1.96) -> int:
    """Comments needed so that 95% CI half-width ≤ target at rate p.
    Uses the standard-normal n = z² p(1-p) / halfwidth² — the Wilson
    correction is negligible at these sample sizes. For missing p, fall
    back to the pilot baseline (18%) so the row still shows a planning
    number instead of NaN."""
    if p is None or pd.isna(p):
        p = 0.18
    p = max(min(p, 0.99), 0.01)
    return int(round((z * z) * p * (1 - p) / (target_halfwidth ** 2)))


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("📊 Pilot Insights")
st.sidebar.markdown("**Viral Micro Dramas campaign**")
st.sidebar.markdown("_Report generated 2026-04-15_")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigate",
    [
        "Overview",
        "Creator Performance",
        "Audience Signals",
        "Data Quality",
    ],
)

st.sidebar.divider()
st.sidebar.markdown(
    "**How to read this**\n\n"
    "**Use now** — stable enough to act on operationally.\n\n"
    "**Test next** — promising, but needs campaign #2 validation.\n\n"
    "**Do not use** — contaminated or too thin for decisions.\n\n"
    "Open **Data Quality** before quoting a number externally."
)

# Load data once for all pages.
T = load_tables(_db_mtime())
videos_df = T["videos"]
comments_df = T["comments"]
clusters_df = T["clusters"]
accounts_df = load_account_rollup()
filter_counts = load_filter_report_counts()
prior_row = T["intent_prior"].iloc[0] if not T["intent_prior"].empty else None


# ---------------------------------------------------------------------------
# Page: Executive Summary
# ---------------------------------------------------------------------------

def page_exec() -> None:
    st.title("Pilot takeaways: reach worked, intent is under-measured")
    st.markdown(
        "**We can confidently say the pilot generated reach and exposed a "
        "measurement problem. We can identify promising intent signals, but "
        "we cannot confidently rank most individual videos or creators yet.**"
    )
    st.divider()

    total_views = int(videos_df["views"].sum(skipna=True))
    real_comments = int(videos_df["n_filtered_comments"].sum())
    orig_comments = int(videos_df["n_total_text_rows"].sum())
    low_comment_videos = int((videos_df["n_filtered_comments"] < 3).sum())
    low_comment_pct = low_comment_videos / max(len(videos_df), 1) * 100
    spam_rate = (
        filter_counts["dropped"] / filter_counts["input"] * 100
        if filter_counts else None
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Videos analyzed", f"{len(videos_df)}")
    m2.metric("Total views", f"{total_views:,}")
    m3.metric("Real viewer comments", f"{real_comments:,}")
    m4.metric(
        "Under-measured videos",
        f"{low_comment_pct:.1f}%",
        help="Share of videos with fewer than 3 real viewer comments.",
    )
    if spam_rate is not None:
        m5.metric(
            "Filtered as spam",
            f"{spam_rate:.1f}%",
            delta=f"{orig_comments - real_comments} rows removed",
            delta_color="inverse",
        )

    st.divider()

    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("The simple story")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(
                "**Use now**\n\n"
                "**Reach worked.** Views do not depend on comment volume, "
                "and the median pilot video got **1.55x** the creator's "
                "usual views."
            )
        with c2:
            st.markdown(
                "**Test next**\n\n"
                "**Intent is promising but under-measured.** "
                f"**{low_comment_pct:.1f}%** of videos have fewer than 3 "
                "real comments, so most per-video intent rates are not "
                "decision-grade."
            )
        with c3:
            st.markdown(
                "**Do not use raw leaderboards**\n\n"
                "**Measurement was polluted.** Creator/self-comment spam and "
                "tiny comment counts can make weak evidence look decisive."
            )

        st.subheader("What to do next")
        st.markdown(
            "- **Keep testing the format** because reach beat creator baselines.\n"
            "- **Separate reach KPIs from intent KPIs**; they are not the same audience behavior.\n"
            "- **Add self-comment filtering before labeling, reporting, or payout math.**\n"
            "- **Sample campaign #2 for comments on purpose** so intent can be measured, not guessed.\n"
            "- **Do not rank most videos or creators by intent yet** unless they have enough real comments."
        )
    with right:
        _mini_scatter()

    st.divider()

    st.subheader("The decision frame")
    d1, d2, d3 = st.columns(3)
    with d1:
        st.markdown(
            "**Creator picks**\n\n"
            "Use Creator Performance to find accounts that may combine "
            "reach and intent. Treat them as sampling priorities unless "
            "they have enough real comments and repeat posts."
        )
    with d2:
        st.markdown(
            "**Content signals**\n\n"
            "Use Audience Signals to understand what comments actually imply "
            "watch intent. Source-identification behavior is the best lead, "
            "but campaign #2 needs more comments to validate it."
        )
    with d3:
        st.markdown(
            "**Trust layer**\n\n"
            "Use Data Quality for the audit trail, spam rules, caveats, and "
            "raw tables. That page is the backup, not the main story."
        )


def _mini_scatter() -> None:
    """Small intent-vs-views chart for the exec page."""
    df = videos_df.dropna(subset=["views", "high_rate_filtered"]).copy()
    if df.empty:
        return
    df["log_views"] = df["views"].clip(lower=1)
    df["profile_display"] = df["profile"].fillna("(unknown)")
    df["intent_evidence"] = df["n_filtered_comments"].apply(
        lambda n: "Weak evidence (<3 comments)"
        if n < 3 else "Some evidence (3+ comments)"
    )
    fig = px.scatter(
        df,
        x="log_views",
        y="high_rate_filtered",
        size="n_filtered_comments",
        color="intent_evidence",
        color_discrete_map={
            "Weak evidence (<3 comments)": "rgba(148,163,184,0.55)",
            "Some evidence (3+ comments)": "#22d3ee",
        },
        category_orders={
            "intent_evidence": [
                "Some evidence (3+ comments)",
                "Weak evidence (<3 comments)",
            ]
        },
        custom_data=[
            "post_id",
            "input_url",
            "profile_display",
            "views",
            "n_filtered_comments",
            "high_rate_filtered",
        ],
        hover_data={
            "post_id": True,
            "profile_display": True,
            "views": ":,",
            "n_filtered_comments": True,
            "high_rate_filtered": ":.0%",
            "log_views": False,
            "input_url": False,
            "intent_evidence": True,
        },
        log_x=True,
        labels={
            "log_views": "Views (log scale)",
            "high_rate_filtered": "High-intent rate",
            "intent_evidence": "Intent evidence",
        },
        title="Views vs intent evidence (each dot = video)",
        height=320,
    )
    fig.update_traces(
        marker=dict(
            line=dict(color="#ffffff", width=1.4),
        )
    )
    fig.update_traces(
        marker=dict(opacity=0.9),
        selector=dict(name="Some evidence (3+ comments)"),
    )
    fig.update_traces(
        marker=dict(opacity=0.36, line=dict(color="rgba(255,255,255,0.35)", width=0.8)),
        selector=dict(name="Weak evidence (<3 comments)"),
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=40, b=10),
        plot_bgcolor="rgba(255,255,255,0.04)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#f8fafc"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            title=None,
        ),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.18)",
            zerolinecolor="rgba(255,255,255,0.24)",
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.18)",
            zerolinecolor="rgba(255,255,255,0.24)",
        ),
    )
    event = selectable_plotly_chart(fig, key="exec_video_scatter")
    point = selected_plotly_point(event)
    if not point:
        st.caption(
            "Faint gray dots have fewer than 3 real comments; their intent "
            "rate is not reliable. Click a dot to open that video's source post."
        )
        return

    customdata = list(point.get("customdata") or [])
    if len(customdata) < 6:
        st.caption(
            "Faint gray dots have fewer than 3 real comments; their intent "
            "rate is not reliable. Click a dot to open that video's source post."
        )
        return

    _, url, profile, views, comments, intent = customdata[:6]
    views_text = f"{int(views):,}" if pd.notna(views) else "n/a"
    comments_text = f"{int(comments):,}" if pd.notna(comments) else "n/a"
    intent_text = f"{float(intent):.0%}" if pd.notna(intent) else "n/a"
    st.markdown(
        "**Selected video:** "
        f"{video_link(url, 'open source video')}  \n"
        f"{profile} · {views_text} views · "
        f"{comments_text} real comments · {intent_text} high-intent"
    )


# ---------------------------------------------------------------------------
# Page: Two-audience problem
# ---------------------------------------------------------------------------

def page_two_audience() -> None:
    st.title("Hypothesis: Do reach and intent trade off?")
    st.info(
        "**This page explores a hypothesis, not a finding.** The reach "
        "audience (big-view videos) sits at **~18% high-intent**, which is "
        "the overall pilot baseline — reach videos are *baseline-intent*, "
        "not *low-intent*. The 'different directions' idea rests mostly on "
        "a small cluster of low-view videos that hits ~60% (n=35, 95% CI "
        "42–76%) — on different accounts, different content, different "
        "view bands. The direction is suggestive but one pilot can't tell "
        "us whether it's a real content trade-off or a confound. "
        "Campaign #2 is designed to answer this head-on by sampling "
        "30+ videos per reach quadrant."
    )
    st.markdown(
        "**The question:** do the videos that rack up views tend to rack "
        "up fewer intent comments? "
        + confidence_badge("medium"),
        unsafe_allow_html=True,
    )
    st.markdown(
        "**What \"intent\" means:** comments where viewers show they want to "
        "watch the source material (\"Movie name?\", \"Where can I find this?\"), "
        "versus passive emoji reactions and friend tags."
    )

    st.divider()

    st.subheader("What the two ends of the data look like")

    # Use the two biggest clusters for the comparison
    # Cluster 1 = high-reach, Cluster 2 (media-id) = high-intent (cluster IDs may shift)
    biggest = (
        clusters_df.groupby("cluster_id")
        .agg(
            n_videos=("post_id", "size"),
            mean_views=("views", "mean"),
            mean_intent=("high_rate_filtered", "mean"),
            total_comments=("n_filtered_comments", "sum"),
        )
        .reset_index()
        .sort_values("total_comments", ascending=False)
        .head(2)
    )
    if len(biggest) < 2:
        st.info("Not enough clusters to show comparison.")
        return

    # Decide which is reach vs intent
    reach_cluster = biggest.loc[biggest["mean_views"].idxmax()]
    intent_cluster = biggest.loc[biggest["mean_intent"].idxmax()]
    if reach_cluster["cluster_id"] == intent_cluster["cluster_id"]:
        # Fall back to 2nd by intent
        intent_cluster = biggest.sort_values(
            "mean_intent", ascending=False
        ).iloc[1]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            "### 👀 The Reach audience"
            + confidence_badge("high")
            + sample_badge(int(reach_cluster["total_comments"]), "comments"),
            unsafe_allow_html=True,
        )
        st.metric("Videos in this group", int(reach_cluster["n_videos"]))
        st.metric(
            "Average views per video",
            f"{reach_cluster['mean_views']:,.0f}",
        )
        st.metric(
            "High-intent rate",
            f"{reach_cluster['mean_intent']*100:.0f}%",
        )
        st.markdown("**What the comments look like:**")
        sample = (
            comments_df[
                (comments_df["post_id"].isin(
                    clusters_df[
                        clusters_df["cluster_id"] == reach_cluster["cluster_id"]
                    ]["post_id"]
                ))
                & (comments_df["text_raw"].str.len() > 0)
            ]
            .sample(min(5, 5), random_state=1)
        )
        for _, r in sample.iterrows():
            st.markdown(f"> {r['text_raw']}")
        st.caption(
            "Short reactions, emojis, friend tags. Big audience, passive engagement."
        )

    with c2:
        st.markdown(
            "### 🎯 The Intent audience"
            + confidence_badge("medium")
            + sample_badge(int(intent_cluster["total_comments"]), "comments"),
            unsafe_allow_html=True,
        )
        st.metric("Videos in this group", int(intent_cluster["n_videos"]))
        st.metric(
            "Average views per video",
            f"{intent_cluster['mean_views']:,.0f}",
        )
        st.metric(
            "High-intent rate",
            f"{intent_cluster['mean_intent']*100:.0f}%",
        )
        st.markdown("**What the comments look like:**")
        sample = (
            comments_df[
                comments_df["post_id"].isin(
                    clusters_df[
                        clusters_df["cluster_id"]
                        == intent_cluster["cluster_id"]
                    ]["post_id"]
                )
                & (comments_df["text_raw"].str.len() > 0)
                & (comments_df["watch_intent_label"].str.lower() == "high")
            ]
            .sample(min(5, 5), random_state=1)
        )
        for _, r in sample.iterrows():
            st.markdown(f"> {r['text_raw']}")
        st.caption(
            "Questions, source-material asks. Smaller audience, active pull."
        )

    st.divider()
    st.subheader("All videos, plotted")
    df = videos_df.dropna(subset=["views", "high_rate_filtered"]).copy()
    df["log_views"] = df["views"].clip(lower=1)
    df["profile_display"] = df["profile"].fillna("(unknown)")
    fig = px.scatter(
        df,
        x="log_views",
        y="high_rate_filtered",
        size="n_filtered_comments",
        color="profile_display",
        hover_data=["post_id", "profile_display", "n_filtered_comments"],
        log_x=True,
        labels={
            "log_views": "Views (log scale)",
            "high_rate_filtered": "High-intent rate (filtered)",
            "profile_display": "Account",
        },
        height=560,
    )
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, width='stretch')
    st.caption(
        "Bubble = video. X = views (log scale). Y = share of real audience "
        "comments showing high watch-intent. Size = number of real comments. "
        "Hover to see the video / account."
    )


# ---------------------------------------------------------------------------
# Page: Accounts
# ---------------------------------------------------------------------------

def page_accounts() -> None:
    st.title("Accounts — who to bet on")
    st.markdown(
        "Ranking accounts by how their real audiences reacted. "
        "**Before filtering**, the leaderboard was dominated by accounts "
        "posting spam on their own videos — those are now removed."
    )
    st.caption(
        "**59 creator accounts** posted videos in the pilot. 39 appear "
        "below — the other 20 had zero scraped comments across their "
        "combined 51 videos, so there's no signal to analyze."
    )
    st.divider()

    if accounts_df.empty:
        st.warning("Run the pipeline first to generate account_rollup.csv")
        return

    st.info(
        "**Two-axis confidence.** An account's intent-rate has two separate "
        "uncertainties: (1) how well we know the *rate itself* — a function "
        "of comment count — and (2) whether the rate generalizes to the "
        "account's *next* video — a function of how many videos we've "
        "seen. A creator with 87 comments on 2 videos has a precise "
        "rate for those 2 videos but tells us little about the account's "
        "repeatable pattern. Both badges shown below."
    )

    df = accounts_df[accounts_df["has_nlp_data"]].copy()
    df["total_labeled_intent"] = df["total_labeled_intent"].fillna(0).astype(int)
    df["n_videos"] = df["n_videos"].astype(int)

    def rate_conf(n: int) -> str:
        if n >= 30:
            return "high"
        if n >= 10:
            return "medium"
        return "low"

    def pattern_conf(nv: int) -> str:
        if nv >= 5:
            return "broad"
        if nv >= 2:
            return "narrow"
        return "single"

    df["_rate"] = df["total_labeled_intent"].apply(rate_conf)
    df["_pattern"] = df["n_videos"].apply(pattern_conf)

    # -----------------------------------------------------------------
    # Headline: pilot views vs each account's own usual performance
    # -----------------------------------------------------------------
    if "views_vs_baseline" in df.columns and df["views_vs_baseline"].notna().any():
        st.subheader("📈 Pilot videos vs each account's own baseline")
        st.caption(
            "For each account we scraped their last ~30 non-pilot reels "
            "and took the median. Ratio = (pilot median views) / "
            "(baseline median views). **1.0× = matched their usual; "
            ">1× = beat it; <1× = underperformed.** Compares each "
            "account to itself, so big and small accounts are on the same scale."
        )

        ratio_df = df[df["views_vs_baseline"].notna()].copy()
        n_over = int((ratio_df["views_vs_baseline"] > 1).sum())
        n_under = int((ratio_df["views_vs_baseline"] < 1).sum())
        median_ratio = ratio_df["views_vs_baseline"].median()

        m1, m2, m3 = st.columns(3)
        m1.metric("Median ratio", f"{median_ratio:.1f}×",
                  delta=f"{(median_ratio - 1) * 100:+.0f}% vs usual")
        m2.metric(
            "Beat their baseline",
            f"{n_over} / {len(ratio_df)} accounts",
        )
        m3.metric(
            "Underperformed baseline",
            f"{n_under} / {len(ratio_df)} accounts",
        )

        c_top, c_bot = st.columns(2)
        top = ratio_df.nlargest(5, "views_vs_baseline")[
            ["profile", "n_videos", "pilot_median_views",
             "baseline_median_views", "views_vs_baseline"]
        ].copy()
        top["pilot_median_views"] = top["pilot_median_views"].round().astype("Int64")
        top["baseline_median_views"] = top["baseline_median_views"].round().astype("Int64")
        top["views_vs_baseline"] = top["views_vs_baseline"].round(1).astype(str) + "×"
        top.columns = ["account", "n pilot videos", "pilot median views",
                        "usual median views", "ratio"]
        c_top.markdown("**Biggest over-performers (pilot beat their usual):**")
        c_top.dataframe(top, hide_index=True, width='stretch')

        bot = ratio_df.nsmallest(5, "views_vs_baseline")[
            ["profile", "n_videos", "pilot_median_views",
             "baseline_median_views", "views_vs_baseline"]
        ].copy()
        bot["pilot_median_views"] = bot["pilot_median_views"].round().astype("Int64")
        bot["baseline_median_views"] = bot["baseline_median_views"].round().astype("Int64")
        bot["views_vs_baseline"] = bot["views_vs_baseline"].round(2).astype(str) + "×"
        bot.columns = ["account", "n pilot videos", "pilot median views",
                        "usual median views", "ratio"]
        c_bot.markdown("**Biggest under-performers (pilot flopped vs usual):**")
        c_bot.dataframe(bot, hide_index=True, width='stretch')

        st.caption(
            f"_Baseline excludes pilot posts, photo posts, and pinned "
            f"posts (creator-curated hero content). {int(ratio_df['n_videos'].sum())} "
            f"pilot videos across {len(ratio_df)} accounts with a "
            f"baseline; 1 account lacks a baseline (private or deleted "
            f"at scrape time)._"
        )
        st.divider()

    def render_account_card(r) -> None:
        c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])
        c1.markdown(
            "**" + account_link(r["profile"]) + "**"
            + confidence_badge(r["_rate"])
            + sample_badge(int(r["total_labeled_intent"]), "comments")
            + pattern_badge(int(r["n_videos"])),
            unsafe_allow_html=True,
        )
        c2.metric("Videos", int(r["n_videos"]))
        c3.metric(
            "Median views",
            f"{int(r['median_views']):,}"
            if pd.notna(r["median_views"]) else "n/a",
        )
        c4.metric(
            "High-intent",
            f"{r['pooled_high_intent_rate']*100:.0f}%",
        )
        # vs own baseline — absent for ~1 account (private/deleted IG profile
        # at scrape time) so we render "n/a" rather than hide the column.
        vb = r.get("views_vs_baseline")
        if pd.notna(vb):
            # Anchor at 1.0x = match their usual. Color via delta: up = beat
            # their baseline, down = underperformed.
            delta = f"{(vb - 1) * 100:+.0f}%"
            c5.metric("vs own baseline", f"{vb:.1f}×", delta=delta)
        else:
            c5.metric("vs own baseline", "n/a")

    st.subheader("🏆 Strong bets — robust rate AND broad video pattern")
    strong = df[(df["_rate"] == "high") & (df["_pattern"] == "broad")]
    if strong.empty:
        st.warning(
            "**No accounts currently meet this bar.** Every account-level "
            "claim in the pilot rests on 1-4 videos. This is the clearest "
            "statement of why campaign #2 needs more videos per creator, "
            "not just more comments."
        )
    else:
        for _, r in strong.sort_values(
            "pooled_high_intent_rate", ascending=False
        ).iterrows():
            with st.container():
                render_account_card(r)

    st.divider()
    st.subheader(
        "🟡 Promising — robust rate but narrow/single video pattern"
    )
    st.caption(
        "We know the comment-level rate precisely, but across only 1-4 "
        "videos. The rate may not repeat on the next post. Treat as "
        "leads worth sampling more videos from, not committed bets."
    )
    promising = df[
        (df["_rate"] == "high")
        & (df["_pattern"].isin(["narrow", "single"]))
    ].sort_values("pooled_high_intent_rate", ascending=False)
    for _, r in promising.iterrows():
        with st.container():
            render_account_card(r)
            if r["profile"] == "moovieshub.ig":
                st.info(
                    "_83 of 87 comments come from one video (220k views, "
                    "46% intent). The other video was an 18k-view post "
                    "with 4 comments at 75%. The account's headline "
                    "number is one video's comment section — get 3-5 "
                    "more posts from this creator before committing._"
                )
            elif r["profile"] == "mensetstandards":
                st.warning(
                    "_529k views on **one** video with 3% high-intent "
                    "across 69 comments. Tells us about that video, "
                    "not the account. Still, single-video reach-only "
                    "signal is striking — worth sampling more._"
                )

    st.divider()
    st.subheader(
        "📊 Broad video pattern but thin per-video data — cheap to upgrade"
    )
    st.caption(
        "5+ videos but <30 labeled comments total. Labeling more of "
        "their existing comment sections (cheaper than finding new "
        "creators) could move them into 'strong bets.'"
    )
    cheap_upgrade = df[
        (df["_pattern"] == "broad")
        & (df["_rate"].isin(["medium", "low"]))
    ].sort_values("n_videos", ascending=False)
    for _, r in cheap_upgrade.iterrows():
        with st.container():
            render_account_card(r)

    st.divider()
    st.subheader("Directional — narrow videos, mid comment count")
    directional = df[
        (df["_rate"] == "medium") & (df["_pattern"].isin(["narrow", "single"]))
    ].sort_values("pooled_high_intent_rate", ascending=False)
    if directional.empty:
        st.caption("_None._")
    else:
        d_table = directional[
            [
                "profile", "n_videos", "total_labeled_intent",
                "pooled_high_intent_rate", "median_views",
            ]
        ].rename(columns={
            "total_labeled_intent": "comments",
            "pooled_high_intent_rate": "intent_rate",
        })
        st.dataframe(d_table, hide_index=True, width='stretch')

    st.divider()
    st.subheader("🔴 Thin on both axes — leads at best")
    thin_both = df[
        (df["_rate"] == "low")
        & (df["_pattern"].isin(["narrow", "single"]))
    ].sort_values("total_labeled_intent", ascending=False)
    t_table = thin_both[
        [
            "profile", "n_videos", "total_labeled_intent",
            "pooled_high_intent_rate",
        ]
    ].rename(columns={
        "total_labeled_intent": "comments",
        "pooled_high_intent_rate": "intent_rate",
    })
    st.dataframe(t_table, hide_index=True, width='stretch')

    st.divider()
    st.subheader("Accounts that lost rankings to spam filtering")
    st.markdown(
        "These accounts **scored very high** in the original analysis, "
        "but after removing their own self-posted SEO paragraphs, most "
        "or all of their 'audience comments' disappeared. Their previous "
        "rankings were artifacts, not real engagement."
    )
    st.markdown(
        "- " + account_link("lilly.h_7") + confidence_badge("dropped")
        + " — dropped from 7 labeled comments to **0**.<br>"
        "- " + account_link("clipper_.media") + confidence_badge("dropped")
        + " — dropped from 5 to **1**.<br>"
        "- " + account_link("spade.clipper") + confidence_badge("dropped")
        + " — dropped from 29 to **6** (23 of 29 were self-spam).<br>"
        "- " + account_link("sharp_clipper") + confidence_badge("dropped")
        + " — pattern confirmed; same SEO-paragraph templates.",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Page: Reach × Intent matrix
# ---------------------------------------------------------------------------

def page_reach_vs_intent() -> None:
    st.title("Creator Performance")
    st.markdown(
        "Creators are easier to reason about when we separate **reach** "
        "(how many people saw the videos) from **intent** (how many viewers "
        "showed they wanted the source material). The goal is the top-right "
        "bucket, but most accounts still need more posts or comments before "
        "we can treat the pattern as repeatable."
    )
    st.info(
        "**Decision rule:** use the quadrant to identify leads, then use the "
        "confidence and pattern badges to decide whether the lead is ready "
        "to act on or only ready to test again."
    )
    st.warning(
        "**Important context:** most videos are under-measured for intent. "
        "80 of 113 videos have fewer than 3 real comments, so creator "
        "rankings are only meaningful when comments are pooled across enough "
        "real audience reactions."
    )
    st.divider()

    if accounts_df.empty:
        st.warning("Run the pipeline first to generate account_rollup.csv.")
        return

    df = accounts_df[accounts_df["has_nlp_data"]].copy()
    df["total_labeled_intent"] = df["total_labeled_intent"].fillna(0).astype(int)
    df["n_videos"] = df["n_videos"].astype(int)

    def conf_for(n: int) -> str:
        if n >= 30:
            return "high"
        if n >= 10:
            return "medium"
        return "low"

    def pattern_for(nv: int) -> str:
        if nv >= 5:
            return "broad"
        if nv >= 2:
            return "narrow"
        return "single"

    df["_conf"] = df["total_labeled_intent"].apply(conf_for)
    df["_pattern"] = df["n_videos"].apply(pattern_for)

    # Quadrant thresholds. Pilot baseline intent ≈ 18%; pilot median views
    # across accounts-with-NLP ≈ 7.7k.
    baseline_intent = 0.18
    views_median = float(df["median_views"].median())

    # ---------- Chart ----------
    st.subheader("The reach × intent map")
    plot = df.dropna(subset=["median_views", "pooled_high_intent_rate"]).copy()
    plot = plot[plot["median_views"] > 0]  # log-scale guard
    conf_label = {"high": "🟢 Robust (30+ comments)",
                  "medium": "🟡 Directional (10-29)",
                  "low": "🔴 Thin (<10)"}
    plot["confidence"] = plot["_conf"].map(conf_label)
    fig = px.scatter(
        plot,
        x="median_views",
        y="pooled_high_intent_rate",
        size="total_labeled_intent",
        color="confidence",
        text="profile",
        custom_data=["profile"],
        log_x=True,
        category_orders={"confidence": list(conf_label.values())},
        color_discrete_map={
            conf_label["high"]: "#16a34a",
            conf_label["medium"]: "#d97706",
            conf_label["low"]: "#dc2626",
        },
        labels={
            "median_views": "Median views per video (log scale)",
            "pooled_high_intent_rate": "Pooled high-intent rate",
            "total_labeled_intent": "Comments",
        },
        height=560,
    )
    fig.add_vline(x=views_median, line_dash="dash", line_color="gray",
                  annotation_text=f"median {views_median:,.0f}",
                  annotation_position="top")
    fig.add_hline(y=baseline_intent, line_dash="dash", line_color="gray",
                  annotation_text=f"pilot baseline {baseline_intent:.0%}",
                  annotation_position="right")
    fig.update_traces(textposition="top center", textfont_size=10)
    event = selectable_plotly_chart(fig, key="creator_reach_intent_map")
    st.caption(
        f"Bubble = account. Bubble size = number of labeled comments "
        f"(confidence). Dashed lines = pilot median views "
        f"({views_median:,.0f}) and pilot baseline high-intent rate "
        f"({baseline_intent:.0%}). Click an account dot to show its videos."
    )
    point = selected_plotly_point(event)
    if point:
        selected_profile = (point.get("customdata") or [None])[0]
        if selected_profile:
            profile_norm = str(selected_profile).lower().lstrip("@")
            account_videos = videos_df[
                videos_df["profile"]
                .fillna("")
                .str.lower()
                .str.lstrip("@")
                .eq(profile_norm)
            ].copy()
            account_videos = account_videos.sort_values(
                ["views", "n_filtered_comments"],
                ascending=[False, False],
                na_position="last",
            )
            st.markdown(f"**Videos for {account_link(selected_profile)}**")
            if account_videos.empty:
                st.info("No linked videos found for this account.")
            else:
                for _, video in account_videos.iterrows():
                    views = (
                        f"{int(video['views']):,}"
                        if pd.notna(video.get("views")) else "n/a"
                    )
                    n_comments = video.get("n_filtered_comments")
                    comments = int(n_comments) if pd.notna(n_comments) else 0
                    intent = video.get("high_rate_filtered")
                    intent_text = (
                        f"{float(intent):.0%}"
                        if pd.notna(intent) else "n/a"
                    )
                    st.markdown(
                        f"- {video_link(video.get('input_url'), 'open video')} "
                        f"· {views} views · {comments} real comments · "
                        f"{intent_text} high-intent"
                    )

    st.divider()

    # ---------- Quadrant cards ----------
    def classify(r):
        hv = r["median_views"] >= views_median
        hi = r["pooled_high_intent_rate"] >= baseline_intent
        if hv and hi:
            return "both"
        if hv and not hi:
            return "reach_only"
        if hi and not hv:
            return "intent_only"
        return "neither"

    df["_quadrant"] = df.apply(classify, axis=1)

    def fmt_account_row(r) -> str:
        badge = confidence_badge(r["_conf"])
        sb = sample_badge(int(r["total_labeled_intent"]), "comments")
        pb = pattern_badge(int(r["n_videos"]))
        views = (f"{int(r['median_views']):,}"
                 if pd.notna(r["median_views"]) else "n/a")
        return (
            f"- **{account_link(r['profile'])}** {badge} {sb} {pb} · "
            f"{views} median views · "
            f"{r['pooled_high_intent_rate']*100:.0f}% high-intent"
        )

    st.subheader("The four buckets")

    q_both = df[df["_quadrant"] == "both"].sort_values(
        "pooled_high_intent_rate", ascending=False)
    st.markdown("### 🏆 Both — reach AND intent")
    st.caption(
        "The bucket campaign #2 should sample more videos from. **None of "
        "the accounts here currently have BROAD video coverage** — every "
        "'both' account is narrow or single-video. These are promising "
        "leads, not committed bets."
    )
    if q_both.empty:
        st.write("_No accounts currently in this bucket._")
    else:
        st.markdown("\n".join(fmt_account_row(r) for _, r in q_both.iterrows()),
                    unsafe_allow_html=True)

    q_reach = df[df["_quadrant"] == "reach_only"].sort_values(
        "median_views", ascending=False)
    st.markdown("### 📺 Reach only — eyeballs without intent")
    st.caption(
        "Big audiences, baseline-or-below intent. Good for awareness-style "
        "goals; weak for a watch-intent-focused campaign."
    )
    if q_reach.empty:
        st.write("_No accounts currently in this bucket._")
    else:
        st.markdown("\n".join(fmt_account_row(r) for _, r in q_reach.iterrows()),
                    unsafe_allow_html=True)

    q_intent = df[df["_quadrant"] == "intent_only"].sort_values(
        "pooled_high_intent_rate", ascending=False)
    st.markdown("### 🎯 Intent only — niche/loyal audiences")
    st.caption(
        "Small audiences showing above-baseline intent. Almost all are thin-n "
        "— treat as leads worth a second look, not commitments."
    )
    if q_intent.empty:
        st.write("_No accounts currently in this bucket._")
    else:
        st.markdown("\n".join(fmt_account_row(r) for _, r in q_intent.iterrows()),
                    unsafe_allow_html=True)

    q_neither = df[df["_quadrant"] == "neither"].sort_values(
        "total_labeled_intent", ascending=False)
    with st.expander(f"⬇ Neither — underperformers ({len(q_neither)} accounts)"):
        if q_neither.empty:
            st.write("_None._")
        else:
            st.markdown(
                "\n".join(fmt_account_row(r) for _, r in q_neither.iterrows()),
                unsafe_allow_html=True,
            )

    st.divider()

    # ---------- Confidence-needed table ----------
    st.subheader("How much more data would we need to place these confidently?")
    st.markdown(
        "Right now intent rates on most accounts are **noisy**. The 95% "
        "confidence interval around a 20% rate at n=20 is roughly ±17 "
        "percentage points — wide enough to cross the quadrant line either "
        "way. This table shows what it'd take to shrink that uncertainty."
    )

    plan = df.copy()
    plan["current_ci_halfwidth"] = plan.apply(
        lambda r: wilson_halfwidth(
            r["pooled_high_intent_rate"], int(r["total_labeled_intent"])
        ),
        axis=1,
    )
    plan["n_needed_10pp"] = plan.apply(
        lambda r: n_for_halfwidth(r["pooled_high_intent_rate"], 0.10), axis=1
    )
    plan["n_needed_5pp"] = plan.apply(
        lambda r: n_for_halfwidth(r["pooled_high_intent_rate"], 0.05), axis=1
    )
    plan["more_needed_10pp"] = (
        plan["n_needed_10pp"] - plan["total_labeled_intent"]
    ).clip(lower=0).astype(int)
    plan["more_needed_5pp"] = (
        plan["n_needed_5pp"] - plan["total_labeled_intent"]
    ).clip(lower=0).astype(int)

    show_cols = [
        "profile", "total_labeled_intent", "pooled_high_intent_rate",
        "current_ci_halfwidth", "more_needed_10pp", "more_needed_5pp",
    ]
    tbl = plan.sort_values("total_labeled_intent", ascending=False)[show_cols].rename(
        columns={
            "total_labeled_intent": "current_n",
            "pooled_high_intent_rate": "intent_rate",
            "current_ci_halfwidth": "current_±95%CI",
            "more_needed_10pp": "+comments for ±10pp",
            "more_needed_5pp": "+comments for ±5pp",
        }
    )
    # Format display
    tbl["intent_rate"] = tbl["intent_rate"].apply(lambda x: f"{x*100:.0f}%")
    tbl["current_±95%CI"] = tbl["current_±95%CI"].apply(
        lambda x: f"±{x*100:.0f}pp"
    )
    st.dataframe(tbl, hide_index=True, width='stretch')

    n_robust = int((plan["total_labeled_intent"] >= 100).sum())
    n_accts = len(plan)
    total_gap_10pp = int(plan["more_needed_10pp"].sum())
    st.markdown(
        f"**Takeaway for campaign #2 sizing:** only **{n_robust}** of "
        f"{n_accts} accounts currently clears 100 comments. To place every "
        f"account inside a ±10 percentage-point CI, we'd need roughly "
        f"**{total_gap_10pp:,} additional labeled comments** — roughly "
        f"{total_gap_10pp / max(plan['total_labeled_intent'].sum(), 1):.1f}× "
        f"the current pilot. A cheaper approach: target ~100 comments per "
        f"account on the ~10 accounts that landed in the 'both' or 'reach "
        f"only' buckets (~1,000 comments) and skip the thin-n accounts."
    )


# ---------------------------------------------------------------------------
# Page: Themes
# ---------------------------------------------------------------------------

@st.cache_data
def _load_curated_exemplars(_mtime: float) -> pd.DataFrame:
    """Exemplars pre-ranked by cosine similarity to the theme-label embedding.
    Produced by analysis/build_theme_exemplars.py. Absent on fresh checkouts;
    in that case the dashboard falls back to the confidence-based heuristic."""
    path = ANALYSIS_DIR / "theme_exemplars.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


@st.cache_data
def _theme_exemplars(theme: str, limit: int = 3, _mtime: float = 0.0) -> pd.DataFrame:
    """Top canonical comments for a theme, with source video URL.

    Primary source: theme_exemplars.csv (comments ranked by embedding
    similarity to the theme label itself — directly shows how well the
    cluster supports its name). Fallback: confidence-based heuristic on
    comments_df. _mtime is a cache-bust key tied to the DuckDB mtime."""
    curated = _load_curated_exemplars(_mtime)
    if not curated.empty and theme in set(curated["theme"]):
        df = curated[curated["theme"] == theme].sort_values("rank").head(limit).copy()
        # Backfill columns the renderer expects.
        if "watch_intent_label" not in df.columns:
            df["watch_intent_label"] = None
        return df.reset_index(drop=True)

    df = comments_df[
        (comments_df["theme_human_label"] == theme)
        & (comments_df["text_raw"].fillna("").str.len() > 0)
    ].copy()
    if df.empty:
        return df
    if "is_canonical" in df.columns:
        df["_is_canon"] = df["is_canonical"].fillna(False).astype(int)
    else:
        df["_is_canon"] = 0
    if "watch_intent_confidence" in df.columns:
        df["_conf"] = pd.to_numeric(df["watch_intent_confidence"], errors="coerce").fillna(0)
    else:
        df["_conf"] = 0.0
    df = df.sort_values(["_is_canon", "_conf"], ascending=[False, False])
    return df.drop_duplicates(subset=["text_raw"]).head(limit)


def page_themes() -> None:
    st.title("Themes — what audiences actually say")
    st.markdown(
        "Every comment was tagged with a conversational theme "
        "(what kind of reaction it is). We can then ask: which themes "
        "correlate with watch-intent, and which are just background noise?"
    )

    st.warning(
        "**View-lift is correlation, not cause.** A theme with high view-lift "
        "might *cause* the views (e.g., 'Movie Name Requests' comments show "
        "up because viewers are hooked and trying to find the source), or it "
        "might be a *passenger* signal (e.g., 'Smooth Move Compliments' "
        "probably comments on a character's charm — which is the real driver, "
        "and would occur whether or not the comment did). We cannot "
        "distinguish these from one pilot — treat view-lift as 'worth "
        "investigating,' not 'causally confirmed.'"
    )
    st.divider()

    theme_path = ANALYSIS_DIR / "theme_rollup.csv"
    if not theme_path.exists():
        st.warning("Run the pipeline first.")
        return
    themes = pd.read_csv(theme_path)
    themes = themes.sort_values("n_comments", ascending=False)

    # Theme-label audit (from relabel_themes.py). Keyed by post-relabel name,
    # so rows retain their audit flag after apply_theme_relabel.py has run.
    relabel_df = load_theme_relabel_mapping()
    audit_by_label: dict[str, dict] = {}
    if not relabel_df.empty and "new_label" in relabel_df.columns:
        for _, r in relabel_df.iterrows():
            key = str(r.get("new_label") or "").strip()
            if not key:
                continue
            audit_by_label[key] = {
                "is_mixed": bool(r.get("is_mixed", False)),
                "supports_share": r.get("supports_share"),
                "current": str(r.get("current_label") or "").strip(),
                "notes": str(r.get("notes") or "").strip(),
            }

    def conf_level(n: int) -> str:
        if n >= 50:
            return "high"
        if n >= 15:
            return "medium"
        return "low"

    themes["_conf"] = themes["n_comments"].apply(conf_level)

    st.subheader("Themes by comment volume")
    for _, r in themes.iterrows():
        lift = r.get("view_lift")
        audit = audit_by_label.get(str(r["theme"]).strip())
        with st.container():
            cols = st.columns([3, 1, 1, 1])
            label_html = (
                f"**{r['theme']}**"
                + confidence_badge(r["_conf"])
                + sample_badge(int(r["n_comments"]), "comments")
            )
            if audit and audit["is_mixed"]:
                label_html += (
                    "<span style='background:#525252;color:white;padding:2px 8px;"
                    "border-radius:4px;font-size:0.75rem;font-weight:600;"
                    "margin-left:6px;white-space:nowrap;'>⚠️ NO SINGLE TOPIC</span>"
                )
            cols[0].markdown(label_html, unsafe_allow_html=True)
            cols[1].metric("Videos", int(r["n_videos_appearing_in"]))
            cols[2].metric(
                "High-intent",
                f"{r['high_intent_rate']*100:.0f}%",
            )
            cols[3].metric(
                "View lift",
                f"{lift:.1f}x" if pd.notna(lift) else "n/a",
            )
        # Outlier warning: big lift on thin sample
        if pd.notna(lift) and lift >= 2.0 and int(r["n_comments"]) < 30:
            st.error(
                f"⚠️ **Thin-sample outlier.** View-lift of {lift:.1f}x on "
                f"only {int(r['n_comments'])} comments across "
                f"{int(r['n_videos_appearing_in'])} videos — likely driven "
                f"by one or two viral videos. Check the scatter before "
                f"quoting this number."
            )
        # Label audit note — shown when relabeling reclassified this cluster
        if audit:
            share = audit.get("supports_share")
            share_txt = (
                f" (audit: label describes ~{share*100:.0f}% of sampled comments)"
                if share is not None and pd.notna(share) else ""
            )
            if audit["is_mixed"]:
                st.warning(
                    f"**Cluster has no single topic.** Originally labeled "
                    f"\"{audit['current']}\"; re-audit found the cluster is a "
                    f"grab-bag of short reactions with no shared subject. "
                    f"Treat stats for this row as aggregate background noise, "
                    f"not a content-type finding.{share_txt}"
                )
            elif audit["current"] and audit["current"] != str(r["theme"]).strip():
                st.info(
                    f"Relabeled from \"{audit['current']}\" — the original "
                    f"name came from the LLM seeing only 6 centroid-nearest "
                    f"comments and didn't describe the bulk of the cluster."
                    f"{share_txt}"
                )
        # Named callouts (kept from v1, now secondary to the auto warning)
        if r["theme"] == "Movie Name Requests":
            st.success(
                "⭐ **The clearest intent signal in the pilot.** "
                "Viewers asking 'Movie name?' / 'What show is this?' "
                "show clear watch-intent. Prioritize content that "
                "triggers this reaction pattern."
            )
        elif r["theme"] == "MIXED":
            st.info(
                "ℹ️ This is the pilot's noise bucket — half of all labeled "
                "comments land here with no shared topic. Its stats are "
                "roughly baseline by construction; don't read content "
                "signal into them."
            )

        # Exemplar comments — show a few inline, rest behind an expander.
        exemplars = _theme_exemplars(r["theme"], limit=8, _mtime=_db_mtime())

        def _intent_tag(label) -> str:
            if not isinstance(label, str):
                return "·"
            wi = label.lower()
            return (
                "🟢" if wi == "high"
                else "⚪" if wi == "med"
                else "🔴" if wi == "low" else "·"
            )

        def _render_example(ex) -> None:
            tag = _intent_tag(ex.get("watch_intent_label"))
            text = str(ex["text_raw"])[:240]
            link = video_link(ex.get("input_url"), "video")
            sim = ex.get("similarity") if hasattr(ex, "get") else None
            if sim is not None and pd.notna(sim):
                sim_str = (
                    f" <span style='color:#6b7280;font-size:0.75rem;'>"
                    f"sim {float(sim):.2f}</span>"
                )
            else:
                sim_str = ""
            st.markdown(
                f"{tag} _{text}_{sim_str}  &nbsp; {link}",
                unsafe_allow_html=True,
            )

        if exemplars is not None and not exemplars.empty:
            curated = (
                "similarity" in exemplars.columns
                and exemplars["similarity"].notna().any()
            )
            heading = (
                "**Example comments** _(most on-label first)_:"
                if curated else "**Example comments:**"
            )
            st.markdown(heading)
            inline_n = min(3, len(exemplars))
            for _, ex in exemplars.head(inline_n).iterrows():
                _render_example(ex)
            if len(exemplars) > inline_n:
                with st.expander(
                    f"{len(exemplars) - inline_n} more example(s)"
                ):
                    for _, ex in exemplars.iloc[inline_n:].iterrows():
                        _render_example(ex)
            st.caption(
                "🟢 high-intent · ⚪ medium · 🔴 low · "
                + ("ranked by cosine similarity to the theme label "
                   "(higher sim = more directly supports the name)"
                   if curated else
                   "sorted by canonical + classifier confidence")
            )

    st.divider()
    st.subheader("Intent vs view-lift by theme")
    plot_df = themes.dropna(subset=["high_intent_rate", "view_lift"]).copy()
    fig = px.scatter(
        plot_df,
        x="high_intent_rate",
        y="view_lift",
        size="n_comments",
        text="theme",
        hover_data=["n_videos_appearing_in"],
        labels={
            "high_intent_rate": "High-intent rate",
            "view_lift": "View lift (1.0 = baseline)",
        },
        height=520,
    )
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray")
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, width='stretch')
    st.caption(
        "Themes in the top-right pull both audience AND views. "
        "Movie Name Requests is the only theme with meaningful volume "
        "sitting there."
    )


def page_audience_signals() -> None:
    st.title("Audience Signals")
    st.markdown(
        "This page translates comments into campaign learning. The useful "
        "distinction is simple: some videos earn **attention**, while a "
        "smaller set earns **source-seeking intent**. Because most videos "
        "have very few real comments, these signals are best treated as "
        "campaign #2 hypotheses rather than final content rules."
    )
    st.divider()

    theme_path = ANALYSIS_DIR / "theme_rollup.csv"
    if not theme_path.exists():
        st.warning("Run the pipeline first.")
        return

    themes = pd.read_csv(theme_path)
    themes["theme_display"] = themes["theme"].replace(
        {
            "Media Identification": "Movie name / source requests",
            "Smooth and Youthful": "Smooth-move compliments",
            "Exclamations and Questions": "Short reactions / punctuation",
            "AI or Fake Content": "AI or fake-content questions",
            "Observations on Women": "Comments about the woman",
            "Wordplay on 'Knee'": "Knee wordplay",
        }
    )
    themes = themes.sort_values("n_comments", ascending=False)

    intent_theme = themes[
        themes["theme"].isin(["Movie Name Requests", "Media Identification"])
    ]
    if intent_theme.empty:
        intent_rate = None
        intent_n = None
        intent_videos = None
    else:
        intent_row = intent_theme.iloc[0]
        intent_rate = float(intent_row["high_intent_rate"])
        intent_n = int(intent_row["n_comments"])
        intent_videos = int(intent_row["n_videos_appearing_in"])

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            "**Use now**\n\n"
            "**Passive reactions dominate reach.** The biggest comment "
            "buckets are short reactions, emojis, tags, and generic "
            "compliments. They are useful engagement, but weak evidence "
            "that viewers want the source."
        )
    with c2:
        if intent_rate is not None:
            st.markdown(
                "**Test next**\n\n"
                f"**Source requests are the clearest intent signal.** "
                f"This bucket shows **{intent_rate:.0%} high-intent** "
                f"across **{intent_n} comments** on **{intent_videos} videos**."
            )
        else:
            st.markdown(
                "**Test next**\n\n"
                "**Source requests are the clearest intent signal.** "
                "They are the audience behavior to deliberately test in "
                "campaign #2."
            )
    with c3:
        st.markdown(
            "**Do not over-read**\n\n"
            "Theme lift is correlation. A comment theme can be a symptom "
            "of a good clip rather than the reason the clip performed."
        )

    st.divider()
    st.subheader("Theme map")
    plot_df = themes.dropna(subset=["high_intent_rate"]).copy()
    fig = px.scatter(
        plot_df,
        x="n_comments",
        y="high_intent_rate",
        size="n_videos_appearing_in",
        text="theme_display",
        log_x=True,
        labels={
            "n_comments": "Comment volume (log scale)",
            "high_intent_rate": "High-intent rate",
            "n_videos_appearing_in": "Videos",
        },
        height=480,
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Top-right means a theme has both volume and intent. Bubble size is "
        "how many videos the theme appeared on."
    )

    st.divider()
    st.subheader("What the comments are telling us")
    priority = [
        "Media Identification",
        "Movie Name Requests",
        "AI or Fake Content",
        "Exclamations and Questions",
        "Smooth and Youthful",
    ]
    shown = themes[themes["theme"].isin(priority)].copy()
    shown["_order"] = shown["theme"].apply(
        lambda x: priority.index(x) if x in priority else 99
    )
    shown = shown.sort_values("_order")
    for _, r in shown.iterrows():
        with st.expander(
            f"{r['theme_display']} · {int(r['n_comments'])} comments · "
            f"{float(r['high_intent_rate']):.0%} high-intent",
            expanded=r["theme"] in ["Media Identification", "Movie Name Requests"],
        ):
            if r["theme"] in ["Media Identification", "Movie Name Requests"]:
                st.markdown(
                    "**Interpretation:** this is the cleanest watch-intent "
                    "behavior in the pilot. Campaign #2 should deliberately "
                    "test content that makes viewers ask for the source."
                )
            elif r["theme"] == "AI or Fake Content":
                st.markdown(
                    "**Interpretation:** viewers are noticing synthetic or "
                    "fake-looking content. Track this as a quality risk, not "
                    "as positive intent."
                )
            elif r["theme"] == "Exclamations and Questions":
                st.markdown(
                    "**Interpretation:** high-volume background engagement. "
                    "Useful for reach, weak for downstream intent."
                )
            else:
                st.markdown(
                    "**Interpretation:** likely a reaction to a character or "
                    "moment, not a reliable campaign KPI by itself."
                )

            exemplars = _theme_exemplars(r["theme"], limit=4, _mtime=_db_mtime())
            if exemplars is not None and not exemplars.empty:
                st.markdown("**Example comments:**")
                for _, ex in exemplars.iterrows():
                    st.markdown(
                        f"- _{str(ex['text_raw'])[:180]}_ "
                        f"{video_link(ex.get('input_url'), 'video')}"
                    )


# ---------------------------------------------------------------------------
# Page: Clusters
# ---------------------------------------------------------------------------

def page_clusters() -> None:
    st.title("Content Clusters — groups of similar videos")
    st.info(
        "**This page is exploratory — skip it if you want the operational "
        "answer** (that's on 'Reach × Intent'). Clusters here are a lens on "
        "the *structure* of the content, not a ranking."
    )
    st.markdown(
        "**Themes vs clusters — what's the difference?**\n\n"
        "- **Themes** are *topics people mention in comments* (e.g., "
        "'Movie Name Requests', 'Critical Comments About Woman'). A single video's "
        "comments span many themes.\n"
        "- **Clusters** are *groups of videos that attract similar mixes of "
        "themes*. Each video belongs to exactly one cluster.\n\n"
        "If Cluster 1 and Cluster 2 look similar to you, that's itself a "
        "finding — the underlying content isn't cleanly differentiable by "
        "comment theme alone. More or different content-level metadata "
        "would be needed to get crisper separation."
    )
    st.markdown(
        "We grouped the 113 videos by the *kinds of reactions* they "
        "attracted (not by their content metadata — we don't have good "
        "metadata yet). Six clusters emerged."
    )
    st.divider()

    cluster_agg = (
        clusters_df.groupby("cluster_id")
        .agg(
            n_videos=("post_id", "size"),
            mean_views=("views", "mean"),
            mean_intent=("high_rate_filtered", "mean"),
            total_comments=("n_filtered_comments", "sum"),
        )
        .reset_index()
        .sort_values("total_comments", ascending=False)
    )

    def cluster_conf(n: int) -> str:
        if n >= 50:
            return "high"
        if n >= 15:
            return "medium"
        return "low"

    cluster_path = ANALYSIS_DIR / "cluster_profile.md"
    if cluster_path.exists():
        cluster_profile_text = cluster_path.read_text(encoding="utf-8")
    else:
        cluster_profile_text = ""

    for _, row in cluster_agg.iterrows():
        cid = int(row["cluster_id"])
        n = int(row["total_comments"])
        conf = cluster_conf(n)
        with st.expander(
            f"Cluster {cid}  ·  {int(row['n_videos'])} videos  ·  "
            f"{n} real comments  ·  "
            f"{row['mean_intent']*100:.0f}% high-intent",
            expanded=(conf == "high"),
        ):
            st.markdown(
                f"**Confidence**: {confidence_badge(conf)}"
                + sample_badge(n, "comments"),
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            c1.metric("Videos", int(row["n_videos"]))
            c2.metric(
                "Mean views",
                f"{row['mean_views']:,.0f}"
                if pd.notna(row["mean_views"]) else "n/a",
            )
            c3.metric("High-intent rate", f"{row['mean_intent']*100:.0f}%")

            # Top themes for this cluster (pooled)
            pids = clusters_df[clusters_df["cluster_id"] == cid][
                "post_id"
            ].tolist()
            theme_counts = (
                comments_df[comments_df["post_id"].isin(pids)]
                .dropna(subset=["theme_human_label"])
                .query("theme_human_label != ''")
                .groupby("theme_human_label")
                .size()
                .sort_values(ascending=False)
                .head(3)
            )
            if not theme_counts.empty:
                st.markdown("**Top themes:**")
                for t, c in theme_counts.items():
                    st.markdown(f"- {t} ({int(c)} comments)")

            # Example real comments
            sample_comments = (
                comments_df[
                    (comments_df["post_id"].isin(pids))
                    & (comments_df["text_raw"].str.len() > 0)
                ]
                .sort_values("watch_intent_confidence", ascending=False)
                .head(4)
            )
            if not sample_comments.empty:
                st.markdown("**Example comments:**")
                cluster_post_urls = (
                    clusters_df[clusters_df["cluster_id"] == cid]
                    .set_index("post_id")["input_url"].to_dict()
                )
                for _, r in sample_comments.iterrows():
                    wi = (r["watch_intent_label"] or "").lower()
                    tag = (
                        "🟢" if wi == "high" else "⚪" if wi == "med" else "🔴"
                    )
                    url = cluster_post_urls.get(r["post_id"])
                    link = f" &nbsp; {video_link(url, 'video')}" if url else ""
                    st.markdown(
                        f"{tag} _{str(r['text_raw'])[:200]}_{link}",
                        unsafe_allow_html=True,
                    )

            # Account concentration
            top_profiles = (
                clusters_df[clusters_df["cluster_id"] == cid]["profile"]
                .dropna()
                .value_counts()
                .head(3)
            )
            if not top_profiles.empty:
                st.markdown("**Most-represented accounts:**")
                for p, n_p in top_profiles.items():
                    st.markdown(
                        f"- {account_link(p)} — {n_p} video(s)",
                        unsafe_allow_html=True,
                    )


# ---------------------------------------------------------------------------
# Page: Data Quality & Caveats
# ---------------------------------------------------------------------------

def page_caveats() -> None:
    st.title("Data Quality & Caveats")
    st.markdown(
        "This page is the one to read before using these findings to "
        "make a commitment. Every analysis has caveats — here are ours."
    )
    st.divider()

    st.header("The contamination we found and removed")
    if filter_counts:
        c1, c2, c3 = st.columns(3)
        c1.metric("Original comments labeled", filter_counts["input"])
        c2.metric(
            "Dropped as spam",
            filter_counts["dropped"],
            delta=f"{filter_counts['dropped']/filter_counts['input']*100:.1f}% of total",
            delta_color="inverse",
        )
        c3.metric("Real viewer comments", filter_counts["kept"])
    st.markdown(
        """
The original data contained **creator-posted SEO spam** — accounts that
posted LLM-generated paragraph essays on their *own* videos to inflate
engagement metrics. The NLP pipeline had no way to know, so it labeled
these as "high-intent audience reactions," which propagated into every
downstream ranking.

We dropped these rows before re-running the analysis. The rules were:

1. **Drop if `is_created_by_media_owner=True`** in the raw Apify scrape — 87 rows.
2. **Drop if the same long text (≥80 chars) appears on 2+ videos** (cross-video promo spam) — 22 rows.
3. **Drop if the commenter's username matches any known creator account** from the campaign report — 76 rows.

Most rows matched more than one rule. **27 videos lost every single
comment** after filtering — their "comment sections" as scraped contained
only creator self-posts.
        """
    )

    st.divider()

    st.header("Sample-size problems (that remain even after cleaning)")
    col1, col2 = st.columns(2)
    with col1:
        buckets = (
            videos_df["n_filtered_comments"]
            .apply(
                lambda n: "0"
                if n == 0
                else "1-2"
                if n <= 2
                else "3-5"
                if n <= 5
                else "6-10"
                if n <= 10
                else "11-30"
                if n <= 30
                else "30+"
            )
            .value_counts()
            .reindex(["0", "1-2", "3-5", "6-10", "11-30", "30+"])
            .fillna(0)
            .astype(int)
        )
        fig = px.bar(
            x=buckets.index,
            y=buckets.values,
            labels={"x": "Comments per video", "y": "Number of videos"},
            title="How many videos have how many comments",
            height=360,
        )
        fig.update_traces(marker_color="#1d3557")
        st.plotly_chart(fig, width='stretch')
    with col2:
        st.markdown(
            """
**Why this matters:**

- Most videos have fewer than 10 real comments. Any per-video
  "high-intent rate" built from 1-2 comments can't be trusted —
  one flip changes it 50%.

- To correct for this we apply **empirical-Bayes shrinkage**: every
  video gets pulled toward the global average (~18%) in proportion
  to how little data backs it.

- **Cluster- and theme-level findings are stable** because they pool
  across dozens to hundreds of comments. **Per-video rankings are
  noisy** and we advise against them.

**Rule of thumb:**
- <10 comments → hypothesis only
- 10-30 comments → directional
- 30+ comments → robust
            """
        )

    st.divider()

    st.header("Things we did NOT fix")
    st.markdown(
        """
Transparent about what's *not* in this analysis:

- **We didn't re-run the embeddings pipeline** — we just filtered the
  existing labels. If the original labels were biased by the spam
  (e.g. the "Father-Daughter Relationships" theme itself was created
  because of the spam), filtering doesn't undo that. A clean-then-embed
  run would produce slightly different themes. Low priority.
- **LLM confidence scores are ignored.** A high-confidence "high" and
  a low-confidence "high" count equally. Could weight them.
- **`winner_score` is still the legacy formula** from the original
  pipeline. It's tainted by the same spam rows. Treat it as reference,
  not authoritative.
- **Payout data is sparse** — only 27 of 113 videos are in the
  submissions feed. Any payout-based finding is thin.
- **20 of 50 roster accounts** had zero scraped comments across 51
  combined videos and are absent from the analysis. No insight into
  why — could be scrape failure, short-lived posts, or low-engagement
  content. Worth investigating before campaign #2.
- **Non-English comments** were labeled by the same English rubric.
  Meaningful share of comments are in other languages.
        """
    )


# ---------------------------------------------------------------------------
# Page: Browse raw numbers
# ---------------------------------------------------------------------------

def page_browse() -> None:
    st.title("Browse: the underlying numbers")
    st.markdown("For anyone who wants to verify findings directly.")

    tab_videos, tab_accounts, tab_comments = st.tabs(
        ["Videos", "Accounts", "Comments"]
    )

    with tab_videos:
        show = videos_df[
            [
                "post_id", "profile", "views", "n_total_text_rows",
                "n_filtered_comments", "high_rate", "high_rate_filtered",
                "winner_score", "top_theme_1",
            ]
        ].rename(columns={
            "n_total_text_rows": "comments_orig",
            "n_filtered_comments": "comments_clean",
            "high_rate": "intent_orig",
            "high_rate_filtered": "intent_clean",
        })
        st.dataframe(show, width='stretch', hide_index=True)

    with tab_accounts:
        if not accounts_df.empty:
            show = accounts_df[
                [
                    "profile",
                    "n_videos",
                    "total_views",
                    "median_views",
                    "total_labeled_intent",
                    "pooled_high_intent_rate",
                    "mean_high_intent_rate_shrunk",
                    "theme_mix_top3",
                ]
            ]
            st.dataframe(show, width='stretch', hide_index=True)

    with tab_comments:
        profiles = ["(all)"] + sorted(
            videos_df["profile"].dropna().unique().tolist()
        )
        chosen = st.selectbox("Filter by account", profiles)
        show = comments_df[
            [
                "post_id", "text_raw", "sentiment_label",
                "watch_intent_label", "theme_human_label",
            ]
        ].copy()
        if chosen != "(all)":
            pids = set(
                videos_df[videos_df["profile"] == chosen]["post_id"]
            )
            show = show[show["post_id"].isin(pids)]
        show = show[show["text_raw"].str.len() > 0]
        st.caption(f"Showing {len(show)} real viewer comments after spam filter.")
        st.dataframe(show, width='stretch', hide_index=True)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

PAGES = {
    "Overview": page_exec,
    "Creator Performance": page_reach_vs_intent,
    "Audience Signals": page_audience_signals,
    "Data Quality": page_caveats,
}

PAGES[page]()
