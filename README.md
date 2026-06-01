# Pilot Campaigns

Analysis workspace for the Viral Micro Dramas pilot campaign.

The repo combines campaign exports, Apify comment scrapes, NLP/theme analysis,
creator/account rollups, and a local Streamlit dashboard for reviewing pilot
performance.

## Layout

- `analysis/` - pipeline scripts, dashboard code, DuckDB workspace, current
  rollups, charts, and methodology docs.
- `analysis/reports/` - generated narrative snapshots and audit reports.
- `data/raw/` - source campaign exports and handoff CSVs.
- `data/apify/` - Apify actor inputs, run metadata, status files, and scraped
  result datasets.
- `data/processed/` - original generated analysis outputs from
  `comment_audience_analysis.py`.
- `comment_audience_analysis.py` - original comment-level NLP pipeline.

## Run

Install the small Python dependency set:

```bash
pip install -r requirements.txt
```

Rebuild the analysis workspace:

```bash
python analysis/run_analysis.py
```

Launch the dashboard:

```bash
python -m streamlit run analysis/dashboard.py
```

For the full methodology and pipeline order, start with
[`analysis/PIPELINE.md`](analysis/PIPELINE.md). For how the repo got to its
current shape, see [`analysis/CHRONOLOGY.md`](analysis/CHRONOLOGY.md). For
dashboard-specific notes, see [`analysis/DASHBOARD.md`](analysis/DASHBOARD.md).
