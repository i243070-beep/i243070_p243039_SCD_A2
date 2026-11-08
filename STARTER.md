# RAHBAR starter kit

This folder is the first commit of your Assignment 02 repository. Unzip it, run `git init`,
commit, push to GitHub, and protect `main` before you write anything else.

The kit gives you **plumbing and contracts**: the pieces every team would otherwise rebuild
identically, and the interfaces your work plugs into. **Everything that is graded is yours.**
The kit contains no Dockerfiles, no Kubernetes manifests and no workflows, and every
function you must write raises `NotImplementedError` next to a `STARTER-TODO(section)`
comment that names the section of the case study it belongs to.

You may change any file in the kit, including the given code. If you change a contract
(the request, the response, the metadata fields), say why in an ADR.

## What is given, and what is yours

| Area | Given | Yours |
| --- | --- | --- |
| API | FastAPI app, routes, the `Answer` and `AskResponse` schemas, JSON logging with request ids, Prometheus metrics, a stub retriever and a stub LLM provider | `ChromaRetriever.retrieve`, the Ollama or hosted provider, the cache, the relevance floor and abstention, validation and fallback, the citation check, `/readyz`, the embedding-pin check |
| Indexer | The CLI and stage runner, document discovery, the `Chunk` model, a `--dummy` mode that writes three fake chunks | `extract`, `clean`, `chunk`, `embed`, `store` |
| UI | A finished chat page (`ui/index.html`) and an nginx config for a non-root container | The Dockerfile |
| Corpus | `corpus/fetch.py` and a list of FAST-NUCES documents to start from | Choosing and checking the documents, `docs/CORPUS.md` |
| Evaluation | `eval/run_eval.py` (talks to the API, writes results, exits non-zero on failure), a fixture corpus for CI | The golden set, `recall_at_k`, `citation_validity`, `summarise`, `gate` |
| Kubernetes, CI/CD | A `Makefile` that runs the commands, empty `k8s/` and `.github/workflows/` folders | All manifests, all workflows, all Dockerfiles |
| Docs | Templates for every required document and an ADR template | Every word in them |

## Quick start: no cluster, no model

You need Python 3.12, `make` and `git`. On Windows, work inside WSL 2 (Ubuntu); the
Makefile needs bash.

```bash
make install      # creates .venv and installs the api, indexer and dev dependencies
make test         # 11 tests, stubs only: no cluster, no model, no network
make lint         # ruff and mypy
make dev          # the API with stubs on http://localhost:8000, serving the chat UI too
```

Open http://localhost:8000 and ask anything. The stub retriever always returns the same
three passages and the stub provider always cites the first one. That is the contract
working end to end with nothing real behind it.

`make` on its own lists every target.

## The contract

**`POST /api/ask`** takes `{"question": "..."}` (3 to 500 characters; anything else is a
422) and returns an `AskResponse`. The request id comes from an `X-Request-ID` header if
the caller sends one, and is generated otherwise; it is echoed back in the response header
and appears on every log line for that request.

```json
{
  "request_id": "demo-1",
  "answer": "(stub) A model would answer here from 3 passages. ...",
  "citations": [
    {"source": "stub-handbook.pdf", "section": "1.1 About the stub", "page": 1}
  ],
  "answered_from_context": true,
  "confidence": "low",
  "retrieved": [
    {"chunk_id": "stub-001", "source": "stub-handbook.pdf", "section": "1.1 About the stub", "page": 1, "score": 0.91},
    {"chunk_id": "stub-002", "source": "stub-handbook.pdf", "section": "1.2 What the stub returns", "page": 1, "score": 0.84},
    {"chunk_id": "stub-003", "source": "stub-handbook.pdf", "section": "1.3 Switching to Chroma", "page": 2, "score": 0.77}
  ],
  "provider": "stub"
}
```

Every citation must match a passage in `retrieved`; `eval/run_eval.py` checks exactly that.
`answered_from_context: false` means the system declined. The UI shows both states, and it
also shows a cache chip if you add `"cached": true` to the response or send an `X-Cache`
header.

| Endpoint | Purpose | State in the kit |
| --- | --- | --- |
| `GET /healthz` | Liveness: is the process alive? Touches nothing else. | Done |
| `GET /readyz` | Readiness: Chroma reachable, collection non-empty, Redis reachable, embedding model matches | Always says ready. Yours to fix (4.3, 4.4). |
| `GET /metrics` | Prometheus: request count by route and status, latency histogram | Done; add your own |
| `POST /api/ask` | The question endpoint | Works with stubs |

