#!/usr/bin/env python3
"""Score a running RAHBAR against a golden set, and gate CI on the result (section 5).

    python eval/run_eval.py --api http://<ingress>                 # your corpus
    python eval/run_eval.py --api ... --golden eval/fixtures/golden.fixture.yaml
    python eval/run_eval.py --api ... --update-baseline            # after a deliberate improvement

Exit code 0 when every gate passes, 1 when any fails. CI relies on that exit code.

What it measures (section 5): recall@3 and recall@5 overall and by question type, citation validity
(every citation must match a chunk retrieved for that request), abstention correctness (every must-abstain
question must be declined: 100 percent, not 90) and, as extras, the answer rate on answerable questions and
how often a superseded document reaches the top 5 for a version-sensitive question.
Matching rule: a retrieved passage matches a golden one when it has the same source AND (the section matches
OR the page is the same); see docs/PIPELINE.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent

# The gate from section 5.4. Change these only with a reason written in docs/PIPELINE.md.
MAX_RECALL5_DROP = 0.05        # recall@5 may fall at most 5 points below the baseline
MIN_CITATION_VALIDITY = 0.95   # at least 95% of citations must match retrieved passages
REQUIRED_ABSTENTION = 1.0      # every must-abstain question must be declined


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    return questions


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """POST one question and return the AskResponse as a dict (see api/app/schemas.py)."""
    response = client.post(f"{api.rstrip('/')}/api/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def _norm(text: object) -> str:
    return " ".join(str(text or "").lower().split())


def section_matches(want: object, got: object) -> bool:
    """Two section names match when, ignoring case and spacing, one contains the other
    ("Tuition Fee" matches "Tuition Fee (w.e.f. Fall 2026 semester)")."""
    w, g = _norm(want), _norm(got)
    return bool(w) and (w == g or w in g or g in w)


def passage_matches(relevant: dict, item: dict) -> bool:
    """The matching rule (docs/PIPELINE.md): same source AND (the section matches OR the page is the same).
    The page fallback keeps a heading-detection quirk from scoring a correct retrieval as a miss."""
    if _norm(relevant.get("source")) != _norm(item.get("source")):
        return False
    same_page = relevant.get("page") is not None and relevant.get("page") == item.get("page")
    return section_matches(relevant.get("section"), item.get("section")) or same_page


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Fraction of the relevant passages found in the top k retrieved (a relevant passage counts once, when any of
    the top-k items matches it). None when the question has no relevant passages (must-abstain questions)."""
    if not relevant:
        return None
    top = retrieved[:k]
    found = sum(1 for rel in relevant if any(passage_matches(rel, item) for item in top))
    return found / len(relevant)


def _citation_counts(response: dict) -> tuple[int, int]:
    """(valid, total) citations. A citation is valid when it matches a passage in response['retrieved']."""
    retrieved = response.get("retrieved") or []
    citations = response.get("citations") or []
    valid = sum(1 for c in citations if any(passage_matches(c, item) for item in retrieved))
    return valid, len(citations)


def citation_validity(response: dict) -> float | None:
    """Fraction of the response's citations that match a passage in response['retrieved'].
    None when there are no citations."""
    valid, total = _citation_counts(response)
    return None if total == 0 else valid / total


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _by_type(rows: list[dict], key: str) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for kind in sorted({r["type"] for r in rows}):
        value = _mean([r[key] for r in rows if r["type"] == kind])
        if value is not None:
            out[kind] = _round(value)
    return out


