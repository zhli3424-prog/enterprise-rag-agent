from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from app.answer_evaluation import score_answer, summarize_scores
from app.config import settings

DEMO_PASSWORDS = {
    "admin": "Admin123!",
    "engineer": "Engineer123!",
    "finance": "Finance123!",
}


def parse_ids(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def load_cases(questions_path: Path, answers_path: Path, selected_ids: set[str] | None) -> list[tuple[dict, dict]]:
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    answers = {
        item["id"]: item
        for item in json.loads(answers_path.read_text(encoding="utf-8"))
    }
    cases = [(case, answers[case["id"]]) for case in questions if selected_ids is None or case["id"] in selected_ids]
    found = {case["id"] for case, _ in cases}
    missing = (selected_ids or set()) - found
    if missing:
        raise ValueError(f"unknown question ids: {', '.join(sorted(missing))}")
    return cases


def ask(client: httpx.Client, question: str) -> dict[str, Any]:
    answer_parts: list[str] = []
    sources: list[dict[str, Any]] = []
    done: dict[str, Any] = {}
    current_event = "message"
    data_lines: list[str] = []

    def handle_event() -> None:
        nonlocal sources, done, current_event, data_lines
        if not data_lines:
            current_event = "message"
            return
        payload = json.loads("".join(data_lines))
        if current_event == "sources":
            sources = payload
        elif current_event == "delta":
            answer_parts.append(payload.get("text", ""))
        elif current_event == "done":
            done = payload
        elif current_event == "error":
            raise RuntimeError(payload.get("message", "SSE answer failed"))
        current_event = "message"
        data_lines = []

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"question": question, "conversation_id": None},
        timeout=180,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                handle_event()
            elif line.startswith("event: "):
                current_event = line[7:]
            elif line.startswith("data: "):
                data_lines.append(line[6:])
        handle_event()
    return {
        "answer": "".join(answer_parts).strip(),
        "sources": sources,
        "refused": bool(done.get("refused")),
        "metrics": done.get("metrics", {}),
    }


def llm_judge(case: dict, key: dict, answer: str, model: str) -> dict[str, Any]:
    client = OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是严格的企业知识库答案评测员。只判断回答是否覆盖标准答案要点，"
                    "不得使用外部知识。输出 JSON：{\"pass\":true或false,\"reason\":\"简短原因\"}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": case["question"],
                        "answer_points": key["answer_points"],
                        "answer": answer,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        temperature=0,
    )
    text = response.choices[0].message.content or ""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("judge did not return JSON")
    return json.loads(match.group())


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate real SSE answers and citations")
    parser.add_argument("--questions", type=Path, default=Path("eval/questions.json"))
    parser.add_argument("--answer-key", type=Path, default=Path("eval/answer_key.json"))
    parser.add_argument("--ids", help="Comma-separated question ids; default is all")
    parser.add_argument("--base-url", default=os.getenv("APP_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument("--llm-judge", action="store_true")
    parser.add_argument("--judge-model", default=settings.deepseek_model)
    parser.add_argument("--output", type=Path, help="Optionally save the complete JSON result")
    args = parser.parse_args()

    cases = load_cases(args.questions, args.answer_key, parse_ids(args.ids))
    clients: dict[str, httpx.Client] = {}
    results = []
    try:
        for case, key in cases:
            username = case["username"]
            if username not in clients:
                client = httpx.Client(base_url=args.base_url)
                login = client.post(
                    "/api/auth/login",
                    json={"username": username, "password": DEMO_PASSWORDS[username]},
                )
                login.raise_for_status()
                clients[username] = client
            response = ask(clients[username], case["question"])
            result = score_answer(
                case,
                key,
                response["answer"],
                response["sources"],
                response["refused"],
                args.threshold,
            )
            result["question"] = case["question"]
            result["metrics"] = response["metrics"]
            if args.llm_judge:
                try:
                    result["llm_judge"] = llm_judge(case, key, response["answer"], args.judge_model)
                except Exception as exc:
                    result["llm_judge"] = {"error": str(exc)}
            results.append(result)
            print(f"{case['id']}: {'PASS' if result['correct'] else 'FAIL'}", file=sys.stderr)
    finally:
        for client in clients.values():
            client.close()

    output = {
        "summary": summarize_scores(results, args.threshold),
        "details": [
            {key: value for key, value in result.items() if key != "_counts"}
            for result in results
        ],
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