## Configuration

Both programs read environment variables only, so on the cluster they come from your
ConfigMap and Secret and one image runs everywhere.

| Variable | Read by | Default | Notes |
| --- | --- | --- | --- |
| `RETRIEVER` | api | `stub` | `stub` or `chroma` |
| `LLM_PROVIDER` | api | `stub` | `stub`, `ollama-host`, `ollama-incluster` or `hosted` |
| `EMBED_MODEL` | api, indexer | `nomic-embed-text` | The pin. Both must read it from the same ConfigMap key. |
| `CHROMA_HOST`, `CHROMA_PORT` | api, indexer | `chroma`, `8000` | The Chroma Service name and port |
| `CHROMA_COLLECTION` | api, indexer | `rahbar` | |
| `TOP_K` | api | `5` | |
| `TEMPERATURE` | api | `0.2` | |
| `LLM_MODEL` | api | `llama3.2:3b` | |
| `OLLAMA_URL` | api, indexer | `http://host.minikube.internal:11434` | The indexer uses it for embeddings |
| `HOSTED_BASE_URL` | api | empty | For `hosted` mode |
| `LLM_API_KEY` | api | empty | **Secret only.** Create it with `make secret`. |
| `LOG_LEVEL` | api | `INFO` | |
| `CORPUS_DIR` | indexer | `/corpus` | Where the Job finds the documents |
| `CHUNK_SIZE`, `CHUNK_OVERLAP` | indexer | `400`, `50` | Your unit (tokens or characters, say which); measure three settings (3.1) |

Add your own keys (relevance floor, cache threshold, Redis address) the same way, in
`api/app/config.py` and `indexer/pipeline/config.py`.

## How the week runs

**Monday to Wednesday: Kubernetes around the stubs.**
Write the three Dockerfiles and the manifests, and get the whole system running on
minikube with `RETRIEVER=stub` and `LLM_PROVIDER=stub`. Run the indexer Job with
`python -m pipeline.run --dummy`: it writes three fake chunks to Chroma with no model,
which is enough to prove the Job, the StatefulSet, the PVC, the probes and the Ingress.

The dummy index records its embedding model as `dummy-768`. Set `EMBED_MODEL=dummy-768`
in the ConfigMap while you use it, and your pin check will agree with it. On Thursday,
change the ConfigMap to your real model and *do not* re-index: the API should refuse to
become ready and log the conflict. That is the section 4.4 demonstration, for free.

**Thursday to Sunday: the RAG system.**
Implement the five pipeline stages, `ChromaRetriever.retrieve` and a provider, switch the
ConfigMap to `RETRIEVER=chroma` and a real `LLM_PROVIDER`, then add the cache, abstention,
evaluation and the CI/CD gate.

## Images and ports

| Component | Port | Start command, from its folder | Notes |
| --- | --- | --- | --- |
| api | 8000 | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | Build context `api/` |
| indexer | none | `python -m pipeline.run` | Build context `indexer/`; a Job, so it exits |
| ui | 8080 | nginx with `ui/nginx.conf` as `/etc/nginx/nginx.conf` | Static files only |
| chroma | 8000 | `chromadb/chroma` | Data in `/data`; heartbeat `GET /api/v2/heartbeat` |
| redis | 6379 | `redis` | If you choose Redis for the cache |

- **Pin every image tag.** The Python client here is `chromadb-client==1.0.12`, so run the
  same server version: `chromadb/chroma:1.0.12`. Pull it once before you rely on it; if you
  change one version, change the other.
- **The UI container runs as non-root with a read-only root filesystem.** `nginx.conf`
  listens on 8080 and writes only under `/tmp`, so mount an `emptyDir` at `/tmp`. Either
  start from `nginxinc/nginx-unprivileged` or set a non-root `USER` yourself.
- **The UI calls `/api/ask` on its own origin**, so your Ingress must route `/api` to the
  api Service and `/` to the ui Service. nginx does not proxy the API. For local testing
  against another address, open the page with `?api=http://host:port`.
- **minikube cannot see images you built with your own Docker.** `make images` builds all
  three and loads them with `minikube image load`; use `imagePullPolicy: IfNotPresent`.
