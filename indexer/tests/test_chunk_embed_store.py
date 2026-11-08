"""Tests for stages 3, 4 and 5: chunk, embed and store."""

from __future__ import annotations

import httpx
import pytest

from pipeline.chunk import _is_heading, amplification, chunk
from pipeline.config import IndexerSettings
from pipeline.embed import BATCH_SIZE, embed
from pipeline.models import Chunk, Document, Page
from pipeline.store import store


def _settings(**over: object) -> IndexerSettings:
    base = dict(embed_model="nomic-embed-text", chroma_host="x", chroma_port=8000, collection="rahbar",
                corpus_dir="/c", chunk_size=40, chunk_overlap=5, ollama_url="http://ollama:11434")
    base.update(over)
    return IndexerSettings(**base)  # type: ignore[arg-type]


def _doc(text: str, page: int = 1) -> Document:
    return Document(source="rules.pdf", doc_version="2026-06", superseded=False,
                    pages=[Page(source="rules.pdf", page=page, text=text)])


@pytest.mark.parametrize("line,expected", [
    ("Academic Warning/Probation", True),
    ("1. Attendance", True),
    ("## 2. Academic warning", True),
    ("VII - LIBRARY SERVICES AND RULES", True),
    ("5.4 Minimum CGPA required to avoid academic warning is 2.00 for all undergraduate programs.", False),
    ("1.1 A student must attend at least 80 percent of the lectures of each course.", False),
    ("Fee | Rs. 12,000", False),
    ("This is an ordinary sentence that ends with a full stop.", False),
])
def test_heading_detection(line: str, expected: bool) -> None:
    assert _is_heading(line) is expected


def test_chunks_carry_section_page_and_metadata_and_start_with_the_heading() -> None:
    text = ("Attendance Requirements\n1.21 Students must keep 100% attendance in lectures.\n\n"
            "Academic Warning/Probation\n5.4 The minimum CGPA to avoid warning is 2.00.")
    chunks = chunk(_doc(text, page=10), 40, 5)
    assert [c.section for c in chunks] == ["Attendance Requirements", "Academic Warning/Probation"]
    assert all(c.page == 10 and c.doc_version == "2026-06" and c.superseded is False for c in chunks)
    assert chunks[0].text.startswith("Attendance Requirements")


def test_no_chunk_exceeds_size_and_neighbours_overlap_only_inside_a_section() -> None:
    words = " ".join(f"w{i}" for i in range(200))
    text = f"Long Section\n{words}\n\nNext Section\nshort text here for the next one"
    chunks = chunk(_doc(text), 40, 5)
    assert all(len(c.text.split()) <= 40 for c in chunks)
    first_section = [c for c in chunks if c.section == "Long Section"]
    assert len(first_section) > 1
    prev_tail = first_section[0].text.split()[-5:]
    assert first_section[1].text.split()[:5] == prev_tail          # overlap inside the section
    nxt = next(c for c in chunks if c.section == "Next Section")
    assert "w199" not in nxt.text                                    # none across sections


def test_ids_are_stable_and_unique() -> None:
    text = "A Heading\n" + " ".join(f"w{i}" for i in range(150))
    a, b = chunk(_doc(text), 40, 5), chunk(_doc(text), 40, 5)
    assert [c.id for c in a] == [c.id for c in b]
    assert len({c.id for c in a}) == len(a)
    assert a[0].id.startswith("rules.pdf::p1::c")


def test_a_table_is_not_cut_in_the_middle_of_a_row() -> None:
    rows = "\n".join(f"Row {i} | value {i} | extra words here" for i in range(30))
    chunks = chunk(_doc("Fees\n" + rows), 30, 0)
    for c in chunks:
        for line in c.text.split("\n"):
            if line.startswith("Row"):
                assert line.endswith("extra words here")


def test_invalid_size_or_overlap_raises() -> None:
    for size, overlap in [(0, 0), (10, 10), (10, -1), (10, 11)]:
        with pytest.raises(ValueError):
            chunk(_doc("x y z"), size, overlap)


def test_amplification_is_at_least_one_with_overlap() -> None:
    doc = _doc("Heading\n" + " ".join(f"w{i}" for i in range(300)))
    assert amplification(doc, chunk(doc, 40, 5)) >= 1.0
    assert amplification(_doc(""), []) == 0.0


def _ollama(handler):  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_embed_uses_the_pinned_model_prefix_and_batches() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3] for _ in body["input"]]})

    texts = [f"chunk {i}" for i in range(BATCH_SIZE + 3)]
    vectors = embed(texts, _settings(), client=_ollama(handler))
    assert len(vectors) == len(texts) and all(len(v) == 3 for v in vectors)
    assert len(seen) == 2                                              # two batches
    assert all(b["model"] == "nomic-embed-text" for b in seen)
    assert seen[0]["input"][0] == "search_document: chunk 0"


def test_embed_empty_input_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    assert embed([], _settings(), client=_ollama(handler)) == []


def test_embed_fails_clearly_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pipeline.embed.time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    with pytest.raises(RuntimeError, match="after 3 attempts"):
        embed(["x"], _settings(), client=_ollama(handler))
    assert calls["n"] == 3


class _FakeCollection:
    def __init__(self, client: _FakeClient, name: str, metadata: dict) -> None:
        self.client, self.name, self.metadata, self.ids = client, name, metadata, []

    def add(self, ids, documents, embeddings, metadatas) -> None:  # type: ignore[no-untyped-def]
        self.ids.extend(ids)

    def count(self) -> int:
        return len(self.ids)

    def modify(self, name: str) -> None:
        self.client.collections[name] = self.client.collections.pop(self.name)
        self.name = name


class _FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, _FakeCollection] = {}

    def create_collection(self, name: str, metadata: dict) -> _FakeCollection:
        self.collections[name] = _FakeCollection(self, name, metadata)
        return self.collections[name]

    def get_collection(self, name: str) -> _FakeCollection:
        return self.collections[name]

    def delete_collection(self, name: str) -> None:
        del self.collections[name]


def _chunks(n: int) -> list[Chunk]:
    return [Chunk(id=f"d::p1::c{i:04d}", text=f"text {i}", source="d.pdf", section="S", page=1,
                  doc_version="2026", superseded=False) for i in range(n)]


def test_store_records_pin_and_swaps_in_the_new_index() -> None:
    client = _FakeClient()
    old = client.create_collection("rahbar", {"index_id": "old"})
    old.ids = ["stale"]
    count = store(_chunks(3), [[0.1, 0.2]] * 3, _settings(), client=client)
    assert count == 3
    assert list(client.collections) == ["rahbar"]                      # build and old names are gone
    live = client.collections["rahbar"]
    assert live.ids == ["d::p1::c0000", "d::p1::c0001", "d::p1::c0002"]
    assert live.metadata["embed_model"] == "nomic-embed-text"
    assert live.metadata["dimension"] == 2
    assert live.metadata["index_id"] != "old"


def test_store_refuses_empty_or_inconsistent_input_and_keeps_the_old_index() -> None:
    client = _FakeClient()
    client.create_collection("rahbar", {"index_id": "old"})
    with pytest.raises(ValueError):
        store([], [], _settings(), client=client)
    with pytest.raises(ValueError):
        store(_chunks(2), [[0.1]], _settings(), client=client)
    with pytest.raises(ValueError):
        store(_chunks(2), [[0.1], [0.1, 0.2]], _settings(), client=client)
    assert list(client.collections) == ["rahbar"]
    assert client.collections["rahbar"].metadata["index_id"] == "old"
