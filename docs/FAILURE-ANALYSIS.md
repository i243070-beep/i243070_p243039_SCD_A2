# Failure analysis: breaking four stages on purpose

Section 5.5 of the assignment asks for four of the six stages to be broken one at a time. We broke **A (extraction), C (retrieval),
D (prompt) and E (source)**. We did not run B (chunking) and F (generation) as separate experiments: B's measured cost is already in the
chunk-size table in `docs/PIPELINE.md` (200/25, 400/50 and 800/100: recall@5 0.889, 0.889 and 0.833), and F is the model's fault, which
the lecture says to suspect last.

Everything below was measured on the live minikube cluster on 9 November 2026 with `llama3.2:3b`, the real 1,120-chunk index and
the 21-question golden set. The baseline is `eval/baseline.json` (recall@5 0.889, citation validity 100%, abstention 100%, answer
rate 65%, superseded leak 0%). The raw numbers for each experiment are in `docs/evidence/failure-*.txt`. None of the experiments changed
the committed code, the live deployment or `eval/`: A ran offline, C changed one ConfigMap key and was restored, D and E ran a patched
copy of the API inside one pod, on another port, with the cache switched off.

| Stage | Break | Did the original gate fail? | The number that showed it | Remedy added |
| --- | --- | --- | --- | --- |
| A Extraction | scanned PDFs indexed without OCR | no live eval was run on the broken index; the Job would have exited 0 | chunks per document: 2023 rules 78 to 2, faculty policy 38 to 0; `golden_coverage.py` reports 2 passages MISSING | the indexer now fails the Job if a document yields no chunks |
| C Retrieval | `TOP_K=1` | **yes**: recall@5 0.611 against 0.889 | `top_k` and the length of `chunk_ids` in the request log; recall@3 equal to recall@5 | none needed: the gate already caught it |
| D Prompt | "answer only from the evidence" removed | **no**: gate passed | answer rate 65% to 53%, citations checked 12 to 9 | a unit test that pins the grounding sentences in the prompt |
| E Source | superseded filter removed | **no**: gate passed | superseded leak rate 0% to 100%; q13 answered while recall@5 stays 0 | a fourth gate condition: the leak rate may not exceed the baseline's |

Two of the four breaks passed the gate that section 5.4 prescribes. That is the main finding of this exercise, and the reason the
fourth condition and the prompt test exist.

---

## Stage A · Extraction: the scanned PDFs indexed without OCR

- **What we broke:** `pipeline.extract._ocr_page` was replaced by a function that returns an empty string, which is what a missing tesseract or
  poppler install produces. Then `eval/golden_coverage.py` ran extract, clean and chunk over the same nine documents
  (`docs/evidence/failure-A-extraction-no-ocr.txt`).
- **Symptom:** nothing visible. No error, the Job would exit 0, the API would become ready. The index holds 975 chunks instead of 1,120. The
  2023 rules (a 26-page scan) give 2 chunks instead of 78, and the faculty policy (an 8-page scan) gives 0 chunks instead of 38. Two golden
  passages, q08 (start-up eligibility) and q12 (summer semester in the 2023 rules), no longer exist anywhere in the index, so those questions can
  only abstain or hallucinate. 2 of the 19 relevant passages are unreachable.
- **Diagnosis, as if we had not caused it:** the first suspicion would be retrieval or the model, because the user sees "the documents do not cover
  this" for a topic the university certainly documents. The way to separate extraction from retrieval is to look *before* any embedding: the indexer
  logs one `document indexed` line per document with `pages`, `ocr_pages` and `chunks`. A document with 26 pages and 2 chunks, or with `ocr_pages` equal
  to `pages` and `chunks` equal to 0, is the signature. `golden_coverage.py` turns the same check into a pass or fail by asking whether each golden
  passage exists as a chunk.
- **Stage:** A, extraction. The failure is upstream of everything else, so no retrieval or prompt change can fix it.
- **Remedy:** done: `indexer/pipeline/run.py` now raises when a document produces no chunks, naming the file, its page count and how many pages needed
  OCR, so the Job fails (Kubernetes shows `Error`) instead of publishing a partial index; `indexer/tests/test_starter_dummy.py` tests it. Not done, and worth
  saying: a low but non-zero chunk count (the 2023 rules gave 2) would still pass this guard, so `golden_coverage.py` remains the better check and should run
  against the real corpus whenever the PDFs are available.

## Stage C · Retrieval: `TOP_K=1`

- **What we broke:** `kubectl patch configmap rahbar-config` with `TOP_K=1`, `kubectl rollout restart deployment/api`, the semantic cache flushed first
  (otherwise answers cached at `top_k=5` would hide the break), then `python eval/run_eval.py --baseline eval/baseline.json`. Restored afterwards
  (`docs/evidence/failure-C-retrieval-top-k-1.txt`).
- **Symptom:** answers look normal but lose evidence: recall@5 falls from 0.889 to **0.611**. By question type: ordinary 0.90 to 0.60, exact 1.00 to 0.667,
  version 0.75 to 0.50. The gate failed: `recall@5 0.611 dropped more than 5% below the baseline 0.889`. Citation validity (100%) and abstention (100%) did not
  move: the citations that remain are still genuine, and the relevance floor does not depend on `top_k`. A quality drop with intact safety numbers is what a
  retrieval failure looks like.
