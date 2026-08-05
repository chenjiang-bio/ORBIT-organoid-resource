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


def _parse_pathway_sources(raw: Optional[str]) -> List[str]:
    """Parse comma-separated B_terms pathway keys (default: enrich,gsea,gsva)."""
    from orbit_ocsp.b_terms_schema import DEFAULT_PATHWAY_SOURCES

    if raw is None or not str(raw).strip():
        return list(DEFAULT_PATHWAY_SOURCES)
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    if not parts:
        raise ValueError("--pathway-sources must list at least one source")
    return parts


def _add_b_term_filter_arguments(p: argparse.ArgumentParser) -> None:
    """B_terms metadata filters shared by expression / genes / sequence."""
    p.add_argument(
        "--factor",
        default=None,
        help=(
            "B_terms factor filter (e.g. IFN-γ, Baricitinib). "
            "Required unless --condition is set (either condition or factor)."
        ),
    )
    p.add_argument(
        "--organ-condition",
        default=None,
        help="B_terms organ_condition filter (experimental arm)",
    )
    p.add_argument(
        "--organ-control",
        default=None,
        help="B_terms organ_control filter",
    )
    p.add_argument(
        "--organ-system-condition",
        default=None,
        help="B_terms organ_system_condition filter (list membership)",
    )
    p.add_argument(
        "--organ-system-control",
        default=None,
        help="B_terms organ_system_control filter (list membership)",
    )
    p.add_argument(
        "--source-condition",
        default=None,
        help="B_terms source_condition filter (e.g. ESCs)",
    )
    p.add_argument(
        "--source-control",
        default=None,
        help="B_terms source_control filter",
    )
    p.add_argument(
        "--additional-condition",
        default=None,
        help="B_terms additional_condition filter",
    )
    p.add_argument(
        "--comparison-condition",
        default=None,
        help="B_terms comparison_condition filter",
    )
    p.add_argument(
        "--comparison-control",
        default=None,
        help="B_terms comparison_control filter",
    )
    p.add_argument(
        "--cell-type",
        default=None,
        help="B_terms cell_type filter",
    )
    p.add_argument(
        "--time-condition",
        default=None,
        help="B_terms time_condition filter (experimental arm)",
    )
    p.add_argument(
        "--time-control",
        default=None,
        help="B_terms time_control filter",
    )
    p.add_argument(
        "--model-condition",
        default=None,
        help=(
            "B_terms model_condition filter; overrides --model when set"
        ),
    )
    p.add_argument(
        "--model-control",
        default=None,
        help="B_terms model_control filter",
    )


def _b_filters_from_args(args: argparse.Namespace) -> dict:
    """Collect optional B_terms filters from parsed CLI args."""
    from orbit_ocsp.b_terms_schema import normalize_b_term_filters

    raw = {
        "category": getattr(args, "category", None),
        "model": getattr(args, "model", None),
        "model_condition": getattr(args, "model_condition", None),
        "model_control": getattr(args, "model_control", None),
        "factor": getattr(args, "factor", None),
        "organ_condition": getattr(args, "organ_condition", None),
        "organ_control": getattr(args, "organ_control", None),
        "organ_system_condition": getattr(args, "organ_system_condition", None),
        "organ_system_control": getattr(args, "organ_system_control", None),
        "source_condition": getattr(args, "source_condition", None),
        "source_control": getattr(args, "source_control", None),
        "additional_condition": getattr(args, "additional_condition", None),
        "comparison_condition": getattr(args, "comparison_condition", None),
        "comparison_control": getattr(args, "comparison_control", None),
        "cell_type": getattr(args, "cell_type", None),
        "time_condition": getattr(args, "time_condition", None),
        "time_control": getattr(args, "time_control", None),
    }
    # --model-condition wins over --model when both are present.
    if raw.get("model_condition"):
        raw["model"] = None
    return normalize_b_term_filters(**raw)


def _has_condition_or_factor(args: argparse.Namespace) -> bool:
    cond = str(getattr(args, "condition", None) or "").strip()
    factor = str(getattr(args, "factor", None) or "").strip()
    return bool(cond or factor)


