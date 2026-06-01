# Data Layout

This directory keeps bulky input and generated files out of the repo root.

- `raw/` contains external campaign inputs such as the All Clips export,
  submissions feed, and intermediate source CSVs.
- `apify/` contains Apify actor inputs, run metadata, statuses, post breakdowns,
  and scraped result datasets.
- `processed/` contains the original generated outputs from
  `comment_audience_analysis.py`, before later filtering and dashboard rollups
  under `analysis/`.

Most day-to-day work should start from `analysis/run_analysis.py`, which reads
from these folders and regenerates the DuckDB workspace plus rollups.
