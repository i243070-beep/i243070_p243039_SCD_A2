"""Stage 2: Clean. Remove artefacts without destroying structure."""

from __future__ import annotations

from .models import Document


def clean(doc: Document) -> Document:
    """Strip headers and footers that repeat on every page; keep headings and
    section boundaries, because chunking and citations depend on them."""
    # STARTER-TODO(3.1): implement cleaning, and record your rules in docs/PIPELINE.md.
    raise NotImplementedError("clean: see STARTER-TODO(3.1)")
