# AI usage

This project was built with heavy AI assistance, and this file says so plainly.

| Tool | What it wrote or shaped | What we changed afterwards, and why |
| --- | --- | --- |
| **Claude Code, Claude Sonnet 5.5** (phases A to J) | Nearly all of the code and configuration in this repository: Dockerfiles, Kubernetes manifests, the indexer stages, the API (retrieval, grounding, cache, metrics, readiness), the evaluation functions, both GitHub workflows, and the first drafts of the documents. It ran the commands, read the logs and fixed the failures. Commits carry a `Co-Authored-By` line naming it. | Saqib set the direction and made the decisions listed below, ran the steps that need a human, and reviewed each phase through a demo PDF. |
| **Claude Code, Claude Opus 5.5** (phase K and a review) | The README, these notes, ADR 0002, and a review of the earlier work that found errors (listed below). | |
| **`llama3.2:3b` through Ollama** (at runtime) | Generates the answers in the running system. `nomic-embed-text` creates the embeddings. | `llama3.2:1b` was tried first and rejected after a live test, because it obeyed the prompt-injection question. |
| **Google AI Studio** (attempted at runtime) | Nothing shipped. The live test returned HTTP 403 for every model (ADR 0004). | Dropped in favour of local Ollama. |

## What the human decided or did

- Started over in this repository, with one contributor and controlled pushes, after an earlier repository was abandoned.
- Chose local Ollama on the GPU after the hosted provider refused the project.
- Approved each phase, each merge to `main`, and the switch from the 1B to the 3B model.
- Created the Docker Hub token and the GitHub Secrets by hand. The AI never saw a secret value.
- Took the branch-protection and merge-gate screenshots.
- Set the working rules that shaped the output: no secrets in any file, no PDFs in Git, report failures honestly, stop and ask before acting.

**Team note.** The assignment is for a pair and the repository name carries both ids, but every commit here is by `i243070-beep`. Work by the partner (p243039) existed only in an earlier repository and was removed; none of it is in this one.

## Where the AI was wrong

We list these because an AI's output needs checking, and these were caught by measuring or by re-reading.

| What the AI got wrong | How it was caught | Outcome |
| --- | --- | --- |
| Told us the 3B download had stalled, from reading a stale partial file. | The output of `ollama pull` itself. | Corrected; see ENGINEERING-NOTES Q7. |
| Set the API's CPU request to 50m from idle numbers, then claimed "89-125m under load" from one stale scrape of pod startup. | Review: identical samples across 39 s, taken just after the pods started. | Claim withdrawn in the evidence and the manifests. CPU during generation is stated as unmeasured. |
| Wrote that 13 of 20 requests "timed out" and that injection q21 "was not obeyed" in experiment D, without having captured either. | Review against the raw outputs. | Reworded to what was measured. |
| Left a real bug: when the model declined, the API still displayed its uncited text. That is how the 1B model's "students do not need to attend" reached a user. | Review of `answer.py` while writing these notes. | Fixed and tested. |
| Wrote the first gate from the three conditions in the assignment and assumed that was enough. | Failure experiments D and E passed it. | Added a fourth condition for superseded documents and a test that pins the prompt. |
| Several editing slips (a literal `\n` in a Dockerfile, a backspace character in a regex, CRLF line endings). | CI and `git diff --stat`. | Fixed. |
| Reported PR #7 as 27 commits (it was 12), by counting against a stale local `main`. | Review. | Corrected in the demo PDF. |
