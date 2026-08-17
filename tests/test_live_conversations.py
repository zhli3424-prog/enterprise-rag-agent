from __future__ import annotations

import json
import os
import unittest

import httpx


@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", "set RUN_LIVE_TESTS=1 against a running stack")
class LiveConversationTests(unittest.TestCase):
    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")

    def login(self, username: str, password: str) -> httpx.Client:
        client = httpx.Client(base_url=self.base_url, timeout=180)
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        response.raise_for_status()
        return client

    def test_history_is_owner_only_and_preserves_messages_and_citations(self):
        engineer = self.login("engineer", "Engineer123!")
        try:
            conversation_id = None
            with engineer.stream(
                "POST",
                "/api/chat/stream",
                json={"question": "公司每天的核心协作时间是什么时候？", "conversation_id": None},
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("data: ") and conversation_id is None:
                        payload = json.loads(line[6:])
                        if "conversation_id" in payload:
                            conversation_id = payload["conversation_id"]
            self.assertIsNotNone(conversation_id)

            conversations = engineer.get("/api/conversations").json()["conversations"]
            self.assertIn(conversation_id, {item["id"] for item in conversations})
            detail = engineer.get(f"/api/conversations/{conversation_id}")
            detail.raise_for_status()
            messages = detail.json()["messages"]
            self.assertEqual([message["role"] for message in messages[-2:]], ["user", "assistant"])
            self.assertTrue(messages[-1]["citations"])
            self.assertLessEqual(messages[-2]["created_at"], messages[-1]["created_at"])
        finally:
            engineer.close()

        finance = self.login("finance", "Finance123!")
        try:
            self.assertEqual(finance.get(f"/api/conversations/{conversation_id}").status_code, 404)
            own_ids = {item["id"] for item in finance.get("/api/conversations").json()["conversations"]}
            self.assertNotIn(conversation_id, own_ids)
        finally:
            finance.close()


if __name__ == "__main__":
    unittest.main()
