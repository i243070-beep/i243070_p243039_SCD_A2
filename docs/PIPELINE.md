# Indexing and retrieval pipeline

The indexer is a Kubernetes Job that runs five stages and exits: **extract, clean, chunk, embed, store** (`indexer/pipeline/`).
All numbers below are from the real run on minikube on 8 November 2026 (1 CPU, 768 Mi limit): **9 documents, 1,120 chunks,
423.6 seconds, peak memory 457 Mi** (`docs/evidence/indexer-job-kubectl-top.txt`). The documents are baked into the indexer image
(`make images` copies the fetched files and `_index.json` into `indexer/corpus/` before the build) so the Job is self-contained;
in CI a ConfigMap with the small fixture corpus is mounted over `/corpus` instead.

## Extraction
`extract.py` reads text page by page with pdfplumber, writes every table as rows of ` | `-separated cells, OCRs any page with fewer than
20 characters of text (tesseract 5.3 at 200 dpi, one page at a time so memory stays flat), and for HTML skips the page chrome
(`header`, `nav`, `footer`, scripts).

| Document | Pages | Pages that needed OCR | Chunks | Amplification |
| --- | ---: | ---: | ---: | ---: |
| Undergraduate Academic Rules, Aug 2023 (superseded) | 26 | **24** (a scan) | 78 | 0.99 |
| Academic Rules Handbook, Jun 2026 | 58 | 5 | 174 | 1.02 |
| Prospectus 2026, academic rules | 5 | 0 | 20 | 1.10 |
| Student Handbook, Jun 2026 | 64 | 4 | 256 | 1.03 |
| Annual Report 2019-20 (superseded) | 33 | 0 | 183 | 1.03 |
| Annual Report 2023-24 | 85 | 0 | 355 | 1.03 |
| Fee Structure page (HTML) | 1 | 0 | 10 | 0.99 |
| Grading page (HTML) | 1 | 0 | 6 | 0.99 |
| Faculty Entrepreneurship Policy | 8 | **8** (a scan) | 38 | 1.03 |

The two scans took most of the extraction time (2023 rules about 186 s, faculty policy about 54 s in the Job).

**Before and after, a table that worked (the Fee Structure page).** A naive extractor (strip the tags) puts every cell on its own line, so
the link between a program and its fee is lost, and the whole page is 367 lines because the site menus come along:

    Program
    Fee
    BBA / BS
    Rs. 12,000
    MBA / MS
    Rs. 12,000

`extract.py` keeps the structure and drops the menus (58 lines for the whole page):

    Program | Fee
    BBA / BS | Rs. 12,000
    MBA / MS | Rs. 12,000
    PhD | Rs. 12,000

**What we could not recover.**
* **Borderless PDF tables.** The faculty tables of the 2019-20 annual report have no ruling lines, so pdfplumber does not detect them and our
  table step never runs. The text is kept but the column alignment is lost: `Computer Science 1 2 9 22 8 42` no longer says which number is
  which rank, and the header wraps into `Profes sor Professor Engine er l`. The row totals (for example the Chiniot-Faisalabad total of 97)
  survive as text, which is why golden question q14 is still answerable, but a question about one rank would not be reliable.
* **OCR errors in the two scans.** Missing spaces (`Astudent`, `Ifthe`, `ofall`), superscripts read as quotes (`1*` or `2"` for 1st and 2nd),
  and in the faculty policy the numbered list is scrambled: the numbers `4.2.` and `4.3.` are separated from their sentences.
* **The 2026 handbook's ruled tables** are detected, but cell merges can still leave an empty cell, which we skip.

## Cleaning
`clean.py` rules (the docstring of the module is the source of truth):

1. Remove header and footer lines: a line in the first or last three lines of a page (never more than a third of a short page) that appears at
   the page edge on at least half of the pages, with digits masked so "Page 3 of 53" matches "Page 4 of 53". Only for documents of three or more pages.
   **Table rows (` | `) are never removed as headers**, even when they repeat; a unit test caught the bug that first stripped a repeated table header.
2. Remove standalone page numbers at the page edge.
3. Drop table-of-contents pages (most lines end in a page number or use dot leaders). Table rows never count as contents lines. This dropped
   2 pages of the 2026 handbook and 1 of the 2023-24 report. One partial contents page of the handbook (page 6) survived and appears as a chunk.
