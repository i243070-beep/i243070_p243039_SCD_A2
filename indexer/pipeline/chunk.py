"""Stage 3: Chunk. Structure-aware, with overlap.

Unit: a "token" is one whitespace-separated word (chunk size and overlap are counted in words;
docs/PIPELINE.md reports the real token amplification). Order of splitting: sections first, then
paragraphs, then sentences, then (only for a sentence longer than the limit) words.

Choices worth defending:
 * A chunk never exceeds `size` words, overlap included.
 * Overlap is carried only between chunks of the SAME section. Carrying the tail of one section into
   the next would make a chunk answer a question about the wrong heading.
 * The heading line is the first line of a section's first chunk, so the section is visible in the text
   that gets embedded, and a table is never cut in the middle of a row.
 * Chunk ids are stable: `<source>::p<page>::c<n>` with a per-document counter, so re-indexing the same
   document gives the same ids.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Chunk, Document

PREAMBLE = "Preamble"
_SMALL_WORDS = {"of", "and", "the", "to", "in", "for", "a", "an", "on", "with", "from", "by",
                "or", "&", "/", "at", "as", "vs"}
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class _Block:
    text: str
    page: int


@dataclass
class _Section:
    name: str
    blocks: list[_Block] = field(default_factory=list)


def _tokens(text: str) -> int:
    return len(text.split())


def _is_heading(line: str) -> bool:
    """A short line that names a section: Markdown heading, numbered title, ALL CAPS or Title Case."""
    s = line.strip()
    if not s or len(s) > 90 or " | " in s:
        return False
    if re.match(r"^#{1,6}\s+\S", s):
        return True
    if re.match(r"^\d+(?:\.\d+){1,3}\.?\s", s):  # 5.4 Minimum CGPA ... : a clause, not a heading
        return False
    words = s.split()
    numbered = re.match(r"^(\d{1,2})[.)]\s+(.+)$", s)
    if numbered:
        rest = numbered.group(2)
        return (len(rest.split()) <= 10 and rest[:1].isupper()
                and not rest.rstrip().endswith((".", ",", ";", ":")))
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 3 and all(c.isupper() for c in letters) and len(words) <= 12:
        return True  # ALL CAPS, also "VII - LIBRARY SERVICES AND RULES"
    if s.endswith((".", ",", ";", ":", "?")) or s[-1].isdigit() or len(words) > 8:
        return False
    if not s[0].isupper():
        return False
    capitalised = sum(1 for w in words if w[:1].isupper() or w.lower() in _SMALL_WORDS)
    return capitalised / len(words) >= 0.75 and (len(words) >= 2 or len(s) >= 5)


def _heading_name(line: str) -> str:
    return re.sub(r"^#{1,6}\s*", "", line.strip()).strip()


def _paragraph_blocks(text: str, page: int) -> list[tuple[bool, _Block]]:
    """Split a page into paragraphs and headings. A run of table rows is one block."""
    blocks: list[tuple[bool, _Block]] = []
    para: list[str] = []
    table: list[str] = []

    def flush_para() -> None:
        if para:
            blocks.append((False, _Block(" ".join(para).strip(), page)))
            para.clear()

    def flush_table() -> None:
        if table:
            blocks.append((False, _Block("\n".join(table), page)))
            table.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            flush_para()
            flush_table()
        elif " | " in stripped:
            flush_para()
            table.append(stripped)
        elif _is_heading(stripped):
            flush_para()
            flush_table()
            blocks.append((True, _Block(_heading_name(stripped), page)))
        else:
            flush_table()
            para.append(stripped)
    flush_para()
    flush_table()
    return blocks


def _sections(doc: Document) -> list[_Section]:
    sections: list[_Section] = [_Section(PREAMBLE)]
    for page in doc.pages:
        for is_heading, block in _paragraph_blocks(page.text, page.page):
            if is_heading:
                sections.append(_Section(block.text, [_Block(block.text, block.page)]))
            elif block.text:
                sections[-1].blocks.append(block)
    return [s for s in sections if any(b.text for b in s.blocks)]


def _split_words(text: str, limit: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + limit]) for i in range(0, len(words), limit)]


def _pack_pieces(pieces: list[str], limit: int, joiner: str) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    used = 0
    for piece in pieces:
        n = _tokens(piece)
        if current and used + n > limit:
            out.append(joiner.join(current))
            current, used = [], 0
        current.append(piece)
        used += n
    if current:
        out.append(joiner.join(current))
    return out


def _fit(block: _Block, limit: int) -> list[_Block]:
    """Split one block so that every piece is at most `limit` words."""
    if _tokens(block.text) <= limit:
        return [block]
    if "\n" in block.text and " | " in block.text:  # a table: split between rows only
        pieces = _pack_pieces(block.text.split("\n"), limit, "\n")
    else:
        sentences: list[str] = []
        for sentence in _SENTENCE_END.split(block.text):
            sentences.extend(_split_words(sentence, limit) if _tokens(sentence) > limit else [sentence])
        pieces = _pack_pieces(sentences, limit, " ")
    return [_Block(piece, block.page) for piece in pieces]


def _chunk_section(section: _Section, size: int, overlap: int) -> list[tuple[str, int]]:
    """(text, page) pairs for one section."""
    cap = size - overlap
    blocks = list(section.blocks)
    if len(blocks) >= 2 and blocks[0].text == section.name and _tokens(blocks[1].text) + _tokens(blocks[0].text) <= cap:
        # keep the heading with its first paragraph so they are never separated
        blocks[0:2] = [_Block(blocks[0].text + "\n" + blocks[1].text, blocks[0].page)]
    units: list[_Block] = []
    for block in blocks:
        units.extend(_fit(block, cap))
    chunks: list[tuple[str, int]] = []
    current: list[_Block] = []
    used = 0
    for unit in units:
        n = _tokens(unit.text)
        if current and used + n > cap:
            chunks.append(("\n\n".join(b.text for b in current), current[0].page))
            current, used = [], 0
        current.append(unit)
        used += n
    if current:
        chunks.append(("\n\n".join(b.text for b in current), current[0].page))
    if overlap:
        with_overlap = [chunks[0]] if chunks else []
        for previous, (text, page) in zip(chunks, chunks[1:], strict=False):
            tail = " ".join(previous[0].split()[-overlap:])
            with_overlap.append((tail + "\n\n" + text, page))
        chunks = with_overlap
    return chunks


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split on sections, then paragraphs, then sentences, keeping each chunk at or under `size`
    words, with `overlap` words shared between neighbouring chunks of the same section. Every chunk
    keeps the section heading it sits under, its page, doc_version and superseded."""
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError(f"need 0 <= overlap < size, got size={size} overlap={overlap}")
    result: list[Chunk] = []
    for section in _sections(doc):
        for text, page in _chunk_section(section, size, overlap):
            if _tokens(text) < 3:
                continue
            result.append(Chunk(
                id=f"{doc.source}::p{page}::c{len(result):04d}",
                text=text, source=doc.source, section=section.name, page=page,
                doc_version=doc.doc_version, superseded=doc.superseded,
            ))
    return result


def amplification(doc: Document, chunks: list[Chunk]) -> float:
    """Storage amplification: tokens stored in chunks divided by tokens in the document."""
    original = sum(_tokens(page.text) for page in doc.pages)
    if original == 0:
        return 0.0
    return sum(_tokens(c.text) for c in chunks) / original
