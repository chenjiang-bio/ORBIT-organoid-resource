#!/usr/bin/env python3
"""Download orbit-ocsp runtime data bundles."""

from __future__ import annotations

import argparse
import json
import sys

from orbit_ocsp.data_manager import (
    DEFAULT_RELEASE_BASE,
    data_status,
    download_data,
    ensure_data_available,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download orbit-ocsp reference data (B_terms, U, meta, protein maps, "
            "semantic resources) into ~/.orbit_ocsp/data/ by default."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  orbit-ocsp-download-data              # default: hsa + mmu (full)\n"
            "  orbit-ocsp-download-data --species hsa   # human only, smaller\n"
            "  orbit-ocsp-download-data --species mmu   # mouse only\n"
            "  orbit-ocsp-download-data --check\n\n"
            "Environment:\n"
            "  ORBIT_OCSP_DATA       Use an existing data directory\n"
            "  ORBIT_OCSP_DATA_BASE_URL  Override release download base URL\n"
        ),
    )
    parser.add_argument(
        "--species",
        choices=["hsa", "mmu", "full"],
        default="full",
        help="Which bundle: full=hsa+mmu+shared (default), or hsa/mmu only",
    )
    parser.add_argument(
        "--dest",
        default=None,
        help="Destination data directory (default: ~/.orbit_ocsp/data)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"Release base URL (default: {DEFAULT_RELEASE_BASE})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if files already exist",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only print data status JSON and exit (no download)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.check:
        print(json.dumps(data_status(args.species), indent=2))
        return 0 if data_status(args.species)["ready"] else 1

    try:
        result = download_data(
            args.species,
            dest=args.dest,
            base_url=args.base_url,
            force=args.force,
        )
    except Exception as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        print(
            "\nIf the release is not published yet, pack locally with:\n"
            "  python scripts/pack_data_release.py --species full\n",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, indent=2))
    missing = result.get("missing_after") or []
    if missing:
        print(f"Warning: still missing {len(missing)} files after extract.", file=sys.stderr)
        return 1

    # Validate readable
    ensure_data_available(args.species if args.species != "full" else "hsa")
    print(f"Data ready under {result['data_root']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
