# Pilot Analysis v2 — Accounts, Themes, Latent Clusters (shrinkage-corrected)

Builds on the original [analysis_summary.md](../analysis_summary.md) by joining the comment NLP output with account attribution and engagement data, then clustering videos by their theme fingerprints — and correcting per-video high-intent rates for small-sample skew via empirical-Bayes shrinkage.

**Inputs joined:** `analysis_post_level.csv` + `analysis_comment_level.csv` + `All Clips.csv` (profile, views, engagement) + `submissions.csv` (payout). Join keyed on post_id extracted from URL. 12 of 113 analyzed posts lack profile attribution — they predate the All Clips report. Flagged as `(unknown)` in outputs.

**Workspace:** `analysis/pilot.duckdb`. Rebuild with `python analysis/run_analysis.py`.

---

## Sample-size problem — why shrinkage was needed

The raw per-video high-intent rate is badly skewed by tiny samples:

- **66 of 113 analyzed videos have only 1-2 labeled comments.** 8 more have zero.
- **Only 11 videos have more than 10 labeled comments.**
- **30 videos show "100% high-intent" in the raw data, all with ≤3 comments.** Zero videos with ≥10 comments hit 100%.

In other words, the "top of the leaderboard" in the raw analysis was almost entirely videos where 2 out of 2 comments happened to be labeled high. That's noise, not signal.

### Fix: empirical-Bayes shrinkage

Fit a Beta prior to the observed rates (method-of-moments on videos with ≥3 comments), then compute each video's shrunk rate as `(k_high + α) / (n_labeled + α + β)`.

- **Prior: Beta(α=0.74, β=3.28)**, prior mean = **18.4%**, prior strength = 4.02 (floored).
- Interpretation: every video is treated as if it had an extra ~4 "synthetic" comments drawn from the global distribution. A 2-of-2 video gets pulled to ~45%; a 40-of-50 video barely moves.
- See [intent_raw_vs_shrunk.svg](intent_raw_vs_shrunk.svg) for the scatter.

**Three measurements now surface in the output:**

| Measurement | What it is | When to trust it |
|---|---|---|
| `raw_rate` | per-video `k/n` | Almost never alone — skewed by n=1,2 videos |
| `shrunk_rate` | empirical-Bayes posterior mean | Default. Regularizes small-n to prior |
| `pooled_rate` | one rate over all comments in the group | Best for cluster/account-level — sidesteps per-video averaging |

---

## Findings, after correction

### How the cluster story changes

| Cluster | n | Mean views | Intent (raw) | Intent (shrunk) | Intent (pooled) | Comments | Character |
|---|---|---|---|---|---|---|---|
| **4** | 11 | 15,501 | 0.75 | **0.39** | **0.60** | **27/45** | Media Identification — survives |
| **2** | 21 | 1,726 | 1.00 | 0.35 | 1.00 | 21/21 | Father-Daughter — suspect, see below |
| 1 | 33 | 179,054 | 0.18 | 0.19 | 0.18 | 112/630 | High-volume memes — unchanged |
| 3 | 26 | 5,103 | 0.17 | 0.16 | 0.08 | 5/65 | Pure reactions ("Exclamations") |
| 0 | 7 | 9,527 | 0.07 | 0.17 | 0.13 | 1/8 | Step-by-step — n too low to say |
| 5 | 7 | 27,358 | 0.04 | 0.13 | 0.05 | 1/22 | "Smooth and Youthful" — low intent |

**What survives:**
- **Cluster 4 (Media Identification)** is real: 27 out of 45 labeled comments across 11 videos show high intent. Pooled rate 60% is the most trustworthy number in the analysis. This is the only cluster with **both** meaningful volume *and* meaningful intent.
- **Cluster 1 is stable**: 112/630 = 18% across 33 videos. The "big views, low intent" finding is rock-solid.

**What's now suspect:**
- **Cluster 2 (Father-Daughter) at 100% pooled rate is built on only 21 comments across 21 videos — one comment per video on average.** The shrunk rate (35%) says "don't trust it yet." The pooled rate (100%) says "what little signal we have is strong." Reality is probably somewhere in the middle, but we need more comments before this finding is actionable.
- **Cluster 5 (Smooth/Attractive)** at 5% pooled rate is also thin (22 comments across 7 videos), but directionally matches the raw finding.

### How the account story changes

