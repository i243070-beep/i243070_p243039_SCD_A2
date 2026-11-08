#!/usr/bin/env python3
"""
RAHBAR submission checker
CS4032 Software Construction & Development - Assignment 02

Run from the root of your repository:

    python scripts/check_submission.py

A LINT, not a grader. It catches the mechanical mistakes behind almost every
automatic deduction in section 8 of the handout. A clean run says nothing
about your retrieval quality, your design, or your viva.

Standard library only. No pip install. Python 3.9+.
"""

import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path.cwd()

if sys.stdout.isatty() and os.name != "nt":
    RED, YELLOW, GREEN, GREY, BOLD, OFF = (
        "\033[31m", "\033[33m", "\033[32m", "\033[90m", "\033[1m", "\033[0m")
else:
    RED = YELLOW = GREEN = GREY = BOLD = OFF = ""

results = []


def fail(sec, msg): results.append(("FAIL", sec, msg))
def warn(sec, msg): results.append(("WARN", sec, msg))
def ok(sec, msg):   results.append(("OK", sec, msg))


def verdict(cond, sec, good, bad):
    (ok if cond else fail)(sec, good if cond else bad)


def soft(cond, sec, good, bad):
    (ok if cond else warn)(sec, good if cond else bad)


def read(path):
    try:
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if str(path).lower().endswith(".md"):
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text


def git(*args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True,
                           timeout=60, cwd=ROOT)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


SKIP = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__",
        ".mypy_cache", ".pytest_cache", "site-packages"}


def _is_test(p):
    rel = p.relative_to(ROOT).parts
    return "tests" in rel or "test" in rel or p.name.startswith("test_") \
        or p.name.endswith("_test.py") or p.name == "conftest.py"


def _code_only(text):
    """Python source with comments and docstrings blanked out, line numbers kept. A
    comment that says `check the embedding model` is not a check."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text
    blank = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                blank.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    cut = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                cut[tok.start[0]] = tok.start[1]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if i in blank:
            out.append("")
        elif i in cut:
            out.append(line[:cut[i]].rstrip())
        else:
            out.append(line)
    return "\n".join(out)


def slurp(patterns, exclude_tests=False, code_only=False):
    text, seen = "", set()
    for pat in patterns:
        for p in sorted(ROOT.rglob(pat)):
            if p in seen or any(part in SKIP for part in p.parts) or not p.is_file():
                continue
            seen.add(p)
            if exclude_tests and _is_test(p):
                continue
            try:
                chunk = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if code_only and p.suffix == ".py":
                chunk = _code_only(chunk)
            text += chunk + "\n"
    return text


def slurp_src(patterns):
    """Source code only: the checks below look for what your code does, not what your
    tests are called."""
    return slurp(patterns, exclude_tests=True, code_only=True)


def find_dir(*names):
    for n in names:
        if (ROOT / n).is_dir():
            return n
    return None


def _function_body(src, name_pattern):
    """Return the body of the first function whose name matches, stopping at the
    next line that is not indented further than the `def` itself. Without this
    bound, one handler's body bleeds into the next and the check lies."""
    m = re.search(r"^([ \t]*)(?:async\s+)?def\s+(" + name_pattern + r")\s*\(", src, re.M)
    if not m:
        return None
    indent = len(m.group(1).expandtabs())
    # skip the remainder of the `def` line (parameters may wrap over several lines)
    nl = src.find("\n", m.end())
    depth = src[m.end():nl if nl != -1 else len(src)].count("(") - \
        src[m.end():nl if nl != -1 else len(src)].count(")")
    while depth > 0 and nl != -1:
        nxt = src.find("\n", nl + 1)
        seg = src[nl:nxt if nxt != -1 else len(src)]
        depth += seg.count("(") - seg.count(")")
        nl = nxt
    if nl == -1:
        return ""
    lines = src[nl + 1:].splitlines()
    body = []
    for line in lines:
        if not line.strip():
            body.append(line)
            continue
        if len(line.expandtabs()) - len(line.expandtabs().lstrip()) <= indent:
            break
        body.append(line)
    return "\n".join(body)


# ==========================================================================
# 0 - starter kit leftovers
# ==========================================================================
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".txt", ".html", ".js", ".ts",
                 ".conf", ".json", ".cfg", ".ini", ".sh"}
TEXT_NAMES = {"Makefile", "Dockerfile", ".gitignore", ".dockerignore"}
NOT_YOURS = {"STARTER.md", "scripts/check_submission.py"}


def check_starter_leftovers():
    """Every placeholder in the starter kit is marked STARTER-TODO. Any that remain are
    unfinished work, and any `raise NotImplementedError` is a stub nobody replaced."""
    s = "0 · starter kit"
    markers, stubs = {}, {}
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(part in SKIP for part in p.parts):
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel in NOT_YOURS or ".example." in p.name or rel.startswith("corpus/raw/"):
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES and p.name not in TEXT_NAMES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n = text.count("STARTER-TODO")
        if n:
            markers[rel] = n
        if p.suffix == ".py" and not _is_test(p):
            k = len(re.findall(r"^\s*raise\s+NotImplementedError", text, re.M))
            if k:
                stubs[rel] = k

    def listing(found):
        top = sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ", ".join(f"{f} ({n})" for f, n in top[:8])
        return shown + (f", and {len(top) - 8} more files" if len(top) > 8 else "")

    if markers:
        fail(s, f"{sum(markers.values())} STARTER-TODO markers left in {len(markers)} files: "
                f"{listing(markers)}. Find them with: grep -rn STARTER-TODO --exclude-dir=.venv .")
    else:
        ok(s, "no STARTER-TODO markers left")
    if stubs:
        fail(s, f"{sum(stubs.values())} `raise NotImplementedError` stubs still in source: "
                f"{listing(stubs)}")
    else:
        ok(s, "no NotImplementedError stubs left in source")


