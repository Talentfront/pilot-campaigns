# Pilot campaigns — analysis pipeline

End-to-end walkthrough of how raw campaign data becomes the findings on the
Streamlit dashboard. Aimed at a new contributor landing in this repo who
wants to understand what runs, in what order, and why — without reading
every script.

For how to *run* the dashboard, see [DASHBOARD.md](DASHBOARD.md).
For methodology decisions and known limitations, see the bottom of this file.

---

## At a glance

```
CSVs + Apify scrape
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ 1. Ingest + normalize + deduplicate to canonicals    │  comment_audience_analysis.py
├──────────────────────────────────────────────────────┤
│ 2. Embed every canonical (Qwen3-Embedding-8B)        │
├──────────────────────────────────────────────────────┤
│ 3. Label intent/sentiment per canonical              │
│    (prototype cosine + softmax + LLM adjudication)   │
├──────────────────────────────────────────────────────┤
│ 4. Theme discovery (k-means #1 on embeddings)        │
├──────────────────────────────────────────────────────┤
│ 5. Per-video rollup (winner_score, theme shares)     │
└──────────────────────────────────────────────────────┘
        │  analysis_comment_level.csv + analysis_post_level.csv
        ▼
┌──────────────────────────────────────────────────────┐
│ 6. Spam filter (3 rules, drops ~11% of rows)         │  build_filtered_comments.py
└──────────────────────────────────────────────────────┘
        │  analysis_comment_level_filtered.csv
        ▼
┌──────────────────────────────────────────────────────┐
│ 7. HDBSCAN audit (re-embed + re-cluster filtered)    │  recluster_comments.py
│    → theme_relabel_mapping.csv                       │  relabel_themes.py
└──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ 8. DuckDB workspace (joins everything)               │  build_workspace.sql
├──────────────────────────────────────────────────────┤
│ 9. Account baselines (scrape each creator's usual)   │  scrape_account_baselines.py
├──────────────────────────────────────────────────────┤
│ 10. Rollups + EB shrinkage + video clustering (#2)   │  run_analysis.py
└──────────────────────────────────────────────────────┘
        │  account_rollup.csv + theme_rollup.csv + video_clusters.csv
        ▼
┌──────────────────────────────────────────────────────┐
│ 11. Streamlit dashboard                              │  dashboard.py
└──────────────────────────────────────────────────────┘
```

---

## Phase 1 — Raw inputs

**Sources.** Three things arrive outside the pipeline:

1. **`Viral_Micro_Dramas_campaign_report_2026-04-13.xlsx - All Clips.csv`** — the agency's campaign report. One row per clip: URL, profile, platform, views, likes, comments, shares, engagement rate, date. This is the *reach* data.
2. **`submissions - submissions.csv`** — the submissions feed. URL, views, likes, payout in USD. This is the *money* data.
3. **`apify_full_results_datadoping.json`** — Apify scrape of every video's comment section. One row per comment / reply / caption, with `text`, `username`, `comment_id`, `is_created_by_media_owner`, etc. This is the *voice* data.

At this point we know who posted, who got views, who got paid — but nothing about what audiences said.

---

## Phase 2 — Prepare comments for labeling

**Script.** [comment_audience_analysis.py](../comment_audience_analysis.py)

**Step 1 — filter + normalize.** Keep only `content_type ∈ {comment, reply}`. Lowercase, strip URLs and `@mentions`, collapse whitespace.

**Step 2 — canonicalize.** Hash each normalized text. Identical texts collapse into one *canonical* row. "Movie name?" appearing 30 times becomes one canonical with `count=30`. This is a cost optimization: labeling and embedding happen *per canonical*, and the labels propagate back to every row that shares that canonical.

Numbers for the pilot: 923 rows → 483 canonicals (~39% dedupe savings).

---

## Phase 3 — Embed every canonical

**Step 3.** Send all canonical texts to **Qwen3-Embedding-8B** via OpenRouter. Each canonical comes back as a ~4000-dimensional vector. Comments with similar meaning land in nearby regions of this space.

