#!/usr/bin/env python3
"""Download the corpus listed in corpus/sources.yaml, politely, and record it.

    python corpus/fetch.py                       # download what is missing
    python corpus/fetch.py --force               # download everything again
    python corpus/fetch.py --verify              # re-hash local files against MANIFEST.md
    python corpus/fetch.py --list URL            # list the documents linked from an index page

Writes:
    corpus/raw/<file>         the documents (gitignored: never commit someone else's PDFs)
    corpus/raw/_index.json    file -> doc_version, superseded; the indexer reads this
    corpus/MANIFEST.md        URL, size and SHA-256 per document (commit this)

Rules this script follows so 40 teams do not hammer one university website:
one request at a time, a pause between requests, a clear User-Agent, each file
downloaded once and then reused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx
import yaml

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
SOURCES = HERE / "sources.yaml"
MANIFEST = HERE / "MANIFEST.md"
USER_AGENT = "RAHBAR-coursework-fetcher/1.0 (CS4032 student project; one request at a time)"
PAUSE_SECONDS = 2.0
DRIVE_VIEW = re.compile(r"https?://drive\.google\.com/file/d/([^/?#]+)")


def normalise(url: str) -> str:
    """Encode spaces and other unsafe characters, and turn Drive viewer links into
    direct downloads. Already-encoded %XX sequences are left alone."""
    match = DRIVE_VIEW.match(url)
    if match:
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return quote(url, safe=":/?&=%#+,;@!$'()*~")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or "document"


def guess_extension(url: str, content_type: str) -> str:
    content_type = content_type.lower()
    if "pdf" in content_type:
        return ".pdf"
    if "html" in content_type:
        return ".html"
    suffix = Path(urlsplit(url).path).suffix.lower()
    return suffix if suffix in {".pdf", ".html", ".htm", ".docx", ".txt", ".md"} else ".bin"


def get(client: httpx.Client, url: str, attempts: int = 3) -> httpx.Response:
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url)
            if response.status_code < 500:
                return response
            reason = f"HTTP {response.status_code}"
        except httpx.TransportError as exc:
            reason = type(exc).__name__
        if attempt < attempts:
            wait = PAUSE_SECONDS * 2 ** attempt
            print(f"    {reason}; retrying in {wait:.0f}s ({attempt}/{attempts - 1})")
            time.sleep(wait)
    raise RuntimeError(f"gave up after {attempts} attempts: {reason}")


def load_sources() -> list[dict]:
    if not SOURCES.exists():
        sys.exit("corpus/sources.yaml not found. Copy corpus/sources.example.yaml to "
                 "corpus/sources.yaml and keep the documents you want.")
    data = yaml.safe_load(SOURCES.read_text(encoding="utf-8")) or {}
    docs = data.get("documents") or []
    for i, doc in enumerate(docs):
        if not doc.get("name") or not doc.get("url"):
            sys.exit(f"sources.yaml entry {i + 1} needs both name and url")
    return docs


def fetch(force: bool) -> int:
    docs = load_sources()
    RAW.mkdir(exist_ok=True)
    index_path = RAW / "_index.json"
    previous = {e["name"]: e for e in json.loads(index_path.read_text())} \
        if index_path.exists() else {}
    entries, failures = [], []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                      timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        for doc in docs:
            name, url = doc["name"], normalise(doc["url"])
            old = previous.get(name)
            if old and not force and (RAW / old["file"]).exists() and old["url"] == url:
                print(f"  have    {old['file']}")
                entries.append({**old, "doc_version": doc.get("doc_version", "unknown"),
                                "superseded": bool(doc.get("superseded", False))})
                continue
            print(f"  fetch   {name}")
            try:
                response = get(client, url)
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "")
                if "drive.google.com" in url and "html" in content_type:
                    raise RuntimeError("Google Drive returned a web page, not the file "
                                       "(too large for direct download, or not shared publicly)")
                file = slug(name) + guess_extension(url, content_type)
                (RAW / file).write_bytes(response.content)
                entries.append({
                    "name": name, "url": url, "file": file, "bytes": len(response.content),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "content_type": content_type.split(";")[0],
                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "doc_version": doc.get("doc_version", "unknown"),
                    "superseded": bool(doc.get("superseded", False)),
                })
                print(f"          {file}, {len(response.content):,} bytes")
            except Exception as exc:  # report every failure, keep going
                failures.append((name, str(exc)))
                print(f"  FAILED  {name}: {exc}")
            time.sleep(PAUSE_SECONDS)

    index_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    write_manifest(entries)
    print(f"\n{len(entries)} documents in corpus/raw, manifest written to corpus/MANIFEST.md")
    if failures:
        print(f"{len(failures)} failed; fix their URLs in sources.yaml and run again:")
        for name, reason in failures:
            print(f"  - {name}: {reason}")
        return 1
    return 0


def write_manifest(entries: list[dict]) -> None:
    lines = [
        "# Corpus manifest",
        "",
        "Generated by `corpus/fetch.py`. The documents themselves live in `corpus/raw/`, "
        "which is gitignored; run the script to download them, then `--verify` to check "
        "you have the same bytes.",
        "",
        "| Document | Version | Superseded | File | Bytes | SHA-256 | URL |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for e in entries:
        lines.append(f"| {e['name']} | {e['doc_version']} | {'yes' if e['superseded'] else 'no'} "
                     f"| `{e['file']}` | {e['bytes']:,} | `{e['sha256']}` | <{e['url']}> |")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify() -> int:
    if not MANIFEST.exists():
        sys.exit("no corpus/MANIFEST.md yet; run fetch first")
    rows = re.findall(r"\| `([^`]+)` \| [\d,]+ \| `([0-9a-f]{64})` \|", MANIFEST.read_text())
    bad = 0
    for file, expected in rows:
        path = RAW / file
        if not path.exists():
            print(f"  missing   {file}")
            bad += 1
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            print(f"  changed   {file}  (the website may have published a new version)")
            bad += 1
        else:
            print(f"  ok        {file}")
    print(f"\n{len(rows) - bad} of {len(rows)} match the manifest")
    return 1 if bad else 0


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def list_documents(index_url: str) -> int:
    """Print the PDF and Google Drive links on an index page, ready to paste into
    sources.yaml. Downloads nothing but the page itself."""
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                      timeout=30.0) as client:
        page = get(client, index_url)
    parser = _Links()
    parser.feed(page.text)
    seen = set()
    for href, text in parser.links:
        url = urljoin(index_url, href)
        is_doc = urlsplit(url).path.lower().endswith(".pdf") or DRIVE_VIEW.match(url)
        if is_doc and url not in seen:
            seen.add(url)
            name = text or Path(urlsplit(url).path).name
            print(f"  - name: {json.dumps(name)}\n    url: {json.dumps(url)}")
    print(f"\n{len(seen)} document links on {index_url}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--force", action="store_true", help="download everything again")
    group.add_argument("--verify", action="store_true", help="check local files against MANIFEST.md")
    group.add_argument("--list", metavar="URL", help="list document links on an index page")
    args = parser.parse_args()
    if args.verify:
        return verify()
    if args.list:
        return list_documents(args.list)
    return fetch(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
