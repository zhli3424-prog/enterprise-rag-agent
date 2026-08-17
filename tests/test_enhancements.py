from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from zipfile import ZipFile

from app.answer_evaluation import answer_point_coverage, score_answer, summarize_scores
from app.parsing import validate_upload_content
from app.worker import reset_stale_job


class AnswerEvaluationTests(unittest.TestCase):
    def case(self, expected_documents: list[str]) -> dict:
        return {"id": "q-test", "username": "engineer", "expected_documents": expected_documents}

    def key(self, points: list[str]) -> dict:
        return {"answer_points": points}

    def test_answer_point_bigram_coverage(self):
        coverage = answer_point_coverage(
            "核心协作时间为 10:00 至 16:00",
            "公司的核心协作时间是每天 10:00 到 16:00。[1]",
        )
        self.assertGreaterEqual(coverage, 0.55)
        self.assertLess(answer_point_coverage("每周二和周四", "每周一付款"), 0.55)

    def test_valid_and_invalid_citation_indices(self):
        sources = [{"title": "员工手册"}]
        valid = score_answer(
            self.case(["员工手册"]),
            self.key(["手机验证和密码重置"]),
            "完成手机验证和密码重置。[1]",
            sources,
            False,
        )
        invalid = score_answer(
            self.case(["员工手册"]),
            self.key(["手机验证和密码重置"]),
            "完成手机验证和密码重置。[2]",
            sources,
            False,
        )
        self.assertTrue(valid["correct"])
        self.assertFalse(invalid["correct"])
        self.assertEqual(invalid["invalid_citation_indices"], [2])

    def test_missing_and_cross_document_citations_fail(self):
        case = self.case(["员工手册", "信息安全规范"])
        key = self.key(["提前申请远程办公", "远程访问启用多因素认证"])
        sources = [{"title": "员工手册"}, {"title": "信息安全规范"}]
        missing = score_answer(
            case,
            key,
            "提前申请远程办公，远程访问启用多因素认证。",
            sources,
            False,
        )
        partial = score_answer(
            case,
            key,
            "提前申请远程办公，远程访问启用多因素认证。[1]",
            sources,
            False,
        )
        complete = score_answer(
            case,
            key,
            "提前申请远程办公。[1] 远程访问启用多因素认证。[2]",
            sources,
            False,
        )
        self.assertFalse(missing["correct"])
        self.assertFalse(partial["correct"])
        self.assertTrue(complete["correct"])

    def test_refusal_and_summary_metrics(self):
        refusal = score_answer(self.case([]), self.key([]), "知识库中未找到依据", [], True)
        answer = score_answer(
            self.case(["制度"]),
            self.key(["每周二和周四"]),
            "付款日是每周二和周四。[1]",
            [{"title": "制度"}],
            False,
        )
        summary = summarize_scores([refusal, answer])
        self.assertEqual(summary["whole_case_accuracy"], 1.0)
        self.assertEqual(summary["refusal_accuracy"], 1.0)
        self.assertEqual(summary["citation_index_validity"], 1.0)
        self.assertEqual(summary["citation_document_recall"], 1.0)


class WorkerRecoveryTests(unittest.TestCase):
    def job(self, locked_at: datetime | None) -> SimpleNamespace:
        return SimpleNamespace(
            status="processing",
            locked_at=locked_at,
            available_at=None,
            document=SimpleNamespace(status="processing"),
        )

    def test_fresh_job_is_not_recovered(self):
        now = datetime.now(timezone.utc)
        job = self.job(now - timedelta(seconds=899))
        self.assertFalse(reset_stale_job(job, now, 900))
        self.assertEqual(job.status, "processing")
        self.assertIsNotNone(job.locked_at)

    def test_stale_job_is_immediately_recoverable_and_unlocks(self):
        now = datetime.now(timezone.utc)
        job = self.job(now - timedelta(seconds=901))
        self.assertTrue(reset_stale_job(job, now, 900))
        self.assertEqual(job.status, "retry")
        self.assertEqual(job.document.status, "pending")
        self.assertEqual(job.available_at, now)
        self.assertIsNone(job.locked_at)


class UploadContentValidationTests(unittest.TestCase):
    def test_pdf_signature_and_markdown_text(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "valid.pdf"
            pdf.write_bytes(b"%PDF-1.7\nfixture")
            validate_upload_content(pdf, ".pdf")

            fake_pdf = root / "fake.pdf"
            fake_pdf.write_bytes(b"not a pdf")
            with self.assertRaisesRegex(ValueError, "not a PDF"):
                validate_upload_content(fake_pdf, ".pdf")

            markdown = root / "valid.md"
            markdown.write_text("# UTF-8 Markdown", encoding="utf-8")
            validate_upload_content(markdown, ".md")

            binary_markdown = root / "binary.md"
            binary_markdown.write_bytes(b"text\x00binary")
            with self.assertRaisesRegex(ValueError, "plain text"):
                validate_upload_content(binary_markdown, ".md")

    def test_docx_requires_word_package_structure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            docx = root / "valid.docx"
            with ZipFile(docx, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types />")
                archive.writestr("word/document.xml", "<document />")
            validate_upload_content(docx, ".docx")

            fake_docx = root / "fake.docx"
            with ZipFile(fake_docx, "w") as archive:
                archive.writestr("data.txt", "not word")
            with self.assertRaisesRegex(ValueError, "not a DOCX"):
                validate_upload_content(fake_docx, ".docx")


if __name__ == "__main__":
    unittest.main()
