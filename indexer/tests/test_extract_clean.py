"""Tests for stages 1 and 2: extract and clean. No real PDF and no OCR engine are needed."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from pipeline import extract as extract_module
from pipeline.clean import clean
from pipeline.extract import _html_to_text, _needs_ocr, _table_to_text, extract
from pipeline.models import Document, Page


def test_needs_ocr_for_empty_and_tiny_text() -> None:
    assert _needs_ocr("")
    assert _needs_ocr("  12  ")
    assert not _needs_ocr("A normal paragraph with real words in it.")


def test_table_rows_use_pipe_separator_and_skip_empty_cells() -> None:
    table = [["Program", "Fee"], ["BS", "Rs. 12,000"], [None, None], ["PhD", ""]]
    assert _table_to_text(table) == "Program | Fee\nBS | Rs. 12,000\nPhD"


def test_markdown_front_matter_is_removed(tmp_path: Path) -> None:
    path = tmp_path / "rules.md"
    path.write_text("---\ndoc_version: 2026\n---\n# Rules\n\n1. Attendance\n", encoding="utf-8")
    doc = extract(str(path), "2026", False)
    assert doc.source == "rules.md"
    assert len(doc.pages) == 1
    assert "doc_version" not in doc.pages[0].text
    assert doc.pages[0].text.startswith("# Rules")


def test_html_skips_chrome_and_keeps_headings_and_table_rows() -> None:
    html = ("<html><head><title>x</title></head><body>"
            "<header><nav><a>Home</a><a>Admissions</a></nav></header>"
            "<div class='content'><h2>Tuition Fee</h2><p>Payable before each semester.</p>"
            "<table><tr><th>Program</th><th>Fee</th></tr><tr><td>BS</td><td>Rs. 12,000</td></tr></table>"
            "</div><footer>Copyright</footer></body></html>")
    text = _html_to_text(html)
    assert "Home" not in text and "Copyright" not in text
    assert "## Tuition Fee" in text
    assert "Program | Fee" in text and "BS | Rs. 12,000" in text


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "data.xyz"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        extract(str(path), "1", False)


def test_pdf_page_without_text_layer_is_ocred(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def find_tables(self) -> list:
            return []

        def extract_text(self) -> str:
            return self._text

        def flush_cache(self) -> None:
            return None

    class FakePdf:
        pages = [FakePage("A page that has a real text layer with enough words."), FakePage("")]

        def __enter__(self) -> FakePdf:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    fake = types.ModuleType("pdfplumber")
    fake.open = lambda path: FakePdf()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)
    monkeypatch.setattr(extract_module, "_ocr_page", lambda path, n: f"OCR text of page {n}")
    doc = extract("scan.pdf", "2023-08", True)
    assert [p.ocr for p in doc.pages] == [False, True]
    assert doc.pages[1].text == "OCR text of page 2"
    assert doc.superseded is True and doc.doc_version == "2023-08"


def _doc(*page_texts: str) -> Document:
    pages = [Page(source="d.pdf", page=i + 1, text=t) for i, t in enumerate(page_texts)]
    return Document(source="d.pdf", doc_version="2026", superseded=False, pages=pages)


def test_clean_removes_repeated_header_and_page_numbers_but_keeps_headings() -> None:
    pages = [f"NATIONAL UNIVERSITY\nAttendance Requirements\n1.21 Students must attend page {i}.\nPage {i} of 9"
             for i in range(1, 5)]
    pages[0] = ("NATIONAL UNIVERSITY\nA heading that appears once\nAttendance Requirements\n"
                "1.21 Students must attend page 1.\nPage 1 of 9")
    out = clean(_doc(*pages))
    first = out.pages[0].text
    assert "NATIONAL UNIVERSITY" not in first
    assert "Page 1 of 9" not in first
    assert "1.21 Students must attend" in first          # clause numbers are never stripped
    assert "A heading that appears once" in first


def test_clean_joins_hyphenated_words_but_not_ranges() -> None:
    out = clean(_doc("The exami-\nnation covers weeks 5-6 only.", "x", "y"))
    assert "examination" in out.pages[0].text
    assert "5-6" in out.pages[0].text


def test_clean_normalises_ligatures_and_collapses_blank_lines() -> None:
    out = clean(_doc("The ﬁnal exam\n\n\n\n\nnext paragraph", "x", "y"))
    text = out.pages[0].text
    assert "final exam" in text
    assert "\n\n\n" not in text


def test_clean_keeps_table_rows() -> None:
    out = clean(_doc("Fee | Rs. 12,000\nAdmission | Rs. 30,000", "x", "y"))
    assert "Fee | Rs. 12,000" in out.pages[0].text


def test_clean_drops_a_table_of_contents_page_but_not_a_table_page() -> None:
    toc = "\n".join(f"Section title {chr(64 + i)} {i}" for i in range(1, 16))  # "Section title A 1"
    table = "\n".join(f"Professor | {i} | 2 | 26" for i in range(1, 16))
    out = clean(_doc(toc, table, "Normal text page with enough words to stay."))
    kept = [p.page for p in out.pages]
    assert 1 not in kept          # the contents page is gone
    assert 2 in kept              # a table page ending in numbers is data, not contents


def test_clean_does_not_strip_a_line_that_repeats_on_short_pages() -> None:
    """On a short page every line is near an edge; a repeated table header must still survive."""
    pages = [f"Department | Total\nComputer Science | {i}\nSoftware Engineering | {i + 1}" for i in range(4)]
    out = clean(_doc(*pages))
    assert all("Department | Total" in p.text for p in out.pages)


def test_clean_does_not_modify_its_input() -> None:
    doc = _doc("Header\ntext\nHeader", "Header\ntext 2\nHeader", "Header\ntext 3\nHeader")
    before = [p.text for p in doc.pages]
    clean(doc)
    assert [p.text for p in doc.pages] == before
