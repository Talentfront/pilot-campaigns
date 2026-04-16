"""Re-label existing themes using a broader sample than the original pipeline.

The original pipeline (comment_audience_analysis.py) named each cluster from
only the first 6 texts + a few keywords, which let the LLM invent names that
didn't describe the bulk of the cluster ("Positive Affirmations" for a cluster
of short dismissals, "Step-by-Step Instructions" for a cluster with zero
instructions).

This script:
  1. For each existing theme (current label + theme_id) in raw_comments,
     samples top-N prototypical members (by theme_confidence desc) + N random
     members. This gives the LLM both the "core" and the "tail" of the cluster.
  2. Asks an LLM for a fresh label, a description, a supports_share estimate
     (what fraction of shown comments the label actually describes), and a
     MIXED flag if no label covers >=60%.
  3. Writes mapping to analysis/theme_relabel_mapping.csv for human review.

Does NOT update the database — use apply_theme_relabel.py for that.

Usage:
  export OPENROUTER_API_KEY=sk-or-...
  python analysis/relabel_themes.py
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path
from urllib import error, request

import duckdb

ANALYSIS_DIR = Path(__file__).resolve().parent
DB_PATH = ANALYSIS_DIR / "pilot.duckdb"
OUT_PATH = ANALYSIS_DIR / "theme_relabel_mapping.csv"

MODEL = os.getenv("RELABEL_MODEL", "anthropic/claude-sonnet-4.5")
N_PROTOTYPICAL = 15
N_RANDOM = 15
MAX_TEXT_CHARS = 200
MIXED_THRESHOLD = 0.60


def openrouter_headers(api_key: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if ref := os.getenv("OPENROUTER_HTTP_REFERER"):
        headers["HTTP-Referer"] = ref
    if app := os.getenv("OPENROUTER_APP_NAME"):
        headers["X-Title"] = app
    return headers


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
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body[:800]}") from exc


def gather_theme_samples() -> list[dict]:
    """One row per existing theme, with prototypical + random member samples."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    themes = con.execute(
        """
        SELECT theme_id, theme_human_label, COUNT(*) AS n_total
        FROM raw_comments
        WHERE theme_human_label IS NOT NULL AND theme_human_label <> ''
          AND text_raw IS NOT NULL AND LENGTH(text_raw) > 0
        GROUP BY theme_id, theme_human_label
        ORDER BY n_total DESC
        """
    ).fetchdf()

    rng = random.Random(17)
    out = []
    for _, t in themes.iterrows():
        tid = t["theme_id"]
        current_label = t["theme_human_label"]
        n_total = int(t["n_total"])

        proto = con.execute(
            """
            SELECT text_raw, theme_confidence
            FROM raw_comments
            WHERE theme_id = ?
              AND text_raw IS NOT NULL AND LENGTH(text_raw) > 0
            ORDER BY COALESCE(theme_confidence, 0) DESC
            LIMIT ?
            """,
            [tid, N_PROTOTYPICAL],
        ).fetchdf()
        proto_texts = [str(r)[:MAX_TEXT_CHARS] for r in proto["text_raw"].tolist()]

        rest = con.execute(
            """
            SELECT text_raw
            FROM raw_comments
            WHERE theme_id = ?
              AND text_raw IS NOT NULL AND LENGTH(text_raw) > 0
            ORDER BY COALESCE(theme_confidence, 0) DESC
            OFFSET ?
            """,
            [tid, N_PROTOTYPICAL],
        ).fetchdf()
        rest_texts = [str(r)[:MAX_TEXT_CHARS] for r in rest["text_raw"].tolist()]
        rng.shuffle(rest_texts)
        random_texts = rest_texts[:N_RANDOM]

        out.append({
            "theme_id": tid,
            "current_label": current_label,
            "n_total": n_total,
            "prototypical": proto_texts,
            "random_tail": random_texts,
        })
    return out


