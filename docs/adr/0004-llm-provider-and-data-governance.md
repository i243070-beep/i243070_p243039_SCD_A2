# ADR 0004: LLM provider and data governance: Ollama on the host for generation and embeddings

## Status
Accepted · 2026-11-08 (revised the same day, see "How the decision changed")

## Context
Generation needs a language model. The assignment allows three modes behind one interface selected by `LLM_PROVIDER`:
`ollama-host` (the default, "lowest memory use on minikube"), `ollama-incluster` (a bonus, needs 8 GB for minikube
alone) and `hosted` (a free-tier endpoint with the key in a Kubernetes Secret). Our machines have 8 GB of RAM shared by
Windows, Docker and a 3 GB minikube, so the model must not live inside the cluster.

## How the decision changed
We first chose `hosted` (Google AI Studio's OpenAI-compatible endpoint) to keep generation off the laptop, implemented
the provider, and created the key as a cluster Secret. The first live test returned **HTTP 403: "The Gemini API free
tier is not available for this project. Set up billing..."** for every model the key could list, so the project is not
eligible for the free tier and no configuration can fix it. A hosted model would have meant paying, which the assignment
rules out ("none needing a credit card").

The laptop has an NVIDIA RTX 4050 with 6 GB of video memory. A 3B-parameter model quantised to about 2 GB runs entirely in
that video memory, so it does not compete with Windows and minikube for system RAM. That makes the assignment's default
mode, `ollama-host`, workable after all.

## Decision
* **Generation: `ollama-host`** with `llama3.2:3b`, served by Ollama on the host. The API calls `POST /api/chat` with
  `format` set to the JSON schema of `Answer`, so the model is constrained to that shape, and the reply is still
  validated with Pydantic because structure can be guaranteed but truth cannot.
* **Embeddings: the same Ollama**, `nomic-embed-text` (768 dimensions), pinned in the ConfigMap as `EMBED_MODEL` and
  identical in the indexer and the API.
* The pods reach Ollama on the host by IP, which the NetworkPolicy allows on port 11434 only.
* The provider sits behind the interface in `api/app/providers/llm/`, so a swap is one file. The hosted provider stays
  implemented and unit-tested; with `LLM_PROVIDER=hosted`, an eligible key and `HOSTED_BASE_URL`, it works unchanged. The
  key would live only in the Secret `rahbar-secret`, created with `make secret` from an environment variable (never from
  a file); the committed Secret manifest holds `REPLACE_ME`.

**Data governance: what leaves the cluster.** With Ollama on the host, **nothing leaves the machine**: the question and
the retrieved passages go from the pod to a process on the same laptop. No third party sees them, which is stronger than
the hosted option. The documents are public FAST-NUCES files in any case. Questions are not stored beyond the semantic
cache (question text and answer, on a PVC in the cluster) and the request log (chunk ids and scores, not answer text). If
the corpus held private documents this arrangement would still be appropriate, which is a reason to prefer it over a
hosted endpoint.

**Failure behaviour.** A timeout, a refusal or invalid JSON must never become a 500. The API validates, retries once, then
returns a safe canned answer and counts the fallback in a metric.

## Options considered
* **`hosted` (Google AI Studio).** Implemented and tested, then rejected on evidence: the free tier is unavailable for our
  project (HTTP 403). Other free hosted providers need new accounts and vary in JSON support.
* **`ollama-incluster` (bonus).** Needs 8 GB for minikube and a long startupProbe for model loading; rejected on memory.
* **`ollama-host` (chosen).** No account, no key, no cost, no data leaving the machine; the price is a smaller model.

## Consequences
* Answer quality is that of a 3B model: adequate for extracting a clause from a few passages, weaker on subtle reasoning.
  Retrieval quality and the abstention floor matter more than the model, and the evaluation measures them.
* The demo needs Ollama running on the host (`OLLAMA_HOST=0.0.0.0 ollama serve`) with `llama3.2:3b` and
  `nomic-embed-text` pulled; the README says so. A machine without a GPU would answer more slowly.
* CI has no GPU, so the end-to-end job must either run a small model on the runner's CPU or use the stub provider for
  generation; this is decided and recorded in the CI documentation.
* Moving to a hosted or private endpoint is a configuration change plus, at most, one provider file.
