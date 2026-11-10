"""Registry behavior: space/column mapping and name normalization."""

import json
from pathlib import Path

from cine_rec_engine.model_spaces import (
    REC_MODELS,
    column_for,
    is_solo,
    normalize_model,
)


class TestNameNormalization:
    def test_keys_resolve_case_insensitively_and_trimmed(self):
        assert normalize_model(" MiniLM ") == "minilm"
        assert normalize_model("original") == "original"

    def test_original_is_a_real_entry(self):
        # the base space — same key CINE_REC_EMBEDDING=original names
        assert column_for("original") == "embedding"
        assert is_solo("original")

    def test_minilm_is_the_public_reference_space(self):
        assert column_for("minilm") == "embedding_minilm"
        assert is_solo("minilm")

    def test_unknown_still_none(self):
        assert normalize_model("bogus") is None
        assert normalize_model("") is None
        assert normalize_model(None) is None


class TestWeights:
    def test_solo_spaces_keep_the_safe_default(self):
        # solo cosine weights are safe defaults, not fitted constants
        assert REC_MODELS["original"]["cosine_weight"] == 10.0
        assert REC_MODELS["minilm"]["cosine_weight"] == 10.0

    def test_ensemble_has_no_solo_column(self):
        assert column_for("ensemble") is None
        assert not is_solo("ensemble")


class TestServeAcceptsRegistryKeys:
    def test_validate_model_passes_through_normalized(self):
        from cine_rec_engine.serve import _validate_model

        assert _validate_model("minilm") == "minilm"
        assert _validate_model("original") == "original"
        assert _validate_model(None) is None


class TestPublishedManifest:
    """models/MANIFEST.json is the pin list for the published encoders —
    it must stay consistent with the registry (space names, columns)."""

    MANIFEST = Path(__file__).resolve().parents[1] / "models" / "MANIFEST.json"

    @classmethod
    def entries(cls):
        return json.loads(cls.MANIFEST.read_text())["encoders"]

    def test_every_manifest_space_is_registered(self):
        for e in self.entries():
            assert e["space"] in REC_MODELS, f"{e['space']} missing from REC_MODELS"

    def test_columns_follow_the_space_convention(self):
        for e in self.entries():
            assert column_for(e["space"]) == f"embedding_{e['space']}"
            assert REC_MODELS[e["space"]]["column"] == e["column"]

    def test_published_spaces_keep_the_safe_default_weight(self):
        for e in self.entries():
            assert REC_MODELS[e["space"]]["cosine_weight"] == 10.0

    def test_entries_are_pinned(self):
        for e in self.entries():
            assert e["repo"].startswith("cine-labs/")
            assert len(e["sha256"]) == 64
            assert e["dim"] in (384, 768)

    def test_e5_space_declares_prefixes(self):
        e = {x["space"]: x for x in self.entries()}["e5_enrich"]
        assert e["query_prefix"] == "query: "
        assert e["passage_prefix"] == "passage: "