This step is the foundation for everything downstream. Every piece of analysis that happens after this uses these embeddings — directly or indirectly.

Seed phrases for the prototype labels (next phase) are embedded in the same batch so their vectors are in the same space as the comment vectors.

---

## Phase 4 — Label intent and sentiment

**Step 4 — prototype vectors.** Hand-written seed phrases define what each label looks like:

| Label dimension | Seed examples |
|---|---|
| `watch_intent = high` | "where can I watch this", "what series is this", "need to watch now" |
| `watch_intent = med` | "looks interesting", "maybe later", "curious about this" |
| `watch_intent = low` | "not watching", "skip this", "boring no thanks" |
| `sentiment = pos` | "love this", "this is great", "amazing hilarious" |
| `sentiment = neu` | "okay sure", "what is this", "interesting" |
| `sentiment = neg` | "this is bad", "cringe", "hate this" |

For each label, we average its seed embeddings into one *prototype vector* — the centroid of what that label looks like in embedding space.

**Step 5 — cosine similarity.** For every canonical, compute cosine similarity against each prototype. Produces raw scores like `{high: 0.42, med: 0.31, low: 0.18}`.

**Step 6 — softmax.** Convert raw similarities into a probability distribution that sums to 1: `{high: 0.52, med: 0.31, low: 0.17}`. The winning label's probability becomes `confidence`; the gap between the top two is `margin`.

**Step 7 — confusion heuristic.** Separately from the ML labels, flag any comment whose text contains `?`, `huh`, `confused`, `what`, `explain`, or similar as having `confusion_flag=True`. Rule-based, not model-based.

**Step 8 — LLM adjudication.** Canonicals where `confidence < 0.55` or `margin < 0.10` are "uncertain." Up to 250 of them are batched to **Gemini 2.5 Flash Lite** for a re-label, which overrides the prototype result.

**Output.** Every canonical now has `(sentiment_label, watch_intent_label, confusion_flag, label_source)`. These propagate back to every row that shares the canonical.

---

## Phase 5 — Theme discovery (k-means #1)

**Step 9 — cluster.** Run k-means on the canonical embeddings with `k = max(3, min(12, √n_canonical))` — at pilot scale that's k=10. Cosine distance. Every canonical is assigned to exactly one cluster. **This is what a "theme" is.** Themes are defined by the geometry of the embedding space, not by keywords.

**Step 10 — provisional keyword label.** For each cluster, tokenize member texts, drop stopwords, take the top 3 tokens. Gives a robot-readable label like `movie_name_series`.

**Step 11 — LLM naming.** Send each cluster's top keywords + 6 sample quotes to Gemini. It returns a human label like "Media Identification" and a one-sentence description. **The LLM is naming boxes whose contents are already fixed by k-means** — it doesn't change who-is-in-what-cluster.

**Step 12 — theme confidence per comment.** For each comment, compute cosine similarity between its embedding and its cluster's centroid, normalize to [0, 1]. That's `theme_confidence`. Used for ranking exemplar quotes.

---

## Phase 6 — Per-video rollup

**Step 13 — post-level aggregation.** For each video, count the distribution of labels and themes across its comments:

- `high_rate` = fraction of labeled comments labeled `watch_intent=high`
- `neg_or_conf_rate` = fraction labeled negative *or* flagged confused
- `winner_score = high_rate - 0.5 * neg_or_conf_rate` — reward intent, penalize negativity (weighted half)
- `top_theme_1/2/3` + shares

**Outputs.** [analysis_comment_level.csv](../analysis_comment_level.csv) (per comment, with labels and theme), [analysis_post_level.csv](../analysis_post_level.csv) (per video), [analysis_summary.md](../analysis_summary.md) (human-readable winners / laggards / top themes from this first pass).

**This was the state of the pipeline on day one** — before anyone noticed the spam.

---

## Phase 7 — Spam discovery and filter

**Script.** [build_filtered_comments.py](build_filtered_comments.py)

