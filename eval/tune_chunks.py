#!/usr/bin/env python3
"""Measure recall@k for several (size, overlap) chunking configurations (section 3.1: tune with measurements).

    python eval/tune_chunks.py --ollama http://<host>:11434 --configs 200:25,400:50,800:100

For each configuration it runs the real extract, clean and chunk stages over the corpus, embeds every chunk with the
pinned model, and scores the golden set with the same retrieval rules the API uses: cosine similarity, superseded
documents excluded unless the question asks about an older version, and the lexical rescue for exact tokens. No LLM is
involved, so this isolates retrieval (the stages A to E of the failure analysis).

Extraction (OCR) is the slow part and does not depend on the chunking, so the cleaned documents are cached on disk.
Writes eval/chunk-tuning/results.json and prints a table for docs/PIPELINE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "indexer"))
sys.path.insert(0, str(HERE.parent / "api"))
sys.path.insert(0, str(HERE))

import run_eval  # noqa: E402
from app.retrieval.chroma import exact_tokens  # noqa: E402
from app.services.grounding import is_older_version_question  # noqa: E402
from pipeline.chunk import amplification, chunk  # noqa: E402
from pipeline.clean import clean  # noqa: E402
from pipeline.extract import extract  # noqa: E402
from pipeline.models import Document, Page  # noqa: E402


def load_documents(corpus: Path, cache_dir: Path) -> list[Document]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    docs = []
    for entry in json.loads((corpus / "_index.json").read_text(encoding="utf-8")):
        path = corpus / entry["file"]
        cache = cache_dir / f"{path.name}.{path.stat().st_size}.json"
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            doc = Document(source=data["source"], doc_version=data["doc_version"], superseded=data["superseded"],
                           pages=[Page(**p) for p in data["pages"]])
        else:
            started = time.perf_counter()
            doc = clean(extract(str(path), str(entry["doc_version"]), bool(entry["superseded"])))
            cache.write_text(json.dumps({
                "source": doc.source, "doc_version": doc.doc_version, "superseded": doc.superseded,
                "pages": [vars(p) for p in doc.pages]}), encoding="utf-8")
            print(f"  extracted {path.name} in {time.perf_counter() - started:.0f}s", flush=True)
        docs.append(doc)
    return docs


def embed_all(client: httpx.Client, url: str, model: str, texts: list[str], prefix: str) -> np.ndarray:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), 16):
        batch = [prefix + t for t in texts[start:start + 16]]
        r = client.post(f"{url.rstrip('/')}/api/embed", json={"model": model, "input": batch})
        r.raise_for_status()
        vectors.extend(r.json()["embeddings"])
    m = np.array(vectors, dtype=float)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def retrieve(question: str, qvec: np.ndarray, chunks: list, cvecs: np.ndarray, k: int, hybrid: bool) -> list[dict]:
    allow_old = is_older_version_question(question)
    idx = [i for i, c in enumerate(chunks) if allow_old or not c.superseded]
    sims = cvecs[idx] @ qvec
    order = [idx[i] for i in np.argsort(-sims)]
    ranked = order[:k]
    if hybrid:
        rescued: list[int] = []
        for token in exact_tokens(question)[:2]:
            hits = [i for i in order if token in chunks[i].text][:2]
            rescued.extend(hits)
        ranked = list(dict.fromkeys(rescued + order))[:k]
    return [{"source": chunks[i].source, "section": chunks[i].section, "page": chunks[i].page} for i in ranked]


def score(questions: list[dict], qvecs: np.ndarray, chunks: list, cvecs: np.ndarray, hybrid: bool) -> dict:
    rows = []
    for q, qv in zip(questions, qvecs, strict=True):
        items = retrieve(q["question"], qv, chunks, cvecs, 5, hybrid)
        rows.append({"id": q["id"], "type": q.get("type", "ordinary"), "relevant": q.get("relevant") or [],
                     "r3": run_eval.recall_at_k(q.get("relevant") or [], items, 3),
                     "r5": run_eval.recall_at_k(q.get("relevant") or [], items, 5)})
    by_type: dict[str, float] = {}
    for kind in sorted({r["type"] for r in rows}):
        vals = [r["r5"] for r in rows if r["type"] == kind and r["r5"] is not None]
        if vals:
            by_type[kind] = round(sum(vals) / len(vals), 3)
    r3 = [r["r3"] for r in rows if r["r3"] is not None]
    r5 = [r["r5"] for r in rows if r["r5"] is not None]
    return {"recall_at_3": round(sum(r3) / len(r3), 3), "recall_at_5": round(sum(r5) / len(r5), 3),
            "recall_at_5_by_type": by_type, "missed": [r["id"] for r in rows if r["r5"] is not None and r["r5"] < 1]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Chunk-size tuning by recall@k.")
    parser.add_argument("--corpus", type=Path, default=HERE.parent / "corpus" / "raw")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="nomic-embed-text")
    parser.add_argument("--configs", default="200:25,400:50,800:100")
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/rahbar-tuning-cache"))
    parser.add_argument("--out", type=Path, default=HERE / "chunk-tuning" / "results.json")
    parser.add_argument("--extract-only", action="store_true",
                        help="only extract and cache the documents (OCR needs tesseract); no embedding")
    args = parser.parse_args()

    questions = yaml.safe_load(args.golden.read_text(encoding="utf-8"))["questions"]
    print("loading documents (OCR is cached after the first run)...", flush=True)
    docs = load_documents(args.corpus, args.cache_dir)
    if args.extract_only:
        print(f"cached {len(docs)} cleaned documents in {args.cache_dir}")
        return 0
    with httpx.Client(timeout=180.0) as client:
        qvecs = embed_all(client, args.ollama, args.model, [q["question"] for q in questions], "search_query: ")
        results = []
        for spec in args.configs.split(","):
            size, overlap = (int(x) for x in spec.split(":"))
            started = time.perf_counter()
            chunks = [c for d in docs for c in chunk(d, size, overlap)]
            cvecs = embed_all(client, args.ollama, args.model, [c.text for c in chunks], "search_document: ")
            amp = sum(len(c.text.split()) for c in chunks) / sum(len(p.text.split()) for d in docs for p in d.pages)
            hybrid = score(questions, qvecs, chunks, cvecs, hybrid=True)
            vector_only = score(questions, qvecs, chunks, cvecs, hybrid=False)
            row = {"size": size, "overlap": overlap, "chunks": len(chunks), "amplification": round(amp, 3),
                   "hybrid": hybrid, "vector_only": vector_only, "seconds": round(time.perf_counter() - started)}
            results.append(row)
            print(f"size={size:<4} overlap={overlap:<3} chunks={len(chunks):<5} amp={amp:.2f} "
                  f"recall@5 hybrid={hybrid['recall_at_5']:.3f} vector-only={vector_only['recall_at_5']:.3f} "
                  f"recall@3 hybrid={hybrid['recall_at_3']:.3f}  missed={hybrid['missed']}", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"golden": str(args.golden.name), "model": args.model, "configs": results},
                                   indent=2), encoding="utf-8")
    print(f"\nwritten {args.out}")
    print("\n| Size (words) | Overlap | Chunks | recall@5 | recall@3 | recall@5 vector only |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in results:
        print(f"| {r['size']} | {r['overlap']} | {r['chunks']} | {r['hybrid']['recall_at_5']:.3f} | "
              f"{r['hybrid']['recall_at_3']:.3f} | {r['vector_only']['recall_at_5']:.3f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
