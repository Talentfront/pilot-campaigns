# Repository Chronology

This document explains how the pilot-campaigns repo got to its current shape:
what was tried, what was kept, and which artifacts are current versus
historical. For the current runnable pipeline, see [PIPELINE.md](PIPELINE.md).
For the detailed theme-methodology experiments, see
[THEME_METHODOLOGY.md](THEME_METHODOLOGY.md).

## 1. Campaign Inputs Arrived

The repo started as a workspace for a Viral Micro Dramas pilot campaign.
Three input families came in from outside the analysis code:

- Campaign reach data: `data/raw/Viral_Micro_Dramas_campaign_report_2026-04-13.xlsx - All Clips.csv`
- Submission and payout data: `data/raw/submissions - submissions.csv`
- Public comment scrape data from Apify actors: `data/apify/`

At this point the campaign had reach, engagement, and payout facts, but no
structured read on what viewers were saying or whether comments implied real
watch intent.

## 2. Comment Scraper Trials

The Apify artifacts show that multiple Instagram comment scrapers were tested:

- `apidojo`
- `datadoping`
- `scrapesmith`

Each has pilot and/or full-run input, result, metadata, and status files in
`data/apify/`. The current analysis standardized on Datadoping:

- Main current scrape: `data/apify/apify_full_results_datadoping.json`
- Actor notes: `datadoping_instagram_comments_replies_scraper.md`

The scraper comparison itself is mostly implied by files rather than narrated
in depth. The important operational result is that downstream scripts now read
the Datadoping full result as the source comment corpus.

## 3. Day-One NLP Pipeline

The first major analysis pass lives in `comment_audience_analysis.py`.

That script:

- Read the Datadoping Apify scrape.
- Kept comment and reply rows.
- Normalized text.
- Collapsed duplicate normalized comments into canonical texts.
- Embedded canonicals with Qwen3-Embedding-8B through OpenRouter.
- Labeled sentiment and watch intent with prototype-vector cosine similarity.
- Sent low-confidence or low-margin labels to an LLM adjudication pass.
- Ran k-means over canonical embeddings to discover comment themes.
- Used an LLM to name those clusters.
- Rolled results back out to comment-level and post-level CSVs.

The original outputs are kept in `data/processed/`:

- `analysis_comment_level.csv`
- `analysis_post_level.csv`
- `analysis_summary.md`

Those files are historical but still important because later filtering and
audits are built on top of that first labeled corpus.

## 4. Spam and Creator-Promo Discovery

The first analysis surfaced a suspicious theme: comments that looked like
"check out my account" or other promotional/self-referential language were
being counted as audience signal.

That revealed a data-quality problem: some rows were creator-posted comments,
cross-video creator promotion, or comments from campaign creator handles.
Those rows could inflate watch-intent metrics if treated as ordinary audience
reactions.

The discovery is documented in generated reports, especially:

- `analysis/reports/analysis_v2_summary.md`
- `analysis/filter_report.md`

This is the moment where the repo shifted from "classify all comments" to
"classify only defensible audience comments."

## 5. Filtering Layer

`analysis/build_filtered_comments.py` was added to join the labeled comment
output back to raw Apify metadata and drop contaminated rows.

The filter rules drop rows when:

- Apify marks the row as created by the media owner.
- A long comment appears across multiple videos, suggesting cross-video promo.
- The commenter username matches a known campaign creator handle.

The filtered output is:

- `analysis/analysis_comment_level_filtered.csv`

The filter currently runs after the original NLP labeling. That was fine at
pilot scale, but the recommended future design is to move filtering upstream
so spam does not consume embedding/LLM budget or influence discovery.

## 6. Theme Methodology Iterations

Theme discovery went through several stages.

The first version used k-means on comment embeddings. It gave complete theme
coverage, which was useful for rollups, but it forced every comment into a
cluster. That created some false coherence: clusters could receive plausible
LLM names even when their contents were mixed.

The next step was an LLM relabel/MIXED audit. `analysis/relabel_themes.py`
reviewed samples from existing clusters, renamed some, and collapsed weak
clusters into a mixed bucket.

