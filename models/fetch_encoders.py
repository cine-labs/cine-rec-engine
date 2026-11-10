#!/usr/bin/env python3
"""Fetch the published tuned encoders and embed your catalog.

Three commands, no engine install required beyond the ``encoders``
extra (``pip install "cine-rec-engine[encoders]"``):

  python models/fetch_encoders.py list
  python models/fetch_encoders.py fetch [--dest DIR] [SPACE ...]   # explicit
  python models/fetch_encoders.py embed --dsn postgresql://... --space e5_enrich

``embed`` downloads the encoder on demand when it is not already on
disk (pinned revision, sha256-verified); an encoder that IS on disk is
never re-fetched. Set ``CINE_REC_AUTO_FETCH=0`` or pass ``--no-fetch``
to keep air-gapped installs fully offline. ``fetch`` is the explicit
variant (same verification) for pre-seeding machines.
``embed`` encodes every catalog title into ``tmdb_media.<column>`` (the
column is created when missing), using the canonical text template from
``models/README.md``; the optional ``tmdb_cinematic`` enrichment table
upgrades the template when present and is skipped when not. Afterwards
``CINE_REC_EMBEDDING=<space>`` (or ``rec_model=<space>`` per request)
selects the space end to end.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parent / "MANIFEST.json"
DEFAULT_DEST = Path(
    os.getenv("CINE_REC_ENCODERS_DIR", Path.home() / ".cache" / "cine-rec-engine" / "encoders")
)


def _load_manifest() -> dict:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _entries(names: list[str] | None) -> list[dict]:
    enc = _load_manifest()["encoders"]
    if not names:
        return enc
    by_space = {e["space"]: e for e in enc}
    missing = [n for n in names if n not in by_space]
    if missing:
        raise SystemExit(
            f"unknown space(s): {', '.join(missing)} — "
            f"manifest has: {', '.join(by_space)}"
        )
    return [by_space[n] for n in names]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_list(_args: argparse.Namespace) -> int:
    print(f"{'space':<14} {'dim':>4}  {'languages':<14} {'repo':<40} column")
    for e in _entries(None):
        print(
            f"{e['space']:<14} {e['dim']:>4}  {e['languages']:<14} "
            f"{e['repo']:<40} {e['column']}"
        )
    return 0


def _download(entry: dict, dest: Path) -> None:
    """Fetch the pinned revision and verify the sha256 before use."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise SystemExit(
            "huggingface-hub is required: pip install huggingface-hub"
        )
    print(f"[{entry['space']}] {entry['repo']}@{entry['revision']} -> {dest}")
    snapshot_download(
        repo_id=entry["repo"],
        revision=entry["revision"],
        local_dir=str(dest),
    )
    weights = dest / "model.safetensors"
    if not weights.exists():
        raise SystemExit(f"[{entry['space']}] download incomplete: no model.safetensors")
    digest = _sha256(weights)
    if digest != entry["sha256"]:
        raise SystemExit(
            f"[{entry['space']}] sha256 mismatch: got {digest}, "
            f"manifest pins {entry['sha256']} — refusing to use the file"
        )
    print(f"[{entry['space']}] sha256 verified")


def auto_fetch_enabled() -> bool:
    """CINE_REC_AUTO_FETCH=0/false/no/off disables on-demand downloads."""
    return (os.getenv("CINE_REC_AUTO_FETCH", "1").strip().lower()
            not in {"0", "false", "no", "off"})


def ensure_encoder(entry: dict, dest_root: Path, auto: bool | None = None) -> Path:
    """Local dir for a published encoder — downloading it when missing.

    Default behavior: fetch on demand (pinned revision, sha256-verified).
    An encoder already on disk is never re-fetched silently; updates are
    deliberate (`fetch` again after a manifest bump). Air-gapped installs
    set CINE_REC_AUTO_FETCH=0 (or pass auto=False) and get an actionable
    error instead of network access.
    """
    dest = Path(dest_root) / entry["space"]
    if (dest / "model.safetensors").exists():
        return dest
    if auto is None:
        auto = auto_fetch_enabled()
    if not auto:
        raise SystemExit(
            f"[{entry['space']}] not fetched and auto-download disabled "
            f"(CINE_REC_AUTO_FETCH=0) — run: python {Path(__file__).name} "
            f"fetch {entry['space']}"
        )
    _download(entry, dest)
    return dest


def cmd_fetch(args: argparse.Namespace) -> int:
    for e in _entries(args.spaces):
        _download(e, Path(args.dest) / e["space"])
    return 0


# ---- catalog embedding ------------------------------------------------


def canonical_text(
    title: str,
    year: int | None,
    overview: str | None,
    cinematic: dict | None,
) -> str:
    """The canonical encoder input (see models/README.md).

    Full template when cinematic tags are available, Title+Overview
    fallback otherwise — byte-compatible with both so a partially
    enriched catalog embeds uniformly.
    """
    head = f"Title: {title} ({year if year else '-'})"
    ov = (overview or "").strip() or "-"
    if cinematic and cinematic.get("emotional_arc"):
        return (
            f"{head}\n"
            f"Emotional arc: {', '.join(cinematic['emotional_arc'])}\n"
            f"Pacing: {cinematic.get('pacing') or '-'}\n"
            f"Narrative: {cinematic.get('narrative_complexity') or '-'}\n"
            f"Sub-genres: {', '.join(cinematic.get('sub_genres') or ['-'])}\n"
            f"Experience: {cinematic.get('viewing_experience') or '-'}\n"
            f"Overview: {ov}"
        )
    return f"{head}\nOverview: {ov}"


