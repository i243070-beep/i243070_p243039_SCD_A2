"""Starter tests for the week-1 dummy index. No Chroma server needed: a fake
client records what the indexer would have written."""

from __future__ import annotations

import math
from pathlib import Path

from pipeline.config import get_settings
from pipeline.dummy import DUMMY_DIM, DUMMY_MODEL, fake_vector, write_dummy_index
from pipeline.run import discover


class FakeCollection:
    def __init__(self, name: str, metadata: dict) -> None:
        self.name, self.metadata, self.rows = name, metadata, {}

    def add(self, ids, documents, embeddings, metadatas) -> None:
        for i, d, e, m in zip(ids, documents, embeddings, metadatas):
            self.rows[i] = (d, e, m)

    def count(self) -> int:
        return len(self.rows)


class FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def delete_collection(self, name: str) -> None:
        if name not in self.collections:
            raise ValueError("no such collection")
        del self.collections[name]

    def create_collection(self, name: str, metadata: dict) -> FakeCollection:
        self.collections[name] = FakeCollection(name, metadata)
        return self.collections[name]


def test_dummy_index_writes_three_chunks_and_records_the_model() -> None:
    client = FakeClient()
    assert write_dummy_index(get_settings(), client) == 3
    col = client.collections["rahbar"]
    assert col.metadata["embed_model"] == DUMMY_MODEL
    assert col.metadata["dimension"] == DUMMY_DIM
    for _doc, vector, meta in col.rows.values():
        assert len(vector) == DUMMY_DIM
        assert set(meta) == {"source", "section", "page", "doc_version", "superseded"}


def test_dummy_index_can_run_twice() -> None:
    client = FakeClient()
    write_dummy_index(get_settings(), client)
    assert write_dummy_index(get_settings(), client) == 3


def test_fake_vectors_are_deterministic_unit_vectors() -> None:
    a, b = fake_vector("same text"), fake_vector("same text")
    assert a == b
    assert math.isclose(sum(v * v for v in a), 1.0, rel_tol=1e-9)


def test_discover_reads_fixture_front_matter() -> None:
    fixtures = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
    found = {p.name: (version, old) for p, version, old in discover(str(fixtures))}
    assert found["academic-rules-2023.md"] == ("2023", True)
    assert found["academic-rules-2026.md"] == ("2026", False)
