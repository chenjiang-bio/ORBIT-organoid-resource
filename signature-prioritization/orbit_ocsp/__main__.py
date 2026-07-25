"""Entry point: python -m orbit_ocsp → product CLI (route by --mode)."""

from orbit_ocsp.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
