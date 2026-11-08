#!/usr/bin/env python3
"""Check that every golden passage exists as a chunk, before any embedding or tuning.

    python eval/golden_coverage.py --corpus corpus/raw [--size 400 --overlap 50]

Runs extract, clean and chunk (no model, no Chroma) over the documents and asks, for each `relevant`
entry of eval/golden.yaml: is there a chunk with the same source whose section matches OR whose page
is the same? A golden passage with no such chunk can never be retrieved, which means the pipeline
(not the golden set) is wrong. It also prints the per-document numbers that docs/PIPELINE.md reports:
pages, OCR pages, chunks and storage amplification.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "indexer"))

from pipeline.chunk import amplification, chunk  # noqa: E402
from pipeline.clean import clean  # noqa: E402
from pipeline.extract import extract  # noqa: E402


def section_matches(want: str, got: str) -> bool:
    w, g = " ".join(want.lower().split()), " ".join(got.lower().split())
    return bool(w) and (w == g or w in g or g in w)


def covered(entry: dict, chunks: list) -> list:
    return [c for c in chunks if c.source == entry["source"]
            and (section_matches(entry.get("section", ""), c.section) or c.page == entry.get("page"))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden passage coverage check.")
    parser.add_argument("--corpus", type=Path, default=HERE.parent / "corpus" / "raw")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--size", type=int, default=400)
    parser.add_argument("--overlap", type=int, default=50)
    parser.add_argument("--json", type=Path, help="write the per-document stats here")
    args = parser.parse_args()

    index = json.loads((args.corpus / "_index.json").read_text(encoding="utf-8"))
    all_chunks = []
    stats = []
    for entry in index:
        path = args.corpus / entry["file"]
        started = time.perf_counter()
        raw = extract(str(path), str(entry["doc_version"]), bool(entry["superseded"]))
        doc = clean(raw)
        pieces = chunk(doc, args.size, args.overlap)
        row = {"source": path.name, "pages": len(raw.pages),
               "ocr_pages": sum(1 for p in raw.pages if p.ocr),
               "dropped_pages": len(raw.pages) - len(doc.pages), "chunks": len(pieces),
               "amplification": round(amplification(doc, pieces), 2),
               "seconds": round(time.perf_counter() - started, 1)}
        stats.append(row)
        print(f"{row['source']:<62} pages={row['pages']:>3} ocr={row['ocr_pages']:>3} "
              f"dropped={row['dropped_pages']:>2} chunks={row['chunks']:>4} "
              f"amp={row['amplification']:.2f} {row['seconds']:>5.1f}s", flush=True)
        all_chunks.extend(pieces)
    print(f"\nTOTAL chunks: {len(all_chunks)}  (size={args.size}, overlap={args.overlap})")

    questions = yaml.safe_load(args.golden.read_text(encoding="utf-8"))["questions"]
    missing = 0
    print("\nGolden coverage (relevant passages that exist as chunks):")
    for q in questions:
        for rel in q.get("relevant") or []:
            hits = covered(rel, all_chunks)
            by_section = [c for c in hits if section_matches(rel.get("section", ""), c.section)]
            status = "ok " if hits else "MISSING"
            if not hits:
                missing += 1
            print(f"  {q['id']} {status} {rel['source']} [{rel.get('section')}, p{rel.get('page')}] "
                  f"chunks_by_section={len(by_section)} chunks_by_page_or_section={len(hits)}")
    if args.json:
        args.json.write_text(json.dumps({"documents": stats, "chunks": len(all_chunks)}, indent=2),
                             encoding="utf-8")
    print(f"\n{'ALL golden passages are reachable' if not missing else str(missing) + ' golden passage(s) MISSING'}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