**How it was caught.** One k-means theme ("Step-by-Step Instructions") had exemplars like *"Check out my account"* and *"I'm gonna use this one"*. That's not audience reaction — that's creator self-promo. Inspection of the raw Apify data revealed ~11% of comments were posted by the video's own creator or by other campaign creators cross-promoting.

**Step 14 — three filter rules.** A row is dropped if *any* of:

1. `is_created_by_media_owner = True` in the raw Apify record.
2. Text length ≥80 chars and the same text appears on 2+ distinct videos (cross-video promo duplication).
3. Commenter `username` matches any known creator handle from All Clips or the Apify caption data.

**Output.** [analysis_comment_level_filtered.csv](analysis_comment_level_filtered.csv) (surviving rows with their original labels intact), [filter_report.md](filter_report.md) (rule-hit counts and top offenders).

**Important.** The filter drops rows; it does not re-embed or re-cluster. Every surviving row still has its day-one k-means theme assignment. ~821 of 923 rows survive.

---

## Phase 8 — HDBSCAN audit

**Scripts.** [recluster_comments.py](recluster_comments.py), [relabel_themes.py](relabel_themes.py), [apply_theme_relabel.py](apply_theme_relabel.py)

**Purpose.** Sanity-check whether the day-one k-means themes hold up once the spam is gone. K-means is forced to produce k clusters even when the data doesn't support them — we wanted a *second opinion* from an algorithm that's allowed to say "these points don't really cluster."

**Step 15 — re-embed filtered canonicals.** Take the surviving canonicals, re-embed them with Qwen3 (same model). Cache to [recluster_embeddings.npy](recluster_embeddings.npy).

**Step 16 — HDBSCAN cluster.** `min_cluster_size=10`, Euclidean distance on L2-normalized vectors (≡ cosine). HDBSCAN explicitly produces a *noise* label (`-1`) for points that don't fit any dense region — the opposite of k-means' forced assignment.

Result on the pilot (453 canonicals): **3 clusters + 387 noise points**. Coherence via DBCV:

| # | Members | Coherence | LLM label | supports |
|---|---:|---:|---|---:|
| 0 | 28 | 0.80 | Asking for Movie Name | 95% |
| 1 | 22 | 0.78 | MIXED (punctuation-only) | 15% |
| 2 | 16 | 0.84 | Praising Smooth Execution | 100% |

**Step 17 — coherence gate.** Clusters with coherence < 0.55 auto-flagged MIXED without paying an LLM call. Surviving clusters are sent to the LLM with 15 centroid-nearest + 15 random members and a 70% "supports-share" requirement.

**Step 18 — relabel mapping.** [theme_relabel_mapping.csv](theme_relabel_mapping.csv) records the audit's decisions: rename some k-means themes (e.g. "Media Identification" → "Movie Name Requests"), collapse three into a MIXED bucket (`Exclamations and Questions`, `Step-by-Step Instructions`, `Personal Statements` — all scored ≤0.20 for topical coherence).

**Important.** The HDBSCAN cluster assignments are *not* used as the theme-of-record. The dashboard still reads k-means assignments; the audit only contributes renaming and MIXED-flagging. See the "Methodology decisions" section below for why — and what would change in campaign #2.

**Outputs.** [canonical_reclustered.csv](canonical_reclustered.csv), [recluster_report.md](recluster_report.md), [theme_relabel_mapping.csv](theme_relabel_mapping.csv).

---

## Phase 9 — Account baselines

**Scripts.** [scrape_account_baselines.py](scrape_account_baselines.py), [build_account_baselines.py](build_account_baselines.py)

For each of the ~55 creator handles in the pilot, scrape their last ~30 non-pilot reels via Apify. Compute each account's own baseline median views on its typical content. This feeds the headline "pilot videos beat each creator's own baseline 1.55×" finding — every account is benchmarked against itself, killing the confound from account size.

**Outputs.** [account_baselines_raw.csv](account_baselines_raw.csv), [account_baselines.csv](account_baselines.csv).

---

## Phase 10 — DuckDB workspace + rollups

