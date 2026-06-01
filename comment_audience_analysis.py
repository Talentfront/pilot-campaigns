#!/usr/bin/env python3
"""
Datadoping comment-level audience analysis pipeline.

Outputs:
- data/processed/analysis_comment_level.csv
- data/processed/analysis_post_level.csv
- data/processed/analysis_summary.md
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple
from urllib import error, request


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
APIFY_DIR = os.path.join(DATA_DIR, "apify")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Comment-level audience analysis.")
    parser.add_argument(
        "--input-json",
        default=os.path.join(APIFY_DIR, "apify_full_results_datadoping.json"),
        help="Path to input datadoping JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default=PROCESSED_DIR,
        help="Directory for output artifacts.",
    )
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--margin-threshold", type=float, default=0.10)
    parser.add_argument("--min-rows-per-post", type=int, default=5)
    parser.add_argument("--cluster-method", choices=["kmeans"], default="kmeans")
    parser.add_argument("--max-themes", type=int, default=12)
    parser.add_argument("--llm-max-items", type=int, default=250)
    parser.add_argument("--llm-batch-size", type=int, default=20)
    parser.add_argument("--quotes-per-theme", type=int, default=5)
    parser.add_argument("--dry-run-no-api", action="store_true")
    return parser.parse_args()


@dataclass
class UsageTotals:
    embedding_input_tokens: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0


def safe_read_json(path: str) -> List[dict]:
    encodings = ["cp1252", "utf-8", "utf-8-sig", "latin-1"]
    last_err = None
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, errors="replace") as f:
                raw = f.read()
            parsed = json.loads(raw, strict=False)
            if isinstance(parsed, list):
                return parsed
            raise ValueError(f"Expected list JSON root, got {type(parsed).__name__}")
        except Exception as exc:  # pylint: disable=broad-except
            last_err = exc
    raise RuntimeError(f"Failed to read JSON at {path}: {last_err}")


URL_RE = re.compile(r"https?://\S+")
MENTION_RE = re.compile(r"@\w+")
WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")


def normalize_text(text: str) -> str:
    lowered = text.lower().strip()
    lowered = URL_RE.sub(" ", lowered)
    lowered = MENTION_RE.sub(" ", lowered)
    lowered = WHITESPACE_RE.sub(" ", lowered).strip()
    return lowered


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def filter_rows(raw_rows: List[dict]) -> List[dict]:
    filtered = []
    for idx, row in enumerate(raw_rows):
        ctype = row.get("content_type")
        if ctype not in {"comment", "reply"}:
            continue
        text = row.get("text")
        if text is None:
            text = ""
        text = str(text)
        post_key = row.get("input_url") or "unknown_post"
        filtered.append(
            {
                "row_id": f"r{idx}",
                "content_type": ctype,
                "input_url": str(post_key),
                "text_raw": text,
                "text_norm": normalize_text(text),
                "comment_id": str(row.get("comment_id", "")),
            }
        )
    return filtered


def build_canonical_map(rows: List[dict]) -> Tuple[Dict[str, dict], Dict[str, str], List[dict], int]:
    canonical_by_key: Dict[str, dict] = {}
    row_to_canonical: Dict[str, str] = {}
    empty_text_rows = 0
    for row in rows:
        text_norm = row["text_norm"]
        if not text_norm:
            empty_text_rows += 1
            continue
        key = stable_hash(text_norm)
        if key not in canonical_by_key:
            canonical_by_key[key] = {
                "canonical_id": f"c{len(canonical_by_key)}",
                "text_norm": text_norm,
                "text_raw_example": row["text_raw"],
                "source_row_id": row["row_id"],
                "count": 0,
                "post_counts": Counter(),
            }
        canonical_by_key[key]["count"] += 1
        canonical_by_key[key]["post_counts"][row["input_url"]] += 1
        row_to_canonical[row["row_id"]] = canonical_by_key[key]["canonical_id"]

    canonical_rows = sorted(canonical_by_key.values(), key=lambda x: x["canonical_id"])
    canonical_lookup = {row["canonical_id"]: row for row in canonical_rows}
    return canonical_lookup, row_to_canonical, canonical_rows, empty_text_rows


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = 0.0
    den_a = 0.0
    den_b = 0.0
    for x, y in zip(a, b):
        num += x * y
        den_a += x * x
        den_b += y * y
    if den_a <= 0.0 or den_b <= 0.0:
        return 0.0
    return num / ((den_a ** 0.5) * (den_b ** 0.5))


def softmax(scores: Dict[str, float], temperature: float = 0.6) -> Dict[str, float]:
    if not scores:
        return {}
    scaled = {k: v / max(temperature, 1e-6) for k, v in scores.items()}
    max_score = max(scaled.values())
    exps = {k: math.exp(v - max_score) for k, v in scaled.items()}
    total = sum(exps.values()) or 1.0
    return {k: exps[k] / total for k in exps}


def top_two(probs: Dict[str, float]) -> Tuple[Tuple[str, float], Tuple[str, float]]:
    ordered = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    first = ordered[0] if ordered else ("unknown", 0.0)
    second = ordered[1] if len(ordered) > 1 else ("unknown", 0.0)
    return first, second


def hashed_text_embedding(text: str, dim: int = 256) -> List[float]:
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8", errors="ignore")).hexdigest(), 16)
        idx = h % dim
        sign = -1.0 if ((h >> 1) & 1) else 1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def post_json(url: str, payload: dict, headers: dict, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=data, method="POST")
    for key, val in headers.items():
        req.add_header(key, val)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body[:500]}") from exc


def openrouter_headers(api_key: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    referer = os.getenv("OPENROUTER_HTTP_REFERER")
    app_name = os.getenv("OPENROUTER_APP_NAME")
    if referer:
        headers["HTTP-Referer"] = referer
    if app_name:
        headers["X-Title"] = app_name
    return headers


def embed_texts_openrouter(
    texts: List[str],
    model: str,
    api_key: str,
    usage: UsageTotals,
    batch_size: int = 64,
) -> List[List[float]]:
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    headers = openrouter_headers(api_key)
    all_embeddings: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        payload = {"model": model, "input": batch}
        response = post_json(f"{base_url}/embeddings", payload, headers=headers)
        data = response.get("data", [])
        if len(data) != len(batch):
            raise RuntimeError(f"Embedding response mismatch: expected {len(batch)} got {len(data)}")
        batch_vectors = [item["embedding"] for item in sorted(data, key=lambda x: x.get("index", 0))]
        all_embeddings.extend(batch_vectors)
        usage_info = response.get("usage", {})
        usage.embedding_input_tokens += int(usage_info.get("prompt_tokens", 0) or 0)
        time.sleep(0.2)
    return all_embeddings


def call_llm_batch(
    texts: List[str],
    model: str,
    api_key: str,
    usage: UsageTotals,
) -> List[dict]:
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    headers = openrouter_headers(api_key)
    instruction = (
        "Classify each social media comment JSON item.\n"
        "Return ONLY JSON object with key 'items', matching input order.\n"
        "Each item must include: sentiment_label(pos|neu|neg), "
        "watch_intent_label(high|med|low), confusion_flag(true|false).\n"
        "Rubric: broad curiosity intent => high includes explicit intent to watch "
        "and strong curiosity/enthusiastic inquiry likely to watch."
    )
    user_payload = {"items": [{"text": t} for t in texts]}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    last_err = None
    for _ in range(3):
        response = post_json(f"{base_url}/chat/completions", payload, headers=headers)
        usage_info = response.get("usage", {})
        usage.llm_input_tokens += int(usage_info.get("prompt_tokens", 0) or 0)
        usage.llm_output_tokens += int(usage_info.get("completion_tokens", 0) or 0)
        content = response["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(content[start : end + 1])
                except json.JSONDecodeError as exc:
                    last_err = exc
                    time.sleep(0.3)
                    continue
            else:
                last_err = RuntimeError("No JSON object in LLM response")
                time.sleep(0.3)
                continue
        items = parsed.get("items", [])
        if len(items) != len(texts):
            last_err = RuntimeError(f"LLM batch mismatch: expected {len(texts)} got {len(items)}")
            time.sleep(0.3)
            continue
        return items
    raise RuntimeError(f"Failed to parse LLM batch response: {last_err}")


def call_llm_theme_names(
    cluster_payload: List[dict],
    model: str,
    api_key: str,
    usage: UsageTotals,
) -> Dict[str, dict]:
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    headers = openrouter_headers(api_key)
    instruction = (
        "You are naming social-comment themes. "
        "For each cluster, return a concise human label (2-5 words) and one sentence description. "
        "Do not include slang unless core to meaning. "
        "Return JSON object with key 'items'. "
        "Each item: theme_id, theme_human_label, theme_description."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps({"clusters": cluster_payload}, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    last_err = None
    parsed = {}
    for _ in range(3):
        response = post_json(f"{base_url}/chat/completions", payload, headers=headers)
        usage_info = response.get("usage", {})
        usage.llm_input_tokens += int(usage_info.get("prompt_tokens", 0) or 0)
        usage.llm_output_tokens += int(usage_info.get("completion_tokens", 0) or 0)
        content = response["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
            break
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(content[start : end + 1])
                    break
                except json.JSONDecodeError as exc:
                    last_err = exc
                    time.sleep(0.3)
                    continue
            last_err = RuntimeError("No JSON object in LLM response")
            time.sleep(0.3)
    if not parsed:
        raise RuntimeError(f"Failed to parse theme-naming response: {last_err}")
    items = parsed.get("items", [])
    out = {}
    for item in items:
        tid = str(item.get("theme_id", "")).strip()
        if not tid:
            continue
        out[tid] = {
            "theme_human_label": str(item.get("theme_human_label", "")).strip(),
            "theme_description": str(item.get("theme_description", "")).strip(),
        }
    return out


SENTIMENT_PROTOTYPES = {
    "pos": ["love this", "this is great", "amazing hilarious", "so good wow"],
    "neu": ["okay sure", "what is this", "interesting", "hmm"],
    "neg": ["this is bad", "cringe", "hate this", "confusing and annoying"],
}

WATCH_INTENT_PROTOTYPES = {
    "high": ["where can i watch this", "what series is this", "need to watch now", "i want to see this"],
    "med": ["looks interesting", "maybe later", "curious about this", "might watch"],
    "low": ["not watching", "skip this", "boring no thanks", "dont care"],
}

CONFUSION_WORDS = {
    "what",
    "huh",
    "confused",
    "confusing",
    "context",
    "explain",
    "series",
    "name",
    "where",
    "?",
}


def mean_vector(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0] * dim
    for vec in vectors:
        for i, val in enumerate(vec):
            out[i] += val
    n = float(len(vectors))
    out = [v / n for v in out]
    norm = math.sqrt(sum(v * v for v in out))
    if norm > 0:
        out = [v / norm for v in out]
    return out


def build_prototype_vectors(
    prototype_map: Dict[str, List[str]],
    embed_lookup: Dict[str, List[float]],
) -> Dict[str, List[float]]:
    vectors = {}
    for label, texts in prototype_map.items():
        vectors[label] = mean_vector([embed_lookup[t] for t in texts])
    return vectors


def classify_by_prototype(
    text_vec: List[float],
    proto_vectors: Dict[str, List[float]],
) -> Tuple[str, float, float]:
    sims = {label: cosine(text_vec, vec) for label, vec in proto_vectors.items()}
    probs = softmax(sims, temperature=0.5)
    (best_label, best_prob), (_, second_prob) = top_two(probs)
    margin = best_prob - second_prob
    return best_label, best_prob, margin


def heuristic_confusion(text_norm: str) -> bool:
    if "?" in text_norm:
        return True
    tokens = set(tokenize(text_norm))
    return any(w in tokens for w in CONFUSION_WORDS if w != "?")


def init_centroids(vectors: List[List[float]], k: int, seed: int = 42) -> List[List[float]]:
    rnd = random.Random(seed)
    indices = list(range(len(vectors)))
    rnd.shuffle(indices)
    return [vectors[i][:] for i in indices[:k]]


def kmeans(vectors: List[List[float]], k: int, iterations: int = 25) -> Tuple[List[int], List[List[float]]]:
    if not vectors:
        return [], []
    if len(vectors) <= k:
        labels = list(range(len(vectors)))
        return labels, [v[:] for v in vectors]
    centroids = init_centroids(vectors, k)
    labels = [0] * len(vectors)
    for _ in range(iterations):
        changed = False
        for i, vec in enumerate(vectors):
            best_idx, best_sim = 0, -2.0
            for c_idx, c in enumerate(centroids):
                sim = cosine(vec, c)
                if sim > best_sim:
                    best_idx, best_sim = c_idx, sim
            if labels[i] != best_idx:
                labels[i] = best_idx
                changed = True
        grouped = defaultdict(list)
        for idx, label in enumerate(labels):
            grouped[label].append(vectors[idx])
        new_centroids = []
        for c_idx in range(k):
            if grouped[c_idx]:
                new_centroids.append(mean_vector(grouped[c_idx]))
            else:
                new_centroids.append(centroids[c_idx])
        centroids = new_centroids
        if not changed:
            break
    return labels, centroids


def top_terms(texts: List[str], top_k: int = 3) -> List[str]:
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "is",
        "it",
        "this",
        "that",
        "i",
        "you",
        "we",
        "they",
        "in",
        "for",
        "on",
        "at",
        "with",
        "so",
        "im",
        "its",
    }
    counts = Counter()
    for text in texts:
        for tok in tokenize(text):
            if len(tok) < 3 or tok in stop:
                continue
            counts[tok] += 1
    return [t for t, _ in counts.most_common(top_k)] or ["misc"]


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def safe_div(n: float, d: float) -> float:
    return (n / d) if d else 0.0


def pick_representative_quotes(
    rows: List[dict],
    quotes_per_theme: int,
) -> Dict[str, List[Tuple[str, str]]]:
    by_theme = defaultdict(list)
    for row in rows:
        theme = row.get("theme_human_label", "")
        text = row.get("text_raw", "")
        post = row.get("input_url", "")
        conf = float(row.get("theme_confidence") or 0.0)
        if not theme or not text:
            continue
        by_theme[theme].append((conf, text, post))

    out: Dict[str, List[Tuple[str, str]]] = {}
    for theme, items in by_theme.items():
        # Prefer high-confidence rows and diversify across posts.
        items_sorted = sorted(items, key=lambda x: x[0], reverse=True)
        selected: List[Tuple[str, str]] = []
        seen_posts = set()

        for _, text, post in items_sorted:
            if post in seen_posts:
                continue
            selected.append((text, post))
            seen_posts.add(post)
            if len(selected) >= quotes_per_theme:
                break

        if len(selected) < quotes_per_theme:
            for _, text, post in items_sorted:
                pair = (text, post)
                if pair in selected:
                    continue
                selected.append(pair)
                if len(selected) >= quotes_per_theme:
                    break

        out[theme] = selected
    return out


def main() -> None:
    args = parse_args()
    started = time.time()
    os.makedirs(args.output_dir, exist_ok=True)

    raw_rows = safe_read_json(args.input_json)
    filtered_rows = filter_rows(raw_rows)
    canonical_lookup, row_to_canonical, canonical_rows, empty_text_rows = build_canonical_map(filtered_rows)

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    use_api = bool(api_key) and not args.dry_run_no_api
    usage = UsageTotals()

    canonical_texts = [c["text_norm"] for c in canonical_rows]
    prototype_seed_texts = sorted(
        set(sum(SENTIMENT_PROTOTYPES.values(), []) + sum(WATCH_INTENT_PROTOTYPES.values(), []))
    )

    if use_api:
        embed_inputs = prototype_seed_texts + canonical_texts
        embed_vectors = embed_texts_openrouter(
            texts=embed_inputs,
            model="qwen/qwen3-embedding-8b",
            api_key=api_key,
            usage=usage,
            batch_size=64,
        )
        embed_lookup: Dict[str, List[float]] = {text: vec for text, vec in zip(embed_inputs, embed_vectors)}
        canonical_vectors = [embed_lookup[t] for t in canonical_texts]
    else:
        embed_lookup = {text: hashed_text_embedding(text) for text in prototype_seed_texts}
        canonical_vectors = [hashed_text_embedding(t) for t in canonical_texts]

    sentiment_proto = build_prototype_vectors(SENTIMENT_PROTOTYPES, embed_lookup)
    watch_proto = build_prototype_vectors(WATCH_INTENT_PROTOTYPES, embed_lookup)

    canonical_labels: Dict[str, dict] = {}
    uncertain_ids: List[str] = []
    for c_row, vec in zip(canonical_rows, canonical_vectors):
        sent_label, sent_conf, sent_margin = classify_by_prototype(vec, sentiment_proto)
        watch_label, watch_conf, watch_margin = classify_by_prototype(vec, watch_proto)
        text_norm = c_row["text_norm"]
        confusion_flag = heuristic_confusion(text_norm)
        uncertain = (
            sent_conf < args.min_confidence
            or watch_conf < args.min_confidence
            or sent_margin < args.margin_threshold
            or watch_margin < args.margin_threshold
        )
        if uncertain:
            uncertain_ids.append(c_row["canonical_id"])
        canonical_labels[c_row["canonical_id"]] = {
            "sentiment_label": sent_label,
            "sentiment_confidence": sent_conf,
            "watch_intent_label": watch_label,
            "watch_intent_confidence": watch_conf,
            "confusion_flag": confusion_flag,
            "label_source": "model",
        }

    llm_routed = uncertain_ids[: args.llm_max_items] if use_api else []
    if use_api and llm_routed:
        for i in range(0, len(llm_routed), args.llm_batch_size):
            batch_ids = llm_routed[i : i + args.llm_batch_size]
            batch_texts = [canonical_lookup[cid]["text_norm"] for cid in batch_ids]
            llm_items = call_llm_batch(
                texts=batch_texts,
                model="google/gemini-2.5-flash-lite",
                api_key=api_key,
                usage=usage,
            )
            for cid, item in zip(batch_ids, llm_items):
                s = str(item.get("sentiment_label", "")).lower()
                w = str(item.get("watch_intent_label", "")).lower()
                c = bool(item.get("confusion_flag", False))
                if s not in {"pos", "neu", "neg"}:
                    s = canonical_labels[cid]["sentiment_label"]
                if w not in {"high", "med", "low"}:
                    w = canonical_labels[cid]["watch_intent_label"]
                canonical_labels[cid].update(
                    {
                        "sentiment_label": s,
                        "watch_intent_label": w,
                        "confusion_flag": c,
                        "label_source": "llm",
                    }
                )
            time.sleep(0.4)

    target_k = max(3, min(args.max_themes, int(round(math.sqrt(max(1, len(canonical_rows))))) ))
    theme_labels, centroids = kmeans(canonical_vectors, target_k, iterations=30)
    cluster_to_texts = defaultdict(list)
    for c_row, cluster_idx in zip(canonical_rows, theme_labels):
        cluster_to_texts[cluster_idx].append(c_row["text_norm"])

    theme_name_by_cluster = {}
    for c_idx, texts in cluster_to_texts.items():
        terms = top_terms(texts, top_k=3)
        theme_name_by_cluster[c_idx] = "_".join(terms[:3])

    cluster_payload = []
    cluster_quality = {}
    for c_idx, texts in cluster_to_texts.items():
        theme_id = f"t{c_idx}"
        member_idxs = [i for i, lbl in enumerate(theme_labels) if lbl == c_idx]
        sims = [cosine(canonical_vectors[i], centroids[c_idx]) for i in member_idxs]
        avg_sim = sum(sims) / len(sims) if sims else 0.0
        posts = Counter()
        for i in member_idxs:
            cid = canonical_rows[i]["canonical_id"]
            posts.update(canonical_lookup[cid]["post_counts"])
        top_post_share = (posts.most_common(1)[0][1] / sum(posts.values())) if posts else 0.0
        cluster_quality[theme_id] = {"avg_similarity": avg_sim, "top_post_share": top_post_share}
        sample_texts = texts[:6]
        cluster_payload.append(
            {
                "theme_id": theme_id,
                "keywords": top_terms(texts, top_k=5),
                "sample_quotes": sample_texts,
            }
        )

    human_theme_meta = {}
    for c_idx, texts in cluster_to_texts.items():
        tid = f"t{c_idx}"
        kws = top_terms(texts, top_k=3)
        human_theme_meta[tid] = {
            "theme_human_label": " ".join(w.capitalize() for w in kws[:3]),
            "theme_description": f"Comments focused on: {', '.join(kws)}.",
        }
    if use_api and cluster_payload:
        llm_named = call_llm_theme_names(
            cluster_payload=cluster_payload,
            model="google/gemini-2.5-flash-lite",
            api_key=api_key,
            usage=usage,
        )
        for tid, meta in llm_named.items():
            if tid in human_theme_meta:
                if meta.get("theme_human_label"):
                    human_theme_meta[tid]["theme_human_label"] = meta["theme_human_label"]
                if meta.get("theme_description"):
                    human_theme_meta[tid]["theme_description"] = meta["theme_description"]

    theme_of_canonical = {}
    for c_row, vec, c_idx in zip(canonical_rows, canonical_vectors, theme_labels):
        center = centroids[c_idx]
        sim = (cosine(vec, center) + 1.0) / 2.0
        tid = f"t{c_idx}"
        theme_of_canonical[c_row["canonical_id"]] = {
            "theme_id": tid,
            "theme_label": theme_name_by_cluster[c_idx],
            "theme_human_label": human_theme_meta[tid]["theme_human_label"],
            "theme_description": human_theme_meta[tid]["theme_description"],
            "theme_confidence": sim,
        }

    comment_level_rows = []
    for row in filtered_rows:
        cid = row_to_canonical.get(row["row_id"], "")
        has_text = bool(row["text_norm"])
        base = {
            "row_id": row["row_id"],
            "input_url": row["input_url"],
            "content_type": row["content_type"],
            "text_raw": row["text_raw"],
            "text_norm": row["text_norm"],
            "is_canonical": "1" if (cid and canonical_lookup[cid]["source_row_id"] == row["row_id"]) else "0",
            "canonical_id": cid,
        }
        if has_text and cid:
            labels = canonical_labels[cid]
            theme = theme_of_canonical[cid]
            base.update(
                {
                    "sentiment_label": labels["sentiment_label"],
                    "sentiment_confidence": f"{labels['sentiment_confidence']:.4f}",
                    "watch_intent_label": labels["watch_intent_label"],
                    "watch_intent_confidence": f"{labels['watch_intent_confidence']:.4f}",
                    "confusion_flag": "1" if labels["confusion_flag"] else "0",
                    "theme_id": theme["theme_id"],
                    "theme_label": theme["theme_label"],
                    "theme_human_label": theme["theme_human_label"],
                    "theme_description": theme["theme_description"],
                    "theme_confidence": f"{theme['theme_confidence']:.4f}",
                    "label_source": labels["label_source"],
                }
            )
        else:
            base.update(
                {
                    "sentiment_label": "",
                    "sentiment_confidence": "",
                    "watch_intent_label": "",
                    "watch_intent_confidence": "",
                    "confusion_flag": "",
                    "theme_id": "",
                    "theme_label": "",
                    "theme_human_label": "",
                    "theme_description": "",
                    "theme_confidence": "",
                    "label_source": "",
                }
            )
        comment_level_rows.append(base)

    by_post = defaultdict(list)
    for row in comment_level_rows:
        by_post[row["input_url"]].append(row)

    post_level_rows = []
    for post, rows in by_post.items():
        n_comments = sum(1 for r in rows if r["content_type"] == "comment")
        n_replies = sum(1 for r in rows if r["content_type"] == "reply")
        labeled = [r for r in rows if r["sentiment_label"]]
        n_total_text_rows = len(labeled)
        sent = Counter(r["sentiment_label"] for r in labeled)
        watch = Counter(r["watch_intent_label"] for r in labeled)
        confusion = sum(1 for r in labeled if r["confusion_flag"] == "1")
        neg_or_conf = sum(
            1 for r in labeled if (r["sentiment_label"] == "neg" or r["confusion_flag"] == "1")
        )
        theme_counts = Counter(r["theme_human_label"] for r in labeled if r["theme_human_label"])
        top3 = theme_counts.most_common(3)
        top_theme = [t[0] for t in top3] + ["", "", ""]
        top_share = [safe_div(t[1], n_total_text_rows) for t in top3] + [0.0, 0.0, 0.0]
        high_rate = safe_div(watch["high"], n_total_text_rows)
        neg_conf_rate = safe_div(neg_or_conf, n_total_text_rows)
        winner_score = high_rate - (0.5 * neg_conf_rate)
        post_level_rows.append(
            {
                "input_url": post,
                "n_comments": n_comments,
                "n_replies": n_replies,
                "n_total_text_rows": n_total_text_rows,
                "pos_rate": safe_div(sent["pos"], n_total_text_rows),
                "neu_rate": safe_div(sent["neu"], n_total_text_rows),
                "neg_rate": safe_div(sent["neg"], n_total_text_rows),
                "high_rate": high_rate,
                "med_rate": safe_div(watch["med"], n_total_text_rows),
                "low_rate": safe_div(watch["low"], n_total_text_rows),
                "confusion_rate": safe_div(confusion, n_total_text_rows),
                "negative_or_confusion_rate": neg_conf_rate,
                "replies_to_comments_ratio": safe_div(n_replies, n_comments),
                "top_theme_1": top_theme[0],
                "top_theme_2": top_theme[1],
                "top_theme_3": top_theme[2],
                "top_theme_share_1": top_share[0],
                "top_theme_share_2": top_share[1],
                "top_theme_share_3": top_share[2],
                "winner_score": winner_score,
            }
        )

    post_level_rows.sort(key=lambda x: x["winner_score"], reverse=True)
    eligible = [r for r in post_level_rows if r["n_total_text_rows"] >= args.min_rows_per_post]
    winners = eligible[:5]
    laggards = list(reversed(eligible[-5:]))

    check_1 = all(r["content_type"] in {"comment", "reply"} for r in filtered_rows)
    check_2 = len(row_to_canonical) == sum(1 for r in filtered_rows if r["text_norm"])
    check_3 = all(
        (not r["text_norm"]) or (r["sentiment_label"] and r["watch_intent_label"])
        for r in comment_level_rows
    )
    uncertain_ratio = safe_div(len(uncertain_ids), len(canonical_rows))

    embed_rate = float(os.getenv("EMBEDDING_USD_PER_1M", "0"))
    llm_in_rate = float(os.getenv("LLM_INPUT_USD_PER_1M", "0"))
    llm_out_rate = float(os.getenv("LLM_OUTPUT_USD_PER_1M", "0"))
    embedding_cost = (usage.embedding_input_tokens / 1_000_000.0) * embed_rate
    llm_cost = (
        (usage.llm_input_tokens / 1_000_000.0) * llm_in_rate
        + (usage.llm_output_tokens / 1_000_000.0) * llm_out_rate
    )
    total_cost = embedding_cost + llm_cost

    comment_level_path = os.path.join(args.output_dir, "analysis_comment_level.csv")
    post_level_path = os.path.join(args.output_dir, "analysis_post_level.csv")
    summary_path = os.path.join(args.output_dir, "analysis_summary.md")

    with open(comment_level_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "row_id",
                "input_url",
                "content_type",
                "text_raw",
                "text_norm",
                "sentiment_label",
                "sentiment_confidence",
                "watch_intent_label",
                "watch_intent_confidence",
                "confusion_flag",
                "theme_id",
                "theme_label",
                "theme_human_label",
                "theme_description",
                "theme_confidence",
                "is_canonical",
                "canonical_id",
                "label_source",
            ],
        )
        writer.writeheader()
        writer.writerows(comment_level_rows)

    with open(post_level_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "input_url",
                "n_comments",
                "n_replies",
                "n_total_text_rows",
                "pos_rate",
                "neu_rate",
                "neg_rate",
                "high_rate",
                "med_rate",
                "low_rate",
                "confusion_rate",
                "negative_or_confusion_rate",
                "replies_to_comments_ratio",
                "top_theme_1",
                "top_theme_2",
                "top_theme_3",
                "top_theme_share_1",
                "top_theme_share_2",
                "top_theme_share_3",
                "winner_score",
            ],
        )
        writer.writeheader()
        writer.writerows(post_level_rows)

    theme_quote_candidates = defaultdict(list)
    theme_desc_lookup = {}
    theme_quality_lookup = {}
    for row in comment_level_rows:
        if not row["theme_label"] or not row["text_raw"]:
            continue
        theme_quote_candidates[row["theme_human_label"]].append((row["text_raw"], row["input_url"]))
        theme_desc_lookup[row["theme_human_label"]] = row["theme_description"]
        q = cluster_quality.get(row["theme_id"], {})
        theme_quality_lookup[row["theme_human_label"]] = q

    selected_quotes_by_theme = pick_representative_quotes(
        comment_level_rows,
        quotes_per_theme=max(1, args.quotes_per_theme),
    )

    theme_lines = []
    for theme, cnt in Counter(
        r["theme_human_label"] for r in comment_level_rows if r["theme_human_label"]
    ).most_common(8):
        quotes = selected_quotes_by_theme.get(theme, [])[: max(1, args.quotes_per_theme)]
        quote_text = " | ".join([f"\"{q[:140]}\" ({u})" for q, u in quotes]) if quotes else ""
        desc = theme_desc_lookup.get(theme, "")
        q = theme_quality_lookup.get(theme, {})
        avg_sim = q.get("avg_similarity", 0.0)
        dom_post = q.get("top_post_share", 0.0)
        theme_lines.append(
            f"- `{theme}` ({cnt} rows, cohesion={avg_sim:.2f}, top_post_share={dom_post:.2f}): "
            f"{desc} {quote_text}"
        )

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# Datadoping Comment-Level Audience Analysis\n\n")
        f.write("## Run Metrics\n")
        f.write(f"- Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- Input rows (raw): {len(raw_rows)}\n")
        f.write(f"- Filtered comment/reply rows: {len(filtered_rows)}\n")
        f.write(f"- Non-empty text rows: {len(row_to_canonical)}\n")
        f.write(f"- Empty text rows excluded from NLP labeling: {empty_text_rows}\n")
        f.write(f"- Canonical unique texts: {len(canonical_rows)}\n")
        dedupe_savings = safe_div(len(row_to_canonical) - len(canonical_rows), max(1, len(row_to_canonical)))
        f.write(f"- Dedupe savings: {fmt_pct(dedupe_savings)}\n")
        f.write(f"- Uncertain routed (pre-LLM cap): {len(uncertain_ids)} ({fmt_pct(uncertain_ratio)})\n")
        f.write(f"- Uncertain LLM-adjudicated (capped): {len(llm_routed)}\n")
        f.write(f"- Labeling mode: {'hybrid (model + llm)' if use_api else 'model-only fallback (no API key)'}\n")
        f.write(f"- Embedding input tokens: {usage.embedding_input_tokens}\n")
        f.write(f"- LLM input tokens: {usage.llm_input_tokens}\n")
        f.write(f"- LLM output tokens: {usage.llm_output_tokens}\n")
        f.write(f"- Cost estimate (USD): {total_cost:.6f}\n\n")

        f.write("## Data Integrity Checks\n")
        f.write(f"- `content_type` filtered correctly: {'PASS' if check_1 else 'FAIL'}\n")
        f.write(f"- Canonical remap count parity: {'PASS' if check_2 else 'FAIL'}\n")
        f.write(f"- Non-empty rows have labels: {'PASS' if check_3 else 'FAIL'}\n\n")

        f.write("## Winners (min volume guardrail applied)\n")
        if winners:
            for row in winners:
                f.write(
                    "- "
                    f"{row['input_url']} | high_intent={fmt_pct(row['high_rate'])}, "
                    f"neg_or_conf={fmt_pct(row['negative_or_confusion_rate'])}, "
                    f"depth={row['replies_to_comments_ratio']:.2f}, "
                    f"winner_score={row['winner_score']:.4f}\n"
                )
        else:
            f.write("- No eligible winners with current min-volume guardrail.\n")
        f.write("\n")

        f.write("## Laggards (min volume guardrail applied)\n")
        if laggards:
            for row in laggards:
                f.write(
                    "- "
                    f"{row['input_url']} | high_intent={fmt_pct(row['high_rate'])}, "
                    f"neg_or_conf={fmt_pct(row['negative_or_confusion_rate'])}, "
                    f"depth={row['replies_to_comments_ratio']:.2f}, "
                    f"winner_score={row['winner_score']:.4f}\n"
                )
        else:
            f.write("- No eligible laggards with current min-volume guardrail.\n")
        f.write("\n")

        f.write("## Top Themes + Representative Quotes\n")
        for line in theme_lines:
            f.write(f"{line}\n")

        f.write("\n## Notes\n")
        f.write("- Watch-intent rubric: broad curiosity intent.\n")
        f.write("- Non-English handling: as-is (no translation pass).\n")
        f.write("- If API key is provided, rerun to enable OpenRouter embeddings + Gemini adjudication.\n")

    elapsed = time.time() - started
    print(f"Done in {elapsed:.2f}s")
    print(comment_level_path)
    print(post_level_path)
    print(summary_path)


if __name__ == "__main__":
    main()
