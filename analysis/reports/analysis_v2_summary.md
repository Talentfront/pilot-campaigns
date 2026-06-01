# Pilot Analysis v2 — Accounts, Themes, Latent Clusters (cleaned + shrunk)

Builds on the original [analysis_summary.md](../../data/processed/analysis_summary.md) in three passes:

1. **Join** comment NLP output with account/views/payout data.
2. **Clean** — drop creator-posted spam (`is_created_by_media_owner`, cross-video duplicate long text, commenter-matches-creator-handle). See [filter_report.md](filter_report.md).
3. **Shrink** — empirical-Bayes on per-video high-intent rates so tiny-n videos can't dominate the leaderboard.

**Inputs:** `data/processed/analysis_comment_level.csv` + `data/processed/analysis_post_level.csv` (original NLP output) + `data/apify/apify_full_results_datadoping.json` (raw scrape for the owner flag and usernames) + `data/raw/Viral_Micro_Dramas_campaign_report_2026-04-13.xlsx - All Clips.csv` (profile, views, engagement) + `data/raw/submissions - submissions.csv` (payout).

**Workspace:** `analysis/pilot.duckdb`. Rebuild with `python analysis/run_analysis.py` — this also regenerates the filtered comment CSV.

---

## The contamination we found

The original pipeline treated all scraped comments as viewer reactions. It wasn't. Inspection of the latent clusters exposed that **two of six clusters were creator-posted SEO spam**:

- **Cluster 2 (Father-Daughter Relationships)**: 21 videos, each with exactly 1 comment, all posted by the video creators themselves (`spade.clipper`, `lilly.h_7`, `clipper_.media`, `sharp_clipper`) with the same ~900-char paragraph — "*In many viral micro dramas, the dad and daughter relationship is one of the most emotional...*"
- **Cluster 0 (Step-by-Step / "Paris metro")**: 4 videos with identical ~620-char "Grand Paris Express" spam posted by the creator.

The LLM labeled these as "high watch-intent" because they're long and grammatical. This inflated the rankings of the spamming accounts and created a fake "Father-Daughter content drives intent" finding.

### Cleaning rules applied (see [build_filtered_comments.py](build_filtered_comments.py))

| Rule | What it drops | Hits |
|---|---|---|
| 1 | `is_created_by_media_owner = True` in the raw Apify scrape | 87 |
| 3 | Long text (≥80 chars) duplicated across ≥2 distinct videos | 22 |
| 4 | Commenter username matches any known creator handle from All Clips | 76 |
| **Any rule** | | **102** (11.1% of input) |

Remaining: **821 comments** that appear to be genuine viewer content. **27 posts lost all their labeled comments** (their entire "comment section" was creator self-posts).

---

## Findings, after cleaning

### Cluster story (k=6, silhouette 0.56 — virtually unchanged)

| Cluster | n videos | Total comments | Pooled intent | Mean views | Character |
|---|---|---|---|---|---|
| **2 (was 4)** | **11** | **35** | **60%** (21/35) | 15,501 | **Media Identification — the real intent signal** |
| 1 | 27 | 586 | 18% (105/586) | 214,764 | **High-views, passive audience (emoji reactions)** |
| 0 | 24 | 47 | 11% (5/47) | 5,227 | Smaller-views emoji reactions |
| 4 | 7 | 12 | 8% (1/12) | 32,644 | Personal Statements — thin |
| 5 | 4 | 4 | 50% (2/4) | 14,897 | Step-by-step — too thin to call |
| 3 | 5 | 5 | 0% (0/5) | 13,751 | Positive Affirmations — too thin |

**The Father-Daughter cluster from the pre-filter analysis is gone entirely.** Confirmed as spam artifact.

**The Media Identification cluster survives unchanged** — 60% pooled intent across 11 videos. This is the only finding that holds up at both meaningful volume (35 genuine comments) and meaningful intent rate.

**The high-views, low-intent cluster is stable** — 586 comments, 18% intent, matches what we saw before.

### Account story (dramatic reshuffling)

| Account | n videos | Labeled (pre) | Labeled (post) | Pooled intent (post) | Interpretation |
|---|---|---|---|---|---|
| **moovieshub.ig** | 2 | 97 | **87** | **46%** | **The clear winner. Real audience engagement at real reach (~118k median views).** |
| millionairegoldmindset | 5 | 6 | 5 | 60% | Interesting but thin (n=5) |
| (unknown)* | 12 | 371 | 345 | 17% | High-view posts; most comments real audience |
| meme.ig | 2 | — | 134 | 9% | High-reach emoji-reaction cluster — Cluster 1 member |
| iconicbloopers | 3 | — | 27 | 11% | Cluster 1 member |
| spade.clipper | 20 | 29 | **6** | 50% on tiny n | 23 of its 29 comments were self-spam |
| **lilly.h_7** | 7 | 7 | **0** | — | **All 7 comments were spam. No real audience signal.** |
| **clipper_.media** | 5 | 5 | **1** | 0% | **4 of 5 were spam.** |

