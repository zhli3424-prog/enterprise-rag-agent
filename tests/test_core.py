from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.parsing import SourcePart, chunk_parts, chunk_text, parse_document
from app.retrieval import SearchHit, evidence_is_sufficient, lexical_coverage
from app.security import create_session, hash_password, read_session, verify_password


class SecurityTests(unittest.TestCase):
    def test_password_hash_and_verify(self):
        encoded = hash_password("StrongPass123!")
        self.assertNotIn("StrongPass123!", encoded)
        self.assertTrue(verify_password("StrongPass123!", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))

    def test_signed_session_rejects_tampering_and_expiration(self):
        token = create_session(42, "a-secret-value", 60)
        self.assertEqual(read_session(token, "a-secret-value"), 42)
        self.assertIsNone(read_session(token + "x", "a-secret-value"))
        expired = create_session(42, "a-secret-value", -1)
        self.assertIsNone(read_session(expired, "a-secret-value"))


class ParsingTests(unittest.TestCase):
    def test_chunking_has_bounded_size_and_overlap(self):
        text = "第一段。" * 100 + "\n\n" + "第二段。" * 100
        chunks = chunk_text(text, target_size=120, overlap=20)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(0 < len(chunk) <= 120 for chunk in chunks))
        self.assertEqual(chunks[0][-20:], chunks[1][:20])

    def test_chunk_ordinals_are_global(self):
        chunks = chunk_parts([SourcePart(1, "甲" * 80), SourcePart(2, "乙" * 80)], target_size=50, overlap=10)
        self.assertEqual([chunk.ordinal for chunk in chunks], list(range(len(chunks))))
        self.assertEqual({chunk.page for chunk in chunks}, {1, 2})

    def test_markdown_utf8(self):
        path = Path(__file__).resolve().parents[1] / "sample_docs" / "员工手册.md"
        parts = parse_document(path)
        self.assertEqual(parts[0].page, 1)
        self.assertIn("员工手册", parts[0].text)

    def test_docx_uses_chunk_reference_instead_of_fake_page_number(self):
        path = Path(__file__).resolve().parent / "fixtures" / "知识库接入操作指南.docx"
        if not path.exists():
            self.skipTest("run scripts/create_test_fixtures.py first")
        parts = parse_document(path)
        self.assertIsNone(parts[0].page)
        self.assertIn("DOCX-READY-2026", parts[0].text)


class EvidenceTests(unittest.TestCase):
    def hit(self, content: str, score: float = 0.6) -> SearchHit:
        return SearchHit(1, 1, "制度", "制度.md", "all", 1, 0, content, score)

    def test_lexical_guard_accepts_grounded_and_rejects_unrelated_evidence(self):
        question = "生产发布的灰度比例和观察时间是什么？"
        grounded = self.hit("生产发布先进行百分之十灰度，观察三十分钟后再继续。")
        unrelated = self.hit("员工食堂每周更新菜单，班车按固定线路运行。")
        self.assertGreater(lexical_coverage(question, grounded.content), 0.18)
        self.assertTrue(evidence_is_sufficient(question, [grounded]))
        self.assertFalse(evidence_is_sufficient(question, [unrelated]))


class EvaluationDataTests(unittest.TestCase):
    def test_answer_key_covers_all_questions_and_matches_expected_documents(self):
        root = Path(__file__).resolve().parents[1]
        questions = json.loads((root / "eval" / "questions.json").read_text(encoding="utf-8"))
        answers = json.loads((root / "eval" / "answer_key.json").read_text(encoding="utf-8"))
        by_id = {answer["id"]: answer for answer in answers}
        self.assertEqual({case["id"] for case in questions}, set(by_id))
        for case in questions:
            sources = by_id[case["id"]]["expected_sources"]
            self.assertEqual({source["document"] for source in sources}, set(case["expected_documents"]))
            self.assertTrue(all(source["page"] and source["section"] for source in sources))
            if case["expected_documents"]:
                self.assertTrue(by_id[case["id"]]["answer_points"])


if __name__ == "__main__":
    unittest.main()
