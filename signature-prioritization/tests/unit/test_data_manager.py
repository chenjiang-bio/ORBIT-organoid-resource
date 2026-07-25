"""Tests for orbit_ocsp.data_manager."""

from __future__ import annotations

import json
from pathlib import Path

from orbit_ocsp.data_manager import (
    missing_paths,
    pack_local_data,
    required_paths,
    resolve_data_path,
)


def test_required_paths_hsa_includes_b_terms():
    paths = required_paths("hsa")
    assert "data_b/B_terms_hsa.json" in paths
    assert "data_u/U_terms_GO_KEGG_hsa.json" in paths


def test_missing_paths_on_empty_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_OCSP_DATA", str(tmp_path))
    missing = missing_paths("hsa", tmp_path)
    assert missing == required_paths("hsa")


def test_resolve_data_path_prefers_env_root(tmp_path, monkeypatch):
    b_dir = tmp_path / "data_b"
    b_dir.mkdir()
    b_file = b_dir / "B_terms_hsa.json"
    b_file.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("ORBIT_OCSP_DATA", str(tmp_path))
    resolved = Path(resolve_data_path("data/data_b/B_terms_hsa.json"))
    assert resolved == b_file


def _make_stub_data_tree(root: Path, species: str = "hsa") -> Path:
    """Create a stub data tree covering exactly ``required_paths(species)``.

    Derived from ``required_paths`` on purpose: adding a new required file
    should not silently break packaging tests.
    """
    for rel in required_paths(species):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".json"):
            target.write_text("{}", encoding="utf-8")
        else:
            target.write_text("x\ty\n", encoding="utf-8")
    return root


def test_pack_local_data_roundtrip(tmp_path):
    source = _make_stub_data_tree(tmp_path / "data", "hsa")
    assert missing_paths("hsa", source) == []

    out = tmp_path / "bundle.tar.gz"
    pack_local_data("hsa", out, source_root=source)
    assert out.exists() and out.stat().st_size > 0


def test_ko2pathway_is_required_for_sequence_mode():
    """Sequence mode needs the KO->pathway maps, so the downloader must fetch them."""
    paths = required_paths("hsa")
    assert "ko2pathway/ko2hsa.txt" in paths
    assert "ko2pathway/ko2mmu.txt" in paths
