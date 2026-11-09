# Engineering notes

File and line references are to this repository. Measurements are from the live minikube cluster and are kept in `docs/evidence/`.

## 1. Indexing in API startup: what breaks with 3 replicas and one Chroma volume?

Three separate things break, in this order.

1. **The kubelet kills every pod before it finishes.** The startup probe allows 30 failures at 2 s, so 60 s (`k8s/base/api.yaml:57-60`). The real index build took 423.6 s (`docs/evidence/indexer-job-kubectl-top.txt`). Every replica is restarted about seven times over before one build could complete, so none ever becomes Ready.
2. **The pod is OOMKilled even if the probe is relaxed.** The indexer peaks at 457 Mi. The api limit is 256 Mi (`k8s/base/api.yaml:84`). Exit code 137.
3. **Three writers race one index.** Even with both of those fixed, each replica would build its own `rahbar-build-<id>` collection and rename it to `rahbar` (`indexer/pipeline/store.py:51-52, 81-82`). Whichever finishes last wins, the others can fail mid-rename, and each build writes a new `index_id`, so every pod restart would also invalidate the whole semantic cache.

The volume is `ReadWriteOnce` and mounted only by the single Chroma pod (`k8s/base/chroma.yaml:6, 15, 80`), so the failure is not a mount conflict: it is three concurrent writers going through one Chroma server.

**The object that prevents it** is the `Job` at `k8s/base/indexer.yaml:5`: one run, `restartPolicy: OnFailure` (line 20), `backoffLimit: 3` (line 13). The API never writes: `api/app/main.py:53` records that, and `/readyz` refuses traffic until the collection exists and is non-empty (`api/app/services/readiness.py:75-79`). Rationale: ADR 0001.

## 2. Readiness and liveness swapped, Chroma slow for 90 seconds: what happens?

Today, liveness is `/healthz` every 20 s with 3 failures, and readiness is `/readyz` every 10 s with 3 failures and a 5 s timeout (`k8s/base/api.yaml:63-72`).

**As configured:** after about 30 s of slow Chroma, all three pods fail readiness and leave the Service. Nothing restarts. Callers get an error from the Ingress for the remaining time. When Chroma recovers, the next successful probe puts them back within about 10 s, so the outage ends when Chroma's does.

**Swapped:** `/readyz` becomes the liveness check, with the default 1 s timeout. After about 60 s (3 failures at 20 s) the kubelet kills **all three pods**, at about the same moment, because all three depend on the same slow Chroma. They restart, wait through the startup probe, and fail again while Chroma is still slow. Meanwhile readiness is now `/healthz`, which never touches Chroma, so a pod reports Ready and takes traffic it cannot serve; the retrieval failure falls back to the canned "could not produce a reliable answer" message (`api/app/services/answer.py`, step 2). A 90-second slowdown becomes a restart storm that outlasts it.

We saw the kill path for real on 9 November: when the PC ran out of memory, the kubelet killed api pods with `Container api failed liveness probe, will be restarted` (`docs/evidence/kubectl-top-under-load.txt`).

## 3. What does a CPU-based HPA measure on a generation service, and what should scale it?

The HPA computes CPU usage divided by `requests.cpu`, averaged over pods, against a 70% target (`k8s/base/hpa.yaml:14-22`, request at `k8s/base/api.yaml:80`). While a request waits for the model, the pod is blocked on an HTTP call to Ollama (`api/app/providers/llm/ollama.py`), which uses almost no CPU. So the HPA is measuring **JSON handling and the embedding and Chroma calls, not generation work**. `docs/evidence/endpoints-and-hpa.txt` shows it at 4%/70%. CPU during generation specifically is **not measured**: our one attempt was invalidated (a stale scrape of pod startup) and the re-run was stopped because the PC was overheating, so we make no numeric claim.

Scaling the api would not help anyway. The bottleneck is one GPU behind one Ollama. With four questions in parallel, latency reached 107 s and 13 of 20 requests failed, although that run was confounded by the PC running out of RAM.

**The right signal** is in-flight generation requests per pod, or the p95 of `rahbar_generation_seconds` (already exported by `api/app/routes/metrics.py`). To use it we would need Prometheus scraping `/metrics`, `prometheus-adapter` (or KEDA) to expose it through the custom metrics API, an `in_flight` gauge in the api, and more generation capacity to scale into; otherwise more api pods just queue on the same GPU.