**Scripts.** [build_workspace.sql](build_workspace.sql), [run_analysis.py](run_analysis.py)

**Step 19 — build_workspace.sql.** Stitches the CSVs into one DuckDB database ([pilot.duckdb](pilot.duckdb)):
- `raw_clips`, `raw_submissions`, `raw_posts`, `raw_comments` — views over the CSVs.
- `post_rates_filtered` — recomputes per-video intent/neg-conf rates from the *filtered* comments.
- `v_videos` — master per-video view with profile, views, payout, intent rates (both original and filtered).
- `v_video_themes` — flattened (profile, post, theme, share).

**Step 20 — empirical-Bayes shrinkage.** Per-video intent rates with n=1 comment are unusable. Fit a Beta(α, β) prior to per-video rates via method-of-moments, shrink each video's rate to `(k_high + α) / (n + α + β)`. Videos with lots of comments barely move; videos with few get pulled toward the global mean (~18%). Written to table `video_intent_shrunk`.

**Step 21 — account rollup.** Per profile: video count, total views, shrunk mean intent rate, pooled intent rate, weighted winner score, top-3 theme mix. → [account_rollup.csv](account_rollup.csv).

**Step 22 — theme rollup.** Per theme: n_comments, n_videos, high_intent_rate, account-concentration HHI, view lift vs median, payout lift. → [theme_rollup.csv](theme_rollup.csv).