- **Diagnosis, as if we had not caused it:** two readings of the evaluation point at retrieval before generation. First, recall@3 and recall@5 are
  identical (0.611 and 0.611), which happens when at most a few chunks are returned. Second, the per-request log line carries `"top_k": 1` and a
  `chunk_ids` list with one entry. The ConfigMap diff in Git shows the cause directly.
- **Stage:** C, retrieval.
- **Remedy:** restore `TOP_K` to 5. The existing gate is enough here; the lesson is that a ConfigMap value changes quality as much as code does, so
  ConfigMap changes go through the same pull request and the same gate.

## Stage D · Prompt: the "use only the supplied evidence" instruction removed

- **What we broke:** a copy of the API started inside one pod with `SYSTEM_INSTRUCTIONS` replaced by "You are RAHBAR, a helpful assistant for a university.
  Answer the user's question." plus the JSON shape. Retrieval, the relevance floor, the schema constraint and the citation check were left as they are
  (`docs/evidence/failure-D-prompt-no-context-instruction.txt`).
- **Symptom:** smaller than expected, and invisible to the gate: **gate passed**. Abstention stayed 100% (q18 to q20 stop at the relevance floor before the
  model is called, and q21 was not obeyed) and citation validity stayed 100% (the code removes any invented citation). What moved is the answer rate: **65%
  to 53%** (11 of 17 answerable questions down to 9) and citations checked 12 to 9. q01, q09 and q16 stopped being answered and q12 started. The defences
  stacked: the schema (`format=`) and the code-side checks held when the prompt did not.
- **Diagnosis, as if we had not caused it:** retrieval is unchanged (recall@5 0.889) and the citations that are returned are valid, so nothing looks wrong in
  the retrieval or the citation counters. The only signals are the fraction of requests with `"answered_from_context": false` in the request log,
  `rahbar_abstentions_total` on `/metrics` rising without a change in the questions, and `answer_rate_on_answerable` in `eval/results.json`. With A, B and C
  clean, the lecture's rule leaves D (or F).
- **Stage:** D, prompt.
- **Remedy:** done: `test_the_prompt_keeps_the_grounding_rules_that_failure_experiment_d_showed_matter` pins five sentences of the prompt, so deleting one
  fails CI. Not done: gating on the answer rate. With 17 answerable questions one question is 6 points, so a threshold tight enough to catch this drop (12
  points) is also tight enough to fire on noise from a 3B model. We report the answer rate and chose not to gate on it.

## Stage E · Source: the superseded-document filter removed

- **What we broke:** a copy of the API in one pod with `is_older_version_question` replaced by `lambda q: True`, so every question retrieves with
  `include_superseded=True`, as if the metadata filter had been deleted (`docs/evidence/failure-E-source-no-superseded-filter.txt`).
- **Symptom:** the original gate again said **gate passed**, and recall@5 (0.889) and citation validity (100%) did not move. What changed: the superseded
  leak rate went from 0% to **100%** (both version questions with an `avoid` list pulled a repealed document into the top 5) and recall@3 fell from 0.889
  to 0.778. q13 ("how many faculty at the Chiniot-Faisalabad campus") changed from "not covered" to *answered* while its recall@5 stayed 0: the current
  report's passage was not retrieved, so the answer can only have come from the 2019-20 report. That is the dangerous case: a confident, cited answer about
  a number or a rule that is no longer true.
- **Diagnosis, as if we had not caused it:** the answer is fluent and cited, so it looks right. The tells are in the request log: `"include_superseded": true`
  on a question that did not ask about an older version, and `chunk_ids` naming `undergraduate-academic-rules-aug-2023.pdf` or `annual-report-2019-20.pdf`.
  In the evaluation it is the `superseded_in_top5` flag per question and `superseded_leak_rate`.
- **Stage:** E, source (metadata). No prompt change fixes this: a model cannot know that a passage it was handed is repealed unless the retriever keeps it out.
- **Remedy:** done: `eval/run_eval.py` has a fourth gate condition, the leak rate may not exceed the baseline's, with a test
  (`test_gate_fails_when_a_superseded_document_leaks_more_than_the_baseline_allows`). Replaying the saved broken results through it gives `superseded leak
  rate 100% is above the baseline 0%: a repealed document reached the top of the retrieval`, and replaying experiment D still gives "gate passed". The check
  is relative to the baseline and silent when the golden set has no `avoid` entries, so the small CI fixture set is not affected.

---

## What we learned

* **A gate only protects what it measures.** The three conditions of section 5.4 caught C and missed D and E. Each miss produced a measurable number in
  `results.json` that nobody was gating.
* **Layers hid some failures and exposed others.** The relevance floor, the schema constraint and the citation check kept D from becoming a safety failure,
  which is the reason to keep three layers; the same layers meant the prompt could rot without the gate noticing.
* **Check A to E before blaming the model.** In all four experiments the model was fine; only the inputs it was given changed.
* **A failure of the environment looks like a failure of the system.** While collecting the resource numbers, the PC ran out of memory (about 320 MB free):
  the Kubernetes API server stopped answering, two api pods were killed by failed probes (exit 137, reason `Error`, not `OOMKilled`) and 13 of 20 requests
  timed out. It looked like an application fault; the events (`failed startup probe`) and the host's free memory showed it was not.
  `docs/evidence/kubectl-top-under-load.txt` records it.
