"""Promote HDBSCAN re-clustering output to primary theme-of-record.

Counterpart to recluster_comments.py. The latter writes a sidecar audit
(canonical_reclustered.csv, recluster_report.md) at min_cluster_size=15
without touching the production pipeline. This script re-runs HDBSCAN at a
*lower* min_cluster_size (default 5 — see PIPELINE.md limitation #2),
routes noise canonicals to a single "Other" bucket, and writes a
drop-in-replacement row-level CSV that downstream rollups can point at.

Cached embeddings (recluster_embeddings.npy) are reused when the canonical
set is unchanged — no OpenRouter embedding cost. Only the LLM naming call
costs tokens (~one request for all coherent clusters).

Outputs (to analysis/):
  - canonical_rethemed.csv              per-canonical new theme assignment
  - analysis_comment_level_rethemed.csv per-row, joined back via canonical_id;
                                        same schema as the filtered CSV plus
                                        three new columns for the new theme
  - recluster_report_applied.md         human-readable summary

Usage:
  export OPENROUTER_API_KEY=sk-or-...
  python analysis/apply_recluster.py
  python analysis/apply_recluster.py --min-cluster-size 8 --coherence-min 0.55

To wire the output into the dashboard, point analysis/build_workspace.sql's
raw_comments view at analysis_comment_level_rethemed.csv and use
theme_human_label_retheme / theme_id_retheme instead of the original columns.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recluster_comments import (  # noqa: E402  sibling import
    Usage,
    cluster_coherence,
    cluster_hdbscan,
    get_embeddings,
    l2_normalize,
    load_canonicals,
    openrouter_headers,
    post_json,
    sort_centroid_nearest,
)

import json as _json  # noqa: E402
import time as _time  # noqa: E402


def umap_project(X: np.ndarray, n_components: int, seed: int = 17) -> np.ndarray:
    """BERTopic-style dim reduction before density clustering.

    Passes raw (un-normalized) embeddings with metric='cosine' so UMAP does
    the normalization internally — matches BERTopic convention. HDBSCAN then
    runs euclidean on the reduced output, which is well-behaved because the
    curse-of-dimensionality doesn't apply to 5-10 dim space.
    """
    try:
        import umap  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "umap-learn is not installed. `pip install umap-learn`."
        ) from exc
    reducer = umap.UMAP(
        n_components=n_components,
        metric="cosine",
        n_neighbors=15,
        min_dist=0.0,
        random_state=seed,
    )
    return reducer.fit_transform(X)


def build_merge_prompt(clusters_payload: list[dict]) -> tuple[str, str]:
    """Second-pass prompt that merges over-fragmented clusters.

    Based on 'LLM-Assisted Topic Reduction for BERTopic on Social Media Data'
    (arXiv:2509.19365). Low min_cluster_size tends to split the same theme
    into multiple lexical variants ('Movie Name Requests' / 'Name Requests' /
    'Which Movie Requests'). This call asks the LLM to group them.
    """
    system = (
        "You are reviewing the output of a density-clustering pass. Some of "
        "these clusters describe the SAME audience theme at different lexical "
        "or phrasing granularities — for example 'Movie Name Requests', "
        "'Name Requests', 'Which Movie Requests', and 'Movie Requests' are "
        "all variations of one theme: asking what the movie is.\n\n"
        "Your job is to group clusters that share an underlying SUBJECT/TOPIC "
        "into merge groups.\n\n"
        "Rules:\n"
        "- Merge only when clusters share the same subject. Same *tone* or "
        "*sentiment* is not enough. 'Smooth Praise' and 'Rizz Compliments' "
        "share a subject (praising charisma) → merge. 'Smooth Praise' and "
        "'Critical Women Comments' do NOT share a subject even if they come "
        "from the same video → leave separate.\n"
        "- Every input cluster must appear in exactly one group.\n"
        "- Singleton groups are fine — not every cluster has a sibling.\n"
        "- `merged_label`: 2-5 words. If the group is a singleton, reuse the "
        "original label. If multiple, write a label that accurately describes "
        "all members (often this is the most general member's label).\n\n"
        "Return ONLY JSON: {\"groups\": [{\"merged_label\": str, "
        "\"member_cluster_ids\": [int, ...], \"rationale\": str}]}"
    )
    user = _json.dumps({"clusters": clusters_payload}, ensure_ascii=False)
    return system, user


def call_merger(clusters_payload: list[dict], model: str, api_key: str,
                usage: Usage) -> list[dict]:
    base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    system, user = build_merge_prompt(clusters_payload)
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
                parsed = _json.loads(content)
            except _json.JSONDecodeError:
                s, e = content.find("{"), content.rfind("}")
                parsed = _json.loads(content[s:e + 1])
            groups = parsed.get("groups", [])
            if not groups:
                raise RuntimeError("Merger returned no groups")
            return groups
        except Exception as exc:
            last_err = exc
            print(f"  merger attempt {attempt+1} failed: {exc}", file=sys.stderr)
            _time.sleep(1.5)
    raise RuntimeError(f"Merger failed after retries: {last_err}")


def build_naming_prompt_lenient(clusters_payload: list[dict],
                                supports_min: float) -> tuple[str, str]:
    """Softer variant of recluster_comments.build_naming_prompt.

    Differences from strict:
      - Supports threshold lowered (default 0.55 vs 0.70).
      - Terse reactions that share a *subject* (e.g. 'Name?' / 'name please')
        DO count toward the label — as long as the subject is identifiable.
      - Label can be loose topical coherence, not just strict shared topic.
    """
    pct = int(round(supports_min * 100))
    system = (
        "You are naming clusters of short social-media comments. For each "
        "cluster you see two samples: `prototypical` (nearest the centroid) "
        "and `random_tail` (random rest of the cluster).\n\n"
        "Assign a label that describes the shared *subject* of at least "
        f"{pct}% of the shown comments across both samples. Be descriptive "
        "but not strict: a very short comment like 'Name?' or 'What movie' "
        "counts as supporting a 'Movie Name Requests' label because its "
        "subject is identifiable from context, even if the phrasing is "
        "minimal.\n\n"
        "Rules:\n"
        "- Labels: 2-5 words, descriptive, not euphemistic. If the content "
        "is dismissive, critical, or negative, say so directly.\n"
        "- The label names what the comments ARE ABOUT (the subject) — not "
        "just their grammatical form.\n"
        "- supports_share: your estimate (0-1) of the fraction of shown "
        "comments whose subject the label describes. Terse-but-on-topic "
        "comments count. Off-topic emoji floods do NOT count.\n"
        f"- is_mixed: true when supports_share < {supports_min:.2f}. When "
        "MIXED, return the literal string 'MIXED' as theme_human_label and "
        "describe what's actually in the cluster.\n"
        "- A cluster of pure emoji / pure punctuation / pure generic 'lol' "
        "with no identifiable subject IS mixed.\n\n"
        "Return ONLY JSON: {\"items\": [{\"theme_id\": str, "
        "\"theme_human_label\": str, \"theme_description\": str, "
        "\"supports_share\": number, \"is_mixed\": bool, \"notes\": str}]} "
        "— one item per input cluster, matching theme_id."
    )
    user = _json.dumps({"clusters": clusters_payload}, ensure_ascii=False)
    return system, user


def call_namer_lenient(clusters_payload: list[dict], model: str, api_key: str,
                       usage: Usage, supports_min: float) -> list[dict]:
    base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    system, user = build_naming_prompt_lenient(clusters_payload, supports_min)
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
                parsed = _json.loads(content)
            except _json.JSONDecodeError:
                s, e = content.find("{"), content.rfind("}")
                parsed = _json.loads(content[s:e + 1])
            items = parsed.get("items", [])
            if not items:
                raise RuntimeError("Namer returned no items")
            return items
        except Exception as exc:
            last_err = exc
            print(f"  namer attempt {attempt+1} failed: {exc}", file=sys.stderr)
            _time.sleep(1.5)
    raise RuntimeError(f"Namer failed after retries: {last_err}")

ANALYSIS_DIR = Path(__file__).resolve().parent
COMMENT_CSV = ANALYSIS_DIR / "analysis_comment_level_filtered.csv"
OUT_CANONICAL = ANALYSIS_DIR / "canonical_rethemed.csv"
OUT_ROWS = ANALYSIS_DIR / "analysis_comment_level_rethemed.csv"
OUT_REPORT = ANALYSIS_DIR / "reports" / "recluster_report_applied.md"

OTHER_LABEL = "Other"
DEFAULT_NAME_MODEL = "anthropic/claude-sonnet-4.5"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--min-cluster-size", type=int, default=5,
        help="HDBSCAN min_cluster_size. 5 at pilot scale recovers small "
             "coherent themes (Knee Pun, AI Content) that 15 marked as noise.",
    )
    p.add_argument("--min-samples", type=int, default=None)
    p.add_argument(
        "--coherence-min", type=float, default=0.50,
        help="Clusters below this mean pairwise cosine are auto-routed to "
             "'Other' without paying for an LLM naming call.",
    )
    p.add_argument("--name-model", default=DEFAULT_NAME_MODEL)
    p.add_argument(
        "--supports-min", type=float, default=0.55,
        help="LLM-reported supports_share below this is routed to Other. "
             "0.70 = strict (matches recluster_comments.py); 0.55 = lenient "
             "(counts terse-but-on-topic comments as supporting).",
    )
    p.add_argument("--n-prototypical", type=int, default=15)
    p.add_argument("--n-random", type=int, default=15)
    p.add_argument("--force-embed", action="store_true",
                   help="Ignore cached embeddings and re-embed (costs tokens).")
    p.add_argument(
        "--umap-dim", type=int, default=5,
        help="Project embeddings to this many dims with UMAP before HDBSCAN "
             "(BERTopic convention). 0 disables UMAP and clusters on raw "
             "L2-normalized embeddings (old behavior).",
    )
    p.add_argument(
        "--skip-merge", action="store_true",
        help="Skip the LLM-assisted topic reduction pass. Default merges "
             "over-fragmented sibling clusters via a second LLM call.",
    )
    args = p.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.", file=sys.stderr)
        return 2

    usage = Usage()

    print("Loading canonicals from filtered comments …")
    canon = load_canonicals()
    print(f"  {len(canon)} unique canonicals.")

    X = get_embeddings(canon, api_key, usage, force=args.force_embed)
    Xn = l2_normalize(X)

    if args.umap_dim > 0:
        print(f"UMAP projecting {X.shape[1]} → {args.umap_dim} dims "
              f"(metric=cosine) …")
        X_for_cluster = umap_project(X, args.umap_dim)
    else:
        X_for_cluster = Xn

    print(f"HDBSCAN(min_cluster_size={args.min_cluster_size}, "
          f"min_samples={args.min_samples}) …")
    labels = cluster_hdbscan(X_for_cluster, args.min_cluster_size, args.min_samples)
    unique = sorted(set(labels))
    n_noise = int((labels == -1).sum())
    n_clusters = len([u for u in unique if u != -1])
    print(f"  {n_clusters} clusters, {n_noise} noise canonicals "
          f"({n_noise / max(1, len(labels)) * 100:.0f}%).")
    if n_clusters == 0:
        print("WARN: no clusters found — lower --min-cluster-size.")
        return 1

    rng = random.Random(17)
    cluster_info: dict[int, dict] = {}
    llm_payload: list[dict] = []
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
        info = {
            "n": int(len(member_idx)),
            "coherence": coh,
            "exemplars": proto + tail,
            "label": "",
            "description": "",
            "supports_share": 0.0,
            "routed_other": False,
        }
        if coh < args.coherence_min:
            info.update({
                "label": OTHER_LABEL,
                "routed_other": True,
                "description": (
                    f"Auto-Other: intrinsic coherence {coh:.2f} "
                    f"< {args.coherence_min:.2f}."
                ),
            })
        else:
            llm_payload.append({
                "theme_id": f"c{cid}",
                "n_total_comments": int(len(member_idx)),
                "coherence": round(coh, 3),
                "prototypical": [str(t)[:200] for t in proto],
                "random_tail": [str(t)[:200] for t in tail],
            })
        cluster_info[int(cid)] = info

    if llm_payload:
        print(f"Naming {len(llm_payload)} coherent clusters via LLM "
              f"(lenient prompt, supports_min={args.supports_min:.2f}) …")
        items = call_namer_lenient(
            llm_payload, args.name_model, api_key, usage, args.supports_min,
        )
        by_id = {str(it.get("theme_id", "")): it for it in items}
        for cid, info in cluster_info.items():
            if info["routed_other"]:
                continue
            it = by_id.get(f"c{cid}", {})
            label = str(it.get("theme_human_label") or "").strip()
            supports = float(it.get("supports_share") or 0.0)
            llm_flagged_mixed = bool(it.get("is_mixed", False)) \
                or label.upper() == "MIXED"
            if llm_flagged_mixed or supports < args.supports_min or not label:
                info["label"] = OTHER_LABEL
                info["routed_other"] = True
                info["description"] = (
                    f"LLM route-to-Other: supports={supports:.0%}, "
                    f"mixed_flag={llm_flagged_mixed}."
                )
            else:
                info["label"] = label
                info["description"] = str(it.get("theme_description") or "").strip()
            info["supports_share"] = supports
    else:
        print("All clusters auto-Other by coherence gate — skipping namer.")

    # LLM-assisted topic reduction (arxiv:2509.19365) — merge sibling clusters
    # that share a subject but were split by density geometry.
    merges: list[dict] = []
    if not args.skip_merge:
        named_clusters = [
            (cid, info) for cid, info in cluster_info.items()
            if not info["routed_other"]
        ]
        if len(named_clusters) >= 2:
            merge_payload = [{
                "cluster_id": int(cid),
                "label": info["label"],
                "coherence": round(info["coherence"], 3),
                "n_members": info["n"],
                "exemplars": [str(t)[:150] for t in info["exemplars"][:6]],
            } for cid, info in named_clusters]
            print(f"Asking LLM to merge sibling clusters over "
                  f"{len(named_clusters)} named clusters …")
            merges = call_merger(
                merge_payload, args.name_model, api_key, usage,
            )
            # Apply merges: rewrite labels on member clusters.
            for group in merges:
                member_ids = [int(m) for m in group.get("member_cluster_ids", [])]
                merged_label = str(group.get("merged_label", "")).strip()
                if not merged_label or not member_ids:
                    continue
                for mcid in member_ids:
                    if mcid in cluster_info and not cluster_info[mcid]["routed_other"]:
                        cluster_info[mcid]["label"] = merged_label
                        cluster_info[mcid]["merged_into"] = merged_label
        else:
            print("Fewer than 2 named clusters — nothing to merge.")

    canon_new_theme: dict[str, dict] = {}
    with OUT_CANONICAL.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "canonical_id", "old_theme_label", "new_cluster_id",
            "new_theme_label", "coherence", "supports_share",
            "new_theme_description",
        ])
        for i, row in canon.iterrows():
            cid = int(labels[i])
            if cid == -1:
                new_label = OTHER_LABEL
                coh = 0.0
                supp = 0.0
                desc = "HDBSCAN noise — not dense enough to form a cluster."
            else:
                info = cluster_info[cid]
                new_label = info["label"]
                coh = info["coherence"]
                supp = info["supports_share"]
                desc = info["description"]
            canon_new_theme[row["canonical_id"]] = {
                "new_theme_label": new_label,
                "new_cluster_id": cid,
                "coherence": coh,
                "supports_share": supp,
            }
            w.writerow([
                row["canonical_id"], row["theme_human_label"], cid,
                new_label, f"{coh:.4f}", f"{supp:.4f}", desc,
            ])
    print(f"Wrote {OUT_CANONICAL.name}.")

    rows = pd.read_csv(COMMENT_CSV, dtype=str, keep_default_na=False)
    labels_out: list[str] = []
    cids_out: list[str] = []
    coh_out: list[str] = []
    for canon_id in rows["canonical_id"]:
        info = canon_new_theme.get(canon_id)
        if info is None:
            # Row text was empty at filter time so it has no canonical embedding.
            labels_out.append(OTHER_LABEL)
            cids_out.append("-1")
            coh_out.append("0.0000")
        else:
            labels_out.append(info["new_theme_label"])
            cids_out.append(str(info["new_cluster_id"]))
            coh_out.append(f"{info['coherence']:.4f}")
    rows["theme_human_label_retheme"] = labels_out
    rows["theme_id_retheme"] = cids_out
    rows["theme_cohesion_retheme"] = coh_out
    rows.to_csv(OUT_ROWS, index=False, encoding="utf-8")
    print(f"Wrote {OUT_ROWS.name} ({len(rows)} rows).")

    lines = [
        "# Applied recluster report",
        "",
        f"- Input canonicals: **{len(canon)}**",
        f"- umap_dim: **{args.umap_dim}** (0 = disabled)  |  "
        f"min_cluster_size: **{args.min_cluster_size}**  |  "
        f"coherence_min: **{args.coherence_min:.2f}**  |  "
        f"supports_min: **{args.supports_min:.2f}**  |  "
        f"merge_pass: **{'on' if not args.skip_merge else 'off'}**",
        f"- Clusters found: **{n_clusters}**  "
        f"(+ {n_noise} noise canonicals → '{OTHER_LABEL}')",
        "",
        "## Row counts by new theme",
        "",
        "| theme | rows |",
        "|---|---:|",
    ]
    counts = pd.Series(labels_out).value_counts().sort_values(ascending=False)
    for label, n in counts.items():
        lines.append(f"| {label} | {n} |")
    lines += [
        "",
        "## Clusters (canonicals)",
        "",
        "| cluster_id | label | members | coherence | supports |",
        "|---|---|---:|---:|---:|",
    ]
    for cid, info in sorted(cluster_info.items()):
        lines.append(
            f"| {cid} | {info['label']} | {info['n']} | "
            f"{info['coherence']:.2f} | {info['supports_share']:.0%} |"
        )
    if n_noise:
        lines.append(
            f"| noise | {OTHER_LABEL} | {n_noise} | — | — |"
        )

    if merges:
        lines += ["", "## Merge groups (LLM-assisted topic reduction)", ""]
        for g in merges:
            ids = g.get("member_cluster_ids", [])
            if len(ids) > 1:
                rationale = str(g.get("rationale", "")).strip()
                lines.append(
                    f"- **{g.get('merged_label','?')}** ← clusters {ids}"
                    + (f"  _{rationale}_" if rationale else "")
                )

    lines += [
        "",
        f"LLM tokens — in: {usage.llm_input_tokens}, "
        f"out: {usage.llm_output_tokens}",
    ]
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_REPORT.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
