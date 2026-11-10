"""Sync cine-rec Postgres catalog + watches into Gorse.

Item IDs use the shared contract ``{tmdb_id}:{media_type}`` (e.g. ``155:movie``).
Gorse user IDs are numeric strings matching cine-rec integer user_ids.

    python sync_to_gorse.py \\
        --dsn postgresql://demo:demo@db:5432/demo \\
        --gorse http://gorse-server:8087

Requires: asyncpg (catalog), urllib (Gorse REST).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable, List


def _post_json(base: str, path: str, body: Any) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _chunks(items: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _fetch(dsn: str, sql: str) -> list:
    """Plain asyncpg — avoid importing cine_rec_engine (heavy deps)."""
    import asyncpg

    pool = await asyncpg.create_pool(dsn)
    try:
        async with pool.acquire() as conn:
            return await conn.fetch(sql)
    finally:
        await pool.close()


async def load_items(dsn: str) -> list[dict]:
    rows = await _fetch(
        dsn,
        """SELECT id AS tmdb_id, media_type,
                  COALESCE(title_en, title, '') AS title
           FROM tmdb_media""",
    )
    return [
        {
            "ItemId": f"{r['tmdb_id']}:{r['media_type']}",
            "Comment": r["title"] or "",
            "Categories": [r["media_type"]],
            "Labels": {"tmdb_id": r["tmdb_id"], "media_type": r["media_type"]},
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "IsHidden": False,
        }
        for r in rows
    ]


async def load_feedback(dsn: str) -> list[dict]:
    rows = await _fetch(
        dsn,
        """SELECT user_id, tmdb_id, media_type, last_watched_at
           FROM user_title_stats
           WHERE w_item > 0 OR max_ratio >= 0.75""",
    )
    out = []
    for r in rows:
        ts = r["last_watched_at"] or datetime.now(timezone.utc)
        if hasattr(ts, "strftime"):
            stamp = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            stamp = str(ts)
        out.append({
            "FeedbackType": "watch",
            "UserId": str(r["user_id"]),
            "ItemId": f"{r['tmdb_id']}:{r['media_type']}",
            "Timestamp": stamp,
            "Value": 1,
        })
    return out


async def load_users(dsn: str) -> list[dict]:
    rows = await _fetch(
        dsn,
        "SELECT DISTINCT user_id FROM user_title_stats",
    )
    return [{"UserId": str(r["user_id"]), "Labels": {}, "Comment": ""} for r in rows]


async def main_async(dsn: str, gorse: str) -> None:
    items = await load_items(dsn)
    users = await load_users(dsn)
    feedback = await load_feedback(dsn)

    n_items = 0
    for batch in _chunks(items, 200):
        res = _post_json(gorse, "/api/items", batch)
        n_items += int(res.get("RowAffected") or len(batch))

    n_users = 0
    for batch in _chunks(users, 200):
        res = _post_json(gorse, "/api/users", batch)
        n_users += int(res.get("RowAffected") or len(batch))

    n_fb = 0
    for batch in _chunks(feedback, 200):
        res = _post_json(gorse, "/api/feedback", batch)
        n_fb += int(res.get("RowAffected") or len(batch))

    print(
        f"synced to {gorse}: items≈{n_items}/{len(items)} "
        f"users≈{n_users}/{len(users)} feedback≈{n_fb}/{len(feedback)}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dsn", required=True)
    p.add_argument("--gorse", default="http://localhost:8087")
    args = p.parse_args()
    try:
        import asyncio

        asyncio.run(main_async(args.dsn, args.gorse))
    except urllib.error.URLError as e:
        print(f"gorse unreachable: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