4. Join words hyphenated across a line break, but not number ranges such as `5-6`.
5. Normalise non-breaking and zero-width characters, the soft hyphen and ligatures; strip control characters.
6. Collapse runs of blank lines.

**One thing we deliberately did not strip: clause numbers and headings** (`1.21`, `5.4`, `Academic Warning/Probation`). Chunking uses the headings as
section names, and exact-term questions ("what does clause 1.21 require?") depend on the numbers surviving.

## Chunking
Chunk size and overlap are counted in **words** ("tokens" in this document means whitespace-separated words). Shipped: **size 400, overlap 50** (the ConfigMap keys
`CHUNK_SIZE` and `CHUNK_OVERLAP`); the measured comparison is in the tuning table below. Order of splitting: sections, then paragraphs, then sentences, then words
only for a sentence longer than the limit. A chunk never exceeds the size including its overlap; overlap is carried only inside one section; a table is split only
between rows; a section's first chunk starts with its heading. Heading detection recognises Markdown headings (from HTML), numbered titles (`1. Attendance`), ALL-CAPS
lines (`VII - LIBRARY SERVICES AND RULES`) and short Title-Case lines; a clause line such as `5.4 Minimum CGPA ...` is deliberately not a heading.

**Storage amplification** (stored words divided by the words of the cleaned document, the lecture's 150 / 120) is **0.99 to 1.10 per document** (table above; most documents sit at
1.02 to 1.03). It is close to 1 because the documents are made of many short sections, so most chunks end at a section boundary and carry no overlap. The Prospectus is highest
(1.10) because it has a few long sections, so most of its chunks carry the 50-word overlap (the theoretical maximum at size 400 and overlap 50 is 400 / 350 = 1.14). Values just
under 1 (the 2023 rules and the two HTML pages) come from the rule that drops stray chunks of fewer than three words.

### Chunk-size tuning (measured, not guessed)
Three `(size, overlap)` configurations were scored on the golden set with `eval/tune_chunks.py`: the real extract, clean and chunk stages, every chunk embedded with the pinned model, then retrieval with the same rules the API
uses (cosine similarity, superseded documents excluded unless an older version is asked for, and the lexical rescue for exact tokens). No LLM is involved, so this isolates retrieval. Raw numbers: `eval/chunk-tuning/results.json`.

| Size (words) | Overlap (words) | Chunks stored | Amplification | recall@5 | recall@3 | recall@5, vector only |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 200 | 25 | 1,303 | 1.07 | 0.889 | 0.889 | 0.833 |
| **400** | **50** | **1,120** | **1.03** | **0.889** | **0.889** | **0.833** |
| 800 | 100 | 1,070 | 1.01 | 0.833 | 0.833 | 0.778 |

**Shipped: 400 / 50.** It ties 200 / 25 on recall (0.889) but stores 14% fewer chunks (1,120 against 1,303) with lower amplification and more context per chunk; 800 / 100 is clearly worse (0.833) because large chunks dilute a short
passage (the dress-code rule, q10, is lost). recall@3 equals recall@5 in every row because the misses are complete misses, not near-misses at rank 4 or 5.

**By question type (400 / 50, recall@5):** ordinary 0.90, exact 1.00, injection 1.00, version 0.75. **Where it is worst, and why.** Without the lexical rescue the exact-term questions are the worst (0.667): "what does clause 1.21 require?" is
missed because an embedding places "1.21" close to "1.22" and to any clause about attendance, so the number itself barely influences the ranking. The lecture's technique for this is hybrid retrieval: when a question contains an exact token
(a clause number or a course code) the API also asks Chroma for chunks that literally contain it. That lifts exact-term recall from 0.667 to 1.00 and overall recall@5 from 0.833 to 0.889. With hybrid retrieval the worst type is "version"
(0.75): q13 asks for a faculty count that lives in a table (`Chiniot-Faisalabad 2 4 17 8 58 12 2 103`), and a row of numbers has almost no semantic content for an embedding to match. Two questions, q02 (a prose question about semester
weeks) and q13, are missed by every configuration; they are reported as they are and not tuned away.

