from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx


DOCUMENTS = {
    "员工手册.md": ("员工手册", "all"),
    "研发发布规范.md": ("研发发布规范", "engineering"),
    "财务报销制度.md": ("财务报销制度", "finance"),
    "信息安全规范.md": ("信息安全规范", "all"),
    "客户支持服务标准.md": ("客户支持服务标准", "all"),
}


def main() -> int:
    base_url = os.getenv("APP_BASE_URL", "http://api:8000")
    root = Path(__file__).resolve().parents[1] / "sample_docs"
    with httpx.Client(base_url=base_url, timeout=60) as client:
        response = client.post("/api/auth/login", json={"username": "admin", "password": "Admin123!"})
        response.raise_for_status()
        for filename, (title, department) in DOCUMENTS.items():
            path = root / filename
            with path.open("rb") as stream:
                response = client.post(
                    "/api/documents",
                    data={"title": title, "department": department},
                    files={"file": (filename, stream, "text/markdown")},
                )
            if response.status_code == 409:
                print(f"SKIP duplicate: {filename}")
            else:
                response.raise_for_status()
                print(f"QUEUED: {filename}")
    print("Worker is indexing documents. Check the document page until every status is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