| Rank (shrunk) | Account | n videos | n labeled | raw | shrunk | pooled | Interpretation |
|---|---|---|---|---|---|---|---|
| 1 | rizzlerreelpull | 1 | 3 | 1.00 | 0.53 | 1.00 | Noise (n=3) |
| 2 | trend_istg | 1 | 7 | 0.71 | 0.52 | 0.71 | Marginal |
| 3 | dailydadly.jokes | 1 | 2 | 1.00 | 0.45 | 1.00 | Noise (n=2) |
| **4** | **moovieshub.ig** | 2 | **97** | 0.46 | **0.40** | **0.43** | **Robust finding** |
| 7 | lilly.h_7 | 7 | 7 | 0.86 | 0.32 | 0.86 | Each video has 1 comment; suspect |
| 8 | clipper_.media | 5 | 5 | 0.80 | 0.31 | 0.80 | Same pattern — 1 comment/video |

**The headline:** `moovieshub.ig` is the only account with *both* real intent (~43% pooled across 97 comments) *and* real reach (two videos averaging 118k views). It was buried at rank #12 in the uncorrected ranking because raw per-video averaging diluted its score. After correction it's the clearest "both axes" winner.

Every other high-ranked account has 1-7 labeled comments total. Treat them as leads to investigate, not conclusions.

---

## Revised top-line interpretation

The "intent and reach are nearly-disjoint" finding **partly survives, partly doesn't.**

- It **survives** as a theme-level claim: Media Identification content pulls intent *and* views (Cluster 4); pure-reaction content pulls views without intent (Cluster 1). That's robust across hundreds of comments.
- It **doesn't survive** as a video-ranking claim at the top of the leaderboard — most of those "winner" videos had 1-3 comments and got lucky. The raw winner_score needs sample-size correction before it's usable for decisioning.

**Practical implication:** Lean into Media-Identification-style content and watch `moovieshub.ig`-style accounts. Everything else is a lead that needs more data before acting on.

---

## What to do with this

1. **For the next campaign, collect more comments per video.** 1-2 comments/video is too few to rank anything with confidence. Aim for ≥20.
2. **Prioritize Cluster 4 (Media Identification) content.** Only cluster passing the correction.
3. **`moovieshub.ig` is the account bet** with actual evidence behind it.
4. **Treat the top of the raw leaderboard as a watchlist, not a ranking.** Investigate `lilly.h_7`, `clipper_.media`, `rizzlerreelpull` — they may be real, but right now they're "1/1 = 100%" evidence.
5. **Fix the clip-report gap:** 12 high-performing posts (including some top view-getters) lack profile attribution.

## Caveats that remain

- **Prior is fit on very thin data.** Only 34 videos have ≥3 labeled comments to inform the Beta prior. The prior is directional, not precise.
- **`winner_score` isn't shrunk.** It's consumed as-is from the earlier pipeline, which has the same tiny-n inflation. Worth re-deriving from scratch on shrunk rates if we iterate again.
- **`payout_lift`** is still empty for most themes — `submissions.csv` covers only 27 of 113 analyzed posts.
- **Clustering is unchanged** by shrinkage (clusters are built on theme-share vectors, not intent rates). But cluster *characterization* now uses corrected numbers.
- **Low-confidence labels** are weighted the same as high-confidence labels — `watch_intent_confidence` column from the NLP output is not yet used.

## Files produced

- [account_rollup.csv](account_rollup.csv) — per-account metrics with raw / shrunk / pooled intent rates
- [theme_rollup.csv](theme_rollup.csv) — per-theme intent, view-lift, account concentration
- [video_clusters.csv](video_clusters.csv) — video → cluster assignments with shrunk rates
- [cluster_profile.md](cluster_profile.md) — cluster cards with raw/shrunk/pooled side-by-side
- [account_winner_scores.svg](account_winner_scores.svg) — accounts by winner_score (uncorrected)
- [account_intent_shrunk.svg](account_intent_shrunk.svg) — accounts by shrunk intent rate
- [theme_intent_vs_viewlift.svg](theme_intent_vs_viewlift.svg) — theme scatter
- [intent_raw_vs_shrunk.svg](intent_raw_vs_shrunk.svg) — per-video raw vs shrunk rate
- [pilot.duckdb](pilot.duckdb) — queryable workspace (`v_videos`, `v_video_themes`, `video_clusters`, `video_intent_shrunk`, `intent_prior`, plus raw views)