Then `analysis/recluster_comments.py` tested HDBSCAN as an independent
sidecar audit. HDBSCAN produced cleaner dense themes and explicit noise
labels, but it left too much of the pilot corpus unlabeled to become the
dashboard's theme-of-record.

After that, `analysis/apply_recluster.py` explored parameter sweeps:

- `min_cluster_size=15`
- `min_cluster_size=5`
- `min_cluster_size=3`
- strict and lenient LLM support thresholds

Smaller clusters improved coverage but over-fragmented semantically similar
themes, especially movie-name requests.

The strongest experimental direction became:

- UMAP dimensionality reduction before HDBSCAN.
- HDBSCAN over the UMAP space.
- LLM topic reduction to merge sibling clusters.

That approach is documented in detail in
`analysis/THEME_METHODOLOGY.md`. The practical conclusion was that discovery
and classification are different jobs:

- Discovery should be strict and find only coherent new themes.
- Classification should be forgiving and assign known themes consistently.

For a future campaign, the recommended architecture is prototype-based
classification for known themes plus UMAP/HDBSCAN/LLM-merge on the residual
"Other" bucket for novelty discovery.

## 7. Campaign-Level Rollups

After filtering and theme audit work, the repo moved from comment-level NLP to
campaign-level decision metrics.

`analysis/build_workspace.sql` builds a DuckDB workspace that joins:

- Campaign clip metadata.
- Submission/payout data.
- Original post-level NLP output.
- Filtered comment-level output.
- Apify owner fallback data.

`analysis/run_analysis.py` then produces:

- Empirical-Bayes-shrunk intent rates.
- Account rollups.
- Theme rollups.
- Video clusters based on theme-share vectors.
- Static SVG charts used by the dashboard and reports.

This is the current operational pipeline for refreshed dashboard data.

## 8. Account Baselines

The repo later added account-baseline scraping and rollups so pilot videos
could be compared against each creator's own usual performance, not just
against other creators.

Relevant files:

- `analysis/scrape_account_baselines.py`
- `analysis/build_account_baselines.py`
- `analysis/account_baselines_raw.csv`
- `analysis/account_baselines.csv`

This layer supports claims like whether pilot videos beat each account's
normal median view performance.

## 9. Dashboard Layer

`analysis/dashboard.py` turns the analysis outputs into a Streamlit dashboard
for non-technical review.

The dashboard reads from `analysis/pilot.duckdb` and the generated rollup CSVs.
It focuses on:

- Executive summary.
- Creator performance.
- Audience signals.
- Reach versus intent.
- Theme readouts.
- Content clusters.
- Data quality and caveats.
- Raw-number browsing.

Dashboard-specific run notes live in `analysis/DASHBOARD.md`.

## 10. Current State of Truth

For day-to-day use, the current source of truth is:

- `data/raw/` for source campaign exports.
- `data/apify/apify_full_results_datadoping.json` for the main comment scrape.
- `data/processed/` for original day-one NLP outputs.
- `analysis/analysis_comment_level_filtered.csv` for cleaned audience comments.
- `analysis/pilot.duckdb` for dashboard queries.
- `analysis/run_analysis.py` for regenerating current rollups and charts.
- `analysis/dashboard.py` for the review interface.

The most important historical or experimental artifacts are:

- `data/processed/analysis_summary.md`: original pre-filter summary.
- `analysis/reports/analysis_v2_summary.md`: spam discovery narrative.
- `analysis/THEME_METHODOLOGY.md`: theme-discovery experimentation record.
- `analysis/reports/recluster_report*.md`: HDBSCAN audit outputs.
- `analysis/analysis_comment_level_rethemed.csv`: experimental rethemed output.

## 11. Open Documentation Gaps

The repo is now reasonably documented, but a few gaps remain:

- The scraper trial decision is still mostly inferred from filenames. A short
  scraper-comparison note would help if more scraping vendors are evaluated.
- Several older markdown files contain encoding artifacts from a previous
  save/export path. They are readable, but a cleanup pass would make them
  easier to scan.
- The distinction between current outputs and historical audit artifacts should
  stay explicit whenever new files are added.
- If `comment_audience_analysis.py` moves into `analysis/`, links in this doc
  and `PIPELINE.md` should be updated at the same time.
