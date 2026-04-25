"""Side-by-side comparison of weighted vs. unweighted intent rates.

Reads analysis_comment_level_filtered.csv (one row = one comment = one vote)
and analysis_comment_level_filtered_weighted.csv (same rows + `weight`).

For every video with ≥5 comments, computes:
- high_rate:          sum(is_high) / N         vs  sum(w*is_high) / sum(w)
- neg_or_conf_rate:   sum(is_neg_or_conf) / N  vs  sum(w*is_nc)   / sum(w)
- winner_score:       high - 0.5*nc            (both variants)

Then:
1. Full per-video table.
2. Top 15 biggest winner_score movers.
3. Theme-share shift (unweighted vs weighted) for the most-moved themes.

Output: analysis/compare_weighted.md

Usage:
  python analysis/add_like_weights.py   # produces the weighted CSV
  python analysis/compare_weighted_vs_unweighted.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ANALYSIS_DIR = Path(__file__).resolve().parent
UNW_CSV = ANALYSIS_DIR / "analysis_comment_level_filtered.csv"
W_CSV = ANALYSIS_DIR / "analysis_comment_level_filtered_weighted.csv"
OUT_MD = ANALYSIS_DIR / "reports" / "compare_weighted.md"

MIN_N_COMMENTS = 5  # guardrail for per-video stats


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """Add is_high and is_neg_or_conf boolean columns."""
    df = df.copy()
    df["is_high"] = (df["watch_intent_label"] == "high").astype(int)
    neg = df["sentiment_label"] == "neg"
    conf = df["confusion_flag"].astype(str).str.lower().isin({"true", "1"})
    df["is_neg_or_conf"] = (neg | conf).astype(int)
    return df


def per_video_unweighted(df: pd.DataFrame) -> pd.DataFrame:
    agg = df.groupby("input_url").agg(
        n=("row_id", "count"),
        high_rate=("is_high", "mean"),
        nc_rate=("is_neg_or_conf", "mean"),
    )
    agg["winner_score"] = agg["high_rate"] - 0.5 * agg["nc_rate"]
    return agg


def per_video_weighted(df: pd.DataFrame) -> pd.DataFrame:
    def wstats(g: pd.DataFrame) -> pd.Series:
        w = g["weight"].to_numpy()
        tot = w.sum()
        if tot == 0:
            return pd.Series({
                "n": len(g),
                "total_weight": 0.0,
                "high_rate_w": 0.0,
                "nc_rate_w": 0.0,
            })
        return pd.Series({
            "n": len(g),
            "total_weight": float(tot),
            "high_rate_w": float((w * g["is_high"].to_numpy()).sum() / tot),
            "nc_rate_w": float((w * g["is_neg_or_conf"].to_numpy()).sum() / tot),
        })
    agg = df.groupby("input_url").apply(wstats, include_groups=False)
    agg["winner_score_w"] = agg["high_rate_w"] - 0.5 * agg["nc_rate_w"]
    return agg


def theme_shares(df: pd.DataFrame, weighted: bool) -> pd.Series:
    if weighted:
        tot = df["weight"].sum()
        return df.groupby("theme_human_label")["weight"].sum() / tot
    return df["theme_human_label"].value_counts(normalize=True)


def main() -> int:
    unw = classify(pd.read_csv(UNW_CSV, dtype=str, keep_default_na=False))
    w = classify(pd.read_csv(W_CSV, dtype=str, keep_default_na=False))
    w["weight"] = w["weight"].astype(float)

    pv_unw = per_video_unweighted(unw)
    pv_w = per_video_weighted(w)

    joined = pv_unw.join(pv_w, how="inner", rsuffix="_w2")
    joined = joined[joined["n"] >= MIN_N_COMMENTS].copy()
    joined["delta_winner"] = joined["winner_score_w"] - joined["winner_score"]

    # Theme-share shifts
    ts_unw = theme_shares(unw, weighted=False)
    ts_w = theme_shares(w, weighted=True)
    theme_cmp = pd.DataFrame({"unweighted": ts_unw, "weighted": ts_w}).fillna(0)
    theme_cmp["delta"] = theme_cmp["weighted"] - theme_cmp["unweighted"]
    theme_cmp = theme_cmp.sort_values("delta", key=lambda s: s.abs(), ascending=False)

    # ---- Write markdown ----
    lines: list[str] = []
    lines.append("# Weighted vs unweighted — comparison")
    lines.append("")
    lines.append(f"- Videos analyzed (n ≥ {MIN_N_COMMENTS}): **{len(joined)}**")
    lines.append(f"- Total comments (filtered): **{len(unw)}**")
    lines.append(f"- Total attention-weight: **{w['weight'].sum():.1f}** "
                 f"(mean per-comment weight {w['weight'].mean():.2f})")
    lines.append("")
    lines.append("## Top 15 winner_score movers")
    lines.append("")
    lines.append("| Video | n | winner (unw) | winner (w) | Δ |")
    lines.append("|---|--:|--:|--:|--:|")
    movers = joined.reindex(joined["delta_winner"].abs()
                                    .sort_values(ascending=False).index).head(15)
    for url, r in movers.iterrows():
        short = url.rstrip("/").split("/")[-1]
        lines.append(
            f"| …/{short} | {int(r['n'])} | "
            f"{r['winner_score']:+.3f} | {r['winner_score_w']:+.3f} | "
            f"{r['delta_winner']:+.3f} |"
        )
    lines.append("")
    lines.append("## Theme share shift (attention vs population)")
    lines.append("")
    lines.append("| Theme | unweighted share | weighted share | Δ |")
    lines.append("|---|--:|--:|--:|")
    for theme, r in theme_cmp.head(15).iterrows():
        if not theme:
            theme = "(blank)"
        lines.append(f"| {theme} | {r['unweighted']:.1%} | "
                     f"{r['weighted']:.1%} | {r['delta']:+.1%} |")
    lines.append("")
    lines.append("## Full per-video table")
    lines.append("")
    lines.append("| Video | n | high (unw) | high (w) | nc (unw) | nc (w) | "
                 "winner (unw) | winner (w) | Δ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    full = joined.sort_values("winner_score_w", ascending=False)
    for url, r in full.iterrows():
        short = url.rstrip("/").split("/")[-1]
        lines.append(
            f"| …/{short} | {int(r['n'])} | "
            f"{r['high_rate']:.1%} | {r['high_rate_w']:.1%} | "
            f"{r['nc_rate']:.1%} | {r['nc_rate_w']:.1%} | "
            f"{r['winner_score']:+.3f} | {r['winner_score_w']:+.3f} | "
            f"{r['delta_winner']:+.3f} |"
        )

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print()
    print(f"  Videos analyzed (n >= {MIN_N_COMMENTS}): {len(joined)}")
    print(f"  Mean |Δ winner_score|: "
          f"{joined['delta_winner'].abs().mean():.3f}")
    print(f"  Max  |Δ winner_score|: "
          f"{joined['delta_winner'].abs().max():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
