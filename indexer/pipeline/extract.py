"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page."""

from __future__ import annotations

from .models import Document


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    Detect pages with no text layer and OCR them; mark those pages ocr=True.
    The OCR libraries need system packages in your Dockerfile (tesseract-ocr,
    poppler-utils), not only pip packages.
    """
    # STARTER-TODO(3.1): implement extraction. Report in docs/PIPELINE.md which
    # documents needed OCR, one before-and-after table, and what you could not recover.
    raise NotImplementedError("extract: see STARTER-TODO(3.1)")