## Embedding
Model **`nomic-embed-text`**, **768 dimensions**, served by Ollama on the host (the pods reach it by IP, allowed by the NetworkPolicy on port 11434 only). Documents are embedded with the
prefix `search_document: ` and questions with `search_query: `, as the model requires. **The pin** lives in one ConfigMap key, `EMBED_MODEL` in `rahbar-config`, read by both the indexer
and the API. On top of that the indexer writes `embed_model` and `dimension` into the Chroma collection metadata, and the API compares them with its own `EMBED_MODEL` at startup and
refuses to become ready on a mismatch, logging the conflict.

## Storage
The indexer writes into Chroma (`chromadb/chroma:1.0.12`, the same version as the client pin). **Metadata schema of every chunk:**

| Field | Type | Meaning |
| --- | --- | --- |
| `source` | string | the file name, e.g. `academic-rules-handbook-jun-2026.pdf` |
| `section` | string | the heading the chunk sits under |
| `page` | int | the 1-based PDF page of the chunk's first paragraph |
| `doc_version` | string | from `corpus/sources.yaml`, e.g. `2026-06` |
| `superseded` | bool | true for the 2023 rules and the 2019-20 report |

Collection metadata: `embed_model`, `dimension`, `index_id` (new on every build; the API keys its cache by it), `built_at`, `chunk_size`, `chunk_overlap`, `chunks`, and cosine distance.
Chunk ids are stable (`<source>::p<page>::c<n>`). **Replacing an index** (the open question of ADR 0001): the new collection is built under a temporary name and swapped in by rename
only when complete and counted; a failed run deletes the temporary collection and the old index keeps serving.

Verified after the real run: 1,120 chunks (the sum of the table above), all five metadata fields present, the 2023 rules and the 2019-20 report flagged `superseded: True`.

## Evaluation method
Retrieval is scored against `eval/golden.yaml`. A retrieved passage matches a golden `relevant` entry when it has **the same source AND (a matching section OR the same page)**. A section matches
when, case-insensitively, one heading contains the other. The page fallback is needed: with heading detection alone, four golden passages (q08, q09, q10, q13) would have scored as misses even
though the right page was retrieved, because the document's heading was a numbered clause line or a table caption rather than a title. `eval/golden_coverage.py` checks, before any embedding,
that every golden passage exists as a chunk; all 19 relevant entries (21 questions) are reachable.

## Relevance floor and abstention
Below a minimum similarity the API answers "the documents do not cover this" **without calling the LLM**, and the model may also decline on its own. The floor is chosen from the golden set, using the top-1 similarity of every question
on the real index: answerable questions score **0.707 to 0.895** and the three must-abstain questions **0.623 to 0.719**. The ranges overlap slightly (q19, "hostel fee at the Peshawar campus", scores 0.719 because the handbook mentions a
Peshawar hostel), so no number separates them perfectly. The floor is **0.72**, just above the highest must-abstain score; the one answerable question that scores below it (q15, "clause 1.21", 0.707) is rescued because its passage
literally contains the exact token, and an exact match counts as evidence. **This floor is fragile** (a margin of 0.001 above q19) and is a measured choice, not a guarantee: the model's own "not covered" answer and the citation check are
the second and third layers.

## Semantic cache
Redis, keyed by the index's `index_id` so a re-index invalidates every entry (ADR 0003). A hit needs cosine similarity of the question embeddings at or above `CACHE_THRESHOLD`. The threshold was measured on 5 paraphrase pairs that should hit
and 6 look-alike pairs that must not (`"…for BS programs"` against `"…for MS and MBA programs"`, `"15th day"` against `"20th day"`, `"clause 1.21"` against `"clause 1.22"`, one campus against another):

| Threshold | Paraphrases served from the cache (of 5) | False hits (of 6) |
| ---: | ---: | ---: |
| 0.85 | 4 | **4** |
| 0.88 | 3 | 2 |
| 0.92 | 2 | **1** (BS against MS/MBA, similarity 0.933) |
| **0.95** | **2** | **0** |
| 0.97 | 1 | 0 |

The lowest paraphrase scores 0.846 and the highest look-alike scores 0.933, so **no threshold separates the groups**; this is the known weakness of semantic caches. A false hit serves a wrong answer to everyone, so we ship **0.95**, the lowest
value with zero false hits, and accept a lower hit rate. The 0.92 setting was ruled out by the BS-against-MS/MBA false hit (the answer differs: 2.00 against 2.50). Never cached: follow-up questions, abstentions, fallbacks, and anything that failed validation.