## 4. The indexer's peak memory, its limit, the margin, and the exit code when it is wrong

Sampled every few seconds across the real Job: **peak 457 Mi** (`docs/evidence/indexer-job-kubectl-top.txt`). Request 384 Mi, **limit 768 Mi** (`k8s/base/indexer.yaml:44, 47`). **Margin 311 Mi, or 40% of the limit.** The margin is deliberately large because memory is driven by OCR of the scanned pages (rendered at 200 dpi, one page at a time, `indexer/pipeline/extract.py:23, 42-47`), so a larger scan would raise the peak. Exceeding the limit gives **`OOMKilled`, exit code 137**; `restartPolicy: OnFailure` retries it and `backoffLimit: 3` stops it failing forever.

Exit 137 alone is not proof of OOM: on 9 November two api pods exited 137 with reason `Error`, killed by failed probes. The `reason` field is what distinguishes them.

## 5. recall@5 by question type: where is it worst, and why?

From `eval/results.json` and `docs/PIPELINE.md`:

| Type | recall@5, vector only | recall@5, shipped (hybrid) |
| --- | ---: | ---: |
| exact | **0.667** | 1.00 |
| ordinary | | 0.90 |
| version | | **0.75** |
| injection | | 1.00 |

**Worst before the fix: exact terms.** An embedding places "clause 1.21" close to "clause 1.22" and to any paragraph about attendance, because the digits barely move the vector. The lecture's technique is **hybrid retrieval**: `api/app/retrieval/chroma.py:84-88` also queries Chroma with `where_document $contains` for tokens such as clause numbers, and those hits count as evidence even below the relevance floor. That took exact-term recall from 0.667 to 1.00.

**Worst after the fix: version questions (0.75).** q13 asks for a faculty count stored in a table row (`Chiniot-Faisalabad 2 4 17 8 58 12 2 103`). A row of numbers has almost nothing for an embedding to match. q02 and q13 are missed by every chunk size we tried, and we report them rather than tune them away. A reranker or table-aware chunking would be the next step.

## 6. EMBED_MODEL changed on the API only: what does your system do?

`EMBED_MODEL` is one ConfigMap key (`k8s/base/configmap.yaml:17`) read by both programs. The indexer writes it and the vector dimension into the collection metadata (`indexer/pipeline/store.py`). The API compares them in the background at startup (`api/app/main.py:52`) and on every readiness probe (`api/app/services/readiness.py:44-47`).

We did exactly this (`docs/evidence/embedding-pin-mismatch.txt`): set `EMBED_MODEL=all-minilm` and restarted only the API. The new pods stayed `0/1 READY`, the log named both models, and with `maxUnavailable: 0` the old pods kept serving, so users saw nothing. The ConfigMap was then restored.

**Without the guardrail:** a model with a different dimension makes every Chroma query raise an error, so every question hits the fallback. A model with the same dimension is worse: the queries succeed, the vectors are not comparable, retrieval returns nonsense with plausible scores, and no error appears anywhere.

## 7. The failure that cost us more than an hour

**No generation model could run.** The first live test was on 8 November at about 15:17 UTC, and a usable model first answered on 9 November at about 04:19 UTC. Active work on it was about 46 minutes on the first day plus about 45 on the second, with a night between.

**Symptoms.** Every question fell back to "could not produce a reliable answer". `/readyz` was green, because readiness does not depend on the model.

**What we wrongly believed, twice.**

1. *That a valid key meant working generation.* The key had been accepted, and `GET /models` returned 200 and listed 61 models, so a model name looked like the likely problem, and every listed model was tried. The truth was in the body of one `POST .../chat/completions`: **HTTP 403, "free tier is not available for this project, set up billing"**, for every model. The key was valid; the project was not eligible. ADR 0004 records the switch to `ollama-host`.
2. *That the 3B download was stuck at 1,926 MB.* We watched the largest `*partial*` file under `.ollama/models/blobs` and it did not move for 20 minutes, so we concluded the network was stalling and tried smaller models. The 1B model then installed but obeyed the injection question. What finally told the truth was the output of the pull itself: **`pulling dde5aa3fc5ff: 13% 252 MB/2.0 GB 1.9 MB/s`**. The file we were watching was a stale partial from an earlier attempt; the real download was moving. It finished in about 27 minutes.

**What we changed.** We now read the tool's own progress and the raw response body before forming a theory, and we keep the model's fitness as a measured number (the evaluation), since `/readyz` cannot see it.
