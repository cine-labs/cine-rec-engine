# Integrating with Gorse

Use cine-rec-engine as a content-based [External
Recommender](https://gorse.io/docs/concepts/recommenders/external) inside
[Gorse](https://gorse.io/). Collaborative filtering stays in Gorse;
personalized content ranking comes from your TMDB mirror.

## Contracts

| | Format |
|---|---|
| **Item ID** | `{tmdb_id}:{media_type}` — e.g. `155:movie`, `1396:tv` |
| **User ID** | Numeric string in Gorse (`"42"`) mapping 1:1 to cine-rec’s integer `user_id` |

TMDB ids collide across media (`movie 155 ≠ tv 155`), so bare numeric item
IDs are not safe.

## Endpoint

```http
GET /v1/gorse/recommend/{user_id}?limit=100
```

Returns a **raw JSON array** of item ID strings:

```json
["27205:movie", "49026:movie", "1396:tv"]
```

Cold start (no watches / watchlist) → `[]`. Same auth gate as other
`/v1/*` routes (`CINE_REC_API_KEYS`).

The rich personalized payload remains at `/v1/for-user/{user_id}`
(`results`, `reason`, `seeds`, optional `why`).

## Gorse config

Gorse does **not** call a fixed URL and has **no** `?recommender=` query
param. It runs a QuickJS script that injects `user_id` and must return a
string ID array. Wire the name into the ranker:

```toml
[[recommend.external]]
name = "cine_rec"
script = """
const response = fetch(
  "http://cine-rec:8000/v1/gorse/recommend/" + user_id + "?limit=100"
);
if (!response.ok) {
  throw new Error(response.status + " " + response.body);
}
JSON.parse(response.body)
"""

[recommend.ranker]
type = "none"
recommenders = ["external/cine_rec"]
```

Clients keep calling:

```bash
curl 'http://gorse:8087/api/recommend/42?n=10'
```

If cine-rec requires an API key, add `"X-API-Key": "…"` to the script’s
`fetch` headers (Gorse scripts no longer expose process `env`).

## Sync items into Gorse

IDs that are not registered in Gorse are useless to API clients. Push
catalog rows and watches with the example script:

```bash
python examples/gorse/sync_to_gorse.py \
  --dsn postgresql://user:pw@db/cine \
  --gorse http://localhost:8087
```

## Worked example

[`examples/gorse/`](../examples/gorse/) — Docker Compose with Postgres,
cine-rec, MySQL, and Gorse master/server/worker (pinned `0.5.11`):

```bash
cd examples/gorse
docker compose up -d --build
docker compose run --rm bootstrap
docker compose run --rm sync
curl 'localhost:8000/v1/gorse/recommend/42?limit=5'
curl 'localhost:8087/api/recommend/42?n=5'
```

Published image (on version tags):
`ghcr.io/dovberkaplan/cine-rec-engine`.
