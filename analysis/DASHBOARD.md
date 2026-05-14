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

- **Overview** — the first-read story: reach worked, intent is under-measured, measurement needs cleanup
- **Creator Performance** — reach vs intent buckets for deciding which accounts are leads vs bets
- **Audience Signals** — simplified theme readout focused on what comments imply about watch intent
- **Data Quality** — spam audit, caveats, and the backup details to read before quoting findings

## Decision language

The simplified dashboard uses decision-oriented labels:

- **Use now** — stable enough to act on operationally
- **Test next** — promising, but needs campaign #2 validation with more real comments
- **Do not use** — contaminated, raw, or too thin for decisions

The deeper creator page still shows sample-size and pattern badges so readers
can distinguish a repeatable account pattern from a single strong post.
The overview graph also fades videos with fewer than 3 real viewer comments,
because their intent rates are not reliable enough to compare directly.

## Sharing it

The dashboard is a local Python app — to share with someone non-technical, you can either:

1. **Screen-share / walk them through it live.** Best for first-time review.
2. **Export the underlying CSVs** (`analysis/account_rollup.csv`, `analysis/theme_rollup.csv`, etc.) and the static SVG charts (`analysis/*.svg`) for asynchronous review.
3. **Host it remotely** (Streamlit Community Cloud, internal server). Out of scope for this pilot.

If you need a fully self-contained shareable artifact, consider exporting the dashboard contents to PDF via the browser print dialog, or build an HTML version next pass.