*`(unknown)` = posts with no profile attribution in the All Clips report (predate its coverage).

The "small-account high-intent" narrative from the pre-filter analysis was **almost entirely spam-driven**. After cleaning, `moovieshub.ig` stands alone as the account with real-audience evidence at real scale.

### 27 posts lost every comment after filtering

These were videos whose entire "comment section" as scraped was creator-posted content. The audience-attention question is unanswerable for them from this data. Concentrated heavily in `spade.clipper` (13 videos), `lilly.h_7` (6), `clipper_.media` (4), `sharp_clipper` (2).

---

## What survives as a real finding

1. **The "intent vs reach" divergence is real.** Cluster 1 (215k mean views, 18% intent, 586 comments) and Cluster 2-new (15k views, 60% intent, 35 comments) are genuinely different groups of real audience comments. This is the cleanest finding in the dataset.
2. **"Movie name?" / Media Identification as the intent signal.** Robust across cleaning. 60% of genuine viewer comments in this cluster are high-intent.
3. **`moovieshub.ig` is the standout account.** Two videos, 87 real audience comments, 46% high-intent, ~118k median views. Only account with this combo.
4. **High-volume meme accounts (`meme.ig`, `iconicbloopers`) drive reach, not intent.** Consistent with Cluster 1.

## What dies after cleaning

1. **Father-Daughter Relationships as a content finding.** Spam artifact.
2. **`lilly.h_7`, `clipper_.media`, `spade.clipper` as high-intent accounts.** Their rankings were built on their own promotional spam.
3. **The 30+ "100% raw watch intent" videos** at the top of the original winner leaderboard. Most lost their signal entirely after spam removal.

## What we now know about the creators

Several creator/poster accounts pad their own comment sections with:
- LLM-generated SEO paragraphs (4+ templates observed: Father-Daughter, Paris metro, micro-drama intro, "Absolutely terrifying scenes")
- Friend-tag clusters (`@thecinema.feed` tagging 9 different handles)
- Pure-emoji spam (`@1_stonealone` posting `??` 19 times on DW20px2kiNY)

This is worth **flagging to the campaign operator** — these are inflating the comment counts reported in the campaign data and potentially the engagement rates too.

---

## Caveats that remain after cleaning

- **Sample sizes are still tight.** 821 comments across 113 videos; median ~5 comments per video. Per-video ranking is still noisy, per-cluster / per-theme is okay.
- **Prior is fit on less data** post-filter (only ~30 videos have ≥3 comments now to inform it).
- **We did NOT re-embed.** The existing theme labels stay; we just filtered them. If spam dominated certain theme clusters during the original embedding run, those themes may still be slightly skewed. Re-running `comment_audience_analysis.py` on the cleaned input would surface cleaner themes; not done yet.
- **27 posts have zero comments after filtering** — the campaign may have more such posts we don't know about yet.
- **LLM confidence scores still ignored** — a high-confidence "low" label counts the same as a low-confidence "high."
- **The `winner_score` column is still the original one** (not re-derived on filtered data). It's tainted the same way the original rankings were. Treat it as legacy.

## Files produced

- [analysis_comment_level_filtered.csv](analysis_comment_level_filtered.csv) — cleaned comments + filter flags
- [filter_report.md](filter_report.md) — rule-hit breakdown, top offender accounts, sample drops
- [account_rollup.csv](account_rollup.csv) — per-account metrics (raw/shrunk/pooled intent)
- [theme_rollup.csv](theme_rollup.csv) — per-theme intent, view-lift, concentration
- [video_clusters.csv](video_clusters.csv) — video → cluster assignments
- [cluster_profile.md](cluster_profile.md) — cluster cards with exemplars
- [account_winner_scores.svg](account_winner_scores.svg) / [account_intent_shrunk.svg](account_intent_shrunk.svg) / [theme_intent_vs_viewlift.svg](theme_intent_vs_viewlift.svg) / [intent_raw_vs_shrunk.svg](intent_raw_vs_shrunk.svg)
- [pilot.duckdb](pilot.duckdb) — queryable workspace (views include `v_videos` with both original and filtered rates side-by-side, `post_rates_filtered`, `video_intent_shrunk`, `video_clusters`, `intent_prior`)
