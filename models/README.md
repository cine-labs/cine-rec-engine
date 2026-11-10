# Models — the embedding sidecar

The engine is deliberately split in two:

```
┌─────────────────────────┐          ┌──────────────────────────────┐
│     cine_rec_engine/    │          │        encoders, vectors     │
│  recall · scoring ·     │ ◄──────  │  published tunes (HF) or     │
│  ranking · weights.json │  vectors │  any encoder you bring,      │
│  (published, MIT)       │  in DB   │  stored as vector columns    │
└─────────────────────────┘          └──────────────────────────────┘
```

The engine's wheel ships **zero model weights**. Its strongest optional
input is a set of overview embeddings — dense vectors describing each
title. You have two ways to get them: use the **published tuned
encoders** below (one command each), or bring your own (any
sentence-encoder, any language).

## Published tuned encoders

Five tuned encoders live on Hugging Face under
[`cine-labs`](https://huggingface.co/cine-labs), pinned in
[`MANIFEST.json`](MANIFEST.json) (repo, revision, sha256). Each is a
fine-tune of a permissively-licensed base model; the base-model lineage
and license are recorded in each model card.

| Space | Dim | Languages | Best at | Base model |
|---|---|---|---|---|
| `bge` | 768 | en | strongest English-only retrieval | `BAAI/bge-base-en-v1.5` (MIT) |
| `mpnet` | 768 | multilingual | mixed-language catalogs | `paraphrase-multilingual-mpnet-base-v2` (Apache-2.0) |
| `mpnet_enrich` | 768 | multilingual | catalogs with cinematic-tag enrichment | same, continued |
| `e5_enrich` | 768 | multilingual | E5-style query/passage prefixes | multilingual-E5 (Apache-2.0) |
| `minilm_tuned` | 384 | en | cheapest tuned space, CPU-friendly | `all-MiniLM-L6-v2` (Apache-2.0) |

### Quickstart (immediate use)

```bash
pip install "cine-rec-engine[encoders]"

python models/fetch_encoders.py embed \
    --dsn postgresql://demo:demo@localhost:5432/demo \
    --space mpnet
# → downloads cine-embed-mpnet-v1 on demand (sha256-verified),
#   embeds the whole catalog, and tells you how to switch to it

export CINE_REC_EMBEDDING=mpnet   # every request now uses the space
```

**On-demand downloads are the default**: `embed` fetches the pinned
encoder automatically when it isn't already on disk, and never touches
the network again once it is. `fetch` is the explicit variant for
pre-seeding machines (`fetch mpnet`, `fetch` for all). To stay fully
offline — air-gapped installs, CI — set `CINE_REC_AUTO_FETCH=0` or pass
`--no-fetch`; you then get an actionable error instead of a download.
The engine itself never downloads anything at query time.

`embed` writes `tmdb_media.embedding_<space>` (creating the `vector`
column when needed). The engine picks the space up from
`CINE_REC_EMBEDDING=<space>`, per-request `rec_model=<space>`, or the
`CINE_REC_COSINE_BLEND` ensemble mix.

### Choosing a space

- **English-only catalog** → `bge` (or `minilm_tuned` on small machines).
- **Multilingual catalog** (overviews in Hebrew, Spanish, …) → `mpnet`
  or `e5_enrich`.
- **You maintain cinematic tags** (the optional `tmdb_cinematic`
  table) → the `_enrich` spaces see the full canonical template and
  perform best; without it they run on the Title+Overview fallback.

### Input format (what `embed` builds)

Catalog side, per title:

```
Title: {title} ({year})
Emotional arc: {tags}          ← only with tmdb_cinematic enrichment
Pacing: {tag}                  ← 〃
Narrative: {tag}               ← 〃
Sub-genres: {tags}             ← 〃
Experience: {tag}              ← 〃
Overview: {overview}
```

Without enrichment the input is the fallback
`Title: {title} ({year})` + `Overview: {overview}`. The `e5_enrich`
space follows the E5 conventions — `passage: ` on the catalog side,
`query: ` on the query side — added automatically by
`fetch_encoders.py`; add them yourself if you encode queries directly.

## Bringing your own encoder (any model, any language)

```python
# 1. encode overviews with YOUR model (example: sentence-transformers)
from sentence_transformers import SentenceTransformer
import asyncpg

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")  # yours
pool = await asyncpg.create_pool(dsn)
await pool.execute("ALTER TABLE tmdb_media ADD COLUMN embedding_minilm vector(384)")

rows = await pool.fetch("SELECT id, media_type, overview FROM tmdb_media")
for row in rows:
    vec = model.encode(row["overview"] or "")
    await pool.execute(
        "UPDATE tmdb_media SET embedding_minilm = $1 WHERE id = $2 AND media_type = $3",
        vec.tolist(), row["id"], row["media_type"],
    )

# 2. register the column in cine_rec_engine/model_spaces.py REC_MODELS
# 3. done — KNN recall and the cosine feature now use your space
```

## What is published vs. kept private

| Artifact | Published? |
|---|---|
| Engine code (recall, scoring, ranking) | ✅ MIT |
| Learned feature **weights** (`cine_rec_engine/weights.json`) | ✅ published |
| Tuned **encoders** (the five spaces above) | ✅ HF, pinned by sha256 |
| Training sets, graded evaluation data, tuning pipelines | ❌ not published |

The weights and encoders tell you *how much* each signal matters and
*how to vectorize a title*; they do not include the labeled data they
were fitted on. Bundled demo vectors derive from TMDb overviews — this
product uses the TMDB API but is not endorsed or certified by TMDb.