- **Ollama on your laptop must listen on all interfaces**: `OLLAMA_HOST=0.0.0.0 ollama serve`.
- **On macOS or Windows with the docker driver**, the minikube IP is not reachable. Run
  `minikube tunnel` in another terminal and use `make ask INGRESS_IP=127.0.0.1`.

## The corpus

```bash
cp corpus/sources.example.yaml corpus/sources.yaml   # keep, drop or add documents
make fetch                                           # downloads to corpus/raw/, writes MANIFEST.md
python corpus/fetch.py --verify                      # re-hash your files against the manifest
python corpus/fetch.py --list https://www.nu.edu.pk/Downloads   # find more documents
```

`fetch.py` downloads one file at a time with a pause between requests. Do not change that:
forty teams share one university website. It writes `corpus/raw/_index.json`, which the
indexer reads for each file's `doc_version` and `superseded` flags.

Commit `corpus/MANIFEST.md` and `corpus/sources.yaml`. **Never commit `corpus/raw/`**; it is
already gitignored. How the documents reach the indexer Job (baked into the image, fetched
at start-up, or a volume) is your decision: explain it in `docs/PIPELINE.md`.

## The fixture corpus

`eval/fixtures/` holds three short Markdown documents about a fictional university, with
front matter for `doc_version` and `superseded`, plus `golden.fixture.yaml` (six questions:
ordinary, version, exact term, a must-abstain and an injection). Your `e2e-eval` CI job
indexes this folder (`CORPUS_DIR=eval/fixtures`) so that CI runs in minutes, not on your
real corpus. Locally: `make dev` in one terminal, `make eval-fixtures` in another.

## Evaluation

Copy `eval/golden.example.yaml` to `eval/golden.yaml` and write at least 15 questions
**before** you tune anything. Implement the four functions in `eval/run_eval.py`, then:

```bash
make eval                                         # through the Ingress
python eval/run_eval.py --api http://<ip> --host rahbar.local --update-baseline
```

Update the baseline only after a deliberate improvement, and commit `eval/baseline.json`
and `eval/results.json`. The exit code is the CI gate: 0 pass, 1 gate failed, 2 not
implemented yet.

## Secrets

- The LLM key is created from the command line, never from a file: `export LLM_API_KEY=...`
  then `make secret`.
- If you want a placeholder Secret manifest in the repository, name it
  `k8s/base/secret.placeholder.yaml` (the `.gitignore` allows that one name pattern), put
  only `REPLACE_ME` in it, and **never list it in `kustomization.yaml`**: applying it would
  overwrite your real Secret.
- `.env`, any other `*secret*.yaml` and kubeconfig files are gitignored. A key that reaches
  Git history must be rotated, even if you delete the commit.

## The checker

```bash
make check        # python3 scripts/check_submission.py, standard library only
```

The first section, **0 · starter kit**, fails until every `STARTER-TODO` marker and every
`raise NotImplementedError` is gone. Find them with:

```bash
grep -rn STARTER-TODO --exclude-dir=.venv .
```

Some `ok` lines pass from day one because the kit already contains that plumbing (the
schemas, the metadata fields). An `ok` means the thing exists, not that your part around it
is finished. The checker is a lint, not a grader.

## Repository map

```
api/            FastAPI service: reads the index, never writes it
  app/schemas.py         the contract
  app/retrieval/         stub.py (given), chroma.py (yours)
  app/providers/llm/     stub.py (given), ollama.py and hosted.py (yours)
  app/services/answer.py retrieve, then generate: add the production steps here
  app/routes/            /api/ask, /healthz, /readyz, /metrics
  tests/                 keep these passing and add your own
indexer/        the Job's image: the only writer
  pipeline/run.py        python -m pipeline.run [--dummy]
  pipeline/{extract,clean,chunk,embed,store}.py   yours
ui/             index.html and nginx.conf (given); the Dockerfile is yours
corpus/         fetch.py, sources.example.yaml; MANIFEST.md once you fetch
eval/           run_eval.py, golden.example.yaml, fixtures/
k8s/            base/ and overlays/{dev,prod}/: empty, yours
docs/           templates for every required document, adr/0000-template.md
scripts/        check_submission.py
.github/        workflows/: empty, yours
```

Replace `README.md` with your own before you submit. This file explains the kit; your
README explains your system.
