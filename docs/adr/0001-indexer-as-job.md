# ADR 0001: The indexer is a Kubernetes Job, not API startup

## Status
Accepted · 2026-11-08

## Context
RAHBAR has two jobs that look similar but are not: turning documents into a searchable index, and answering
questions from that index. The first is slow and expensive (we measured it: OCR of the two scanned PDFs alone takes
well over a minute, and every chunk then has to be embedded). The second must be fast and always available.

The API runs three replicas and there is one Chroma volume. It would be easy to write `build_index()` at the top of
the API's startup code, and it is wrong, for four concrete reasons:

1. **Three writers race one volume.** Each replica would be halfway through a different document when another one
   writes, and the result is an index that no single document set produced.
2. **Every restart pays the full cost.** A rolling update, an OOMKill, a node drain or a readiness blip would each
   repeat extraction, OCR and embedding, with the API unavailable or serving a partial index meanwhile.
3. **Readiness becomes a lie.** Either a pod reports ready before the index exists and serves empty retrievals, or it
   takes minutes to become ready and is killed by its own probes halfway, so a rolling update swaps three working pods
   for three that are still chunking PDFs.
4. **You cannot re-index without a redeploy.** A change to the corpus or the chunk size would need a new image and a
   restart, which is the "configuration change that needs a rebuild" failure.

## Decision
Indexing is a **Job** (`k8s/base/indexer.yaml`, `restartPolicy: OnFailure`, `backoffLimit: 3`) plus a weekly
**CronJob** `reindex` with the same image and arguments. The indexer is the **only writer** to Chroma; the API only
reads. The API's `/readyz` returns 503 until the collection exists and is non-empty, so a pod is withheld from the
Service until there is something to retrieve. Re-indexing is one command and needs no redeploy:

    kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar

**What happens to the old index while a new one is built.** The new index is built under a temporary collection name
and is swapped in (renamed to the live name) only when it is complete and its count is checked
(`indexer/pipeline/store.py`). If any step fails, the temporary collection is deleted and the old index keeps
serving. Each build also writes a fresh `index_id`, the embedding model name and the vector dimension into the
collection metadata: the API uses the model name for its pin check (ADR 0003 explains the cache use of `index_id`).

## Options considered
* **Index on API startup.** Rejected for the four reasons above.
* **An initContainer on the API pods.** Still three writers, still a full re-index on every pod start.
* **One "leader" API replica that indexes.** Needs leader election, still ties indexing to the serving process, and a
  crash of the leader mid-index leaves a half-built index.
* **A sidecar that re-indexes on a timer.** Same coupling and memory cost inside every API pod.

## Consequences
* One extra Kubernetes object pair (Job and CronJob) and one more image, but the serving pods stay small: the API
  limit is a few hundred MiB while the Job's limit is sized for OCR and embedding, justified with `kubectl top`.
* Re-indexing has no downtime and needs no rebuild; a failed run leaves the previous index intact.
* The cost moves into the Job: its memory limit must cover OCR (an exit code 137 means OOMKilled), and the Job must
  reach Chroma and the embedding host, which the NetworkPolicy allows explicitly.
* Watch for: a Job whose pod template changes cannot be updated in place (`field is immutable`), so switching overlays
  means deleting the finished Job first.