# ==========================================================================
# A - structure and git
# ==========================================================================
def check_structure():
    s = "A · structure"
    for f in ["README.md", ".gitignore",
              "docs/CORPUS.md", "docs/PIPELINE.md", "docs/FAILURE-ANALYSIS.md",
              "docs/ENGINEERING-NOTES.md", "docs/AI-USAGE.md"]:
        verdict((ROOT / f).exists(), s, f"{f} present", f"{f} is missing")

    for d in ["api", "indexer", "k8s", "eval"]:
        verdict((ROOT / d).is_dir(), s, f"{d}/ present", f"{d}/ directory is missing")
    soft((ROOT / "ui").is_dir(), s, "ui/ present", "no ui/ directory found")

    adr = ROOT / "docs" / "adr"
    adrs = [p for p in adr.glob("*.md") if "template" not in p.name.lower()] \
        if adr.is_dir() else []
    n = len(adrs)
    verdict(n >= 4, s, f"{n} ADRs found",
            f"{n} ADRs - 4 required (indexer-as-Job, chunking, cache store, LLM provider/PII)")
    if adr.is_dir():
        names = " ".join(p.name.lower() for p in adrs)
        verdict("job" in names, s, "an ADR names the indexer-as-Job decision",
                "no ADR filename mentions the indexer Job - ADR 0001 is the first thing graded")

    ev = ROOT / "docs" / "evidence"
    n = len([p for p in ev.iterdir() if p.is_file() and not p.name.startswith(".")]) \
        if ev.is_dir() else 0
    verdict(n >= 5, s, f"{n} evidence files",
            f"{n} evidence files - need branch protection, blocked merge, kubectl top, "
            f"get endpoints, get hpa")

    wf = ROOT / ".github" / "workflows"
    n = len(list(wf.glob("*.yml")) + list(wf.glob("*.yaml"))) if wf.is_dir() else 0
    verdict(n >= 2, s, f"{n} workflow files", f"{n} workflows - ci.yml and cd.yml required")


