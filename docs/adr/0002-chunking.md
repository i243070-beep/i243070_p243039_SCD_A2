# ADR 0002: Structure-aware chunking at 400 words with 50 words of overlap

## Status
Accepted · 2026-11-08

## Context
The corpus is rules and policies: numbered clauses, headed sections, and tables of fees and grades. An answer has to cite a source, section and page, and a question often targets one short clause. Chunks that cross a heading blur two rules together and make the citation wrong. Chunks that are too long dilute a short rule inside unrelated text, and chunks that are too short lose the condition attached to the rule.

The assignment requires at least three `(size, overlap)` settings to be measured on the golden set, and scores a number with no measurement behind it as zero.

## Decision
Chunk by **structure first, size second** (`indexer/pipeline/chunk.py`):

- Split at headings (Markdown headings from HTML, numbered titles, ALL-CAPS titles). A chunk never crosses a section.
- Within a section, split by paragraph, then sentence, and by words only for a single sentence longer than the limit. A table is split only between rows.
- **Size 400 words, overlap 50 words**, overlap only inside a section, and a chunk never exceeds the size with its overlap included. Both are ConfigMap keys (`CHUNK_SIZE`, `CHUNK_OVERLAP`).
- Clause numbers and headings are kept in the text, so exact-term search can find them, and a section's first chunk starts with its heading.

Measured with `eval/tune_chunks.py` (retrieval only, no LLM; raw numbers in `eval/chunk-tuning/results.json`):

| Size / overlap (words) | Chunks | Amplification | recall@5 | recall@5, vector only |
| ---: | ---: | ---: | ---: | ---: |
| 200 / 25 | 1,303 | 1.07 | 0.889 | 0.833 |
| **400 / 50 (shipped)** | **1,120** | **1.03** | **0.889** | **0.833** |
| 800 / 100 | 1,070 | 1.01 | 0.833 | 0.778 |

We shipped 400 / 50 because it ties the smallest setting on recall while storing 14% fewer chunks, with more context per chunk.

## Options considered
- **Fixed-size chunks with no structure.** Rejected: they cross headings, so a chunk can hold the end of one rule and the start of another, and its section metadata is wrong for half of it.
- **200 / 25.** Equal recall at 16% more chunks, and less context around each rule for the model.
- **800 / 100.** Measurably worse (0.833): large chunks dilute a short passage, and the dress-code rule (q10) is lost.
- **Counting real tokens instead of words.** More exact against a model's limit, but it ties the indexer to one tokenizer. Words are simple, and 400 words stays well inside the embedding model's limit.

## Consequences
- Citations point at a real section and page, which the citation check depends on.
- Amplification is low (about 1.03) because most sections are short and carry no overlap.
- Changing either value means re-running the Job and re-evaluating; the CI gate catches a change that drops recall@5 by more than 5 points on the fixture set.
- Heading detection is a heuristic: for four golden passages the detected section was a numbered clause or a table caption, so the evaluation also accepts a match on the same page (`docs/PIPELINE.md`).
- A row of numbers still embeds poorly. q13 is missed at every size, so chunk size is not the fix for it.
