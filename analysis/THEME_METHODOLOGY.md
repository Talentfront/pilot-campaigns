# Theme discovery — iterations and methodology

Audience: data scientists inheriting this project or reviewing the pilot's
NLP stack. Assumes familiarity with sentence embeddings, clustering, and
LLM-in-the-loop workflows.

Companion to [PIPELINE.md](PIPELINE.md), which documents the *current*
pipeline. This document tells the story of how we got here — what we
started with, what failed, what each change bought us, and what still needs
doing.

---

## TL;DR

1. The day-one pipeline used k-means (k≈10) on 4096-dim Qwen3 embeddings with
   LLM naming of clusters. K-means' forced assignment produced topically
   incoherent clusters that needed a post-hoc MIXED audit to salvage.
2. An HDBSCAN sidecar audit confirmed three themes were real and flagged
   three as junk, but at `min_cluster_size=15` it marked 85% of canonicals
   as noise — clean themes but unusable coverage.
3. Lowering `min_cluster_size` (15 → 5 → 3) improved coverage marginally but
   over-fragmented themes (7 separate clusters for *"asking for the movie
   name"*).
4. Two changes from the literature closed the gap: **UMAP dimensionality
   reduction before HDBSCAN** (BERTopic convention) and **LLM-assisted topic
   reduction** (a post-clustering merge pass, arXiv 2509.19365). Together
   they delivered 27 coherent themes with 453/821 rows assigned (vs. 143
   before), roughly matching the original k-means coverage but with
   defensible theme quality.
5. The real structural finding is that **discovery and classification are
   different jobs with opposite error profiles** — you can't do both well
   with a single clustering pass. At pilot scale the remedies above are
   enough; at campaign scale the pipeline should split into prototype-based
   classification for known themes plus a residual-only clustering pass for
   novelty.

---

## 1. Starting state (day one)

**Script**: `comment_audience_analysis.py`
**Corpus**: 923 comment/reply rows → 483 canonical texts (~39% dedupe).
**Embeddings**: Qwen3-Embedding-8B via OpenRouter, 4096-dim.
**Sentiment/intent labels**: prototype cosine similarity (hand-written seed
phrases per label → averaged to centroid → softmax over label scores per
comment). LLM adjudication (Gemini 2.5 Flash Lite) on borderline cases.
**Themes**: k-means with `k = max(3, min(12, round(sqrt(N_canonical))))` ≈ 10
on the canonical embeddings. TF-IDF top keywords + 6 exemplar texts sent to
an LLM that returned a human label and description.
**Post-processing**: `analysis/relabel_themes.py` was a second LLM pass that
sampled 15 prototypical + 15 random members per cluster, asked for a fresh
label, and flagged clusters as MIXED when no label covered ≥60% of the
shown comments. Three of eleven clusters failed the gate and were merged
into a MIXED bucket: `Exclamations and Questions` (279 rows → mostly `"??"`
punctuation), `Step-by-Step Instructions` (80 rows → spam-adjacent
self-promo), `Personal Statements` (53 rows → no unifying topic).

The relabel pass is the first evidence that k-means was producing false
coherence — it forced ~400 disperse canonicals into ten clusters, and three
of those clusters had no real topic. The LLM naming step had previously
invented plausible-sounding labels for them (e.g. *"Positive Affirmations"*
on a cluster of short dismissals), which the relabel pass caught.

## 2. Independent identification of the spam problem

Before we diagnosed the clustering issue, inspection of `Step-by-Step
Instructions` revealed that its exemplars (*"Check out my account"*, *"I'm
gonna use this one"*) were creator self-promo and cross-campaign promotion
by other creators. About 11% of raw rows were dropped via three filter
rules (`is_created_by_media_owner=True`, long-text cross-video duplicates,
commenter username matches known creator handle) in
`analysis/build_filtered_comments.py`.

The filter ran *after* labeling — we paid to embed and label rows we then
threw away. This cost is negligible at 923 rows; at campaign scale it
becomes meaningful. See PIPELINE.md limitation #4.

## 3. HDBSCAN sidecar audit

**Script**: `analysis/recluster_comments.py`
**Hypothesis**: k-means' forced partition was producing false coherence.
HDBSCAN's density-based approach with explicit noise labels (-1) should
either confirm the k-means themes or reveal them as fragments of a less
structured embedding space.

**Parameters**: `min_cluster_size=15`, Euclidean distance on L2-normalized
4096-dim embeddings (monotonic with cosine on unit vectors).
Auto-MIXED coherence gate (mean pairwise cosine) < 0.55; LLM
`supports_share` threshold ≥ 0.70.

**Result on filtered canonicals (n=453)**:

| Cluster | Members | DBCV coherence | LLM label | supports |
|--:|--:|--:|---|--:|
| 0 | 28 | 0.80 | Asking for Movie Name | 95% |
| 1 | 22 | 0.78 | MIXED (punctuation-only) | 15% |
| 2 | 16 | 0.84 | Praising Smooth Execution | 100% |
| noise | 387 | — | — | — |

**Reading**: HDBSCAN endorses two k-means themes as genuinely dense (Movie
Name, Smooth Praise), rejects the emoji-heavy cluster, and refuses to
cluster 85% of the canonical space. This is the structural failure — the
pilot corpus simply does not have enough density to support HDBSCAN at
`min_cluster_size=15`. Themes that were nameable at k-means (Knee Pun, AI
Content, Traffic Stop Debate, Critical Comments About Woman) vanished
because their member canonicals were spread too thinly.

The audit is a sidecar: `apply_recluster.py` did not exist. Its output
(`canonical_reclustered.csv`, `recluster_report.md`) informed the relabel
mapping but did not replace the k-means theme-of-record. This is where
today's dashboard pipeline landed.

## 4. Iterating on `apply_recluster.py`

The central question became whether HDBSCAN could be made usable for
assignment (not just audit) at pilot scale. We built `apply_recluster.py`
to reuse the cached embeddings and vary parameters cheaply.

### 4.1 `min_cluster_size=5`, `supports_min=0.70` (strict)

| Config | Clusters | Themed rows | Noise canonicals |
|---|--:|--:|--:|
| HDBSCAN 5, strict | 7 | 109 | 353 (78%) |

Recovered Knee Pun (`Kneed vs Need Confusion`, 12 rows) and surfaced a
novel sub-theme (`Guy Who Looks 17`, 8 rows). But 712 rows routed to Other.
AI Content (17 rows in original), Traffic Stop (15), and Critical Comments
About Woman (46) were completely lost.

Notable failure mode: three HDBSCAN clusters had high coherence (0.86–0.93)
but the strict LLM prompt refused to name them, treating e.g. `"Name?"` /
`"Name please"` as too terse to count as "about" movie identification.

### 4.2 `min_cluster_size=5`, `supports_min=0.55` + softened prompt

The prompt change: dropped the "terse reactions don't count as supporting"
rule, explicitly allowed short subject-identifiable comments (e.g. `"Name?"`)
to count. Threshold dropped to 0.55.

| Config | Clusters | Themed rows | Noise canonicals |
|---|--:|--:|--:|
| HDBSCAN 5, lenient | 7 | 126 | 353 (78%) |

Marginal gain (109 → 126). The LLM now accepts the `Name Requests` and
`General Content Questions` clusters (adding 17 rows). But HDBSCAN still
can't *form* clusters for the themes we lost — prompt lenience is
downstream of density clustering, and the density problem is where the
information is lost.

### 4.3 `min_cluster_size=3`, lenient

| Config | Clusters | Themed rows | Noise canonicals |
|---|--:|--:|--:|
| HDBSCAN 3, lenient | 23 | 143 | 329 (73%) |

Small absolute gain in coverage, real gain in novelty. New themes:

- `Movie Doesn't Exist` (3 canonicals)
- `Not MatPat Corrections` (4)
- `Craig's List Reference` (3)
- `Rizz Compliments` (3)
- `Turn Around Instruction Confusion` (3)
- Traffic Stop split into `Speeding and Traffic Enforcement` + `Officer's
  Condescending Attitude Debate`

But severe over-fragmentation: "asking for the movie name" became **seven
separate clusters** — `Movie Name Requests` (7), `Which Movie Requests` (5),
`Movie Requests` (3), `Name Requests` (6), `Show or Movie Requests` (3),
`What Is This Requests` (10), `Movie Doesn't Exist` (3). LLM named each as
a distinct theme because they were presented as distinct clusters; at
supports 100% each, the LLM had no way to know they were siblings.

## 5. Literature review

Before committing to a direction, we surveyed current (2024-2026) approaches
to the problem. Key findings:

- **The standard 2025-2026 playbook is BERTopic**: sentence embeddings →
  UMAP → HDBSCAN → TF-IDF keywords → LLM naming. What `comment_audience_
  analysis.py` implements is structurally the same pipeline *minus UMAP*.
- **Over-fragmentation on social media data is a known problem with a known
  remedy**: Choi et al. (arXiv 2509.19365, *LLM-Assisted Topic Reduction for
  BERTopic on Social Media Data*) propose a second LLM pass that reviews
  cluster labels + exemplars and proposes merges. Directly targets our
  seven-way movie-name split.
- **Taxonomy expansion frameworks** (TaxoAdapt, ACL 2025; EvoTaxo for
  evolving streams) propose prototype-classify-then-cluster-residual as the
  forward-looking architecture — which is the structure we converged on
  independently as the campaign-#2 target.
- **Zero-shot classification via structured prompting** (Frontiers AI 2024,
  *One size fits all*) validates prototype cosine with boundary constraints
  in the LLM prompt for social media classification tasks.

Two concrete changes were immediately applicable:

1. Add UMAP before HDBSCAN.
2. Add an LLM topic-reduction pass after naming.

## 6. UMAP + LLM topic reduction

### 6.1 Why UMAP matters for density clustering

In 4096-dim space, pairwise Euclidean distances concentrate (curse of
dimensionality) — nearly every point is roughly equidistant from every
other, making density-based methods unable to distinguish genuinely dense
regions from noise. Cosine distance partially mitigates this on
L2-normalized vectors (by collapsing magnitude) but doesn't eliminate it.

UMAP projects to a low-dimensional manifold (`n_components=5` is standard
in BERTopic) while preserving local neighborhood structure under a chosen
metric (we use `metric="cosine"`). HDBSCAN on the UMAP output runs on
well-behaved low-dim Euclidean space where "density" has a meaningful
geometric interpretation.

Implementation (`apply_recluster.py`):

```python
reducer = umap.UMAP(
    n_components=5, metric="cosine",
    n_neighbors=15, min_dist=0.0, random_state=17,
)
X_umap = reducer.fit_transform(X)  # raw 4096d embeddings, not L2-normalized
labels = HDBSCAN(min_cluster_size=3, metric="euclidean").fit_predict(X_umap)
```

Note: UMAP metric is `cosine` (takes raw high-dim embeddings), HDBSCAN
metric is `euclidean` (operates on UMAP output where cosine is not
meaningful). This matches BERTopic convention.

Coherence and centroid-nearest exemplar selection still run on the
*original* L2-normalized 4096-dim embeddings — UMAP is only a clustering
aid, not a semantic-similarity metric.

### 6.2 Why LLM topic reduction

HDBSCAN finds local density modes. When a theme has multiple lexical
phrasings (*"Movie name?"* vs *"Which movie is this?"* vs *"name please"*)
each phrasing forms its own density peak, and HDBSCAN — which has no
notion of semantic equivalence — returns them as distinct clusters.

The reduction prompt sends the list of all coherent clusters (label,
coherence, member count, 6 exemplars) to an LLM and asks for merge groups.
Rules emphasized in the prompt:

- Merge only when clusters share an underlying subject. Tone/sentiment
  alone is not enough.
- Every cluster must appear in exactly one merge group.
- Singleton groups are fine.
- Merged labels should describe all members (often the most general member's
  label).

See `build_merge_prompt()` and `call_merger()` in `apply_recluster.py`.

### 6.3 Results

`apply_recluster.py --min-cluster-size 3` (with `--umap-dim=5` and merge on,
both defaults):

| Config | Clusters found | After merge | Themed rows | Noise canonicals |
|---|--:|--:|--:|--:|
| HDBSCAN 15 (audit) | 3 | — | ~66 canonicals | 387 (85%) |
| HDBSCAN 5, strict | 7 | — | 109 | 353 (78%) |
| HDBSCAN 5, lenient | 7 | — | 126 | 353 (78%) |
| HDBSCAN 3, lenient | 23 | — | 143 | 329 (73%) |
| **UMAP + HDBSCAN 3 + merge** | **56** | **27 themes** | **453** | **96 (21%)** |

The coverage jump (143 → 453 themed rows) comes primarily from UMAP — HDBSCAN
on the UMAP projection finds density where 4096-dim HDBSCAN saw noise.

Recovery of themes lost at every previous configuration:

| Theme (current-dashboard relabel) | Rows lost | Recovered |
|---|--:|--:|
| AI Content Questions | 17 | 10 (AI-Generated Content Identification) |
| Traffic Stop Debate | 15 | 11 (Traffic Stop Rights Debate + Woman's Reaction Analysis) |
| Critical Comments About Woman | 46 | 23 (Critical Women + Woman's Reaction Analysis + Violent Hypothetical) |

Merge pass correctly collapsed the seven-way movie-name fragmentation:

- Six HDBSCAN clusters → `Content Name Requests` (57 rows)
- Six Knee-wordplay clusters → `Kneed vs Need Wordplay` (40 rows)
- Two `Looks 17` clusters → one theme
- Two `Critical Women` clusters → one theme
- Two `Smooth Move Praise` clusters → one theme

LLM cost per run: ~11k input tokens, ~7k output tokens for naming + merge
combined (Claude Sonnet 4.5). Sub-dollar per run.

## 7. Known quality issues in the current output

### `Confusion Reactions` (141 rows, 15 canonicals)

LLM-named cluster whose members are predominantly emoji/punctuation floods
(`"??"`, `"??????"`, `"????????"`). The cluster has real embedding coherence
(short noisy text is geometrically similar in UMAP space) but no
substantive topic. The 141-row figure is inflated by canonical duplication
— one `"??"` canonical corresponds to ~30 rows.

Proposed fix: short-text / punctuation-only override before finalizing
labels. If ≥70% of a cluster's canonicals are ≤3 chars or pure punctuation
after normalization, override label to Other regardless of LLM output.
Five-line change in `apply_recluster.py`.

### `Clever Move Praise` (7 rows, 7 canonicals)

Members are sarcastic replies to other commenters (*"aren't you clever"*,
*"thanks Einstein"*), not praise of the video. LLM miscalibration. Small
enough to either ignore or manually relabel to `Sarcastic Replies`.

### `Compliments on Gameplay` (6 rows, 6 canonicals)

Members are *"well played"* reactions. Video is not gameplay. Should merge
into `Smooth Move Praise` / `Clever Move Praise`. LLM hallucinated the
domain.

### Incomplete merging of praise themes

`Smooth Move Praise` (18), `Rizz and Charm Praise` (19), `Clever Move
Praise` (7), `Compliments on Gameplay` (6) could conceptually all be one
"Praising Male Lead" theme (~50 rows). The merge LLM was conservative on
these — it correctly identified them as related but distinct enough to
keep separate. A more aggressive merge prompt might consolidate; too
aggressive and you lose the `Rizz` vs `Smooth` distinction that is
genuinely Gen-Z-coded and might matter for campaign targeting.

## 8. Bottlenecks identified

Ranked by how much each one cost us in output quality.

### 8.1 Discovery and classification are different jobs

Discovery ("what themes exist") wants to be strict — only name themes with
tight evidence. Classification ("which theme does this comment belong to")
wants to be forgiving — every comment should get a label.

These have opposite error profiles and no single clustering pass can do
both. k-means' forced assignment is classification-first and produces junk
themes; HDBSCAN is discovery-first and produces unlabeled majorities.

Every iteration in this document is a workaround for this structural
mismatch. The campaign-#2 architecture splits them cleanly: prototype
cosine similarity (classification, stable, fast) for known themes; HDBSCAN
on the residual Other bucket (discovery, cheap because small) for novelty.

### 8.2 Embedding geometry ≠ semantic co-reference

Comments about *"the female character"* range across cute / critical /
neutral sentiment. They are the same subject but land in different
embedding neighborhoods. No density-based method can group them; even at
campaign scale they will form multiple sub-clusters or partial noise.

Prototypes handle this natively — a hand-defined centroid can span
multiple semantic modes if the seed phrases cover them. This is the
single biggest reason to move to prototype-based theme classification
post-pilot.

### 8.3 Pilot scale starves the statistics

453 canonicals is too small for most clustering methods to confidently
separate real micro-themes from coincidental density. This is why we had
to drop `min_cluster_size` to 3 (small-sample workaround) and UMAP had
such a large effect (its manifold learning amplifies weak density signal
into clear structure at low N). At campaign scale (~5000+ canonicals
projected), `min_cluster_size` can return to 15-30 and most small-themes
will form naturally.

### 8.4 Single-label-per-comment assumption

Comments like *"She kneed him so smooth"* contribute to Knee Pun AND Smooth
Praise. Current pipeline forces a single theme assignment. Multi-label
would require rewriting the per-video theme-share rollup (shares no longer
sum to 1) but would recover ~10-15% of genuinely dual-purpose comments.

### 8.5 Spam filter after labeling

Operational cost only — we paid Qwen + Gemini tokens on rows we then
discarded. Negligible at pilot; campaign-scale refactor.

## 9. What we did not try (and why)

- **Pure-LLM clustering** (send 453 canonicals to Claude, ask for topic
  groups). Feasible at pilot scale, doesn't scale past ~1000-2000
  canonicals, throws away Qwen embeddings entirely. Literature review
  found this dismissed in every recent survey as non-scalable.
- **Agglomerative / spectral / affinity propagation clustering**. All
  operate on the same embedding geometry HDBSCAN does; the disperse-topics
  problem (§8.2) is structural, not fixable by swapping the clustering
  algorithm.
- **Neural topic models** (ETM, BERTopic+CTM). Comparable to BERTopic
  empirically (Weinberg & Bojanowski 2022) with more moving parts. Not
  worth the complexity at pilot scale.
- **Per-video clustering**. Typical video has 10-80 comments → too sparse
  for any clustering. Pooled themes sliced by `input_url` (which the
  dashboard already does in its top-themes-per-post column) is the correct
  per-video view.
- **Per-source-clip clustering**. Would be valuable — many pilot videos
  share underlying source clips (the knee scene appears across 10 videos
  from different accounts) — but requires a clip-ID field we don't have.
  Manual tagging of 51 thumbnails is the cheapest path; visual embeddings
  of frames / transcripts is the scalable path. Flagged as campaign-#2
  infrastructure.

## 10. Campaign #2 recommendations

1. **Move spam filter upstream of labeling.** Cuts embedding and LLM cost
   ~10% and prevents spam from influencing discovery.

2. **Replace k-means theme-of-record with the UMAP + HDBSCAN + merge
   pipeline.** `apply_recluster.py` is the implementation; wire its output
   into `build_workspace.sql` by pointing the `raw_comments` view at
   `analysis_comment_level_rethemed.csv` and using
   `theme_human_label_retheme` as the theme column.

3. **Promote the taxonomy we earned from this pilot to prototypes.** Hand-
   curate seed phrases per theme (Movie Name Requests, Smooth Praise, Knee
   Pun, AI Content, Critical Women Comments, Traffic Stop Rights, Where to
   Watch, etc.), average into centroids, classify new campaign rows by
   cosine similarity with a per-theme threshold. This is
   classification-ready, deterministic, scales trivially, and handles the
   disperse-topic themes.

4. **Run HDBSCAN + UMAP + merge on the residual Other bucket only**, on a
   regular cadence (e.g. weekly). Surface proposed new themes (with seeds)
   to a human for approval. Approved themes get added to the prototype
   taxonomy. This is the "novelty watchdog" — matches TaxoAdapt / EvoTaxo
   in the literature.

5. **Add a `clip_id` field** to `v_videos`. Per-clip rollups are more
   actionable than per-video (same clip across accounts → which account
   performed best). Cheapest path: manual tag 51 thumbnails once. Forward
   path: visual embeddings.

6. **Multi-label theme assignment.** Drop the single-theme assumption.
   Compute cosine similarity against every prototype; assign all themes
   above threshold. Adjust downstream rollups (theme shares no longer sum
   to 1; move to per-comment-per-theme counts).

7. **Tune `min_cluster_size` to ~3% of canonical count** for the novelty
   pass (auto-scales with data volume).

8. **Keep `supports_min=0.55` and the lenient naming prompt.** The original
   0.70 threshold was too strict at pilot scale and masked valid terse-
   subject themes. At larger scale, re-evaluate — the prompt's
   "terse-subject counts" rule may start letting in false positives when
   cluster sizes grow.

## 11. Reproducing the iterations

Each row of the comparison table can be reproduced with a single command.
Cached embeddings (`analysis/recluster_embeddings.npy`) make this cheap —
no new API costs for embedding, only LLM naming/merging calls.

```bash
# Environment
export OPENROUTER_API_KEY=sk-or-...

# Baselines
python analysis/recluster_comments.py --min-cluster-size 15    # day-one audit

# apply_recluster.py iterations
python analysis/apply_recluster.py --min-cluster-size 5 --supports-min 0.70 --umap-dim 0 --skip-merge  # strict, no UMAP
python analysis/apply_recluster.py --min-cluster-size 5 --supports-min 0.55 --umap-dim 0 --skip-merge  # lenient
python analysis/apply_recluster.py --min-cluster-size 3 --umap-dim 0 --skip-merge                      # lenient, finer
python analysis/apply_recluster.py --min-cluster-size 3                                                # UMAP + merge (current)
```

Each run writes:
- `analysis/canonical_rethemed.csv`
- `analysis/analysis_comment_level_rethemed.csv`
- `analysis/recluster_report_applied.md`

The row-level CSV is a drop-in replacement for
`analysis_comment_level_filtered.csv` with three added columns
(`theme_human_label_retheme`, `theme_id_retheme`, `theme_cohesion_retheme`).

## References

- Choi, S. et al. (2025). *LLM-Assisted Topic Reduction for BERTopic on
  Social Media Data.* arXiv:2509.19365.
- ACL 2025. *TaxoAdapt: Aligning LLM-Based Multidimensional Taxonomy.*
- *EvoTaxo: Building and Evolving Taxonomy from Social Media Streams.*
  arXiv.
- Frontiers in AI 2024. *One size fits all: Enhanced zero-shot text
  classification for patient listening on social media.*
- McInnes, L., Healy, J., Melville, J. (2018). *UMAP: Uniform Manifold
  Approximation and Projection for Dimension Reduction.* arXiv:1802.03426.
- McInnes, L., Healy, J. (2017). *Accelerated Hierarchical Density Based
  Clustering.* HDBSCAN reference.
- Grootendorst, M. (2022). *BERTopic: Neural Topic Modeling with a
  Class-based TF-IDF procedure.* arXiv:2203.05794.
