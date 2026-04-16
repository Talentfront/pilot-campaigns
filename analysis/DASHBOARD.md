# Pilot Insights Dashboard

Exec-facing dashboard built with Streamlit. Designed for non-technical readers — every claim carries an inline confidence/sample-size badge.

## Run it

From the **project root** (`c:/Users/shahe/Documents/pilot-campaigns`):

```bash
# 1. Build the analysis workspace (only needed when raw data changes)
python analysis/run_analysis.py

# 2. Launch the dashboard
python -m streamlit run analysis/dashboard.py
```

Default URL: <http://localhost:8501>. Use `Ctrl+C` to stop.

To run on a specific port:

```bash
python -m streamlit run analysis/dashboard.py --server.port=8789
```

## Pages

- **Executive Summary** — one-pager with the headline finding, top metrics, and what-to-do panel
- **The Two-Audience Problem** — side-by-side of the reach audience vs the intent audience, with sample comments
- **Accounts — who to bet on** — account ranking with confidence tiers; calls out spam-contaminated accounts
- **Themes — what works** — per-theme intent rates and view-lift, with explicit "thin sample" warnings
- **Content Clusters** — the six latent groupings with example comments and theme breakdowns
- **Data Quality & Caveats** — the page to read before quoting any finding
- **Browse: raw numbers** — searchable tables for verification

## Confidence legend

The dashboard uses a four-tier badge system on every claim:

- 🟢 **ROBUST** — hundreds of comments, stable across cuts
- 🟡 **DIRECTIONAL** — real signal but thin sample (~10-30 comments)
- 🔴 **THIN** — fewer than 10 comments, treat as a hypothesis
- ⚫ **SPAM-CONTAMINATED** — finding disappeared after spam removal (called out for transparency)

## Sharing it

The dashboard is a local Python app — to share with someone non-technical, you can either:

1. **Screen-share / walk them through it live.** Best for first-time review.
2. **Export the underlying CSVs** (`analysis/account_rollup.csv`, `analysis/theme_rollup.csv`, etc.) and the static SVG charts (`analysis/*.svg`) for asynchronous review.
3. **Host it remotely** (Streamlit Community Cloud, internal server). Out of scope for this pilot.

If you need a fully self-contained shareable artifact, consider exporting the dashboard contents to PDF via the browser print dialog, or build an HTML version next pass.
