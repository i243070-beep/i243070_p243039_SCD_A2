"""Stage 2: Clean. Remove artefacts without destroying structure.

Rules applied (copied into docs/PIPELINE.md):

 1. Repeated headers and footers. A line in the first or last three lines of a page (never more than
    a third of a short page) is removed when the same line (digits replaced by `#`, case and spacing
    ignored) appears at the page edge on at least half of the pages. Only for documents of three or
    more pages. Table rows (" | ") are data and are never removed as headers, even when they repeat.
 2. Standalone page numbers at the page edge ("12", "Page 3 of 53", "3 of 53") are removed.
 3. Table-of-contents pages are dropped: a page where most lines end in a page number or use dot
    leaders. They repeat every section title, so they would be retrieved instead of the section.
 4. Words hyphenated across a line break are joined ("exami-\\nnation" becomes "examination"), but
    never inside a number range or clause such as "5-6".
 5. Typographic artefacts become plain text: non-breaking and zero-width characters, the soft
    hyphen and the ligatures fi, fl, ff, ffi, ffl; control characters are removed.
 6. Runs of three or more blank lines collapse to one blank line; trailing spaces are stripped.

Deliberately NOT stripped: clause numbers such as "1.21" and "5.4", headings (including ALL-CAPS ones),
table rows with " | ", and the blank lines between paragraphs. Chunking and citations depend on them.
"""

from __future__ import annotations

import re

from .models import Document, Page

EDGE_LINES = 3
REPEAT_SHARE = 0.5
MIN_PAGES_FOR_HEADERS = 3

_REPLACEMENTS = {
    " ": " ", "­": "", "​": "", "‌": "", "‍": "", "﻿": "",
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PAGE_NUMBER = re.compile(r"^(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?$", re.IGNORECASE)
_HYPHEN_BREAK = re.compile(r"(?<=[a-z])-\n(?=[a-z])")
_TOC_LINE = re.compile(r"(?:\.{4,}|\s\.{2,}\s)|(?<=\D)\s+\d{1,3}$")


def _normalise_chars(text: str) -> str:
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    return _CONTROL.sub("", text)


def _key(line: str) -> str:
    """A line with digits masked, so 'Page 3 of 53' and 'Page 4 of 53' compare equal."""
    return " ".join(re.sub(r"\d+", "#", line).lower().split())


def _edge_indexes(lines: list[str]) -> set[int]:
    """Indexes of the first and last non-empty lines of a page (the header and footer zone).

    The zone is at most EDGE_LINES lines on each side and never more than a third of the page, so on a
    short page (a small table, a few lines) a line that merely repeats is not mistaken for a running
    header and stripped."""
    non_empty = [i for i, line in enumerate(lines) if line.strip()]
    n = min(EDGE_LINES, len(non_empty) // 3)
    if n == 0:
        return set()
    return set(non_empty[:n]) | set(non_empty[-n:])


def _repeated_keys(page_lines: list[list[str]]) -> set[str]:
    if len(page_lines) < MIN_PAGES_FOR_HEADERS:
        return set()
    counts: dict[str, int] = {}
    for lines in page_lines:
        # a table row (" | ") is data, never a running header, even when it repeats on every page
        seen = {_key(lines[i]) for i in _edge_indexes(lines) if lines[i].strip() and " | " not in lines[i]}
        for key in seen:
            counts[key] = counts.get(key, 0) + 1
    limit = max(MIN_PAGES_FOR_HEADERS, REPEAT_SHARE * len(page_lines))
    return {key for key, n in counts.items() if n >= limit and not _PAGE_NUMBER.match(key.replace("#", "1"))}


def _is_toc_page(lines: list[str]) -> bool:
    body = [line.strip() for line in lines if line.strip()]
    if len(body) < 12:
        return False
    # Table rows (" | ") often end in a small number too; they are data, never contents entries.
    tocish = sum(1 for line in body
                 if " | " not in line and _TOC_LINE.search(line) and len(line) < 100)
    return tocish / len(body) >= 0.6


def _clean_page_text(lines: list[str], repeated: set[str]) -> str:
    edges = _edge_indexes(lines)
    kept = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i in edges and stripped and (_key(stripped) in repeated or _PAGE_NUMBER.match(stripped)):
            continue
        kept.append(line.rstrip())
    text = "\n".join(kept)
    text = _HYPHEN_BREAK.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean(doc: Document) -> Document:
    """Return a cleaned copy of the document (the input is not modified)."""
    normalised = [_normalise_chars(page.text) for page in doc.pages]
    page_lines = [text.split("\n") for text in normalised]
    repeated = _repeated_keys(page_lines)
    pages = []
    for page, lines in zip(doc.pages, page_lines, strict=True):
        if len(doc.pages) >= MIN_PAGES_FOR_HEADERS and _is_toc_page(lines):
            continue
        pages.append(Page(source=page.source, page=page.page,
                          text=_clean_page_text(lines, repeated), ocr=page.ocr))
    return Document(source=doc.source, doc_version=doc.doc_version,
                    superseded=doc.superseded, pages=pages)
