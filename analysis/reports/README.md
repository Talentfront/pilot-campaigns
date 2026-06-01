# analysis/reports/

Experiment artifacts and generated snapshots. **Not primary documentation.**
Files here are regenerated each time the script listed as "producer" runs;
they're committed so the repo has a record of the last output without having
to re-run the pipeline.

For living documentation, see the analysis/ parent directory:

- [PIPELINE.md](../PIPELINE.md) — what the current pipeline does, step by step
- [CHRONOLOGY.md](../CHRONOLOGY.md) - how the repo evolved and which artifacts
  are current vs. historical
- [DASHBOARD.md](../DASHBOARD.md) — how to run the Streamlit dashboard
- [THEME_METHODOLOGY.md](../THEME_METHODOLOGY.md) — iteration history and
  design choices for theme discovery

---

## Files in this directory

| File | Producer | What it is |
|---|---|---|
| [analysis_summary_filtered.md](analysis_summary_filtered.md) | `write_filtered_summary.py` | Per-theme summary + winners/laggards on the filtered 821-row corpus with the theme relabel mapping applied |
| [analysis_v2_summary.md](analysis_v2_summary.md) | handwritten | Historical narrative: how creator-self-spam was discovered during the first pipeline audit. Kept as provenance |
| [compare_weighted.md](compare_weighted.md) | `compare_weighted_vs_unweighted.py` | Side-by-side weighted vs unweighted intent rates + theme shares. Uses log1p(likes)+1 weighting, half-weight replies |
| [recluster_report.md](recluster_report.md) | `recluster_comments.py` | HDBSCAN sidecar audit at `min_cluster_size=15` — the first independent check on the day-one k-means themes |
| [recluster_report_applied.md](recluster_report_applied.md) | `apply_recluster.py` | Latest HDBSCAN+UMAP+LLM-merge rethemed output. Row counts per theme, cluster table, merge groups |

## Files **not** in this directory but logically similar

- [../filter_report.md](../filter_report.md) stays in `analysis/` because
  `dashboard.py` reads it directly to render the Data Quality page.
- [../cluster_profile.md](../cluster_profile.md) stays in `analysis/` for
  the same reason (surfaced on the Content Clusters page).
- [../../data/processed/analysis_summary.md](../../data/processed/analysis_summary.md) is
  the original pre-filter k-means summary — kept as an audit trail of what
  the pipeline looked like before spam was discovered.

## Regenerating

From project root, with `OPENROUTER_API_KEY` set:

```bash
# Latest theme output (UMAP + HDBSCAN + merge)
python analysis/apply_recluster.py

# Weighted-metrics comparison
python analysis/add_like_weights.py
python analysis/compare_weighted_vs_unweighted.py

# Filtered corpus summary (uses current theme_relabel_mapping.csv)
python analysis/write_filtered_summary.py

# HDBSCAN audit at min_cluster_size=15 (original sidecar, rarely rerun)
python analysis/recluster_comments.py
```
