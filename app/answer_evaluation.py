from __future__ import annotations

import re
from typing import Any

CITATION_PATTERN = re.compile(r"\[(\d+)]")


def chinese_bigrams(value: str) -> set[str]:
    normalized = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", value.lower()))
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def answer_point_coverage(answer_point: str, answer: str) -> float:
    expected = chinese_bigrams(answer_point)
    return len(expected & chinese_bigrams(answer)) / len(expected) if expected else 0.0


def score_answer(
    case: dict[str, Any],
    answer_key: dict[str, Any],
    answer: str,
    sources: list[dict[str, Any]],
    refused: bool,
    threshold: float = 0.55,
) -> dict[str, Any]:
    points = answer_key["answer_points"]
    point_coverages = [answer_point_coverage(point, answer) for point in points]
    point_hits = [coverage >= threshold for coverage in point_coverages]

    citation_indices = [int(value) for value in CITATION_PATTERN.findall(answer)]
    valid_indices = [index for index in citation_indices if 1 <= index <= len(sources)]
    invalid_indices = [index for index in citation_indices if index < 1 or index > len(sources)]
    cited_documents = {
        sources[index - 1].get("title") or sources[index - 1].get("document")
        for index in valid_indices
    }
    cited_documents.discard(None)
    expected_documents = set(case["expected_documents"])
    cited_expected = expected_documents & cited_documents

    if expected_documents:
        correct = (
            not refused
            and all(point_hits)
            and bool(citation_indices)
            and not invalid_indices
            and cited_expected == expected_documents
        )
    else:
        correct = refused

    return {
        "id": case["id"],
        "username": case["username"],
        "answer": answer,
        "refused": refused,
        "expected_documents": sorted(expected_documents),
        "answer_points": [
            {
                "text": point,
                "coverage": round(coverage, 4),
                "hit": hit,
            }
            for point, coverage, hit in zip(points, point_coverages, point_hits, strict=True)
        ],
        "citation_indices": citation_indices,
        "invalid_citation_indices": invalid_indices,
        "cited_documents": sorted(cited_documents),
        "sources": sources,
        "correct": correct,
        "_counts": {
            "points": len(points),
            "point_hits": sum(point_hits),
            "citation_refs": len(citation_indices),
            "valid_citation_refs": len(valid_indices),
            "expected_documents": len(expected_documents),
            "cited_expected_documents": len(cited_expected),
            "unanswerable": int(not expected_documents),
            "correct_refusal": int(not expected_documents and refused),
        },
    }


def summarize_scores(results: list[dict[str, Any]], threshold: float = 0.55) -> dict[str, Any]:
    counts = {
        key: sum(result["_counts"][key] for result in results)
        for key in (
            "points",
            "point_hits",
            "citation_refs",
            "valid_citation_refs",
            "expected_documents",
            "cited_expected_documents",
            "unanswerable",
            "correct_refusal",
        )
    }

    def ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 1.0

    return {
        "cases": len(results),
        "answer_point_threshold": threshold,
        "answer_point_recall": ratio(counts["point_hits"], counts["points"]),
        "whole_case_accuracy": ratio(sum(result["correct"] for result in results), len(results)),
        "refusal_accuracy": ratio(counts["correct_refusal"], counts["unanswerable"]),
        "citation_index_validity": ratio(counts["valid_citation_refs"], counts["citation_refs"]),
        "citation_document_recall": ratio(
            counts["cited_expected_documents"],
            counts["expected_documents"],
        ),
    }
