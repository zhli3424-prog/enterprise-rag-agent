from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.retrieval import evidence_is_sufficient, search_knowledge


def evaluate(path: Path) -> dict:
    cases = json.loads(path.read_text(encoding="utf-8"))
    relevant_total = relevant_found = 0
    single_document_total = single_document_hit_at_1 = 0
    answerable_total = answerable_accepted = 0
    unanswerable_total = unanswerable_correct = 0
    acl_violations = 0
    details = []
    with SessionLocal() as session:
        users = {user.username: user for user in session.scalars(select(User))}
        for case in cases:
            user = users[case["username"]]
            hits = search_knowledge(session, user, case["question"], limit=5)
            titles = {hit.title for hit in hits}
            expected = set(case["expected_documents"])
            relevant_total += len(expected)
            relevant_found += len(expected & titles)
            if len(expected) == 1:
                single_document_total += 1
                single_document_hit_at_1 += int(bool(hits) and hits[0].title in expected)
            predicted_refusal = not evidence_is_sufficient(case["question"], hits)
            if expected:
                answerable_total += 1
                answerable_accepted += int(not predicted_refusal)
            if not expected:
                unanswerable_total += 1
                unanswerable_correct += int(predicted_refusal)
            allowed = {"all", user.department} if user.role != "admin" else {"all", "engineering", "finance"}
            acl_violations += sum(hit.department not in allowed for hit in hits)
            details.append(
                {
                    "id": case["id"],
                    "top_score": hits[0].score if hits else None,
                    "retrieved": [hit.title for hit in hits],
                    "expected": sorted(expected),
                    "predicted_refusal": predicted_refusal,
                }
            )
    return {
        "cases": len(cases),
        "recall_at_5": round(relevant_found / relevant_total, 4) if relevant_total else 1.0,
        "single_document_hit_at_1": round(single_document_hit_at_1 / single_document_total, 4)
        if single_document_total
        else 1.0,
        "answerable_acceptance": round(answerable_accepted / answerable_total, 4) if answerable_total else 1.0,
        "refusal_accuracy": round(unanswerable_correct / unanswerable_total, 4) if unanswerable_total else 1.0,
        "acl_violations": acl_violations,
        "semantic_threshold": settings.min_retrieval_score,
        "lexical_threshold": settings.min_lexical_coverage,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval, refusal and ACL behavior")
    parser.add_argument("--questions", type=Path, default=Path("eval/questions.json"))
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.questions)
    if not args.details:
        result.pop("details")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(
        result["recall_at_5"] < 0.8
        or result["answerable_acceptance"] < 0.8
        or result["refusal_accuracy"] < 0.8
        or result["acl_violations"] > 0
    )


if __name__ == "__main__":
    sys.exit(main())
