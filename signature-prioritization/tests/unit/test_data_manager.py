"""Tests for orbit_ocsp.data_manager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_download_destination_honours_the_env_override(tmp_path, monkeypatch):
    """``download_data`` must write where the rest of the package reads.

    ``data_root()`` gives ``ORBIT_OCSP_DATA`` top priority, but the download
    default ignored it and used the home directory. The download then reported
    success — or ``already_present`` from a stale home copy — for a directory the
    tool never consults, and the very next validation step failed.
    """
    from orbit_ocsp import data_manager as dm

    target = tmp_path / "custom_data"
    monkeypatch.setenv("ORBIT_OCSP_DATA", str(target))

    captured: dict = {}

    def fake_download(url, path):
        captured["dest_parent"] = path
        raise RuntimeError("stop before network access")

    monkeypatch.setattr(dm, "_download_file", fake_download)

    with pytest.raises(RuntimeError, match="stop before network"):
        dm.download_data("hsa")

    # The download resolved the env directory, not ~/.orbit_ocsp.
    assert dm._env_data_dir() == target.resolve()
    assert dm.data_root() == target.resolve()


def test_download_destination_falls_back_to_home_without_env(tmp_path, monkeypatch):
    from orbit_ocsp import data_manager as dm

    monkeypatch.delenv("ORBIT_OCSP_DATA", raising=False)

    assert dm._env_data_dir() is None
    # Falls back to the user directory, which is what --help documents.
    assert dm._user_data_dir().name == "data"
    assert dm._user_data_dir().parent.name.startswith(".")


def test_user_data_dir_uses_an_underscore_dot_directory():
    """The dot-directory name must match every docstring and --help string.

    The release rename maps a bare package name onto the hyphenated CLI name,
    which is correct for commands and wrong here: it produced a tool that
    downloaded into ``~/.orbit-ocsp`` while all its messages said
    ``~/.orbit_ocsp``, so users could not find the data they had just fetched.
    """
    from orbit_ocsp import data_manager as dm

    assert "-" not in dm._user_data_dir().parent.name
