"""fetch_encoders: on-demand download policy + canonical text format.

All network access is mocked — these tests are offline. The sha256
pins come from the real MANIFEST, so the template/hash logic is tested
against the actual published values.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "fetch_encoders", _REPO / "models" / "fetch_encoders.py"
)
fe = importlib.util.module_from_spec(_spec)
sys.modules["fetch_encoders"] = fe
_spec.loader.exec_module(fe)

MANIFEST = json.loads((_REPO / "models" / "MANIFEST.json").read_text())
MP = next(e for e in MANIFEST["encoders"] if e["space"] == "mpnet")


@pytest.fixture()
def entry(tmp_path):
    """A manifest entry whose sha256 pin matches b'fake-weights'."""
    e = dict(MP, sha256=hashlib.sha256(b"fake-weights").hexdigest())
    return e, tmp_path


def _place(root: Path) -> None:
    (root / "mpnet").mkdir(parents=True, exist_ok=True)
    (root / "mpnet" / "model.safetensors").write_bytes(b"fake-weights")


class TestEnsureEncoder:
    def test_present_locally_never_touches_network(self, entry, monkeypatch):
        e, root = entry
        _place(root)
        monkeypatch.setattr(
            "huggingface_hub.snapshot_download",
            lambda **kw: pytest.fail("network access attempted"),
        )
        out = fe.ensure_encoder(e, root)
        assert out == root / "mpnet"

    def test_missing_downloads_when_auto(self, entry, monkeypatch):
        e, root = entry
        (root / "mpnet").mkdir()

        def fake_download(**kw):
            (root / "mpnet" / "model.safetensors").write_bytes(b"fake-weights")
            return str(root / "mpnet")

        monkeypatch.setattr("huggingface_hub.snapshot_download", fake_download)
        out = fe.ensure_encoder(e, root)
        assert (out / "model.safetensors").exists()

    def test_auto_disabled_is_an_actionable_error(self, entry, monkeypatch):
        e, root = entry
        (root / "mpnet").mkdir()
        monkeypatch.setattr(
            "huggingface_hub.snapshot_download",
            lambda **kw: pytest.fail("network access attempted"),
        )
        with pytest.raises(SystemExit, match="CINE_REC_AUTO_FETCH"):
            fe.ensure_encoder(e, root, auto=False)

    def test_env_knob_disables_auto(self, entry, monkeypatch, tmp_path):
        e, root = entry
        (root / "mpnet").mkdir()
        monkeypatch.setenv("CINE_REC_AUTO_FETCH", "0")
        with pytest.raises(SystemExit, match="CINE_REC_AUTO_FETCH"):
            fe.ensure_encoder(e, root)
        monkeypatch.setenv("CINE_REC_AUTO_FETCH", "off")
        assert fe.auto_fetch_enabled() is False
        monkeypatch.setenv("CINE_REC_AUTO_FETCH", "1")
        assert fe.auto_fetch_enabled() is True
        monkeypatch.delenv("CINE_REC_AUTO_FETCH")
        assert fe.auto_fetch_enabled() is True  # default: on

    def test_bad_hash_is_rejected(self, entry, monkeypatch):
        e, root = entry
        (root / "mpnet").mkdir()

        def fake_download(**kw):
            (root / "mpnet" / "model.safetensors").write_bytes(b"TAMPERED")

        monkeypatch.setattr("huggingface_hub.snapshot_download", fake_download)
        with pytest.raises(SystemExit, match="sha256 mismatch"):
            fe.ensure_encoder(e, root)


class TestCanonicalText:
    def test_fallback_template_without_enrichment(self):
        out = fe.canonical_text("Arrival", 2016, "A linguist arrives.", None)
        assert out == "Title: Arrival (2016)\nOverview: A linguist arrives."

    def test_full_template_with_enrichment(self):
        out = fe.canonical_text(
            "Arrival", 2016, "A linguist arrives.",
            {"emotional_arc": ["contemplative", "melancholic"],
             "pacing": "measured", "narrative_complexity": "linear",
             "sub_genres": ["first-contact"], "viewing_experience": "brainy"},
        )
        assert out == (
            "Title: Arrival (2016)\n"
            "Emotional arc: contemplative, melancholic\n"
            "Pacing: measured\n"
            "Narrative: linear\n"
            "Sub-genres: first-contact\n"
            "Experience: brainy\n"
            "Overview: A linguist arrives."
        )

    def test_empty_arc_fields_fall_back_not_half_template(self):
        out = fe.canonical_text("Arrival", 2016, "x", {"emotional_arc": []})
        assert "Emotional arc" not in out
        assert out.startswith("Title: Arrival (2016)\nOverview:")

    def test_missing_overview_becomes_dash(self):
        out = fe.canonical_text("Arrival", None, None, None)
        assert out == "Title: Arrival (-)\nOverview: -"


class TestManifestShape:
    def test_spaces_and_repos_unique(self):
        spaces = [e["space"] for e in MANIFEST["encoders"]]
        repos = [e["repo"] for e in MANIFEST["encoders"]]
        assert len(set(spaces)) == len(spaces)
        assert len(set(repos)) == len(repos)


class TestCliDispatch:
    def test_fetch_parses_without_dsn(self, monkeypatch, tmp_path):
        # regression: dsn is only required for embed, not fetch
        monkeypatch.setattr(fe, "cmd_fetch", lambda a: 0)
        assert fe.main(["fetch", "--dest", str(tmp_path)]) == 0

    def test_embed_requires_dsn(self, monkeypatch, capsys):
        monkeypatch.delenv("CINE_REC_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit):
            fe.main(["embed", "--space", "mpnet"])
