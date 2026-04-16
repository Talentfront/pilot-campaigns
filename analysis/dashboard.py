"""Exec-facing dashboard for the Viral Micro Dramas pilot analysis.

Run:  streamlit run analysis/dashboard.py   (from the project root)

This dashboard is designed for non-technical readers. Every claim carries an
inline confidence/sample-size badge so findings can't be quoted without the
context behind them. The dashboard reads from analysis/pilot.duckdb, which is
produced by  python analysis/run_analysis.py  (must be run first).
"""

from __future__ import annotations

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
    path = ANALYSIS_DIR / "account_rollup.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


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
        "Executive Summary",
        "Hypothesis: Reach vs Intent",
        "Accounts — who to bet on",
        "Reach × Intent — who to bet on",
        "Themes — what works",
        "Content Clusters",
        "Data Quality & Caveats",
        "Browse: raw numbers",
    ],
)

st.sidebar.divider()
st.sidebar.markdown(
    "**Confidence legend (two axes)**\n\n"
    "_Rate precision — how well we know the number:_\n\n"
    "🟢 **Robust** — 30+ comments\n\n"
    "🟡 **Directional** — 10-29 comments\n\n"
    "🔴 **Thin** — <10 comments\n\n"
    "⚫ **Contaminated** — disappeared after spam removal\n\n"
    "_Pattern breadth — is it a repeatable pattern or one video:_\n\n"
    "📊🟢 **Broad** — 5+ videos\n\n"
    "📊🟡 **Narrow** — 2-4 videos\n\n"
    "📊🔴 **Single-video** — 1 video (the number describes that video, "
    "not a pattern)"
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
    st.title("Viral Micro Dramas — What the pilot told us")
    st.markdown(
        "_One-pager for campaign decisions. Every claim is tagged with "
        "its confidence level. Drill into each finding via the sidebar._"
    )
    st.divider()

    # Top metrics strip.
    m1, m2, m3, m4 = st.columns(4)
    total_views = int(videos_df["views"].sum(skipna=True))
    m1.metric("Videos analyzed", f"{len(videos_df)}")
    m2.metric("Total views", f"{total_views:,}")
    real_comments = int(videos_df["n_filtered_comments"].sum())
    orig_comments = int(videos_df["n_total_text_rows"].sum())
    m3.metric(
        "Real viewer comments",
        f"{real_comments:,}",
        delta=f"-{orig_comments - real_comments} dropped as spam",
        delta_color="inverse",
    )
    if filter_counts:
        pct = filter_counts["dropped"] / filter_counts["input"] * 100
        m4.metric("Spam rate", f"{pct:.1f}%", help="Share of comments flagged as creator-posted spam")

    st.divider()

    st.header("What this pilot can and can't tell you")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(
            "**One pilot, 113 videos, 821 real audience comments after "
            "spam removal — enough to spot contamination and generate "
            "hypotheses, not enough to recommend a strategy.**"
        )
        st.markdown(
            "The median video has ~5 real comments. Most account-level "
            "rates have 95% confidence intervals wider than ±15 "
            "percentage points — wide enough that the same data could "
            "support opposite conclusions depending on which slice you "
            "pick. The clearest signal in the data turned out to be a "
            "**data-quality problem** (creator self-spam, see below), "
            "not a content one."
        )
        st.markdown(
            "**How to read this dashboard:** treat every finding below "
            "as a hypothesis for campaign #2 to confirm or kill, not as "
            "an answer. The one exception — the contamination finding — "
            "is flagged explicitly. Everything else is directional."
        )
    with col2:
        _mini_scatter()

    st.divider()

    st.header("What we actually learned")

    st.subheader("✅ The one robust finding")
    st.markdown(
        "**Comment-section gaming is real and material.** "
        + confidence_badge("high")
        + "<br><br>"
        + "**Four creator accounts** ("
        + account_link("spade.clipper") + ", "
        + account_link("lilly.h_7") + ", "
        + account_link("clipper_.media") + ", "
        + account_link("sharp_clipper")
        + ") were caught posting LLM-generated SEO paragraphs on their own "
        + "videos. **~11% of all labeled comments** were creator self-spam, "
        + "and it dominated the original rankings — three of those four "
        + "accounts lost effectively all their 'audience engagement' after "
        + "filtering. **Actionable now:** audit how payouts were calculated "
        + "against this pilot, and add a self-comment filter to the pipeline "
        + "before campaign #2.",
        unsafe_allow_html=True,
    )

    st.divider()

    st.subheader("🔬 Hypotheses worth testing in campaign #2")
    st.caption(
        "None of these clear the bar for a commitment. They're the leads "
        "a second pilot should be *designed* to confirm or kill — not "
        "findings to act on now."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            '**"Movie name?" content may drive intent** '
            + confidence_badge("medium")
            + sample_badge(35, "comments")
            + "<br><br>"
            + "11 videos where viewers ask for the source material show "
            + "~60% high-intent (CI 42-76%). But this may be a *passenger* "
            + "signal — viewers might comment because the content hooked "
            + "them, not because the comment itself indicates anything "
            + "special. **Test:** commission 10+ videos explicitly "
            + "designed to trigger source-ID questions and see if the "
            + "rate holds.",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            "**"
            + account_link("moovieshub.ig")
            + " had one strong video** "
            + confidence_badge("medium")
            + sample_badge(87, "comments")
            + "<br><br>"
            + "One post (220k views, 46% high-intent on 83 comments) is "
            + "the pilot's best single both-sides example. The account's "
            + "other video was an 18k-view dud. **Not an account pattern "
            + "yet.** **Test:** get 3-5 more posts from this creator "
            + "before committing budget.",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            "**Reach and intent may trade off** "
            + confidence_badge("medium")
            + "<br><br>"
            + "The 27 high-view videos sit at baseline ~18% intent; a "
            + "separate group of 11 low-view videos hits ~60%. Different "
            + "videos, different accounts — directionally a real split, "
            + "but one pilot can't tell us whether this is a content "
            + "choice or a confound. **Test:** sample 30+ videos per "
            + "quadrant in campaign #2 so the split can be measured, "
            + "not inferred.",
            unsafe_allow_html=True,
        )

    st.divider()

    st.header("How we'll make campaign #2 conclusive")
    st.markdown(
        "The pilot surfaced specific, fixable reasons the evidence is thin. "
        "Each one has a concrete change for the next run:"
    )

    f1, f2 = st.columns(2)
    with f1:
        st.markdown(
            "**📈 More videos, more accounts, more comments — sampled "
            "deliberately**<br>"
            "The three biggest gaps all come down to scale: only 1 of "
            "20+ accounts clears 100 comments; the reach/intent split "
            "rests on 11 videos; the 'Movie name?' hypothesis is 35 "
            "comments across 11 videos. Campaign #2 needs roughly "
            "**~1,000 additional labeled comments** concentrated on "
            "~10 accounts in the 'both' or 'reach-only' buckets, plus "
            "**30+ videos per reach quadrant** sampled on purpose (not "
            "whichever videos happened to exist), plus **10+ "
            "commissioned videos designed to trigger source-ID "
            "comments** to test whether 'Movie name?' comments *cause* "
            "intent or just ride along. Same workstream, three things "
            "it buys us.",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<br>**🧹 Move the spam filter upstream of labeling**<br>"
            "We did filter out the ~11% creator self-spam for this "
            "report — but *after* the LLM had already labeled it and "
            "after the themes/clusters were built on top of it. The "
            "three filter rules (self-comment flag, cross-video "
            "duplicate detection, known-creator username list) will "
            "run *before* labeling in campaign #2 so the LLM never "
            "sees contaminated rows. Cuts LLM spend and removes the "
            "need to re-audit findings after the fact.",
            unsafe_allow_html=True,
        )
    with f2:
        st.markdown(
            "**📈 Benchmark each video against its own account's "
            "baseline**<br>"
            "Right now we compare videos across accounts — so a 200k-view "
            "post looks 'high reach' whether it came from an account that "
            "usually gets 5k views (a massive hit) or one that usually "
            "gets 500k (an underperformer). Campaign #2 will pull each "
            "creator's recent-posts average and express every pilot video "
            "as a **lift vs. that account's baseline**, not a raw number. "
            "Same fix for comment volume. Separates 'content that worked "
            "unusually well' from 'content on an already-big account.'",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<br>**🏷️ Audit the embeddings for residual spam influence "
            "(likely low impact)**<br>"
            "The original theme clusters were built *including* the "
            "spam, so in principle themes like 'Father-Daughter "
            "Relationships' could partly reflect SEO-paragraph content. "
            "In practice we already re-clustered on the filtered data "
            "and the surviving themes (Movie Name Requests, Praising "
            "Smooth Execution) are coherent and stable — so a full "
            "re-embed probably wouldn't change much. We'll do a "
            "targeted audit rather than a rerun.",
            unsafe_allow_html=True,
        )

    st.divider()

    st.header("Top-line caveats")
    st.markdown(
        """
- **Sample sizes are small.** 821 real viewer comments across 113 videos — median of ~5 comments per video. Per-video rankings are noisy; cluster- and theme-level findings are stable.
- **11% of original comments were spam** (creators posting on their own videos). This invalidated the original analysis's top rankings entirely.
- **Findings are directional, not precise.** Use this to set priorities for the next campaign, not to rank individual videos or commit budget against specific accounts with <30 comments.
        """
    )


def _mini_scatter() -> None:
    """Small intent-vs-views chart for the exec page."""
    df = videos_df.dropna(subset=["views", "high_rate_filtered"]).copy()
    if df.empty:
        return
    df["log_views"] = df["views"].clip(lower=1)
    fig = px.scatter(
        df,
        x="log_views",
        y="high_rate_filtered",
        size="n_filtered_comments",
        log_x=True,
        color_discrete_sequence=["#1d3557"],
        labels={
            "log_views": "Views (log scale)",
            "high_rate_filtered": "High-intent rate",
        },
        title="Views vs intent (each dot = video)",
        height=320,
    )
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width='stretch')


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

    def render_account_card(r) -> None:
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
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
    st.title("Reach × Intent — who to bet on")
    st.markdown(
        "Every account, plotted by the two things the campaign actually "
        "cares about: **reach** (how many people see their videos) and "
        "**intent** (how many of those viewers actively want to watch the "
        "source). Four buckets emerge."
    )
    st.info(
        "**Read the pattern badge alongside the quadrant.** An account in "
        "the top-right with a 📊🔴 SINGLE-VIDEO badge is a promising "
        "single post, not a repeatable account pattern. The quadrant "
        "tells you where the rate sits; the pattern badge tells you how "
        "far you can generalize from it."
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
    st.plotly_chart(fig, width='stretch')
    st.caption(
        f"Bubble = account. Bubble size = number of labeled comments "
        f"(confidence). Dashed lines = pilot median views "
        f"({views_median:,.0f}) and pilot baseline high-intent rate "
        f"({baseline_intent:.0%}). Top-right = the gold bucket."
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
    "Executive Summary": page_exec,
    "Hypothesis: Reach vs Intent": page_two_audience,
    "Accounts — who to bet on": page_accounts,
    "Reach × Intent — who to bet on": page_reach_vs_intent,
    "Themes — what works": page_themes,
    "Content Clusters": page_clusters,
    "Data Quality & Caveats": page_caveats,
    "Browse: raw numbers": page_browse,
}

PAGES[page]()
