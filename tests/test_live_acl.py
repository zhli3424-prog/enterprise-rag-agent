from __future__ import annotations

import os
import unittest

import httpx


@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", "set RUN_LIVE_TESTS=1 against a running stack")
class LiveAclTests(unittest.TestCase):
    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")

    def titles_for(self, username: str, password: str) -> set[str]:
        with httpx.Client(base_url=self.base_url) as client:
            response = client.post("/api/auth/login", json={"username": username, "password": password})
            response.raise_for_status()
            documents = client.get("/api/documents").json()["documents"]
            return {document["title"] for document in documents}

    def test_department_documents_are_isolated(self):
        engineering = self.titles_for("engineer", "Engineer123!")
        finance = self.titles_for("finance", "Finance123!")
        self.assertNotIn("财务报销制度", engineering)
        self.assertNotIn("研发发布规范", finance)
        self.assertIn("员工手册", engineering)
        self.assertIn("员工手册", finance)

    def test_direct_document_id_cannot_bypass_acl(self):
        with httpx.Client(base_url=self.base_url) as admin:
            admin.post("/api/auth/login", json={"username": "admin", "password": "Admin123!"}).raise_for_status()
            documents = admin.get("/api/documents").json()["documents"]
            finance_id = next(item["id"] for item in documents if item["title"] == "财务报销制度")
        with httpx.Client(base_url=self.base_url) as engineer:
            engineer.post("/api/auth/login", json={"username": "engineer", "password": "Engineer123!"}).raise_for_status()
            response = engineer.get(f"/api/documents/{finance_id}/status")
            self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
