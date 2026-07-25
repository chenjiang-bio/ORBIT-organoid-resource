"""Runtime data directory resolution and optional download helpers.

Search order for ``data/`` content:
  1. ``ORBIT_OCSP_DATA`` environment variable (points at the ``data/`` folder)
  2. ``~/.orbit_ocsp/data/`` when it contains required marker files
  3. Project / editable-install ``<repo>/data/``
  4. Current working directory ``./data/``
"""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

import requests
from tqdm import tqdm

__version__ = "0.1.0"

_PKG_ROOT = Path(__file__).resolve().parents[1]
SpeciesBundle = Literal["hsa", "mmu", "full"]

DEFAULT_RELEASE_BASE = os.environ.get(
    "ORBIT_OCSP_DATA_BASE_URL",
    f"https://github.com/chenjiang-bio/ORBIT-organoid-resource/releases/download/ocsp-data-v{__version__}",
)

SHARED_PATHS: tuple[str, ...] = (
    "meta/go_meta.json",
    "DAG/go_ancestors.json",
    "DAG/go_namespace.json",
    "semantic_resources_v2/go_ancestors.json",
    "semantic_resources_v2/go_ic.json",
    "semantic_resources_v2/go_namespace.json",
    "protein/all_merged_result.json",
    "protein/Gene_Annotation_Human.txt",
    "protein/Gene_Annotation_Mouse.txt",
    # sequence mode: KO -> species pathway mapping
    "ko2pathway/ko2hsa.txt",
    "ko2pathway/ko2mmu.txt",
)

SPECIES_PATHS: dict[str, tuple[str, ...]] = {
    "hsa": (
        "data_b/B_terms_hsa.json",
        "data_u/U_terms_GO_KEGG_hsa.json",
        "meta/kegg_meta_hsa.json",
        "IC/go_ic_hsa.json",
        "annotations/term_size_human.tsv",
        "KEGG_count_topology/hsa_topology.json",
    ),
    "mmu": (
        "data_b/B_terms_mmu.json",
        "data_u/U_terms_GO_KEGG_mmu.json",
        "meta/kegg_meta_mmu.json",
        "IC/go_ic_mmu.json",
        "annotations/term_size_mouse.tsv",
        "KEGG_count_topology/mmu_topology.json",
    ),
}

BUNDLE_ARCHIVE = {
    "hsa": f"orbit-ocsp-data-hsa-{__version__}.tar.gz",
    "mmu": f"orbit-ocsp-data-mmu-{__version__}.tar.gz",
    "full": f"orbit-ocsp-data-full-{__version__}.tar.gz",
}


def project_root() -> Path:
    """Repository / editable-install root (parent of ``orbit-ocsp/`` package dir)."""
    return _PKG_ROOT


def _strip_data_prefix(relpath: str) -> Path:
    p = Path(relpath)
    if p.parts and p.parts[0] == "data":
        return Path(*p.parts[1:])
    return p


def _user_data_dir() -> Path:
    return Path.home() / ".orbit-ocsp" / "data"


