# cine-rec-engine + Gorse

Run cine-rec as a [Gorse External Recommender](https://gorse.io/docs/concepts/recommenders/external).
Gorse executes a QuickJS script that `fetch`es cine-rec; there is no
`?recommender=` query param — the script is selected in config via
`ranker.recommenders = ["external/cine_rec"]`.

## ID contract

| System | Format |
|---|---|
| Item | `{tmdb_id}:{media_type}` — e.g. `155:movie`, `1396:tv` |
| User | numeric string — `"42"` in Gorse ↔ `42` in cine-rec |

Items returned by cine-rec must already exist in Gorse (run `sync`).

## Quick start

```bash
cd examples/gorse
docker compose up -d --build
docker compose run --rm bootstrap   # demo catalog + user 42
docker compose run --rm sync        # Postgres → Gorse items/feedback
```

Verify:

```bash
# rich personalized row
curl -s 'localhost:8000/v1/for-user/42?limit=5' | head -c 400; echo

# Gorse adapter — raw ID array
curl -s 'localhost:8000/v1/gorse/recommend/42?limit=5'; echo

# through Gorse (config wires external/cine_rec)
curl -s 'localhost:8087/api/recommend/42?n=5'; echo
```

Dashboard: http://localhost:8088 · Gorse API docs: http://localhost:8087/apidocs

Tear down: `docker compose down -v`

## What each file does

| File | Role |
|---|---|
| `docker-compose.yml` | Postgres (catalog) + MySQL (Gorse) + cine-rec + Gorse master/server/worker |
| `gorse-config.toml` | `[[recommend.external]] name = "cine_rec"` + `ranker.type = "none"` |
| `bootstrap.py` | Load demo titles + seed user `42` |
| `sync_to_gorse.py` | Push items / users / watch feedback into Gorse |

## Production notes

- Point the External script at your cine-rec URL (compose uses `http://cine-rec:8000`).
- If you set `CINE_REC_API_KEYS`, add an `X-API-Key` header inside the script.
- Prefer the published image: `ghcr.io/cine-labs/cine-rec-engine:latest` instead of `build: ../..`.
- Full write-up: [docs/gorse.md](../../docs/gorse.md).
