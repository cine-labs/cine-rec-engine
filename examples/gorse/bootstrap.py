"""Load demo catalog + seed user 42 (Nolan fan) for the Gorse example.

Runs after Postgres is healthy. Applies user_data after the catalog dump.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DSN = os.environ.get("DATABASE_URL", "postgresql://demo:demo@localhost:5432/demo")
USER_ID = int(os.environ.get("DEMO_USER_ID", "42"))

PROFILE = [
    dict(tmdb_id=155, media_type="movie", watched_sec=8000, duration_sec=8000, completed=True),
    dict(tmdb_id=77, media_type="movie", watched_sec=7000, duration_sec=7000, completed=True),
    dict(tmdb_id=157336, media_type="movie", watched_sec=8000, duration_sec=8000, completed=True),
]


async def main() -> None:
    # demo/seed.py runs asyncio.run at import — invoke as a process
    env = {
        **os.environ,
        "DATABASE_URL": DSN,
        "PYTHONPATH": str(ROOT) + (
            os.pathsep + os.environ["PYTHONPATH"]
            if os.environ.get("PYTHONPATH") else ""
        ),
    }
    subprocess.check_call(
        [sys.executable, str(ROOT / "demo" / "seed.py")],
        cwd=str(ROOT),
        env=env,
    )

    import asyncpg

    from cine_rec_engine import init_db, user_stats, user_vector

    pool = await asyncpg.create_pool(DSN)
    async with pool.acquire() as conn:
        result = await init_db.apply_schema(conn, full=True)
    print(f"schema: {result}")

    now = datetime.now(timezone.utc)
    for ev in PROFILE:
        await user_stats.record_event(
            pool,
            {**ev, "user_id": USER_ID, "watched_at": now - timedelta(days=1)},
        )
    await user_stats.refresh_user_stats(pool, USER_ID)
    try:
        await user_vector.build_user_vector(pool, USER_ID)
    except Exception as e:
        print(f"user vector skipped: {e}")
    await pool.close()
    print(f"seeded user {USER_ID} with {len(PROFILE)} watches")


if __name__ == "__main__":
    asyncio.run(main())
