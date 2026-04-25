"""Re-embed and re-cluster canonical comments with HDBSCAN + strict naming.

Why this exists:
  The original pipeline (comment_audience_analysis.py) uses k-means with
  k=~sqrt(N)≈12. K-means has no concept of noise — every point must join a
  cluster — so the large residual of off-topic / emoji-heavy comments gets
  fragmented across clusters that look similar in embedding space but aren't
  topically similar. The relabel pass (relabel_themes.py) flagged 3/11
  clusters as MIXED but left clusters like "Smooth Move Compliments" partly
  incoherent because the supports_share threshold was too permissive.

What this does instead:
  1. Load canonical (deduped) comments with existing NLP labels from
     analysis_comment_level_filtered.csv.
  2. Re-embed them via qwen3-embedding-8b (same model the original pipeline
     uses, for continuity).
  3. Cluster with sklearn HDBSCAN, which explicitly produces a "noise" label
     (-1) for points that don't fit. Tune min_cluster_size so we end up with
     a small number of tight clusters rather than k=12 fragments.
  4. For each real cluster, compute an intrinsic coherence score (mean
     pairwise cosine similarity). Clusters below a threshold are auto-MIXED
     without paying for an LLM call.
  5. For clusters that pass coherence, call an LLM with 15 centroid-nearest
     + 15 random members and a strict 70% supports-share requirement.

Outputs (to --out-dir, default analysis/):
  - canonical_reclustered.csv:  canonical_id, new_theme_id, new_theme_label,
                                is_mixed, coherence, new_theme_description
  - recluster_report.md:        human-readable summary of what happened
  - recluster_embeddings.npy:   saved embeddings so we can re-cluster without
                                paying OpenRouter again

This script does NOT modify the production CSVs or DuckDB. Use
apply_recluster.py once you're happy with the output.

Usage:
  export OPENROUTER_API_KEY=sk-or-...
  python analysis/recluster_comments.py
  python analysis/recluster_comments.py --min-cluster-size 20 --coherence-min 0.55
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = Path(__file__).resolve().parent
COMMENT_CSV = ANALYSIS_DIR / "analysis_comment_level_filtered.csv"
OUT_CSV = ANALYSIS_DIR / "canonical_reclustered.csv"
OUT_REPORT = ANALYSIS_DIR / "reports" / "recluster_report.md"
EMBEDDINGS_CACHE = ANALYSIS_DIR / "recluster_embeddings.npy"
CANONICAL_CACHE = ANALYSIS_DIR / "recluster_canonicals.csv"

EMBED_MODEL = "qwen/qwen3-embedding-8b"
NAME_MODEL_DEFAULT = "anthropic/claude-sonnet-4.5"


# ---------------------------------------------------------------------------
# OpenRouter helpers (copied from comment_audience_analysis.py to keep this
# script self-contained — stdlib + numpy + pandas + sklearn only)
# ---------------------------------------------------------------------------

@dataclass
class Usage:
    embedding_tokens: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0


def openrouter_headers(api_key: str) -> dict:
    h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if ref := os.getenv("OPENROUTER_HTTP_REFERER"):
        h["HTTP-Referer"] = ref
    if app := os.getenv("OPENROUTER_APP_NAME"):
        h["X-Title"] = app
    return h


def post_json(url: str, payload: dict, headers: dict, timeout: int = 90) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body[:600]}") from exc


def embed_batch(
    texts: list[str], api_key: str, usage: Usage, batch_size: int = 64
) -> np.ndarray:
    base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    headers = openrouter_headers(api_key)
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        payload = {"model": EMBED_MODEL, "input": batch}
        resp = post_json(f"{base}/embeddings", payload, headers=headers)
        data = resp.get("data", [])
        if len(data) != len(batch):
            raise RuntimeError(
                f"Embedding response mismatch: {len(data)} vs {len(batch)}"
            )
        vecs = [d["embedding"] for d in sorted(data, key=lambda x: x.get("index", 0))]
        out.extend(vecs)
        u = resp.get("usage", {})
        usage.embedding_tokens += int(u.get("prompt_tokens", 0) or 0)
        print(f"  embedded {min(i + batch_size, len(texts))}/{len(texts)}")
        time.sleep(0.2)
    return np.asarray(out, dtype=np.float32)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_canonicals() -> pd.DataFrame:
    df = pd.read_csv(COMMENT_CSV, dtype=str, keep_default_na=False)
    has_text = df["text_raw"].str.len() > 0
    df = df[has_text].copy()
    # One row per canonical_id — prefer is_canonical=1 (the "representative"
    # member as chosen by the original dedup pass).
    df["_is_canon"] = (df["is_canonical"] == "1").astype(int)
    df = df.sort_values(["canonical_id", "_is_canon"], ascending=[True, False])
    canon = df.drop_duplicates(subset=["canonical_id"], keep="first")
    return canon[[
        "canonical_id", "text_raw", "text_norm",
        "theme_human_label", "watch_intent_label", "watch_intent_confidence",
    ]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Embeddings with cache
# ---------------------------------------------------------------------------

def l2_normalize(X: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(X, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return X / n


def get_embeddings(
    canon: pd.DataFrame, api_key: str, usage: Usage, force: bool = False
) -> np.ndarray:
    """Cached embeddings. Regenerate if the canonical set changes or --force."""
    signature = (
        CANONICAL_CACHE.exists()
        and EMBEDDINGS_CACHE.exists()
        and not force
    )
    if signature:
        cached = pd.read_csv(CANONICAL_CACHE, dtype=str, keep_default_na=False)
        if (
            len(cached) == len(canon)
            and (cached["canonical_id"].values == canon["canonical_id"].values).all()
        ):
            X = np.load(EMBEDDINGS_CACHE)
            if X.shape[0] == len(canon):
                print(f"Reusing cached embeddings ({X.shape}).")
                return X
        print("Cache present but canonical set has changed — re-embedding.")
    print(f"Embedding {len(canon)} canonical texts with {EMBED_MODEL} …")
    X = embed_batch(canon["text_norm"].tolist(), api_key, usage)
    canon[["canonical_id"]].to_csv(CANONICAL_CACHE, index=False)
    np.save(EMBEDDINGS_CACHE, X)
    print(f"Saved embeddings to {EMBEDDINGS_CACHE.name} (shape {X.shape}).")
    return X


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def cluster_hdbscan(
    Xn: np.ndarray, min_cluster_size: int, min_samples: int | None
) -> np.ndarray:
    """HDBSCAN on L2-normalized vectors. Using euclidean distance on
    L2-normalized vectors is monotonic with cosine distance, so this is
    equivalent to cosine clustering without sklearn needing a custom metric."""
    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = model.fit_predict(Xn)
    return labels


def cluster_coherence(Xn: np.ndarray, member_idx: np.ndarray) -> float:
    """Mean pairwise cosine similarity over a cluster's members. Since Xn is
    L2-normalized, cosine similarity = dot product."""
    if len(member_idx) < 2:
        return 1.0
    # Sample to keep O(n^2) manageable
    if len(member_idx) > 120:
        rng = np.random.default_rng(17)
        member_idx = rng.choice(member_idx, size=120, replace=False)
    V = Xn[member_idx]
    S = V @ V.T
    iu = np.triu_indices_from(S, k=1)
    return float(S[iu].mean())


def sort_centroid_nearest(
    Xn: np.ndarray, member_idx: np.ndarray
) -> np.ndarray:
    centroid = Xn[member_idx].mean(axis=0)
    centroid = centroid / (np.linalg.norm(centroid) + 1e-12)
    sims = Xn[member_idx] @ centroid
    order = np.argsort(-sims)  # descending
    return member_idx[order]


# ---------------------------------------------------------------------------
# LLM naming (strict prompt)
# ---------------------------------------------------------------------------

def build_naming_prompt(clusters_payload: list[dict]) -> tuple[str, str]:
    system = (
        "You are auditing and naming clusters of short social-media comments. "
        "For each cluster you are given two samples: "
        "`prototypical` (closest to the cluster centroid) and `random_tail` "
        "(a random sample of the rest of the cluster).\n\n"
        "Your job is to assign a label that accurately describes AT LEAST 70% "
        "of the shown comments across BOTH samples. Be strict: a comment only "
        "counts as supporting the label if it directly references the "
        "specific topic — not if it merely shares a mood, tone, or grammatical "
        "shape.\n\n"
        "Rules:\n"
        "- Labels: 2-5 words, descriptive, not euphemistic. If the content is "
        "dismissive or negative, say so — do not soften.\n"
        "- The label must describe what the comments ARE ABOUT, not just "
        "their form ('Short Replies' is not a topic).\n"
        "- supports_share: your strict estimate (0-1) of the fraction of "
        "shown comments where the label directly applies.\n"
        "- is_mixed: true when supports_share < 0.70. When MIXED, return the "
        "literal string 'MIXED' as theme_human_label and explain in the "
        "description what's actually in the cluster.\n"
        "- Reactions like '??', emoji-only, generic \"lol\" / \"nice\" / "
        "\"oh\" do NOT count as supporting any topic label. If >30% of the "
        "shown comments are like that, the cluster is MIXED.\n\n"
        "Return ONLY JSON: {\"items\": [{\"theme_id\": str, "
        "\"theme_human_label\": str, \"theme_description\": str, "
        "\"supports_share\": number, \"is_mixed\": bool, \"notes\": str}]} "
        "— one item per input cluster, matching theme_id."
    )
    user = json.dumps({"clusters": clusters_payload}, ensure_ascii=False)
    return system, user


def call_namer(
    clusters_payload: list[dict], model: str, api_key: str, usage: Usage
) -> list[dict]:
    base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    system, user = build_naming_prompt(clusters_payload)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = post_json(
                f"{base}/chat/completions", payload,
                headers=openrouter_headers(api_key),
            )
            u = resp.get("usage", {})
            usage.llm_input_tokens += int(u.get("prompt_tokens", 0) or 0)
            usage.llm_output_tokens += int(u.get("completion_tokens", 0) or 0)
            content = resp["choices"][0]["message"]["content"]
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                s, e = content.find("{"), content.rfind("}")
                parsed = json.loads(content[s:e + 1])
            items = parsed.get("items", [])
            if not items:
                raise RuntimeError("Namer returned no items")
            return items
        except Exception as exc:
            last_err = exc
            print(f"  namer attempt {attempt+1} failed: {exc}", file=sys.stderr)
            time.sleep(1.5)
    raise RuntimeError(f"Namer failed after retries: {last_err}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def write_report(
    canon: pd.DataFrame,
    labels: np.ndarray,
    result_by_cluster: dict[int, dict],
    params: dict,
) -> None:
    lines = []
    lines.append("# Recluster report\n")
    lines.append(f"- min_cluster_size: **{params['min_cluster_size']}**")
    lines.append(f"- min_samples: **{params['min_samples']}**")
    lines.append(f"- coherence_min (auto-MIXED below): **{params['coherence_min']:.2f}**")
    lines.append(f"- supports_share_min (LLM threshold): **0.70**")
    lines.append(f"- N canonical texts: **{len(canon)}**")
    n_noise = int((labels == -1).sum())
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    lines.append(
        f"- Clusters found: **{n_clusters}** (+ {n_noise} noise points)"
    )
    lines.append("")
    lines.append("## Clusters\n")
    lines.append(
        "| cluster_id | members | coherence | label | is_mixed | supports |"
    )
    lines.append("|---|---|---|---|---|---|")
    for cid, info in sorted(result_by_cluster.items()):
        lines.append(
            f"| {cid} | {info['n']} | {info['coherence']:.2f} | "
            f"{info['label']!r} | {'Y' if info['is_mixed'] else 'N'} | "
            f"{info['supports_share']:.0%} |"
        )
    if -1 in labels:
        lines.append(
            f"| **noise** | {n_noise} | — | _(auto-MIXED)_ | Y | — |"
        )
    lines.append("")
    # Per-cluster exemplars
    lines.append("## Per-cluster exemplars\n")
    for cid, info in sorted(result_by_cluster.items()):
        lines.append(
            f"### Cluster {cid}  ·  {info['label']}  "
            f"({info['n']} members, coherence {info['coherence']:.2f}"
            f"{', MIXED' if info['is_mixed'] else ''})\n"
        )
        for t in info["exemplars"][:6]:
            lines.append(f"- _{t[:200]}_")
        lines.append("")
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_REPORT.name}.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-cluster-size", type=int, default=15)
    parser.add_argument("--min-samples", type=int, default=None)
    parser.add_argument("--coherence-min", type=float, default=0.55,
                        help="Clusters with mean pairwise cosine below this "
                             "are auto-labeled MIXED without an LLM call.")
    parser.add_argument("--force-embed", action="store_true",
                        help="Ignore cached embeddings and re-embed.")
    parser.add_argument("--name-model", default=NAME_MODEL_DEFAULT)
    parser.add_argument("--n-prototypical", type=int, default=15)
    parser.add_argument("--n-random", type=int, default=15)
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.", file=sys.stderr)
        return 2

    usage = Usage()
    print("Loading canonicals …")
    canon = load_canonicals()
    print(f"  {len(canon)} unique canonical texts (with prior labels).")

    X = get_embeddings(canon, api_key, usage, force=args.force_embed)
    Xn = l2_normalize(X)

    print(f"Clustering with HDBSCAN "
          f"(min_cluster_size={args.min_cluster_size}, "
          f"min_samples={args.min_samples}) …")
    labels = cluster_hdbscan(Xn, args.min_cluster_size, args.min_samples)
    unique = sorted(set(labels))
    n_noise = int((labels == -1).sum())
    n_clusters = len([u for u in unique if u != -1])
    print(f"  {n_clusters} clusters, {n_noise} noise points "
          f"({n_noise / len(labels) * 100:.0f}% of canonicals).")
    if n_clusters == 0:
        print("WARN: no clusters found — lower --min-cluster-size.")
        return 1

    # Build per-cluster payload: compute coherence, pick exemplars, gate LLM.
    cluster_info: dict[int, dict] = {}
    llm_payload: list[dict] = []
    rng = random.Random(17)
    for cid in unique:
        if cid == -1:
            continue
        member_idx = np.where(labels == cid)[0]
        coh = cluster_coherence(Xn, member_idx)
        ordered = sort_centroid_nearest(Xn, member_idx)
        proto = [canon["text_raw"].iloc[i] for i in ordered[:args.n_prototypical]]
        tail_pool = list(ordered[args.n_prototypical:])
        rng.shuffle(tail_pool)
        tail = [canon["text_raw"].iloc[i] for i in tail_pool[:args.n_random]]
        cluster_info[int(cid)] = {
            "n": int(len(member_idx)),
            "coherence": coh,
            "exemplars": proto + tail,
            "label": "",
            "description": "",
            "supports_share": 0.0,
            "is_mixed": False,
            "notes": "",
        }
        if coh < args.coherence_min:
            cluster_info[int(cid)].update({
                "label": "MIXED",
                "is_mixed": True,
                "description": f"Auto-flagged: intrinsic coherence {coh:.2f} "
                               f"< {args.coherence_min:.2f}. Cluster vectors "
                               f"don't tightly co-locate; no single topic.",
                "supports_share": 0.0,
                "notes": "auto-mixed (low coherence)",
            })
        else:
            llm_payload.append({
                "theme_id": f"c{cid}",
                "n_total_comments": int(len(member_idx)),
                "coherence": round(coh, 3),
                "prototypical": [str(t)[:200] for t in proto],
                "random_tail": [str(t)[:200] for t in tail],
            })

    if llm_payload:
        print(f"Calling namer on {len(llm_payload)} coherent clusters …")
        items = call_namer(llm_payload, args.name_model, api_key, usage)
        by_id = {str(it.get("theme_id", "")): it for it in items}
        for cid in list(cluster_info):
            key = f"c{cid}"
            if key in by_id and not cluster_info[cid]["is_mixed"]:
                it = by_id[key]
                cluster_info[cid].update({
                    "label": str(it.get("theme_human_label") or "").strip(),
                    "description": str(it.get("theme_description") or "").strip(),
                    "supports_share": float(it.get("supports_share") or 0.0),
                    "is_mixed": bool(it.get("is_mixed", False))
                                or str(it.get("theme_human_label", "")).strip().upper() == "MIXED",
                    "notes": str(it.get("notes") or "").strip(),
                })
                if cluster_info[cid]["supports_share"] < 0.70:
                    cluster_info[cid]["is_mixed"] = True
                if cluster_info[cid]["is_mixed"]:
                    cluster_info[cid]["label"] = "MIXED"
    else:
        print("All clusters auto-MIXED by coherence gate — skipping namer.")

    # Write canonical → new-theme mapping CSV
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "canonical_id", "old_theme_label", "new_cluster_id",
            "new_theme_label", "is_mixed", "coherence", "supports_share",
            "new_theme_description",
        ])
        for i, row in canon.iterrows():
            cid = int(labels[i])
            if cid == -1:
                new_label = "MIXED"
                is_mixed = True
                coh = 0.0
                supp = 0.0
                desc = "HDBSCAN noise point — no nearby cluster."
            else:
                info = cluster_info[cid]
                new_label = info["label"] or "MIXED"
                is_mixed = info["is_mixed"]
                coh = info["coherence"]
                supp = info["supports_share"]
                desc = info["description"]
            w.writerow([
                row["canonical_id"],
                row["theme_human_label"],
                cid,
                new_label,
                1 if is_mixed else 0,
                f"{coh:.4f}",
                f"{supp:.4f}",
                desc,
            ])
    print(f"Wrote {OUT_CSV.name}.")

    write_report(canon, labels, cluster_info, {
        "min_cluster_size": args.min_cluster_size,
        "min_samples": args.min_samples,
        "coherence_min": args.coherence_min,
    })

    print()
    print("Summary:")
    n_mixed_points = int(sum(
        info["n"] for info in cluster_info.values() if info["is_mixed"]
    )) + n_noise
    n_named_points = int(sum(
        info["n"] for info in cluster_info.values() if not info["is_mixed"]
    ))
    print(f"  clusters total: {n_clusters}")
    print(f"  clusters MIXED: "
          f"{sum(1 for i in cluster_info.values() if i['is_mixed'])}"
          f" (+ {n_noise} noise points)")
    print(f"  canonicals in named clusters: {n_named_points}")
    print(f"  canonicals in MIXED/noise: {n_mixed_points}")
    print(f"  embedding tokens used: {usage.embedding_tokens}")
    print(f"  LLM tokens: in={usage.llm_input_tokens} "
          f"out={usage.llm_output_tokens}")
    print()
    print("Review canonical_reclustered.csv and recluster_report.md.")
    print("If it looks right, run apply_recluster.py to write to DB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
