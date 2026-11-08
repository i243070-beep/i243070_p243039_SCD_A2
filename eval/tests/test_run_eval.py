"""Tests for the evaluation functions: recall, citation validity, summary and the CI gate (section 5)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_eval as ev  # noqa: E402


def rel(source: str = "rules.pdf", section: str = "Academic Warning/Probation", page: int | None = 24) -> dict:
    return {"source": source, "section": section, "page": page}


def item(source: str = "rules.pdf", section: str = "Academic Warning/Probation", page: int | None = 24) -> dict:
    return {"source": source, "section": section, "page": page, "chunk_id": "c", "score": 0.9}


def test_section_matching_ignores_case_and_accepts_containment() -> None:
    assert ev.section_matches("Tuition Fee", "Tuition Fee (w.e.f. Fall 2026 semester)")
    assert ev.section_matches("LIBRARY SERVICES AND RULES", "VII - LIBRARY SERVICES AND RULES")
    assert not ev.section_matches("Attendance Requirements", "Academic Year")
    assert not ev.section_matches("", "anything")


def test_a_passage_matches_on_source_and_section_or_on_source_and_page() -> None:
    assert ev.passage_matches(rel(), item())
    assert ev.passage_matches(rel(section="Dress Code", page=12), item(section="VI - CODE OF CONDUCT", page=12))  # page fallback
    assert not ev.passage_matches(rel(), item(source="other.pdf"))                      # the source must always match
    assert not ev.passage_matches(rel(page=24), item(section="Elsewhere", page=25))


def test_recall_counts_each_relevant_passage_once_and_respects_k() -> None:
    relevant = [rel(section="Admission Fee", page=1), rel(section="Security Deposit", page=2)]
    retrieved = [item(section="Admission Fee", page=1), item(section="Noise", page=9), item(section="Security Deposit", page=2)]
    assert ev.recall_at_k(relevant, retrieved, 1) == 0.5
    assert ev.recall_at_k(relevant, retrieved, 3) == 1.0
    assert ev.recall_at_k([], retrieved, 5) is None                                       # a must-abstain question


def test_citation_validity_catches_a_fabricated_citation() -> None:
    response = {"retrieved": [item()], "citations": [rel(), rel(source="invented.pdf", section="9", page=1)]}
    assert ev.citation_validity(response) == 0.5
    assert ev.citation_validity({"retrieved": [item()], "citations": []}) is None


def row(qid: str, kind: str, relevant: list[dict], retrieved: list[dict], answered: bool, cites: list[dict],
        must_abstain: bool = False, avoid: list[dict] | None = None) -> dict:
    return {"id": qid, "type": kind, "must_abstain": must_abstain, "relevant": relevant, "avoid": avoid or [],
            "seconds": 1.0, "response": {"retrieved": retrieved, "citations": cites, "answered_from_context": answered}}


def test_summarise_reports_overall_by_type_abstention_and_superseded_leaks() -> None:
    rows = [
        row("q1", "ordinary", [rel()], [item()], True, [rel()]),
        row("q2", "exact", [rel(section="Attendance Requirements", page=10)], [item(section="Noise", page=3)], True, []),
        row("q3", "version", [rel()], [item(source="old.pdf"), item()], True, [rel()], avoid=[{"source": "old.pdf"}]),
        row("q4", "abstain", [], [item()], False, [], must_abstain=True),
    ]
    s = ev.summarise(rows)
    assert s["recall_at_5"] == pytest.approx((1 + 0 + 1) / 3, abs=1e-3)
    assert s["recall_at_5_by_type"]["exact"] == 0.0 and s["recall_at_5_by_type"]["ordinary"] == 1.0
    assert s["abstention_correctness"] == 1.0 and s["wrongly_answered"] == []
    assert s["citation_validity"] == 1.0
    assert s["superseded_leak_rate"] == 1.0                                               # old.pdf reached the top 5


def test_summarise_names_the_must_abstain_question_that_was_answered() -> None:
    s = ev.summarise([row("q18", "abstain", [], [item()], True, [], must_abstain=True)])
    assert s["abstention_correctness"] == 0.0 and s["wrongly_answered"] == ["q18"]


BASE = {"recall_at_5": 0.80, "abstention_correctness": 1.0, "citation_validity": 1.0}


def test_gate_passes_when_nothing_regressed() -> None:
    assert ev.gate({"recall_at_5": 0.78, "abstention_correctness": 1.0, "citation_validity": 0.97}, BASE) == []
    assert ev.gate({"recall_at_5": 0.5, "abstention_correctness": 1.0, "citation_validity": 1.0}, None) == []  # no baseline yet


def test_gate_fails_on_each_of_the_three_conditions() -> None:
    assert any("recall@5" in m for m in ev.gate({"recall_at_5": 0.70, "abstention_correctness": 1.0, "citation_validity": 1.0}, BASE))
    assert any("must-abstain" in m for m in ev.gate({"recall_at_5": 0.8, "abstention_correctness": 0.67,
                                                   "wrongly_answered": ["q18"], "citation_validity": 1.0}, BASE))
    assert any("citation validity" in m for m in ev.gate({"recall_at_5": 0.8, "abstention_correctness": 1.0, "citation_validity": 0.90}, BASE))


def test_the_recall_gate_allows_exactly_five_points_of_drop() -> None:
    assert ev.gate({"recall_at_5": 0.75, "abstention_correctness": 1.0, "citation_validity": 1.0}, BASE) == []
    assert ev.gate({"recall_at_5": 0.749, "abstention_correctness": 1.0, "citation_validity": 1.0}, BASE) != []
