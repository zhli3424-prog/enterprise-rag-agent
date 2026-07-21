from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.database import SessionLocal
from app.models import QueryTrace


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize real RAG traces without inventing performance numbers")
    parser.add_argument("--limit", type=int, default=500, help="Most recent traces to include")
    args = parser.parse_args()
    with SessionLocal() as session:
        traces = list(
            session.scalars(select(QueryTrace).order_by(QueryTrace.created_at.desc()).limit(max(1, args.limit)))
        )
    totals = [trace.total_ms for trace in traces if trace.total_ms is not None]
    first_tokens = [trace.first_token_ms for trace in traces if trace.first_token_ms is not None]
    retrievals = [trace.retrieval_ms for trace in traces if trace.retrieval_ms is not None]
    result = {
        "trace_count": len(traces),
        "failure_rate": round(sum(bool(trace.error) for trace in traces) / len(traces), 4) if traces else None,
        "refusal_rate": round(sum(trace.refused for trace in traces) / len(traces), 4) if traces else None,
        "latency_ms": {
            "retrieval_p50": percentile(retrievals, 0.50),
            "retrieval_p95": percentile(retrievals, 0.95),
            "first_token_p50": percentile(first_tokens, 0.50),
            "first_token_p95": percentile(first_tokens, 0.95),
            "total_p50": percentile(totals, 0.50),
            "total_p95": percentile(totals, 0.95),
        },
        "tokens": {
            "prompt": sum(trace.prompt_tokens for trace in traces),
            "completion": sum(trace.completion_tokens for trace in traces),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
