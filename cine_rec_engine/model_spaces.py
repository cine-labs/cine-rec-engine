"""Embedding space registry — the seam between engine and models.

The engine's KNN recall channel and cosine-blend feature read OVERVIEW
EMBEDDINGS from columns on ``tmdb_media``. Which column(s) exist is a
property of YOUR database: you generate embeddings with whichever
sentence-encoder you like (see ``models/README.md``), store them as
``vector`` columns, and register them here.

Each entry names:
- ``column``: the tmdb_media column holding the vectors (None = the
  tuned multi-model ensemble driven by config.COSINE_BLEND).
- ``cosine_weight``: the cosine_sim feature weight to use when this
  space is selected solo (overrides the tuned default).

The published ``weights.json`` was tuned on the ensemble space; solo
weights below are safe defaults, not fitted constants.
"""

from __future__ import annotations

from typing import Optional

REC_MODELS: dict = {
    "ensemble": {
        "column": None,
        "cosine_weight": None,
    },
    "original": {
        # the base space — the plain `embedding` column that
        # CINE_REC_EMBEDDING=original selects; lightweight default.
        "column": "embedding",
        "cosine_weight": 10.0,
    },
    "minilm": {
        # the public reference encoder (all-MiniLM-L6-v2, 384-dim) —
        # the space the bundled demo ships and the public benchmark
        # uses. Registered here as the worked example of the
        # name → embedding_<name> convention.
        "column": "embedding_minilm",
        "cosine_weight": 10.0,
    },
    # ---- published tuned encoders (cine-labs on Hugging Face) --------
    # Fitted on this project's title-similarity data; pinned (repo,
    # revision, sha256) in models/MANIFEST.json and fetched with
    # models/fetch_encoders.py. Catalog texts follow the canonical
    # template in models/README.md; spaces whose MANIFEST entry lists a
    # prefix prepend it on the matching side (E5 convention). Solo
    # cosine weights are safe defaults, not fitted constants.
    "bge": {
        # English BGE-base tune (768-dim) — strongest English-only space.
        "column": "embedding_bge",
        "cosine_weight": 10.0,
    },
    "mpnet": {
        # Multilingual MPNet tune (768-dim).
        "column": "embedding_mpnet",
        "cosine_weight": 10.0,
    },
    "mpnet_enrich": {
        # MPNet tune trained on canonical texts that include cinematic
        # tags; runs on the Title+Overview fallback, best with
        # enrichment.
        "column": "embedding_mpnet_enrich",
        "cosine_weight": 10.0,
    },
    "e5_enrich": {
        # Multilingual E5 tune with the E5 prefix convention
        # ("query: " / "passage: ") — fetch_encoders.py adds them.
        "column": "embedding_e5_enrich",
        "cosine_weight": 10.0,
    },
    "minilm_tuned": {
        # Lightweight fine-tune of the MiniLM reference encoder
        # (384-dim) — the cheapest tuned space.
        "column": "embedding_minilm_tuned",
        "cosine_weight": 10.0,
    },
}


def normalize_model(name: Optional[str]) -> Optional[str]:
    """Case-insensitive match against REC_MODELS, or None."""
    if not name:
        return None
    low = name.strip().lower()
    for key in REC_MODELS:
        if key.lower() == low:
            return key
    return None


def column_for(space: Optional[str]) -> Optional[str]:
    """The embedding column a solo space builds and searches from.

    None = the default column (config.EMBEDDING_COLUMN) — used by the
    ensemble and unknown spaces. Single source for this mapping: the
    user-vector build, the ANN recall, and the request path must agree,
    or a vector built from one column gets searched against another.
    """
    if space:
        spec = REC_MODELS.get(space)
        if spec and spec["column"]:
            return spec["column"]
    return None


def is_solo(model_key: str) -> bool:
    """True when the key selects a single embedding column."""
    spec = REC_MODELS.get(model_key)
    return bool(spec and spec["column"])