def summarise(rows: list[dict]) -> dict:
    """Overall recall@3, recall@5, citation validity and abstention correctness, plus recall@5 and recall@3 broken
    down by question type. This dict becomes results.json."""
    per_question = []
    valid_total = cites_total = 0
    for row in rows:
        response = row["response"]
        retrieved = response.get("retrieved") or []
        relevant = row.get("relevant") or []
        valid, total = _citation_counts(response)
        valid_total += valid
        cites_total += total
        leaked = [a["source"] for a in (row.get("avoid") or [])
                  if any(_norm(a["source"]) == _norm(item.get("source")) for item in retrieved[:5])]
        per_question.append({
            "id": row["id"], "type": row["type"],
            "recall_at_3": recall_at_k(relevant, retrieved, 3),
            "recall_at_5": recall_at_k(relevant, retrieved, 5),
            "citation_validity": citation_validity(response),
            "answered_from_context": bool(response.get("answered_from_context")),
            "superseded_in_top5": bool(leaked),
            "seconds": row.get("seconds"),
        })
    must = [r for r in rows if r.get("must_abstain")]
    wrongly = [r["id"] for r in must if r["response"].get("answered_from_context")]
    answerable = [q for q, r in zip(per_question, rows, strict=True)
                  if not r.get("must_abstain") and r["type"] != "injection"]
    with_avoid = [q for q, r in zip(per_question, rows, strict=True) if r.get("avoid")]
    return {
        "recall_at_3": _round(_mean([q["recall_at_3"] for q in per_question])),
        "recall_at_5": _round(_mean([q["recall_at_5"] for q in per_question])),
        "recall_at_3_by_type": _by_type(per_question, "recall_at_3"),
        "recall_at_5_by_type": _by_type(per_question, "recall_at_5"),
        "citation_validity": None if cites_total == 0 else round(valid_total / cites_total, 4),
        "citations_checked": cites_total,
        "abstention_correctness": None if not must else round(1 - len(wrongly) / len(must), 4),
        "wrongly_answered": wrongly,
        "answer_rate_on_answerable": _round(_mean([1.0 if q["answered_from_context"] else 0.0 for q in answerable])),
        "superseded_leak_rate": _round(_mean([1.0 if q["superseded_in_top5"] else 0.0 for q in with_avoid])),
        "per_question": per_question,
        "n_questions": len(rows),
    }


def gate(results: dict, baseline: dict | None) -> list[str]:
    """Return one message per failed gate (section 5.4); an empty list means pass."""
    eps = 1e-9
    failures = []
    abstention = results.get("abstention_correctness")
    if abstention is not None and abstention < REQUIRED_ABSTENTION - eps:
        failures.append("a must-abstain question was answered from context: "
                        + ", ".join(results.get("wrongly_answered") or ["?"]))
    validity = results.get("citation_validity")
    if validity is not None and validity < MIN_CITATION_VALIDITY - eps:
        failures.append(f"citation validity {validity:.1%} is below the {MIN_CITATION_VALIDITY:.0%} minimum")
    now, before = results.get("recall_at_5"), (baseline or {}).get("recall_at_5")
    if now is not None and before is not None and now < before - MAX_RECALL5_DROP - eps:
        failures.append(f"recall@5 {now:.3f} dropped more than {MAX_RECALL5_DROP:.0%} below the baseline {before:.3f}")
    # A fourth, stricter-than-required check, added after failure experiment E (docs/FAILURE-ANALYSIS.md): without the
    # superseded filter the first three conditions all passed while 100% of the version questions leaked a repealed document.
    leak, leak_before = results.get("superseded_leak_rate"), (baseline or {}).get("superseded_leak_rate")
    if leak is not None and leak_before is not None and leak > leak_before + eps:
        failures.append(f"superseded leak rate {leak:.0%} is above the baseline {leak_before:.0%}: "
                        "a repealed document reached the top of the retrieval")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAHBAR against a golden set.")
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header, when your Ingress rule names a host")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write these results as the new baseline")
    args = parser.parse_args()

    questions = load_golden(args.golden)
    rows = []
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        for q in questions:
            started = time.perf_counter()
            response = ask(client, args.api, q["question"])
            rows.append({
                "id": q["id"], "type": q.get("type", "ordinary"),
                "must_abstain": bool(q.get("must_abstain", False)),
                "relevant": q.get("relevant") or [],
                "avoid": q.get("avoid") or [],
                "expect": q.get("expect"),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"  {q['id']:<5} {rows[-1]['seconds']:>6.2f}s  {q['question'][:60]}")

    results = summarise(rows)
    baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
    failures = gate(results, baseline)

    results["golden"] = str(args.golden)
    results["questions"] = len(rows)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out}")
    if args.update_baseline:
        args.baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"baseline updated: {args.baseline}")

    if failures:
        print("\nGATE FAILED")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\ngate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
