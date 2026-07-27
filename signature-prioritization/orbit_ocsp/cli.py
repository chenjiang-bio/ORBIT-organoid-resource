"""Product CLI: one entry point, route by --mode.

Usage:
  orbit-ocsp --mode expression --matrix ... --groups ... --condition ...
  orbit-ocsp --mode genes --genes LEF1,CD44 --condition ...
  orbit-ocsp expression ...          # same as --mode expression
  orbit-ocsp genes ...               # same as --mode genes
  orbit-ocsp ensemble ...            # legacy permutation_test_terms CLI
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence


def _parse_genes(genes: Optional[str], genes_file: Optional[str]) -> List[str]:
    out: List[str] = []
    if genes:
        out.extend(g.strip() for g in genes.split(",") if g.strip())
    if genes_file:
        text = Path(genes_file).read_text(encoding="utf-8")
        out.extend(line.strip() for line in text.splitlines() if line.strip())
    # de-dupe, keep order
    seen = set()
    uniq: List[str] = []
    for g in out:
        key = g.upper()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(g)
    return uniq


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="orbit_ocsp",
        description=(
            "ORBIT biomarker scoring — one command, choose path with --mode.\n\n"
            "  expression  matrix + groups → DE → score → biomarker_ranked.json\n"
            "  genes       gene list → score → biomarker_ranked.json\n"
            "  sequence    KOfam/InterProScan/DeepGOPlus outputs (or a\n"
            "              pre-merged JSON) → merge → score\n\n"
            "Field contract: docs/CONTRACT.md (in the developer bundle)."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--mode",
        choices=["expression", "genes", "sequence"],
        help="Which input path to run (required unless using subcommand style)",
    )

    # shared
    p.add_argument("--condition", help="B_terms condition (e.g. \"Colorectal Cancer\")")
    p.add_argument("--species", default="hsa", help="hsa or mmu (default: hsa)")
    p.add_argument("--outdir", default="out_orbit-ocsp", help="Output directory")
    p.add_argument(
        "--alpha",
        type=float,
        default=0.005,
        help="Primary hypergeometric threshold (default: 0.005)",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--b-terms", default=None, help="Optional B_terms JSON path")
    p.add_argument(
        "--merged-result",
        default=None,
        help="Optional all_merged_result.json path",
    )

    # expression
    p.add_argument("--matrix", help="[expression] matrix TSV/CSV (abs or relative path)")
    p.add_argument("--groups", help="[expression] groups TSV/CSV")
    p.add_argument(
        "--data-type",
        choices=["microarray", "rnaseq_count", "rnaseq", "normalized"],
        help="[expression] data type (rnaseq is an alias for rnaseq_count)",
    )
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument("--padj-max", type=float, default=0.05)
    p.add_argument("--abs-log2fc-min", type=float, default=1.0)
    p.add_argument(
        "--de-backend",
        default="r",
        choices=["r", "mock"],
        help="[expression] DE backend (mock = no R)",
    )
    p.add_argument("--de-results", default=None, help="[expression] precomputed DE TSV")
    p.add_argument(
        "--skip-scoring",
        action="store_true",
        help="[expression] DE + map only",
    )

    # genes
    p.add_argument("--genes", help="[genes] comma-separated symbols/IDs")
    p.add_argument("--genes-file", help="[genes] text file, one gene per line")

    # sequence
    p.add_argument("--kofam", help="[sequence] KOfam native output (.txt)")
    p.add_argument("--interproscan", help="[sequence] InterProScan native TSV")
    p.add_argument("--deepgo", help="[sequence] DeepGOPlus native TSV")
    p.add_argument(
        "--annotation-dir",
        help="[sequence] batch dir with kofam/, interproscan/, deepgoplus/",
    )
    p.add_argument(
        "--merged-json",
        help="[sequence] pre-merged A_terms JSON (skips parsing/merging)",
    )
    p.add_argument(
        "--id-map",
        help="[sequence] TSV: query_id + optional entrez_id/gene_symbol/identity/evalue",
    )
    p.add_argument(
        "--ko2pathway",
        help="[sequence] KO->pathway TSV (default: data/ko2pathway/ko2<species>.txt)",
    )
    p.add_argument(
        "--deepgo-min-score",
        type=float,
        default=0.0,
        help="[sequence] DeepGOPlus score cutoff (default: 0 = keep all)",
    )
    p.add_argument(
        "--kofam-min-score",
        type=float,
        default=None,
        help="[sequence] KOfam score cutoff (default: no filter)",
    )
    p.add_argument("--query-id", help="[sequence] keep only this query ID")
    p.add_argument(
        "--merge-only",
        action="store_true",
        help="[sequence] write merged JSON and skip scoring",
    )
    return p


def _run_expression(args: argparse.Namespace) -> int:
    from orbit_ocsp.data_manager import ensure_data_available
    from orbit_ocsp.expression_pipeline import run_expression_biomarker_pipeline

    missing = [n for n in ("matrix", "groups", "data_type", "condition") if not getattr(args, n)]
    if missing:
        print(
            f"expression mode requires: --matrix --groups --data-type --condition\n"
            f"missing: {', '.join('--' + m.replace('_', '-') for m in missing)}",
            file=sys.stderr,
        )
        return 2

    try:
        ensure_data_available(args.species)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    ranked = run_expression_biomarker_pipeline(
        matrix_path=args.matrix,
        groups_path=args.groups,
        data_type=args.data_type,
        condition=args.condition,
        species=args.species,
        top_k=args.top_k,
        padj_max=args.padj_max,
        abs_log2fc_min=args.abs_log2fc_min,
        outdir=args.outdir,
        merged_result=args.merged_result,
        b_terms=args.b_terms,
        de_backend=args.de_backend,
        de_results_path=args.de_results,
        skip_scoring=args.skip_scoring,
        alpha=args.alpha,
        seed=args.seed,
    )
    print(f"[expression] ranked {len(ranked)} genes")
    print(f"Results: {Path(args.outdir) / 'biomarker_ranked.json'}")
    return 0


def _run_genes(args: argparse.Namespace) -> int:
    from orbit_ocsp.data_manager import ensure_data_available
    from orbit_ocsp.expression_pipeline import run_genes_biomarker_pipeline

    if not args.condition:
        print("genes mode requires: --condition", file=sys.stderr)
        return 2
    gene_list = _parse_genes(args.genes, args.genes_file)
    if not gene_list:
        print("genes mode requires: --genes A,B,C  or  --genes-file path", file=sys.stderr)
        return 2

    try:
        ensure_data_available(args.species)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    ranked = run_genes_biomarker_pipeline(
        genes=gene_list,
        condition=args.condition,
        species=args.species,
        outdir=args.outdir,
        merged_result=args.merged_result,
        b_terms=args.b_terms,
        alpha=args.alpha,
        seed=args.seed,
    )
    print(f"[genes] ranked {len(ranked)} genes")
    print(f"Results: {Path(args.outdir) / 'biomarker_ranked.json'}")
    return 0


def _run_sequence(args: argparse.Namespace) -> int:
    from orbit_ocsp.data_manager import ensure_data_available
    from orbit_ocsp.sequence_annotation import (
        SequenceInputError,
        run_sequence_pipeline,
    )

    if not args.condition and not args.merge_only:
        print(
            "sequence mode requires: --condition "
            "(or --merge-only to just build the merged JSON)",
            file=sys.stderr,
        )
        return 2

    # Validate arguments before touching the data bundle, so a usage mistake
    # reports the usage error (exit 2) rather than "data missing" (exit 1).
    native_inputs = [args.kofam, args.interproscan, args.deepgo, args.annotation_dir]
    if args.merged_json and any(native_inputs):
        print(
            "error: --merged-json (entry B) is mutually exclusive with --kofam / "
            "--interproscan / --deepgo / --annotation-dir (entry A). Pick one.",
            file=sys.stderr,
        )
        return 2
    if not args.merged_json and not any(native_inputs):
        print(
            "error: sequence mode needs either:\n"
            "  entry A: --kofam / --interproscan / --deepgo (or --annotation-dir)\n"
            "  entry B: --merged-json <path>",
            file=sys.stderr,
        )
        return 2

    if not args.merge_only:
        try:
            ensure_data_available(args.species)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    try:
        result = run_sequence_pipeline(
            condition=args.condition or "",
            outdir=args.outdir,
            species=args.species,
            kofam=args.kofam,
            interproscan=args.interproscan,
            deepgo=args.deepgo,
            annotation_dir=args.annotation_dir,
            merged_json=args.merged_json,
            id_map=args.id_map,
            ko2pathway=args.ko2pathway,
            deepgo_min_score=args.deepgo_min_score,
            kofam_min_score=args.kofam_min_score,
            query_id=args.query_id,
            b_terms=args.b_terms,
            alpha=args.alpha,
            seed=args.seed,
            merge_only=args.merge_only,
        )
    except SequenceInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"[sequence] merged {result['n_records']} record(s)")
    print(f"Merged JSON: {result['merged_json']}")
    print(f"Report: {result['report']}")
    if not args.merge_only:
        print(f"Results: {Path(args.outdir) / 'biomarker_ranked.json'}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # Subcommand aliases: orbit-ocsp expression|genes|sequence|ensemble ...
    if raw and raw[0] in {"expression", "genes", "sequence", "ensemble"} and not raw[0].startswith("-"):
        cmd = raw.pop(0)
        if cmd == "ensemble":
            from orbit_ocsp.permutation_test_terms import main as ensemble_main

            # ensemble_main() reads sys.argv directly and takes no arguments.
            saved = sys.argv
            try:
                sys.argv = ["orbit-ocsp-ensemble", *raw]
                return int(ensemble_main() or 0)
            finally:
                sys.argv = saved
        raw = ["--mode", cmd, *raw]

    parser = build_parser()
    args = parser.parse_args(raw)

    if not args.mode:
        parser.print_help()
        print(
            "\nerror: provide --mode expression|genes|sequence "
            "(or: orbit-ocsp expression|genes ...)",
            file=sys.stderr,
        )
        return 2

    if args.mode == "expression":
        return _run_expression(args)
    if args.mode == "genes":
        return _run_genes(args)
    return _run_sequence(args)


if __name__ == "__main__":
    raise SystemExit(main())
