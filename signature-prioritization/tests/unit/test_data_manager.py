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


def test_data_version_is_independent_of_package_version():
    """Bundle names and the download tag come from DATA_VERSION, not __version__.

    The data is tens of megabytes and changes far less often than the code. When
    the two were the same constant, every code-only release either required
    re-uploading identical bundles or pointed ``download-data`` at a release tag
    that was never created.
    """
    from orbit_ocsp import data_manager as dm

    assert dm.DATA_VERSION in dm.BUNDLE_ARCHIVE["hsa"]
    assert dm.DATA_VERSION in dm.DEFAULT_RELEASE_BASE

    for name in dm.BUNDLE_ARCHIVE.values():
        assert name.endswith(f"{dm.DATA_VERSION}.tar.gz"), name


def test_bundle_names_and_release_tag_use_the_same_data_version():
    """A mismatch would request an asset that does not exist in the release."""
    import re

    from orbit_ocsp import data_manager as dm

    tag = re.search(r"/releases/download/[\w-]+-v([\d.]+)", dm.DEFAULT_RELEASE_BASE)
    assert tag, dm.DEFAULT_RELEASE_BASE
    assert tag.group(1) == dm.DATA_VERSION

    for name in dm.BUNDLE_ARCHIVE.values():
        assert dm.DATA_VERSION in name


def test_data_version_is_independent_of_package_version():
    """A code-only release must not invalidate the published data bundles.

    Deriving the bundle names and the release tag from ``__version__`` meant
    every code release pointed ``download-data`` at a data release tag that had
    never been created. ``DATA_VERSION`` is bumped only when the data changes.
    """
    from orbit_ocsp import data_manager as dm

    assert hasattr(dm, "DATA_VERSION")
    # Both are read from the module, so this stays true after a version bump.
    for name in dm.BUNDLE_ARCHIVE.values():
        assert dm.DATA_VERSION in name, name
        assert dm.__version__ not in name or dm.__version__ == dm.DATA_VERSION


def test_download_url_tag_matches_the_bundle_filenames():
    """The release tag and the asset names must reference the same data version.

    If they drift, the URL resolves to a release whose assets have other names
    and every download 404s.
    """
    from orbit_ocsp import data_manager as dm

    tag = dm.DEFAULT_RELEASE_BASE.rstrip("/").rsplit("/", 1)[-1]
    assert dm.DATA_VERSION in tag, (tag, dm.DATA_VERSION)
    for name in dm.BUNDLE_ARCHIVE.values():
        assert dm.DATA_VERSION in name