def check_git():
    s = "A · git"
    if not (ROOT / ".git").is_dir():
        warn(s, "not a git repository - skipping history checks")
        return

    added = git("log", "--all", "--diff-filter=A", "--name-only", "--pretty=format:") or ""
    danger = re.compile(
        r"(^|/)\.env$|(^|/)\.env\.(local|prod|production)$|\.pem$|(^|/)id_(rsa|ed25519)$"
        r"|(^|/)[\w.-]*secret[\w.-]*\.ya?ml$|\.kubeconfig$|(^|/)kubeconfig$", re.I)
    hits = sorted({ln.strip() for ln in added.splitlines()
                   if ln.strip() and danger.search(ln.strip())})
    # a committed secret TEMPLATE is fine; flag it as a warning, real names as failures
    real = [h for h in hits if not re.search(r"(example|template|sample|placeholder)", h, re.I)]
    if real:
        fail(s, "SECRET-BEARING FILES IN HISTORY (-20, rotate the credential): "
                + ", ".join(real[:5]))
    elif hits:
        warn(s, "secret-shaped files in history, but all look like templates: "
                + ", ".join(hits[:3]))
    else:
        ok(s, "no secret / key / kubeconfig files in history")

    gi = read(".gitignore") or ""
    verdict(bool(re.search(r"secret", gi, re.I)), s,
            "a secret pattern is gitignored",
            ".gitignore has no secret pattern - add *-secret.yaml before you write one")
    soft("corpus" in gi.lower() or (ROOT / "corpus").is_dir(), s,
         "corpus handled", "no corpus/ directory and no corpus rule in .gitignore")

    log = git("log", "--oneline", "--no-merges") or ""
    n = len([ln for ln in log.splitlines() if ln.strip()])
    soft(n >= 25, s, f"{n} non-merge commits",
         f"only {n} non-merge commits - small, frequent commits are how a marker reads your history")

    short = git("shortlog", "-sn", "--all", "--no-merges")
    if short:
        rows = []
        for line in short.splitlines():
            m = re.match(r"\s*(\d+)\s+(.+)", line)
            if m:
                rows.append((int(m.group(1)), m.group(2).strip()))
        total = sum(c for c, _ in rows) or 1
        if len(rows) < 2:
            warn(s, "only one commit author - both partners should commit under their own identity")
        else:
            low = min(100 * c // total for c, _ in rows[:2])
            detail = ", ".join(f"{nm} {c}({100 * c // total}%)" for c, nm in rows[:4])
            soft(low >= 35, s, f"authorship: {detail}",
                 f"authorship: {detail} - one partner wrote {low}% of the commits")

    subjects = [ln.split(" ", 1)[1] for ln in log.splitlines() if " " in ln]
    if subjects:
        conv = re.compile(r"^(feat|fix|docs|test|chore|refactor|build|ci|perf|style)(\(.+\))?!?:\s")
        pct = 100 * sum(1 for x in subjects if conv.match(x)) // len(subjects)
        soft(pct >= 60, s, f"{pct}% of commits use conventional prefixes",
             f"only {pct}% of commits use conventional prefixes")

    soft(bool(re.search(r"\bdev\b", git("branch", "-a") or "")), s,
         "a dev branch exists", "no dev branch - the two-branch model is required")


# ==========================================================================
# B - corpus
# ==========================================================================
def check_corpus():
    s = "B · corpus"
    cdir = ROOT / "corpus"
    manifest = read("corpus/MANIFEST.md") or read("corpus/MANIFEST.yaml") or ""
    docs = []
    if cdir.is_dir():
        # corpus/raw/ is where fetch.py downloads to; it is gitignored, so it does not count
        docs = [p for p in cdir.rglob("*")
                if p.is_file() and p.suffix.lower() in {".pdf", ".md", ".txt", ".html", ".docx"}
                and "raw" not in p.relative_to(cdir).parts
                and p.name.lower() not in {"manifest.md", "readme.md"}
                and not any(part in SKIP for part in p.parts)]
    urls = len(set(re.findall(r"https?://[^\s|>)]+", manifest)))
    total = len(docs) + urls
    if total == 0:
        fail(s, "no corpus/ documents and no corpus/MANIFEST.md - run corpus/fetch.py "
                "and commit the MANIFEST it writes")
    else:
        verdict(total >= 6, s,
                f"{total} corpus documents ({len(docs)} committed, {urls} listed in MANIFEST)",
                f"only {total} corpus documents ({len(docs)} committed, {urls} in MANIFEST) "
                f"- at least 6 required")
    if urls:
        verdict(bool(re.search(r"\b[0-9a-f]{64}\b", manifest)), s,
                "MANIFEST carries SHA-256 checksums",
                "MANIFEST has no SHA-256 checksums - required for documents you do not commit")

    doc = read("docs/CORPUS.md") or ""
    verdict(len(doc) >= 1200, s, "docs/CORPUS.md has substance",
            "docs/CORPUS.md is too short to have mapped all seven required properties")
    for pat, label in [
        (r"(scan|ocr|image-only|no text layer)", "the scanned/OCR document"),
        (r"(table)", "the table-bearing document"),
        (r"(version|supersed|revis|2023|2024|2025)", "the two-version policy pair"),
        (r"(absent|abstain|not cover|deliberate(ly)? (missing|absent)|no answer)",
         "the deliberately absent topic"),
        (r"(clause|course code|threshold|CGPA|exact)", "exact-term content"),
    ]:
        verdict(bool(re.search(pat, doc, re.I)), s,
                f"CORPUS.md documents {label}",
                f"CORPUS.md does not document {label} - a required corpus property")


# ==========================================================================
# C/D - indexing, retrieval, embedding pin
# ==========================================================================
def check_indexer():
    s = "C · indexer"
    src = slurp_src(["indexer/**/*.py"]) or slurp_src(["**/*.py"])
    if not src.strip():
        fail(s, "no indexer Python source found")
        return

    for pat, good, bad in [
        (r"(pdfplumber|pypdf|PyPDF|fitz|pymupdf|pdfminer|unstructured)",
         "a PDF extraction library is used", "no PDF extraction library found"),
        (r"(pytesseract|tesseract|easyocr|ocrmypdf|paddleocr)",
         "an OCR path exists for the scanned document",
         "no OCR library found - property 3 of the corpus needs one, or an honest documented loss"),
        (r"overlap", "chunk overlap is implemented",
         "no `overlap` anywhere in the indexer - boundary splitting is unhandled"),
        (r"(chromadb|PersistentClient|HttpClient)", "ChromaDB client used",
         "no ChromaDB client found in the indexer"),
    ]:
        verdict(bool(re.search(pat, src, re.I)), s, good, bad)

    # structure-aware chunking, not just fixed windows
    soft(bool(re.search(r"(section|heading|paragraph|structure[_-]?aware|split_on)", src, re.I)),
         s, "structure-aware chunking signals present",
         "chunking looks purely fixed-size - structure-aware splitting is required")

    # metadata fields
    for field in ["source", "section", "page", "doc_version", "superseded"]:
        verdict(field in src, s, f"metadata field `{field}` written",
                f"metadata field `{field}` not found - version filtering cannot work without it")

    # the pin must be written into collection metadata
    soft(bool(re.search(r"(embed_model|embedding_model|EMBED_MODEL)", src, re.I)), s,
         "the indexer records the embedding model",
         "the indexer never references the embedding model name - the pin cannot be verified later")


def check_api_and_pin():
    s = "D · api & pin"
    src = slurp_src(["api/**/*.py"]) or slurp_src(["**/*.py"])
    if not src.strip():
        fail(s, "no api Python source found")
        return

    for route in ["/healthz", "/readyz", "/metrics"]:
        verdict(route in src, s, f"route {route} referenced", f"route {route} not found")
    soft(bool(re.search(r"/ask|/query|/chat", src)), s,
         "a question endpoint is present", "no /ask, /query or /chat endpoint found")

    # liveness must not touch dependencies
    live = _function_body(src, r"\w*health\w*")
    if live is None:
        warn(s, "could not locate the liveness handler to inspect it - check by hand")
    else:
        touches = re.search(r"(chroma|collection|redis|ollama|client\.|requests\.|httpx\.)",
                            live, re.I)
        verdict(not touches, s, "the liveness handler does not touch dependencies",
                "the liveness handler appears to touch a dependency - a slow Chroma then "
                "becomes a cluster-wide restart storm")

    # readiness must check a non-empty collection
    ready = _function_body(src, r"\w*read(y|iness)\w*")
    if ready is None:
        warn(s, "could not locate the readiness handler - check by hand")
    else:
        soft(bool(re.search(r"(count\(|n_results|is_empty|len\(|peek\()", ready, re.I)), s,
             "readiness appears to check the collection is non-empty",
             "readiness does not look like it checks for a NON-EMPTY collection - required")

    # the embedding pin guardrail
    guard = re.search(r"(dimension|embed_model|embedding_model).{0,200}(mismatch|!=|does not match)",
                      src, re.I | re.S) or \
        re.search(r"(mismatch).{0,200}(embed|dimension)", src, re.I | re.S)
    verdict(bool(guard), s, "an embedding-model mismatch guardrail is present",
            "no embedding-model mismatch check found (-8) - without it a changed EMBED_MODEL "
            "fails silently: retrieval returns nonsense and nothing errors")

    verdict(bool(re.search(r"superseded", src)), s,
            "the API filters on `superseded`",
            "the API never references `superseded` - a repealed clause can be quoted as current")


def check_generation():
    s = "E · generation"
    src = slurp_src(["api/**/*.py"]) or slurp_src(["**/*.py"])
    if not src.strip():
        return

    verdict(bool(re.search(r"class\s+\w*Answer\w*\s*\(\s*BaseModel", src)), s,
            "an Answer Pydantic schema is defined",
            "no Answer(BaseModel) schema found - the structured output contract is required")
    verdict(bool(re.search(r"citation", src, re.I)), s, "citations are modelled",
            "no citation handling found")
    verdict(bool(re.search(r"answered_from_context", src)), s,
            "`answered_from_context` present",
            "no `answered_from_context` field - abstention cannot be measured")
    verdict(bool(re.search(r"(model_validate|ValidationError)", src)), s,
            "model output is validated with Pydantic",
            "no Pydantic validation of model output - structure is not guaranteed by asking nicely")
    verdict(bool(re.search(
        r"(format\s*=|[\"']format[\"']\s*:|response_format|json_schema|response_schema"
        r"|json_object|guided_json)", src)), s,
        "constrained decoding / JSON mode requested",
        "no constrained-decoding parameter found (format= / \"format\": / response_format "
        "/ response_schema)")
    verdict(bool(re.search(r"\bretr(y|ies|ying)\b", src, re.I)), s,
            "a retry path exists", "no retry on validation failure")
    verdict(bool(re.search(r"(fallback|FALLBACK)", src)), s,
            "a safe fallback exists", "no fallback - a bad JSON reply will surface as a 500")
    verdict(bool(re.search(r"timeout", src, re.I)), s,
            "a timeout is set on the provider call",
            "no timeout on the LLM call - a hung request can exhaust the worker pool")
    verdict(bool(re.search(r"request_?id", src, re.I)), s,
            "request_id propagation present",
            "no request_id - structured logging and per-request tracing need one")

    # retrieval observability
    soft(bool(re.search(r"(score|similarit|distance)", src, re.I)), s,
         "retrieval scores are handled/logged",
         "no retrieval score handling - you cannot diagnose stage C without the scores")

    if re.search(r"\beval\s*\(", src):
        fail(s, "eval() found in the source - never evaluate model or document text")

    # provider interface
    providers = set(re.findall(r"class\s+(\w*(?:Provider|LLM|Triage)\w*)\b", src))
    soft(len(providers) >= 3, s, f"{len(providers)} provider classes: {sorted(providers)[:4]}",
         f"only {len(providers)} provider class(es) - an interface plus a stub is needed for CI")
    verdict(bool(re.search(r"class\s+\w*Stub\w*|StubProvider|stub", src, re.I)), s,
            "a stub provider exists for offline tests",
            "no stub provider - CI must not call a real model")

    # hardcoded keys anywhere
    everything = slurp(["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.yaml", "**/*.yml"])
    for pat, label in [(r"gsk_[A-Za-z0-9]{20,}", "a Groq key"),
                       (r"AIza[A-Za-z0-9_\-]{25,}", "a Google API key"),
                       (r"sk-[A-Za-z0-9]{30,}", "an OpenAI-style key")]:
        if re.search(pat, everything):
            fail(s, f"{label} appears hard-coded in the repository (-20, rotate it now)")


def check_cache():
    s = "F · cache"
    src = slurp_src(["api/**/*.py"]) or slurp_src(["**/*.py"])
    if not src.strip():
        return
    verdict(bool(re.search(r"(cache)", src, re.I)), s, "a cache layer is present",
            "no cache code found - the semantic cache is required")
    verdict(bool(re.search(r"(threshold)", src, re.I)), s, "a similarity threshold is used",
            "no threshold found - a semantic cache needs one")
    soft(bool(re.search(r"(invalidat|flush|expire|clear_cache|bump|generation_id)", src, re.I)),
         s, "cache invalidation logic present",
         "no cache invalidation - after a re-index your new index serves old answers")
    soft(bool(re.search(r"(never_cache|do_not_cache|skip_cache|is_followup|standalone)", src, re.I)),
         s, "never-cache rules present",
         "no never-cache rule found - abstentions and follow-ups must never be cached")


# ==========================================================================
# G - Kubernetes
# ==========================================================================
def check_k8s():
    s = "G · kubernetes"
    if not (ROOT / "k8s").is_dir():
        fail(s, "no k8s/ directory")
        return
    blob = slurp(["k8s/**/*.yaml", "k8s/**/*.yml"])
    if not blob.strip():
        fail(s, "k8s/ contains no manifests")
        return

    kinds = set(re.findall(r"^kind:\s*(\w+)", blob, re.M))
    for need in ["Namespace", "Deployment", "StatefulSet", "Service", "Ingress",
                 "ConfigMap", "Secret", "Job", "CronJob",
                 "HorizontalPodAutoscaler", "NetworkPolicy"]:
        verdict(need in kinds, s, f"{need} present", f"no {need} manifest")

    verdict("StatefulSet" in kinds and "volumeClaimTemplates" in blob, s,
            "the Chroma StatefulSet uses volumeClaimTemplates",
            "no volumeClaimTemplates - a vector store without a PVC loses the index (-8)")

    # the indexer must be a Job, and the Job must not be a Deployment in disguise
    jobs = re.findall(r"(?s)kind:\s*Job(.{0,1200})", blob)
    if jobs:
        jb = jobs[0]
        soft(bool(re.search(r"restartPolicy:\s*(OnFailure|Never)", jb)), s,
             "the indexer Job sets a batch restartPolicy",
             "the Job has no restartPolicy: OnFailure|Never")
        soft("backoffLimit" in jb, s, "backoffLimit set on the Job",
             "no backoffLimit on the indexer Job")

    # namespace discipline
    verdict(not re.search(r"namespace:\s*default", blob), s,
            "no manifest targets the default namespace",
            "manifests target the default namespace (-5)")
    soft(bool(re.search(r"namespace:\s*\w", blob)), s,
         "manifests carry an explicit namespace", "no explicit namespace on objects")

    # services must be ClusterIP for data tiers
    for m in re.finditer(r"(?s)kind:\s*Service(.{0,900}?)(?=\n---|\Z)", blob):
        block = m.group(1)
        name = re.search(r"name:\s*([\w-]+)", block)
        nm = name.group(1) if name else "?"
        if re.search(r"type:\s*(NodePort|LoadBalancer)", block):
            if re.search(r"(chroma|redis|vector|cache|mongo|postgres)", nm, re.I):
                fail(s, f"Service `{nm}` is NodePort/LoadBalancer - the data tier must be "
                        f"ClusterIP (-8)")
            else:
                warn(s, f"Service `{nm}` is NodePort/LoadBalancer - acceptable only if it is "
                        f"not a data tier")

    # probes
    for probe in ["startupProbe", "livenessProbe", "readinessProbe"]:
        verdict(probe in blob, s, f"{probe} configured", f"no {probe} configured")
    live_ok = re.search(r"livenessProbe:(?:.|\n){0,250}?/healthz", blob)
    ready_ok = re.search(r"readinessProbe:(?:.|\n){0,250}?/readyz", blob)
    verdict(bool(live_ok and ready_ok), s,
            "liveness -> /healthz and readiness -> /readyz wired correctly",
            "liveness/readiness are not wired to /healthz and /readyz - swapping them turns a "
            "slow dependency into a restart storm")

    # resources
    verdict(bool(re.search(r"requests:\s*\n\s*(cpu|memory)", blob)), s,
            "resource requests set",
            "no resources.requests - the HPA has no denominator and reads <unknown>/70% (-6)")
    verdict(bool(re.search(r"limits:\s*\n\s*(cpu|memory)", blob)), s,
            "resource limits set", "no resources.limits")

    # HPA
    if "HorizontalPodAutoscaler" in kinds:
        soft("autoscaling/v2" in blob, s, "HPA uses autoscaling/v2",
             "HPA is not autoscaling/v2")
        hpa = re.search(r"(?s)kind:\s*HorizontalPodAutoscaler(.{0,800})", blob)
        if hpa and re.search(r"minReplicas:\s*([3-9]|\d\d)", hpa.group(1)):
            ok(s, "HPA minReplicas >= 3")
        else:
            warn(s, "HPA minReplicas looks below 3 - the handout asks for 3->8")

    # replicas on the api
    reps = [int(x) for x in re.findall(r"^\s*replicas:\s*(\d+)", blob, re.M)]
    soft(any(r >= 3 for r in reps), s, f"replica counts found: {reps}",
         f"no Deployment asks for 3+ replicas (found {reps}) - the api must run 3")

    # rollout + graceful shutdown
    soft("maxUnavailable: 0" in blob.replace("maxUnavailable:0", "maxUnavailable: 0"), s,
         "rolling update configured for zero unavailability",
         "no maxUnavailable: 0 - a zero-downtime rollout is not guaranteed")
    soft("terminationGracePeriodSeconds" in blob or "preStop" in blob, s,
         "graceful shutdown configured",
         "no preStop / terminationGracePeriodSeconds - rollouts will drop live requests")

    # security context
    verdict(bool(re.search(r"runAsNonRoot:\s*true", blob)), s,
            "runAsNonRoot: true set", "no runAsNonRoot: true - containers run as root")
    soft(bool(re.search(r"readOnlyRootFilesystem:\s*true", blob)), s,
         "readOnlyRootFilesystem: true set", "no readOnlyRootFilesystem: true")
    soft(bool(re.search(r"drop:\s*\n\s*-\s*(ALL|all)", blob)), s,
         "capabilities dropped", "no capabilities drop: [ALL]")
    soft(bool(re.search(r"automountServiceAccountToken:\s*false", blob)), s,
         "service-account token not auto-mounted where unneeded",
         "no automountServiceAccountToken: false anywhere")

    # NetworkPolicy must be deny-by-default somewhere
    if "NetworkPolicy" in kinds:
        npblob = "".join(re.findall(r"(?s)kind:\s*NetworkPolicy(.{0,900})", blob))
        deny = re.search(r"podSelector:\s*\{\s*\}", npblob) or \
            re.search(r"podSelector:\s*$\s*\n\s*(?!match)", npblob, re.M)
        soft(bool(deny), s, "a deny-by-default NetworkPolicy is present",
             "no NetworkPolicy with an empty podSelector - deny-by-default is the requirement")

    # committed secrets with real values
    for m in re.finditer(r"(?s)kind:\s*Secret.*?\bdata:\s*\n((?:[ \t]+\S+:\s*\S+\n)+)", blob):
        for line in m.group(1).splitlines():
            v = line.split(":", 1)[-1].strip().strip('"').strip("'")
            if len(v) > 24 and re.fullmatch(r"[A-Za-z0-9+/=]+", v):
                fail(s, "a Secret manifest holds a long base64 value - base64 is encoding, not "
                        "encryption (-15). Commit placeholders only.")
                break

    soft(bool(list((ROOT / "k8s").rglob("kustomization.yaml")) +
              list((ROOT / "k8s").rglob("kustomization.yml"))), s,
         "Kustomize kustomization files present",
         "no kustomization.yaml - base/overlay structure is expected")
    soft((ROOT / "k8s" / "overlays").is_dir(), s, "overlays/ present",
         "no k8s/overlays/ - dev and prod should differ by overlay, not by hand-editing")


def check_indexing_not_in_startup():
    """The central design decision: indexing must not run on API startup."""
    s = "G · indexer-as-Job"
    api = slurp_src(["api/**/*.py"])
    if not api.strip():
        return
    # look for pipeline verbs inside startup hooks
    hooks = re.findall(
        r"(?s)(@app\.on_event\(\s*[\"']startup[\"']\s*\)|lifespan|def\s+startup\w*)(.{0,1500})",
        api)
    smell = False
    for _, body in hooks:
        if re.search(r"(chunk|extract_pdf|build_index|index_corpus|ingest|add_documents|"
                     r"collection\.add|embed_corpus)", body, re.I):
            smell = True
    verdict(not smell, s,
            "no indexing work detected in API startup",
            "the API appears to index on startup (-10) - with 3 replicas that is three writers "
            "racing one PVC, and a re-index on every restart. Move it to the Job.")
    soft(bool(re.search(r"(\.add\s*\(|\.upsert\s*\()", slurp_src(["indexer/**/*.py"]) or "", re.I)),
         s, "writes to the collection live in the indexer",
         "no collection write (.add / .upsert) found in indexer/ - who builds the index?")


# ==========================================================================
# H - evaluation
# ==========================================================================
def check_eval():
    s = "H · evaluation"
    g = read("eval/golden.yaml") or read("eval/golden.yml") or read("eval/golden.json") or ""
    if not g:
        fail(s, "no eval/golden.yaml - the golden set is required and gates everything else")
    else:
        qs = len(re.findall(r"^\s*-\s*(question|id)\s*:", g, re.M)) or \
            len(re.findall(r"\bquestion\s*:", g))
        verdict(qs >= 15, s, f"{qs} golden questions", f"{qs} golden questions - 15 required")
        verdict(bool(re.search(r"(must_abstain|abstain|expect_abstention|no_answer)", g, re.I)),
                s, "must-abstain questions are marked in the golden set",
                "no must-abstain marker in golden.yaml - abstention correctness cannot be measured")
        soft(bool(re.search(r"(exact|clause|code|threshold)", g, re.I)), s,
             "exact-term questions present", "no exact-term questions flagged in the golden set")
        soft(bool(re.search(r"(injection|ignore your instructions)", g, re.I)), s,
             "an injection probe is in the golden set",
             "no prompt-injection question in the golden set")
        soft(bool(re.search(r"(version|supersed)", g, re.I)), s,
             "version-sensitive questions present",
             "no version-sensitive questions - your doc_version filter is untested")

    runner = read("eval/run_eval.py") or ""
    verdict(bool(runner), s, "eval/run_eval.py present", "no eval/run_eval.py")
    if runner:
        runner = _code_only(runner)
        stubbed = bool(re.search(r"raise\s+NotImplementedError", runner))
    if runner and stubbed:
        fail(s, "run_eval.py still raises NotImplementedError - recall@k, citation validity, "
                "summarise and gate are yours to write")
    elif runner:
        verdict(bool(re.search(r"recall", runner, re.I)), s, "recall@k is computed",
                "run_eval.py does not compute recall - the retrieval metric is required")
        verdict(bool(re.search(r"citation", runner, re.I)), s, "citation validity is measured",
                "run_eval.py does not check citation validity - and a fabricated citation costs -10")
        verdict(bool(re.search(r"(abstain|answered_from_context)", runner, re.I)), s,
                "abstention correctness is measured",
                "run_eval.py does not check abstention")
        verdict(bool(re.search(r"(sys\.exit|exit\(1\)|raise SystemExit)", runner)), s,
                "run_eval.py exits non-zero on failure",
                "run_eval.py never exits non-zero - it cannot gate CI")

    base = read("eval/baseline.json")
    verdict(bool(base), s, "eval/baseline.json committed",
            "no eval/baseline.json - without a baseline there is no regression gate")
    if base:
        try:
            b = json.loads(base)
            keys = " ".join(str(k).lower() for k in _flatten_keys(b))
            soft("recall" in keys, s, "baseline records a recall figure",
                 "baseline.json has no recall key")
        except json.JSONDecodeError:
            fail(s, "eval/baseline.json is not valid JSON")
    soft(bool(read("eval/results.json")), s, "eval/results.json committed",
         "no eval/results.json - submit your measured numbers")
    soft((ROOT / "eval" / "fixtures").is_dir(), s, "eval/fixtures/ present for CI",
         "no eval/fixtures/ - CI needs a tiny corpus so the e2e job stays fast")

    pipe = read("docs/PIPELINE.md") or ""
    verdict(len(pipe) >= 1200, s, "docs/PIPELINE.md has substance",
            "docs/PIPELINE.md is too short to hold the chunking table and threshold reasoning")
    verdict(len(re.findall(r"\|", pipe)) >= 12, s,
            "PIPELINE.md contains a table (chunking configurations)",
            "no table in PIPELINE.md - three measured (size, overlap) configurations are required")
    soft(bool(re.search(r"(amplification|stored .*original|150 ?/ ?120|ratio)", pipe, re.I)), s,
         "storage amplification reported",
         "no storage-amplification figure in PIPELINE.md")

    fa = read("docs/FAILURE-ANALYSIS.md") or ""
    verdict(len(fa) >= 1200, s, "docs/FAILURE-ANALYSIS.md has substance",
            "FAILURE-ANALYSIS.md is too short to cover four broken stages")
    stages = sum(1 for p in [r"extract", r"chunk", r"retriev", r"prompt", r"source|supersed",
                             r"generat|temperatur"]
                 if re.search(p, fa, re.I))
    verdict(stages >= 4, s, f"{stages} of 6 failure stages discussed",
            f"only {stages} failure stages discussed - four are required")


def _flatten_keys(o, out=None):
    out = [] if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            out.append(k)
            _flatten_keys(v, out)
    elif isinstance(o, list):
        for v in o:
            _flatten_keys(v, out)
    return out


# ==========================================================================
# I - images and pipeline
# ==========================================================================
def check_dockerfiles():
    for label, path, multi_required in [
        ("I · api image", "api/Dockerfile", False),
        ("I · indexer image", "indexer/Dockerfile", False),
        ("I · ui image", "ui/Dockerfile", False),
    ]:
        df = read(path)
        if df is None:
            fail(label, f"{path} not found")
            continue
        froms = re.findall(r"^\s*FROM\s+(\S+)", df, re.M | re.I)
        if not froms:
            fail(label, "no FROM instruction")
        for img in froms:
            base = img.split("@")[0]
            if "@sha256:" in img:
                ok(label, f"base pinned by digest: {base}")
            elif ":" not in base or base.endswith(":latest"):
                fail(label, f"unpinned base `{img}` - pin a version tag (python:3.12-slim, not python)")
            else:
                ok(label, f"base pinned: {img}")
        if multi_required:
            verdict(len(froms) >= 2, label, f"multi-stage build ({len(froms)} stages)",
                    "single-stage - the ui image must be multi-stage (no Node in the final layer)")
        verdict(bool(re.search(r"^\s*USER\s+(?!root\b)\S+", df, re.M | re.I)), label,
                "non-root USER set", "no non-root USER - the container runs as root")
        verdict(bool(re.search(r"^\s*(CMD|ENTRYPOINT)\s*\[", df, re.M | re.I)), label,
                "exec-form CMD/ENTRYPOINT",
                "CMD/ENTRYPOINT not in exec form - stop signals will not reach PID 1")
        if re.search(r"(PASSWORD|SECRET|TOKEN|API_?KEY)\s*=\s*[\"']?\S{8,}", df, re.I):
            fail(label, "a credential appears hard-coded in the Dockerfile")

    for ctx in ["api/.dockerignore", "indexer/.dockerignore"]:
        s = "I · " + ctx
        di = read(ctx)
        if di is None:
            fail(s, "missing")
            continue
        entries = {ln.strip().rstrip("/") for ln in di.splitlines()
                   if ln.strip() and not ln.startswith("#")}
        for nd in [".git", "__pycache__"]:
            verdict(any(e == nd or e.startswith(nd) for e in entries), s,
                    f"{nd} excluded", f"{nd} not excluded from the build context")
        soft(any("corpus" in e or "venv" in e for e in entries), s,
             "heavy directories excluded",
             "neither corpus/ nor a venv is excluded - your build context will be large")


def check_workflows():
    s = "I · CI/CD"
    if not (ROOT / ".github" / "workflows").is_dir():
        fail(s, "no .github/workflows/")
        return
    blob = slurp([".github/workflows/*.yml", ".github/workflows/*.yaml"])

    for pat, good, bad in [
        (r"\bpytest\b", "pytest runs in CI", "no pytest step"),
        (r"\b(ruff|flake8|pylint)\b", "a Python linter runs", "no Python linter step"),
        (r"\b(kubeconform|kubeval)\b", "manifest validation runs",
         "no kubeconform step - a broken manifest should fail in 20s, not on the cluster"),
        (r"\b(trivy|aquasecurity)\b", "image vulnerability scan runs", "no Trivy scan step"),
        (r"\b(kind|k3d|minikube)\b", "an ephemeral cluster job exists",
         "no kind/k3d job - the e2e eval job needs a real cluster"),
        (r"rollout\s+status", "the deploy waits on rollout status",
         "no `kubectl rollout status` - the deploy does not wait"),
        (r"github\.sha", "images tagged by commit SHA",
         "no ${{ github.sha }} tag - no traceability and no rollback path"),
        (r"docker/login-action|docker\s+login|ghcr\.io", "registry login configured",
         "no registry login step - use docker/login-action with a Docker Hub access token "
         "from GitHub Secrets"),
        (r"run_eval|eval/", "the eval gate runs in CI",
         "no reference to the eval runner in CI - without it there is no regression gate"),
    ]:
        verdict(bool(re.search(pat, blob, re.I)), s, good, bad)

    soft(bool(re.search(r"(create\s+job|kubectl\s+apply.*job|indexer)", blob, re.I)), s,
         "CI runs the indexer Job",
         "CI never runs the indexer - the e2e job must index a fixture corpus first")

    verdict(bool(re.search(r"^\s*needs\s*:", blob, re.M)), s,
            "jobs are gated with `needs:`",
            "no `needs:` anywhere (-6) - you are publishing artifacts from untested code")

    # the publishing job specifically must be gated
    gated = True
    for wfile in sorted(list((ROOT / ".github" / "workflows").glob("*.yml")) +
                        list((ROOT / ".github" / "workflows").glob("*.yaml"))):
        text = wfile.read_text(encoding="utf-8", errors="replace")
        for jb in re.split(r"^  (?=[A-Za-z][\w-]*:\s*$)", text, flags=re.M):
            publishes = re.search(r"(build-push-action|docker\s+push|push:\s*true)", jb)
            if publishes and not re.search(r"^\s{4}needs\s*:", jb, re.M):
                name = jb.strip().split(":")[0][:40]
                fail(s, f"the publishing job `{name}` in {wfile.name} has no `needs:` (-6) - "
                        f"it can publish an image built from code that failed its tests")
                gated = False
    if gated and re.search(r"(build-push-action|docker\s+push)", blob):
        ok(s, "the publishing job itself is gated by `needs:`")

    soft(bool(re.search(r"^\s*permissions\s*:", blob, re.M)), s,
         "explicit permissions block present",
         "no least-privilege `permissions:` block on any workflow")
    soft(bool(re.search(r"secrets\.\w+", blob)), s,
         "credentials come from GitHub Secrets", "no secrets.* reference found")
    for m in re.finditer(r"(password|token|api[_-]?key)\s*:\s*[\"']?([A-Za-z0-9_\-]{12,})[\"']?\s*$",
                         blob, re.M | re.I):
        if "secrets." not in m.group(0) and "${{" not in m.group(0):
            fail(s, f"literal credential in a workflow: `{m.group(0).strip()[:40]}...`")
    soft(bool(re.search(r"uses:\s*\S+@(v\d|[0-9a-f]{40})", blob)), s,
         "actions are version-pinned", "actions are not pinned to a version or SHA")


def check_tests():
    s = "I · tests"
    tests = slurp(["api/tests/**/*.py", "indexer/tests/**/*.py", "tests/**/*.py"])
    if not tests.strip():
        fail(s, "no tests found")
        return
    n = len(re.findall(r"^\s*(?:async\s+)?def\s+test_", tests, re.M))
    verdict(n >= 12, s, f"{n} test functions", f"{n} tests - at least 12 expected")
    verdict(bool(re.search(r"(injection|ignore your instructions|poison)", tests, re.I)), s,
            "a prompt-injection test exists",
            "no prompt-injection test - required")
    verdict(bool(re.search(r"(abstain|answered_from_context)", tests, re.I)), s,
            "abstention is tested", "no abstention test")
    soft(bool(re.search(r"(fallback|ValidationError)", tests, re.I)), s,
         "the validation/fallback path is tested",
         "no test for the schema-failure fallback path")
    if re.search(r"(requests|httpx)\.(get|post)\s*\(\s*[\"']https?://(?!localhost|127)", tests):
        fail(s, "a test appears to call a real external endpoint - CI must not depend on a "
                "third party or a live model")
    if re.search(r"\btime\.sleep\(", tests):
        warn(s, "time.sleep() in tests - a sign of a timing-dependent, flaky suite")


def check_docs():
    s = "J · docs"
    r = read("README.md") or ""
    verdict(len(r) >= 2000, s, f"README is {len(r)} characters",
            f"README is only {len(r)} characters - too thin for a portfolio repo's front door")
    for pat, label in [(r"```mermaid|\.(png|svg|gif)", "architecture diagram or screenshot"),
                       (r"badge|shields\.io", "CI badge"),
                       (r"kubectl apply", "the exact apply order"),
                       (r"minikube|kind|k3d", "cluster start instructions"),
                       (r"\|\s*(GET|POST)\s*\|", "API table"),
                       (r"(indexer|create job|Job)", "how to run the indexer")]:
        verdict(bool(re.search(pat, r, re.I)), s, f"{label} present", f"{label} missing")

    notes = read("docs/ENGINEERING-NOTES.md") or ""
    verdict(len(notes) >= 2000, s, "engineering notes have substance",
            "ENGINEERING-NOTES.md is too short to have answered all seven questions")
    soft(bool(re.search(r"(hpa|autoscal)", notes, re.I)), s,
         "notes discuss the HPA signal question",
         "notes do not mention the HPA - question 3 is required")
    corpus_notes = notes + (read("docs/PIPELINE.md") or "")
    soft(bool(re.search(r"kubectl top", corpus_notes)), s,
         "kubectl top output referenced",
         "no `kubectl top` reference - resource numbers must be justified with real output")


# ==========================================================================
def main():
    print(f"\n{BOLD}RAHBAR submission checker{OFF}  ·  {ROOT}\n")
    for fn in (check_starter_leftovers, check_structure, check_git, check_corpus, check_indexer,
               check_api_and_pin, check_generation, check_cache,
               check_k8s, check_indexing_not_in_startup, check_eval,
               check_dockerfiles, check_workflows, check_tests, check_docs):
        try:
            fn()
        except Exception as exc:
            warn(fn.__name__, f"checker error: {exc!r} - verify this section by hand")

    section = None
    for level, sec, msg in results:
        if sec != section:
            print(f"\n{BOLD}{sec}{OFF}")
            section = sec
        mark, col = {"OK": ("  ok  ", GREEN), "WARN": (" warn ", YELLOW),
                     "FAIL": (" FAIL ", RED)}[level]
        print(f"  {col}{mark}{OFF} {msg}")

    f = sum(1 for lvl, _, _ in results if lvl == "FAIL")
    w = sum(1 for lvl, _, _ in results if lvl == "WARN")
    o = sum(1 for lvl, _, _ in results if lvl == "OK")
    print(f"\n{BOLD}{o} passed · {w} warnings · {f} failures{OFF}")
    if f:
        print(f"{RED}Fix the failures before submitting. Most map to an automatic "
              f"deduction in section 8.{OFF}\n")
    else:
        print(f"{GREEN}No mechanical failures. This says nothing about your recall@k, your "
              f"design, or your viva - go and re-read section 7.{OFF}\n")
    print(f"{GREY}A lint, not the rubric. Passing it is necessary, not sufficient.{OFF}\n")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
