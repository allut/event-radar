"""Read-only stats over llm_calls: completion_tokens percentiles per provider and
task (successful rows) and failure_reason counts per provider.

Reads the read-only Neon role URL from LLM_STATS_DATABASE_URL, set in the
environment or in backend/.env (never DATABASE_URL, so it cannot hit the wrong DB
by accident). Two aggregate queries, no writes.

Run from backend/ with the venv active:
    python scripts/llm_calls_stats.py            # last 7 days
    python scripts/llm_calls_stats.py --days 30
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.constants.llm import LLM_STATS_DATABASE_URL_ENV, LLM_STATS_DEFAULT_DAYS
from app.db import mask_db_url

BACKEND_DIR = Path(__file__).parent.parent
LIBPQ_ONLY_PARAMS = {"channel_binding"}

TOKENS_SQL = text(
    """
    SELECT provider, task, count(*) AS n,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY completion_tokens) AS p50,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY completion_tokens) AS p95,
           max(completion_tokens) AS max_tokens
    FROM llm_calls
    WHERE created_at >= now() - make_interval(days => :days)
      AND failure_reason IS NULL
      AND completion_tokens IS NOT NULL
    GROUP BY provider, task
    ORDER BY provider, task
    """
)

FAILURES_SQL = text(
    """
    SELECT provider, failure_reason, count(*) AS n
    FROM llm_calls
    WHERE created_at >= now() - make_interval(days => :days)
      AND failure_reason IS NOT NULL
    GROUP BY provider, failure_reason
    ORDER BY provider, n DESC
    """
)


def normalize_url(url: str) -> str:
    """Accept a Neon-style postgres:// URL; asyncpg wants its own driver prefix, ssl=,
    and rejects libpq-only params such as channel_binding."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
    parts = urlsplit(url)
    query = [
        ("ssl" if k == "sslmode" else k, v)
        for k, v in parse_qsl(parts.query)
        if k not in LIBPQ_ONLY_PARAMS
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def print_table(title: str, headers: list[str], rows: list[list[object]]) -> None:
    print(f"\n{title}")
    if not rows:
        print("  (no rows)")
        return
    cells = [[str(c) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) for i, h in enumerate(headers)]
    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for r in cells:
        print("  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)))


async def main(days: int) -> int:
    url = os.environ.get(LLM_STATS_DATABASE_URL_ENV) or dotenv_values(
        BACKEND_DIR / ".env"
    ).get(LLM_STATS_DATABASE_URL_ENV)
    if not url:
        print(f"{LLM_STATS_DATABASE_URL_ENV} is not set.", file=sys.stderr)
        return 1
    url = normalize_url(url)
    print(f"DB: {mask_db_url(url)}  window: last {days} day(s)")

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            tokens = (await conn.execute(TOKENS_SQL, {"days": days})).all()
            failures = (await conn.execute(FAILURES_SQL, {"days": days})).all()
    finally:
        await engine.dispose()

    print_table(
        "completion_tokens, successful calls",
        ["provider", "task", "count", "p50", "p95", "max"],
        [[r.provider, r.task, r.n, round(r.p50), round(r.p95), r.max_tokens] for r in tokens],
    )
    print_table(
        "failures by reason",
        ["provider", "failure_reason", "count"],
        [[r.provider, r.failure_reason, r.n] for r in failures],
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stats over llm_calls (read-only).")
    parser.add_argument("--days", type=int, default=LLM_STATS_DEFAULT_DAYS)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.days)))