def _require_condition_or_factor(args: argparse.Namespace, mode: str) -> Optional[int]:
    """Return exit code 2 if neither --condition nor --factor is set."""
    if _has_condition_or_factor(args):
        return None
    print(
        f"{mode} mode requires either --condition or --factor "
        "(one is enough; both may be combined)",
        file=sys.stderr,
    )
    return 2


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
    p.add_argument(
        "--condition",
        help=(
            "B_terms condition (e.g. \"Colorectal Cancer\"). "
            "Required unless --factor is set (either condition or factor)."
        ),
    )
    p.add_argument(
        "--category",
        default=None,
        help='B_terms category filter (e.g. "Drug Screening"); omit for all categories',
    )
    p.add_argument(
        "--model",
        default="Organoid",
        help=(
            "B_terms model_condition filter (default: Organoid). "
            "Pass an empty string to disable the model filter."
        ),
    )
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
    p.add_argument(
        "--pathway-mode",
        choices=["union", "majority"],
        default="majority",
        help=(
            "Per-record pathway combine then GSE recurrence cut. "
            "majority (default, paper/OCSP evaluation): pairwise majority on "
            "enrich/gsea/gsva with single-method fallback; "
            "union: per-record union of pathway sources. "
            "Both then apply --min-dataset-freq."
        ),
    )
    p.add_argument(
        "--pathway-sources",
        default="enrich,gsea,gsva",
        help=(
            "Comma-separated B_terms pathway keys to use "
            "(default: enrich,gsea,gsva — all sources)"
        ),
    )
    p.add_argument(
        "--min-dataset-freq",
        type=int,
        default=None,
        help=(
            "Minimum datasets (GSE IDs) a pathway term must appear in. "
            "Default: auto — 6 for data-rich conditions "
            "(>=30 matched datasets, e.g. Colorectal Cancer), else 1"
        ),
    )
    _add_b_term_filter_arguments(p)

    # expression
    p.add_argument("--matrix", help="[expression] matrix TSV/CSV (abs or relative path)")
    p.add_argument("--groups", help="[expression] groups TSV/CSV")
    p.add_argument(
        "--data-type",
        choices=["microarray", "rnaseq_count", "rnaseq", "normalized"],
        default=None,
        help=(
            "[expression] data type (rnaseq → rnaseq_count). Optional: omit to "
            "auto-infer from the matrix; count-like matrices wrongly labeled "
            "normalized/microarray are corrected to rnaseq_count"
        ),
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

    missing = [n for n in ("matrix", "groups") if not getattr(args, n)]
    if missing:
        print(
            f"expression mode requires: --matrix --groups "
            f"and either --condition or --factor "
            f"(--data-type optional; auto-inferred from the matrix)\n"
            f"missing: {', '.join('--' + m.replace('_', '-') for m in missing)}",
            file=sys.stderr,
        )
        return 2
    bad = _require_condition_or_factor(args, "expression")
    if bad is not None:
        return bad

    try:
        ensure_data_available(args.species)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        pathway_sources = _parse_pathway_sources(args.pathway_sources)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    ranked = run_expression_biomarker_pipeline(
        matrix_path=args.matrix,
        groups_path=args.groups,
        data_type=args.data_type,
        condition=args.condition or "",
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
        pathway_mode=args.pathway_mode,
        pathway_sources=pathway_sources,
        min_dataset_freq=args.min_dataset_freq,
        model=args.model,
        category=args.category,
        b_filters=_b_filters_from_args(args),
    )
    print(f"[expression] ranked {len(ranked)} genes")
    print(f"Results: {Path(args.outdir) / 'biomarker_ranked.json'}")
    return 0


def _run_genes(args: argparse.Namespace) -> int:
    from orbit_ocsp.data_manager import ensure_data_available
    from orbit_ocsp.expression_pipeline import run_genes_biomarker_pipeline

    bad = _require_condition_or_factor(args, "genes")
    if bad is not None:
        return bad
    gene_list = _parse_genes(args.genes, args.genes_file)
    if not gene_list:
        print("genes mode requires: --genes A,B,C  or  --genes-file path", file=sys.stderr)
        return 2

    try:
        ensure_data_available(args.species)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        pathway_sources = _parse_pathway_sources(args.pathway_sources)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    ranked = run_genes_biomarker_pipeline(
        genes=gene_list,
        condition=args.condition or "",
        species=args.species,
        outdir=args.outdir,
        merged_result=args.merged_result,
        b_terms=args.b_terms,
        alpha=args.alpha,
        seed=args.seed,
        pathway_mode=args.pathway_mode,
        pathway_sources=pathway_sources,
        min_dataset_freq=args.min_dataset_freq,
        model=args.model,
        category=getattr(args, "category", None),
        b_filters=_b_filters_from_args(args),
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

    if not args.merge_only:
        bad = _require_condition_or_factor(args, "sequence")
        if bad is not None:
            return bad

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
        pathway_sources = _parse_pathway_sources(args.pathway_sources)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

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
            pathway_mode=args.pathway_mode,
            pathway_sources=pathway_sources,
            min_dataset_freq=args.min_dataset_freq,
            model=args.model,
            category=getattr(args, "category", None),
            b_filters=_b_filters_from_args(args),
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
