# ADR 0004: Hosted LLM provider, local embeddings, and what leaves the cluster

## Status
Accepted · 2026-11-08

## Context
Generation needs a language model; the assignment allows three modes behind one interface selected by `LLM_PROVIDER`:
`ollama-host`, `ollama-incluster` and `hosted`. Our development machines have 8 GB of RAM, shared between Windows,
Docker and a 3 GB minikube. A local generation model next to that is not realistic, and in-cluster Ollama needs
8 GB for minikube alone.

## Decision
* **Generation: `hosted`**, Google AI Studio (free tier, no credit card) through its OpenAI-compatible endpoint, with a
  JSON response schema so structure is enforced, and Pydantic validation on top because structure can be guaranteed
  but truth cannot. The provider sits behind the interface in `api/app/providers/llm/`, so a swap is one file.
* **Embeddings: local Ollama** with `nomic-embed-text` (768 dimensions), pinned in the ConfigMap as `EMBED_MODEL` and
  identical in the indexer and the API. The model is small (274 MB) and it keeps document text off any third-party
  service during indexing. The pods reach Ollama on the host by its IP, which the NetworkPolicy allows on port 11434 only.
* **The key** lives only in a Kubernetes Secret created from an environment variable with `make secret` (never from a
  file), and in GitHub Secrets for CI. The committed Secret manifest holds `REPLACE_ME`.

**Data governance: what leaves the cluster.** To the hosted provider we send the user's question and the retrieved
passages, nothing else. The passages come from public FAST-NUCES documents, so no private or personal document text
is transmitted. We do not store user questions beyond the cache (which holds question text and answer) and the request
log (question length, chunk ids and scores, not the answer text). If the corpus held private documents, the decision
would change: we would switch to `ollama-incluster` or a private endpoint, because retrieved passages would then leave
the cluster with every question.

**Failure behaviour.** A rate limit, a timeout or invalid JSON must never become a 500: the API validates, retries
once, then returns a safe canned answer, and counts the fallback in a metric.

## Options considered
* **`ollama-host`.** Easiest, but needs a 3B model in laptop RAM next to minikube; rejected on memory.
* **`ollama-incluster` (bonus).** Needs 8 GB for minikube and a long startupProbe for model loading; rejected on memory.
* **`hosted` (chosen).** Free, fast, no local memory cost.
* **Hosted embeddings too.** Would send every document chunk to a third party during indexing and complicate the pin;
  rejected.

## Consequences
* The system depends on the internet and on the provider's free-tier limits at question time (not at indexing time).
* Generation latency and token counts become metrics we watch; the cache reduces calls.
* Moving to private documents or a different provider is a configuration change plus one provider file.