async def _embed_rows(conn, entry: dict, model, batch: int, limit: int | None) -> int:
    """Read titles, encode in batches, write the vector column."""
    from pgvector.asyncpg import register_vector

    await register_vector(conn)
    table = None
    from cine_rec_engine import tables

    table = tables.name("tmdb_media")
    cin_table = tables.name("tmdb_cinematic")

    # Optional enrichment: use the columns the user's table actually has
    # (the engine only requires narrative_complexity/pacing/emotional_arc;
    # sub_genres/viewing_experience extend the template when present).
    cin_cols = {
        r["column_name"]
        for r in await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = $1
            """,
            cin_table,
        )
    }
    wanted = [
        "emotional_arc",
        "pacing",
        "narrative_complexity",
        "sub_genres",
        "viewing_experience",
    ]
    have = [c for c in wanted if c in cin_cols]
    join_sql = (
        f"LEFT JOIN {cin_table} c ON c.media_id = m.id AND c.media_type = m.media_type"
        if have
        else ""
    )
    cin_select = ", ".join(f"c.{col}" for col in have)

    prefix = entry.get("passage_prefix") or ""
    col = entry["column"]
    limit_sql = f"LIMIT {int(limit)}" if limit else ""

    rows = await conn.fetch(
        f"""
        SELECT m.id, m.media_type,
               COALESCE(NULLIF(m.title, ''), m.original_title) AS title,
               m.overview,
               EXTRACT(YEAR FROM COALESCE(m.release_date, m.first_air_date))::int AS yr
               {', ' + cin_select if cin_select else ''}
        FROM {table} m
        {join_sql}
        WHERE COALESCE(m.overview, '') <> ''
        ORDER BY m.vote_count DESC NULLS LAST
        {limit_sql}
        """
    )
    if not rows:
        print("no titles with an overview — nothing to embed")
        return 0

    total = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        texts = [
            prefix
            + canonical_text(
                r["title"], r["yr"], r["overview"],
                {k: r.get(k) for k in have} if have else None,
            )
            for r in chunk
        ]
        vecs = model.encode(texts, batch_size=batch, show_progress_bar=False)
        await conn.executemany(
            f"UPDATE {table} SET {col} = $1 WHERE id = $2 AND media_type = $3",
            [
                (v.tolist(), r["id"], r["media_type"])
                for r, v in zip(chunk, vecs)
            ],
        )
        total += len(chunk)
        print(f"  embedded {total}/{len(rows)}")
    return total


async def _run_embed(args: argparse.Namespace) -> int:
    try:
        import asyncpg
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit(
            f"missing dependency ({exc.name}) — "
            f'pip install "cine-rec-engine[encoders]"'
        )

    entries = _entries([args.space])
    entry = entries[0]
    # On-demand download by default (already-on-disk skips the network);
    # --no-fetch / CINE_REC_AUTO_FETCH=0 keeps air-gapped installs offline.
    dest = ensure_encoder(entry, Path(args.dest), auto=not args.no_fetch)

    model = SentenceTransformer(str(dest))

    conn = await asyncpg.connect(args.dsn)
    try:
        # Degrade, never fail: create the target column only when the
        # extension and table are ready; a missing pgvector extension is
        # an explicit, actionable error.
        ext = await conn.fetchval("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
        if ext == 0:
            raise SystemExit(
                "pgvector extension not installed in this database — "
                "CREATE EXTENSION vector; first (the KNN channel is optional)"
            )
        table = None
        from cine_rec_engine import tables

        table = tables.name("tmdb_media")
        await conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
            f"{entry['column']} vector({entry['dim']})"
        )
        if args.dry_run:
            print(f"dry run: would embed into {table}.{entry['column']}")
            return 0
        n = await _embed_rows(conn, entry, model, args.batch, args.limit)
        print(
            f"done: {n} vectors in {table}.{entry['column']} — "
            f"set CINE_REC_EMBEDDING={entry['space']} to serve from it"
        )
        return 0
    finally:
        await conn.close()


def cmd_embed(args: argparse.Namespace) -> int:
    return asyncio.run(_run_embed(args))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show the published encoders")

    p_fetch = sub.add_parser("fetch", help="download pinned encoders from Hugging Face")
    p_fetch.add_argument("spaces", nargs="*", help="space names (default: all)")
    p_fetch.add_argument("--dest", default=str(DEFAULT_DEST))
    p_fetch.set_defaults(fn=cmd_fetch)

    p_embed = sub.add_parser("embed", help="embed the catalog into a space's column")
    p_embed.add_argument("--dsn", default=os.getenv("CINE_REC_DSN") or os.getenv("DATABASE_URL"))
    p_embed.add_argument("--space", required=True)
    p_embed.add_argument("--dest", default=str(DEFAULT_DEST))
    p_embed.add_argument("--batch", type=int, default=64)
    p_embed.add_argument("--limit", type=int, default=None, help="embed only the top-N titles")
    p_embed.add_argument("--no-fetch", action="store_true",
                         help="never download; fail if the encoder is not already local "
                              "(same as CINE_REC_AUTO_FETCH=0)")
    p_embed.add_argument("--dry-run", action="store_true")
    p_embed.set_defaults(fn=cmd_embed)

    args = ap.parse_args(argv)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "fetch":
        return cmd_fetch(args)
    if not getattr(args, "dsn", None):
        ap.error("--dsn or CINE_REC_DSN/DATABASE_URL is required")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