**Step 23 — video clustering (k-means #2).** This is a *second* k-means, unrelated to the comment-theme clustering. Each video is represented as a ~10-dim vector of its theme shares (e.g. 77% Movie Name Requests, 10% Smooth, ...). K-means on those vectors with k swept 3–6, picked by silhouette. For the pilot: 6 video-clusters. Output: [video_clusters.csv](video_clusters.csv), [cluster_profile.md](cluster_profile.md). These are the video archetypes the dashboard's "Content Clusters" page shows — reach-audience videos (cluster 1, mean 214k views, 18% intent) vs intent-audience videos (cluster 2, mean 15k views, 60% intent).

**Step 24 — charts.** SVGs for the dashboard and for external sharing: `account_winner_scores.svg`, `account_intent_shrunk.svg`, `intent_raw_vs_shrunk.svg`, `theme_intent_vs_viewlift.svg`.

**Step 25 — filtered summary.** [write_filtered_summary.py](write_filtered_summary.py) regenerates a per-theme summary on the post-filter, post-relabel data. Output: [analysis_summary_filtered.md](analysis_summary_filtered.md). The pre-filter [analysis_summary.md](../analysis_summary.md) is kept on disk as an audit trail.

---

## Phase 11 — Dashboard

**Script.** [dashboard.py](dashboard.py) (Streamlit).

Reads DuckDB + the CSV rollups. Every page reads **filtered comments** with **k-means themes named by the relabel mapping**. Pages:

- **Executive Summary** — headline findings with confidence badges.
- **Two-Audience** — side-by-side of the reach vs intent clusters (video-cluster k-means output).
- **Accounts** — ranked by shrunk intent rate, with two-axis confidence (rate precision × video count).
- **Reach × Intent** — the four-quadrant map.
- **Themes** — every theme with view-lift, sample size, exemplar comments. Uses the relabel mapping's rename/MIXED decisions.
- **Content Clusters** — expanders for each of the 6 video-clusters (k-means #2 output).
- **Data Quality & Caveats** — filter rules, sample-size distribution, what we didn't fix.
- **Browse: raw numbers** — searchable per-video table.

---

## Methodology decisions worth knowing

**Why canonicals for clustering, rows for reporting.** We cluster at the *canonical* level so "Movie name?" appearing 30 times counts as one point in embedding space, not 30 piled-up copies. This discovers semantic *structure*. For reporting, we multiply back out by row count so the headline numbers reflect audience attention volume. Standard NLP type/token separation.

**Why k-means is the theme-of-record despite the HDBSCAN audit.** K-means forces every comment into a cluster — required for downstream math, because the video-cluster step needs per-video theme-share vectors that sum to 1. HDBSCAN would leave 85% of canonicals as noise, breaking that downstream dependency. The audit exists to rename/flag the k-means output, not replace it. A cleaner future design (see below) would use HDBSCAN + an explicit "Other" noise bucket.

**Why the filter drops rows and doesn't re-cluster.** Re-embedding + re-clustering the filtered set would produce *different* themes than what's on the dashboard. Keeping the day-one assignments (with relabel decisions on top) keeps the dashboard consistent with how findings were initially framed. The audit confirmed the surviving themes were coherent, so re-clustering would have been mostly churn.

**Why two k-means runs instead of one algorithm for everything.**
- **K-means #1 on comment embeddings** → discovers *themes* (what people talk about). Input: canonical embeddings. Output: ~10 themes.
- **K-means #2 on video theme-share vectors** → discovers *video archetypes* (what mix of reactions a video attracts). Input: per-video shares across the themes from k-means #1. Output: 6 video-clusters.

They operate on completely different data shapes and answer different questions.

**Why `winner_score = high_rate - 0.5 * neg_or_conf_rate`.** Positive signal (viewers asking for source material) is harder to elicit than negative signal, so it gets full weight; negative/confusion is half-weighted. Not derived from first principles — it's a heuristic inherited from the day-one pipeline. Flagged on the dashboard's Data Quality page as "legacy formula, tainted by spam, treat as reference not authoritative."

---

## Known limitations and what campaign #2 should change

1. **K-means overreach.** At pilot scale (~500 canonicals), k-means produced 3 junk "themes" that had to be post-hoc collapsed to MIXED. The HDBSCAN audit (`recluster_comments.py`) is essentially the right algorithm for theme discovery — the missing piece is an `apply_recluster.py` that promotes its output from sidecar to primary, with HDBSCAN noise points routed to a single "Other" bucket so the video-cluster step downstream still works.

2. **`min_cluster_size=10` is too strict.** HDBSCAN at the pilot scale leaves semantically coherent small themes (Knee Pun Wordplay, AI Content Questions) in the noise bucket because they don't have enough dense canonicals to form a cluster. Lowering to `min_cluster_size=5` would likely recover them at campaign #2 scale.

3. **Top-post concentration metric.** `top_post_share` can be misleading when a theme has a long tail of 1-comment videos. `write_filtered_summary.py` now also reports `top_post_share_ge3` (concentration restricted to videos with ≥3 rows in the theme). The dashboard's Themes page should probably surface this too.

4. **Spam filter runs *after* labeling.** The day-one LLM already paid tokens to label spam rows that we then discarded. For campaign #2, the filter should run *before* labeling to cut costs and prevent spam from influencing theme discovery in the first place.

5. **20 of 55 roster accounts had zero scraped comments** across 51 videos — unclear whether scrape failures, short-lived posts, or genuinely dead engagement. Worth investigating before relying on account-level rankings.

6. **Non-English comments** were labeled by the same English-centric rubric. A meaningful share of comments are in other languages.

---

## Reproducing end-to-end

From project root:

```bash
# Requires OPENROUTER_API_KEY for embeddings + LLM steps.
python comment_audience_analysis.py         # Phases 1-6
python analysis/build_filtered_comments.py  # Phase 7
python analysis/recluster_comments.py       # Phase 8 (optional — audit)
python analysis/relabel_themes.py           # Phase 8 (optional — produces mapping)
python analysis/apply_theme_relabel.py      # Phase 8 (optional — applies mapping)
python analysis/scrape_account_baselines.py # Phase 9 (slow — rate-limited Apify)
python analysis/build_account_baselines.py  # Phase 9
python analysis/run_analysis.py             # Phase 10 (incl. k-means #2)
python analysis/write_filtered_summary.py   # Phase 10 (filtered summary md)
python -m streamlit run analysis/dashboard.py  # Phase 11
```

`run_analysis.py` regenerates the filter, the DuckDB workspace, the rollups, the charts, and the video-cluster assignments in one command. Run it any time the filtered CSV or the relabel mapping changes.
