#!/usr/bin/env python3
"""Pack local data/ trees into release tarballs for GitHub Releases."""

from __future__ import annotations

import argparse
from pathlib import Path

from orbit_ocsp.data_manager import (
    BUNDLE_ARCHIVE,
    DEFAULT_RELEASE_BASE,
    __version__,
    pack_local_data,
    project_root,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--species", choices=["hsa", "mmu", "full"], default="full")
    ap.add_argument(
        "--source",
        type=Path,
        default=project_root() / "data",
        help="Local data/ directory",
    )
    ap.add_argument(
        "--outdir",
        type=Path,
        default=project_root() / "dist" / "data-release",
        help="Output directory for .tar.gz files",
    )
    args = ap.parse_args()

    name = BUNDLE_ARCHIVE[args.species]
    out = args.outdir / name
    path = pack_local_data(args.species, out, source_root=args.source)
    print(f"Wrote {path} ({path.stat().st_size / 1e6:.1f} MB)")
    # Derive the tag from the URL the downloader actually requests, so this hint
    # can never drift from it. Hardcoding a tag here once told users to publish
    # under `data-v<version>` while the downloader fetched `ocsp-data-v<version>`.
    tag = DEFAULT_RELEASE_BASE.rstrip("/").rsplit("/", 1)[-1]
    print(f"Upload as an asset of GitHub release tag: {tag}")
    print(f"Download URL will be: {DEFAULT_RELEASE_BASE}/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
