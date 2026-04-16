"""Pre-compute curated exemplars per theme, ranked by similarity to the
theme label itself.

Why:
  The default _theme_exemplars() heuristic in the dashboard sorts by
  is_canonical + watch_intent_confidence, which surfaces "representative"
  canonical comments — but for a cluster whose label only describes ~75%
  of its members (e.g. "Smooth Move Compliments"), the top-confidence
  exemplars include the tangential 25% that don't support the label.

  Solution: embed each theme label, then rank each cluster's members by
  cosine similarity to that label embedding. Comments that most directly
  support the label float to the top.

Inputs:
  - analysis/recluster_embeddings.npy + recluster_canonicals.csv
    (produced by recluster_comments.py; covers all 453 canonicals)
  - analysis/pilot.duckdb (for current theme_human_label + text + url)

Output:
  - analysis/theme_exemplars.csv: theme, rank, text_raw, input_url,
    canonical_id, watch_intent_label, similarity

The dashboard reads this file and falls back to the previous heuristic
if the file is missing.

Usage:
  export OPENROUTER_API_KEY=sk-or-...
  python analysis/build_theme_exemplars.py
  python analysis/build_theme_exemplars.py --top-k 12  # more per theme
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib import error, request

import duckdb
import numpy as np
import pandas as pd

ANALYSIS_DIR = Path(__file__).resolve().parent
DB_PATH = ANALYSIS_DIR / "pilot.duckdb"
EMBEDDINGS_PATH = ANALYSIS_DIR / "recluster_embeddings.npy"
CANONICALS_PATH = ANALYSIS_DIR / "recluster_canonicals.csv"
OUT_PATH = ANALYSIS_DIR / "theme_exemplars.csv"

EMBED_MODEL = "qwen/qwen3-embedding-8b"
MIN_THEME_SIZE = 3


def openrouter_headers(api_key: str) -> dict:
    h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if ref := os.getenv("OPENROUTER_HTTP_REFERER"):
        h["HTTP-Referer"] = ref
    if app := os.getenv("OPENROUTER_APP_NAME"):
        h["X-Title"] = app
    return h


def post_json(url: str, payload: dict, headers: dict, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body[:500]}") from exc


def embed_labels(labels: list[str], api_key: str) -> np.ndarray:
    """One batched request — themes are ~10 labels."""
    base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    payload = {"model": EMBED_MODEL, "input": labels}
    resp = post_json(
        f"{base}/embeddings", payload, headers=openrouter_headers(api_key)
    )
    data = resp.get("data", [])
    if len(data) != len(labels):
        raise RuntimeError(f"Label embedding mismatch: {len(data)} vs {len(labels)}")
    vecs = [d["embedding"] for d in sorted(data, key=lambda x: x.get("index", 0))]
    return np.asarray(vecs, dtype=np.float32)


def l2_normalize(X: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(X, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return X / n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10,
                        help="Exemplars to keep per theme.")
    parser.add_argument(
        "--label-template",
        default="comment about {label}",
        help="How to phrase a label for embedding. Default wraps the label in "
             "a short sentence so the embedding space matches the comments' "
             "shape. Use {label} as the placeholder.",
    )
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.", file=sys.stderr)
        return 2
    if not EMBEDDINGS_PATH.exists() or not CANONICALS_PATH.exists():
        print(
            "ERROR: canonical embeddings missing. "
            "Run: python analysis/recluster_comments.py first.",
            file=sys.stderr,
        )
        return 2
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} missing.", file=sys.stderr)
        return 2

    X_canon = np.load(EMBEDDINGS_PATH)
    canon_ids = pd.read_csv(CANONICALS_PATH, dtype=str, keep_default_na=False)[
        "canonical_id"
    ].tolist()
    if len(canon_ids) != X_canon.shape[0]:
        print("ERROR: embeddings/canonicals row mismatch.", file=sys.stderr)
        return 2
    canon_to_idx = {cid: i for i, cid in enumerate(canon_ids)}
    Xn_canon = l2_normalize(X_canon)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    comments = con.execute(
        """
        SELECT theme_human_label AS theme, canonical_id, text_raw, input_url,
               watch_intent_label, COALESCE(is_canonical, 0) AS is_canonical,
               COALESCE(watch_intent_confidence, 0) AS watch_intent_confidence
        FROM raw_comments
        WHERE theme_human_label IS NOT NULL AND theme_human_label <> ''
          AND text_raw IS NOT NULL AND LENGTH(text_raw) > 0
        """
    ).fetchdf()

    theme_counts = comments["theme"].value_counts()
    themes = [t for t, n in theme_counts.items() if n >= MIN_THEME_SIZE]
    print(f"Ranking exemplars for {len(themes)} themes "
          f"({len(comments)} comment rows, {len(canon_ids)} canonicals).")

    label_strings = [args.label_template.format(label=t) for t in themes]
    print("Embedding theme labels …")
    label_vecs = l2_normalize(embed_labels(label_strings, api_key))

    out_rows = []
    for theme, label_vec in zip(themes, label_vecs):
        rows = comments[comments["theme"] == theme].copy()
        # Map each row's canonical_id to a canonical vector. Rows whose
        # canonical_id is missing from the embeddings (shouldn't happen, but
        # be defensive) are dropped.
        rows["_idx"] = rows["canonical_id"].map(canon_to_idx)
        rows = rows.dropna(subset=["_idx"])
        rows["_idx"] = rows["_idx"].astype(int)
        if rows.empty:
            continue
        sims = Xn_canon[rows["_idx"].values] @ label_vec
        rows["_sim"] = sims
        # One row per canonical (same canonical comment appears multiple times
        # across videos; pick the rep with highest classifier confidence for
        # display, but rank by similarity to the label).
        rows["_rank_tiebreak"] = (
            rows["is_canonical"].astype(int) * 1e6
            + pd.to_numeric(rows["watch_intent_confidence"], errors="coerce").fillna(0)
        )
        rows = rows.sort_values(
            ["_sim", "_rank_tiebreak"], ascending=[False, False]
        ).drop_duplicates(subset=["canonical_id"], keep="first")
        top = rows.head(args.top_k)
        for rank, (_, r) in enumerate(top.iterrows(), 1):
            out_rows.append({
                "theme": theme,
                "rank": rank,
                "text_raw": r["text_raw"],
                "input_url": r["input_url"],
                "canonical_id": r["canonical_id"],
                "watch_intent_label": r["watch_intent_label"],
                "similarity": round(float(r["_sim"]), 4),
            })
        print(f"  {theme!r:38s} top-{len(top)} ranked "
              f"(max sim {top['_sim'].max():.3f}, "
              f"min {top['_sim'].min():.3f})")

    out_df = pd.DataFrame(out_rows)
    out_df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH.name} ({len(out_df)} rows across "
          f"{out_df['theme'].nunique()} themes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
