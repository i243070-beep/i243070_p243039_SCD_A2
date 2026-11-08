"""Stage 3: Chunk. Structure-aware, with overlap."""

from __future__ import annotations

from .models import Chunk, Document


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split on sections, then paragraphs, then sentences, keeping each chunk under
    `size` tokens, with `overlap` tokens shared between neighbours. Every chunk keeps
    the section heading it sits under, its page, doc_version and superseded."""
    # STARTER-TODO(3.1): implement chunking. Measure three (size, overlap) settings
    # against recall@5 and put the table in docs/PIPELINE.md.
    raise NotImplementedError("chunk: see STARTER-TODO(3.1)")