def build_prompt(themes: list[dict]) -> tuple[str, str]:
    system = (
        "You are auditing labels for clusters of short social-media comments. "
        "Each cluster has a current label that may or may not fit. "
        "You are given two samples per cluster: prototypical (closest to cluster "
        "centroid) and random_tail (a random sample of the rest). "
        "Your job is to return a label that accurately describes at least "
        f"{int(MIXED_THRESHOLD*100)}% of the shown comments. "
        "If no single topic describes that many, return theme_human_label "
        "exactly as the string \"MIXED\" and explain in the description what "
        "the cluster actually contains (e.g., 'short dismissive one-liners — "
        "no shared topic').\n\n"
        "Rules:\n"
        "- Labels must be 2-5 words, descriptive, not slang, not euphemistic. "
        "If comments are negative/dismissive, say so (do not soften to "
        "'Positive Affirmations').\n"
        "- The label must describe what the comments ARE, not what they are "
        "ABOUT in the abstract. E.g., 'Short Dismissive Replies' not "
        "'Negative Sentiment'.\n"
        "- supports_share: your estimate of the fraction of shown comments "
        "(across both samples) the label actually describes. Must be between "
        "0 and 1.\n"
        "- is_mixed: true if supports_share < "
        f"{MIXED_THRESHOLD}, else false.\n"
        "- Never invent content. If the cluster is short reactions with no "
        "topic, call it MIXED.\n\n"
        "Return ONLY a JSON object of the form:\n"
        "{\"items\": [{\"theme_id\": str, \"theme_human_label\": str, "
        "\"theme_description\": str, \"supports_share\": number, "
        "\"is_mixed\": bool, \"notes\": str}]}\n"
        "Return one item per input cluster, same theme_id, same order."
    )
    user_clusters = [
        {
            "theme_id": t["theme_id"],
            "current_label": t["current_label"],
            "n_total_comments": t["n_total"],
            "prototypical": t["prototypical"],
            "random_tail": t["random_tail"],
        }
        for t in themes
    ]
    user = json.dumps({"clusters": user_clusters}, ensure_ascii=False)
    return system, user


def call_relabel(themes: list[dict], api_key: str) -> list[dict]:
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    system, user = build_prompt(themes)
    payload = {
        "model": MODEL,
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
                f"{base_url}/chat/completions",
                payload,
                headers=openrouter_headers(api_key),
            )
            content = resp["choices"][0]["message"]["content"]
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                s, e = content.find("{"), content.rfind("}")
                parsed = json.loads(content[s:e + 1])
            items = parsed.get("items", [])
            if not items:
                raise RuntimeError("No items in LLM response")
            return items
        except Exception as exc:
            last_err = exc
            print(f"  attempt {attempt+1} failed: {exc}", file=sys.stderr)
            time.sleep(1.5)
    raise RuntimeError(f"LLM call failed after retries: {last_err}")


def write_mapping(themes: list[dict], items: list[dict]) -> None:
    import csv
    by_id = {str(it.get("theme_id", "")): it for it in items}
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "theme_id", "n_total", "current_label", "new_label",
            "is_mixed", "supports_share", "description", "notes",
        ])
        for t in themes:
            it = by_id.get(str(t["theme_id"]), {})
            w.writerow([
                t["theme_id"],
                t["n_total"],
                t["current_label"],
                it.get("theme_human_label", ""),
                "1" if it.get("is_mixed") else "0",
                it.get("supports_share", ""),
                it.get("theme_description", ""),
                it.get("notes", ""),
            ])
    print(f"Wrote mapping -> {OUT_PATH}")


def main() -> int:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.", file=sys.stderr)
        return 2
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found.", file=sys.stderr)
        return 2

    themes = gather_theme_samples()
    print(f"Auditing {len(themes)} themes "
          f"({sum(t['n_total'] for t in themes)} total comments).")
    for t in themes:
        print(f"  - {t['current_label']!r:40s} "
              f"n_total={t['n_total']:4d} "
              f"proto={len(t['prototypical']):2d} "
              f"random={len(t['random_tail']):2d}")

    items = call_relabel(themes, api_key)
    write_mapping(themes, items)

    print("\nProposed changes:")
    by_id = {str(it.get("theme_id", "")): it for it in items}
    for t in themes:
        it = by_id.get(str(t["theme_id"]), {})
        new = it.get("theme_human_label", "?")
        share = it.get("supports_share", "?")
        mixed = " [MIXED]" if it.get("is_mixed") else ""
        mark = "CHANGE" if new != t["current_label"] else "keep  "
        print(f"  {mark}: {t['current_label']!r:38s} -> {new!r:38s} "
              f"(supports={share}{mixed})")
    print("\nReview the mapping, then run apply_theme_relabel.py to write to DB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