def _env_data_dir() -> Path | None:
    raw = os.environ.get("ORBIT_OCSP_DATA", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _bundled_data_dir() -> Path:
    return project_root() / "data"


def data_root() -> Path:
    """Return the active ``data/`` directory root."""
    env = _env_data_dir()
    if env is not None:
        return env
    user = _user_data_dir()
    if user.is_dir() and any(user.iterdir()):
        return user
    bundled = _bundled_data_dir()
    if bundled.is_dir():
        return bundled
    return user


def resolve_data_path(relpath: str) -> str:
    """Resolve ``data/...`` paths against the active data root."""
    p = Path(relpath)
    if p.is_absolute():
        return str(p)

    inner = _strip_data_prefix(relpath)
    env = _env_data_dir()
    if env is not None:
        candidate = env / inner
        if candidate.exists():
            return str(candidate.resolve())

    cwd_candidate = Path.cwd() / p
    if cwd_candidate.exists():
        return str(cwd_candidate.resolve())

    for root in (_user_data_dir(), _bundled_data_dir(), Path.cwd() / "data"):
        candidate = root / inner
        if candidate.exists():
            return str(candidate.resolve())

    if env is not None:
        return str((env / inner).resolve())
    return str((_bundled_data_dir() / inner).resolve())


def required_paths(species: SpeciesBundle) -> list[str]:
    if species == "full":
        paths = list(SHARED_PATHS)
        paths.extend(SPECIES_PATHS["hsa"])
        paths.extend(SPECIES_PATHS["mmu"])
        return paths
    return list(SHARED_PATHS) + list(SPECIES_PATHS[species])


def missing_paths(species: SpeciesBundle, root: Path | None = None) -> list[str]:
    root = root or data_root()
    missing: list[str] = []
    for rel in required_paths(species):
        target = root / rel
        if not target.exists():
            missing.append(rel)
    return missing


def data_status(species: SpeciesBundle = "full") -> dict:
    root = data_root()
    missing = missing_paths(species, root)
    return {
        "data_root": str(root),
        "species": species,
        "ready": not missing,
        "missing": missing,
    }


def ensure_data_available(
    species: str = "hsa",
    *,
    auto_prompt: bool = True,
) -> None:
    """Raise FileNotFoundError with download instructions when data is missing."""
    bundle: SpeciesBundle
    key = species.strip().lower()
    if key in {"hsa", "human"}:
        bundle = "hsa"
    elif key in {"mmu", "mouse"}:
        bundle = "mmu"
    else:
        bundle = "full"

    missing = missing_paths(bundle)
    if not missing:
        return

    cmd = "orbit-ocsp-download-data"
    if bundle in {"hsa", "mmu"}:
        hint = (
            f" (or --species {bundle} for {bundle} only, smaller download)"
        )
    else:
        hint = ""
    msg = (
        f"Required orbit-ocsp data files are missing under {data_root()}.\n"
        f"Missing ({len(missing)}): {', '.join(missing[:5])}"
        f"{'...' if len(missing) > 5 else ''}\n\n"
        f"Download with:\n  {cmd}{hint}\n\n"
        f"Or set ORBIT_OCSP_DATA to an existing data directory.\n"
        f"Release bundles: {DEFAULT_RELEASE_BASE}/"
    )
    if auto_prompt:
        raise FileNotFoundError(msg)
    return


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as handle, tqdm(
            total=total or None,
            unit="B",
            unit_scale=True,
            desc=dest.name,
        ) as bar:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
                    bar.update(len(chunk))
        tmp.replace(dest)


def _extract_tar(tar_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as archive:
        archive.extractall(dest)


def download_data(
    species: SpeciesBundle = "full",
    *,
    dest: Path | None = None,
    base_url: str | None = None,
    force: bool = False,
) -> dict:
    """Download and extract an orbit-ocsp data bundle."""
    dest = (dest or _user_data_dir()).expanduser().resolve()
    archive_name = BUNDLE_ARCHIVE[species]
    base = (base_url or DEFAULT_RELEASE_BASE).rstrip("/") + "/"
    url = urljoin(base, archive_name)

    if dest.exists() and not force:
        missing = missing_paths(species, dest)
        if not missing:
            return {
                "status": "already_present",
                "data_root": str(dest),
                "url": url,
            }

    with tempfile.TemporaryDirectory(prefix="orbit-ocsp-data-") as tmpdir:
        tar_path = Path(tmpdir) / archive_name
        _download_file(url, tar_path)
        staging = Path(tmpdir) / "extract"
        _extract_tar(tar_path, staging)

        # Accept either flat layout (data_b/...) or nested data/...
        src = staging / "data" if (staging / "data").is_dir() else staging
        dest.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            target = dest / item.name
            if target.exists() and target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)

    missing = missing_paths(species, dest)
    return {
        "status": "downloaded",
        "data_root": str(dest),
        "url": url,
        "missing_after": missing,
    }


def pack_local_data(
    species: SpeciesBundle,
    output: Path,
    *,
    source_root: Path | None = None,
) -> Path:
    """Create a release tarball from a local ``data/`` tree (maintainer helper)."""
    source_root = (source_root or _bundled_data_dir()).resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="orbit-ocsp-pack-") as tmpdir:
        stage = Path(tmpdir) / "data"
        stage.mkdir()
        for rel in required_paths(species):
            src = source_root / rel
            if src.is_symlink():
                src = src.resolve()
            if not src.exists():
                raise FileNotFoundError(f"Cannot pack missing path: {src}")
            dst = stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        with tarfile.open(output, "w:gz") as archive:
            archive.add(stage, arcname="data")

    return output
