from __future__ import annotations

import os
import time
import unittest
from pathlib import Path

import httpx


FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_NAMES = {
    "知识库接入操作指南.docx",
    "procurement-approval-flow.pdf",
    "scan-only-no-text.pdf",
    "format-validation.md",
}


@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", "set RUN_LIVE_TESTS=1 against a running stack")
class LiveDocumentLifecycleTests(unittest.TestCase):
    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")

    def setUp(self) -> None:
        self.client = httpx.Client(base_url=self.base_url, timeout=30)
        response = self.client.post("/api/auth/login", json={"username": "admin", "password": "Admin123!"})
        response.raise_for_status()
        self.document_ids: set[int] = set()
        self._remove_leftover_fixtures()

    def tearDown(self) -> None:
        for document_id in self.document_ids:
            self.client.delete(f"/api/documents/{document_id}")
        self.client.close()

    def _remove_leftover_fixtures(self) -> None:
        response = self.client.get("/api/documents")
        response.raise_for_status()
        for document in response.json()["documents"]:
            if document["filename"] in FIXTURE_NAMES:
                self.client.delete(f"/api/documents/{document['id']}").raise_for_status()

    def upload(self, filename: str, title: str, media_type: str) -> httpx.Response:
        path = FIXTURE_DIR / filename
        with path.open("rb") as source:
            return self.client.post(
                "/api/documents",
                data={"title": title, "department": "all"},
                files={"file": (filename, source, media_type)},
            )

    def wait_for(self, document_id: int, expected: set[str], timeout: float = 45) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.client.get(f"/api/documents/{document_id}/status")
            response.raise_for_status()
            document = response.json()["document"]
            if document["status"] in expected:
                return document
            time.sleep(1)
        self.fail(f"document {document_id} did not reach {sorted(expected)} within {timeout}s")

    def test_supported_formats_duplicate_and_delete(self):
        cases = [
            ("知识库接入操作指南.docx", "DOCX 格式联调", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("procurement-approval-flow.pdf", "PDF 格式联调", "application/pdf"),
            ("format-validation.md", "Markdown 格式联调", "text/markdown"),
        ]
        for filename, title, media_type in cases:
            with self.subTest(filename=filename):
                response = self.upload(filename, title, media_type)
                self.assertEqual(response.status_code, 202, response.text)
                document_id = response.json()["document"]["id"]
                self.document_ids.add(document_id)
                document = self.wait_for(document_id, {"ready"})
                self.assertGreater(document["chunk_count"], 0)

        duplicate = self.upload("procurement-approval-flow.pdf", "重复 PDF", "application/pdf")
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        deleted_id = next(iter(self.document_ids))
        self.client.delete(f"/api/documents/{deleted_id}").raise_for_status()
        self.document_ids.remove(deleted_id)
        self.assertEqual(self.client.get(f"/api/documents/{deleted_id}/status").status_code, 404)

    def test_scan_only_pdf_fails_and_can_be_retried(self):
        response = self.upload("scan-only-no-text.pdf", "扫描件失败联调", "application/pdf")
        self.assertEqual(response.status_code, 202, response.text)
        document_id = response.json()["document"]["id"]
        self.document_ids.add(document_id)

        document = self.wait_for(document_id, {"failed"})
        self.assertIn("no extractable text", (document["error"] or "").lower())

        retry = self.client.post(f"/api/documents/{document_id}/retry")
        self.assertEqual(retry.status_code, 202, retry.text)
        status = self.client.get(f"/api/documents/{document_id}/status").json()["document"]["status"]
        self.assertIn(status, {"pending", "processing"})

    def test_extension_spoof_is_rejected_before_indexing(self):
        response = self.client.post(
            "/api/documents",
            data={"title": "伪装 PDF", "department": "all"},
            files={"file": ("fake.pdf", b"MZ-not-a-pdf", "application/pdf")},
        )
        self.assertEqual(response.status_code, 415, response.text)
        self.assertIn("not a PDF", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
