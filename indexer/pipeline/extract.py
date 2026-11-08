"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page.

What this stage must not lose (section 3.1): structure. So it keeps, per page,
the text in reading order, turns every table into rows of ` | `-separated cells
(a naive extractor jumbles the columns), and OCRs pages that have no text layer.
Headers, footers and table-of-contents pages are removed later, by `clean`.
"""

from __future__ import annotations

import logging
import os
import re
from html.parser import HTMLParser
from typing import Any

from .models import Document, Page

# pdfminer warns "CropBox missing from /Page" once per page of many university PDFs; it is harmless
# and would drown the Job's JSON log.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

OCR_DPI = 200
MIN_TEXT_CHARS = 20  # fewer non-space characters than this: the page has no usable text layer


def _needs_ocr(text: str) -> bool:
    """True when a page has (almost) no text layer, i.e. it is an image."""
    return len(text.strip()) < MIN_TEXT_CHARS


def _table_to_text(table: list[list[str | None]]) -> str:
    """One table row per line, cells joined by ` | `. Empty rows and empty cells are skipped."""
    rows = []
    for row in table:
        cells = [" ".join((cell or "").split()) for cell in row]
        if any(cells):
            rows.append(" | ".join(cell for cell in cells if cell))
    return "\n".join(rows)


def _ocr_page(path: str, number: int) -> str:
    """OCR one page. One page at a time, then freed: OCR memory is what limits the Job."""
    import pytesseract
    from pdf2image import convert_from_path

    images = convert_from_path(path, dpi=OCR_DPI, first_page=number, last_page=number)
    try:
        return str(pytesseract.image_to_string(images[0])) if images else ""
    finally:
        for image in images:
            image.close()


def _page_text_and_tables(page: Any) -> tuple[str, str]:
    """Text outside the tables, and the tables as rows (so no table cell is counted twice)."""
    try:
        tables = page.find_tables()
    except Exception:  # a malformed page must not stop the whole document
        tables = []
    if not tables:
        return str(page.extract_text() or ""), ""
    try:
        outside = page
        for table in tables:
            outside = outside.outside_bbox(table.bbox)
        text = str(outside.extract_text() or "")
        rows = "\n\n".join(t for t in (_table_to_text(table.extract()) for table in tables) if t)
        return text, rows
    except Exception:
        return str(page.extract_text() or ""), ""


def _extract_pdf(path: str, source: str) -> list[Page]:
    import pdfplumber

    pages: list[Page] = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text, rows = _page_text_and_tables(page)
            if _needs_ocr(text + rows):
                pages.append(Page(source=source, page=number,
                                  text=_ocr_page(path, number).strip(), ocr=True))
            else:
                body = text.strip() + ("\n\n" + rows if rows else "")
                pages.append(Page(source=source, page=number, text=body.strip(), ocr=False))
            page.flush_cache()  # keep memory flat on an 85-page report
    return pages


def _strip_front_matter(text: str) -> str:
    """Remove a leading block between two `---` lines (the CI fixtures use it for doc_version)."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:]).lstrip("\n")
    return text


class _TextHTMLParser(HTMLParser):
    """HTML to text. Skips page chrome (header, nav, footer, scripts), keeps headings as
    Markdown headings, list items as bullets and table rows as ` | `-separated cells."""

    SKIP = {"script", "style", "noscript", "head", "header", "nav", "footer", "aside"}
    BLOCK = {"p", "div", "br", "section", "article", "ul", "ol", "table", "form", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buf: list[str] = []
        self._skip_depth = 0
        self._heading = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        self._buf = []
        if not text:
            return
        if self._heading:
            text = "#" * self._heading + " " + text
        self.lines.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "tr":
            self._flush()
            self._row = []
        elif tag in {"td", "th"}:
            self._cell = []
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self._heading = int(tag[1])
        elif tag == "li":
            self._flush()
            self._buf.append("- ")
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            cell = " ".join("".join(self._cell).split())
            if cell:
                self._row.append(cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.lines.append(" | ".join(self._row))
            self._row = None
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self._heading = 0
        elif tag in self.BLOCK or tag == "li":
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._cell is not None:
            self._cell.append(data)
        else:
            self._buf.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextHTMLParser()
    parser.feed(html)
    parser._flush()
    return "\n".join(parser.lines)


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    PDFs: text per page with pdfplumber; tables as rows; a page with no text layer is OCR'd
    (tesseract, 200 dpi) and marked ocr=True. Markdown, text and HTML give one page.
    """
    source = os.path.basename(path)
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".pdf":
        pages = _extract_pdf(path, source)
    elif suffix in {".md", ".txt", ".html", ".htm"}:
        with open(path, encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
        text = _html_to_text(raw) if suffix in {".html", ".htm"} else _strip_front_matter(raw)
        pages = [Page(source=source, page=1, text=text.strip(), ocr=False)]
    else:
        raise ValueError(f"unsupported document type: {suffix!r} ({source})")
    return Document(source=source, doc_version=doc_version, superseded=superseded, pages=pages)
