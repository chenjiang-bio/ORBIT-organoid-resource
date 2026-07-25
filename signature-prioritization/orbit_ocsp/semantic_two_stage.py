"""Label-blind two-stage Resnik/Lin screening and formal inference."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from orbit_ocsp.permutation_test_terms import (
    _configure_go_resources,
    _ensemble_run_single_method,
)


SEMANTIC_METHODS = ("resnik_bma", "lin_bma")
_WORKER_DATA: dict[str, Any] = {}


def formal_selection_decision(
    method_results: list[dict[str, Any]],
    p_threshold: float = 0.10,
) -> tuple[bool, list[str]]:
    """Apply the pre-specified label-free screening rule."""
    by_method = {
        str(result.get("method")): result
        for result in method_results
        if result.get("method") in SEMANTIC_METHODS
    }
    passing = [
        method
        for method in SEMANTIC_METHODS
        if method in by_method
        and float(by_method[method]["p_value"]) <= p_threshold
        and float(by_method[method]["effect_size"]) > 0.0
    ]
    return bool(passing), passing


def select_formal_candidates(
    screening_results: dict[str, list[dict[str, Any]]],
    p_threshold: float = 0.10,
) -> dict[str, Any]:
    """Build a selection manifest using semantic outputs only."""
    decisions = []
    selected = []
    for sample_id in sorted(screening_results):
        is_selected, passing_methods = formal_selection_decision(
            screening_results[sample_id],
            p_threshold=p_threshold,
        )
        if is_selected:
            selected.append(sample_id)
        decisions.append(
            {
                "sample_id": sample_id,
                "selected": is_selected,
                "passing_screening_methods": passing_methods,
            }
        )
    return {
        "selection_rule": (
            f"either semantic method has effect_size > 0 and p_value <= "
            f"{p_threshold:g}"
        ),
        "p_threshold": p_threshold,
        "selection_is_label_blind": True,
        "formal_methods": list(SEMANTIC_METHODS),
        "screened_count": len(screening_results),
        "selected_count": len(selected),
        "selected_sample_ids": selected,
        "decisions": decisions,
    }


def load_pairs_from_reference(
    reference_dir: str | Path,
) -> list[dict[str, str]]:
    """Load gene/condition identifiers without reading evaluation labels."""
    rows = []
    root = Path(reference_dir) / "gene_reports"
    for path in sorted(root.glob("*/ENSEMBLE.json")):
        with path.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
        config = report.get("config") or {}
        gene = str(config.get("gene_name", "")).strip()
        condition = str(config.get("condition", "")).strip()
        if gene and condition:
            rows.append(
                {
                    "sample_id": path.parent.name,
                    "gene_name": gene,
                    "condition": condition,
                }
            )
    return rows


def _load_inputs(
    gene_annotations: str | Path,
    condition_terms: str | Path,
    universe_terms: str | Path,
) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    with Path(gene_annotations).open("r", encoding="utf-8") as handle:
        gene_rows = json.load(handle)
    genes: dict[str, set[str]] = {}
    for row in gene_rows:
        gene = str(row.get("similarity_gene_name", "")).strip()
        if gene:
            genes.setdefault(gene, set()).update(
                str(term) for term in row.get("pathway", [])
            )
    with Path(condition_terms).open("r", encoding="utf-8") as handle:
        condition_rows = json.load(handle)
    conditions: dict[str, set[str]] = {}
    for row in condition_rows:
        condition = str(row.get("condition", "")).strip()
        if condition:
            conditions.setdefault(condition, set()).update(
                str(term) for term in row.get("pathway", [])
            )
    with Path(universe_terms).open("r", encoding="utf-8") as handle:
        universe_data = json.load(handle)
    if isinstance(universe_data, dict):
        universe = set(str(term) for term in universe_data)
    else:
        universe = set(str(term) for term in universe_data)
    return genes, conditions, universe


def _worker_initialize(
    gene_annotations: str,
    condition_terms: str,
    universe_terms: str,
    ancestors: str,
    ic: str,
    namespace: str,
) -> None:
    genes, conditions, universe = _load_inputs(
        gene_annotations,
        condition_terms,
        universe_terms,
    )
    _WORKER_DATA.clear()
    _WORKER_DATA.update(
        {
            "genes": genes,
            "conditions": conditions,
            "universe": universe,
        }
    )
    _configure_go_resources(ancestors, ic, namespace)


def _pair_seed(base_seed: int, sample_id: str) -> int:
    digest = hashlib.sha256(f"{base_seed}:{sample_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _write_result_atomic(
    output_dir: str | Path,
    pair: dict[str, str],
    results: list[Any],
    permutations: int,
    base_seed: int,
    semantic_term_cap: int | None,
    stage: str,
) -> Path:
    destination = (
        Path(output_dir)
        / "gene_reports"
        / pair["sample_id"]
        / "ENSEMBLE.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "type": "semantic_two_stage",
            "stage": stage,
            "selection_is_label_blind": True,
        },
        "config": {
            "gene_name": pair["gene_name"],
            "condition": pair["condition"],
            "sample_id": pair["sample_id"],
            "methods": list(SEMANTIC_METHODS),
            "semantic_permutations": permutations,
            "semantic_term_cap": semantic_term_cap,
            "base_seed": base_seed,
            "pair_seed": _pair_seed(base_seed, pair["sample_id"]),
        },
        "individual_methods": [asdict(result) for result in results],
    }
    temporary = destination.with_suffix(
        f".json.tmp.{os.getpid()}"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def _run_pair(
    pair: dict[str, str],
    output_dir: str,
    permutations: int,
    base_seed: int,
    semantic_term_cap: int | None,
    stage: str,
) -> dict[str, Any]:
    genes = _WORKER_DATA["genes"]
    conditions = _WORKER_DATA["conditions"]
    universe = _WORKER_DATA["universe"]
    a_terms = set(genes.get(pair["gene_name"], set())) & universe
    b_terms = set(conditions.get(pair["condition"], set())) & universe
    if not a_terms or not b_terms:
        return {
            "sample_id": pair["sample_id"],
            "status": "error",
            "error": "missing gene or condition terms",
        }
    pair_seed = _pair_seed(base_seed, pair["sample_id"])
    results = [
        _ensemble_run_single_method(
            method,
            a_terms,
            b_terms,
            universe,
            R_value=permutations,
            alpha=0.05,
            seed=pair_seed,
            component_tests=False,
            semantic_term_cap=semantic_term_cap,
        )
        for method in SEMANTIC_METHODS
    ]
    if any(result.verdict == "error" for result in results):
        return {
            "sample_id": pair["sample_id"],
            "status": "error",
            "error": "; ".join(
                str(result.metadata.get("error", "semantic method error"))
                for result in results
                if result.verdict == "error"
            ),
        }
    path = _write_result_atomic(
        output_dir,
        pair,
        results,
        permutations,
        base_seed,
        semantic_term_cap,
        stage,
    )
    return {
        "sample_id": pair["sample_id"],
        "status": "complete",
        "path": str(path),
    }


def _result_is_complete(
    output_dir: str | Path,
    sample_id: str,
    permutations: int,
) -> bool:
    path = Path(output_dir) / "gene_reports" / sample_id / "ENSEMBLE.json"
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
        methods = {
            result.get("method"): result
            for result in report.get("individual_methods", [])
        }
        return all(
            method in methods
            and int(methods[method].get("metadata", {}).get("R", -1))
            == permutations
            for method in SEMANTIC_METHODS
        )
    except (OSError, ValueError, TypeError):
        return False


def run_stage(
    pairs: list[dict[str, str]],
    output_dir: str | Path,
    permutations: int,
    base_seed: int,
    semantic_term_cap: int | None,
    stage: str,
    workers: int,
    initializer_args: tuple[str, str, str, str, str, str],
    resume: bool = True,
) -> list[dict[str, Any]]:
    """Run one semantic stage with resumable process-level parallelism."""
    pending = [
        pair
        for pair in pairs
        if not (
            resume
            and _result_is_complete(
                output_dir,
                pair["sample_id"],
                permutations,
            )
        )
    ]
    statuses: list[dict[str, Any]] = [
        {"sample_id": pair["sample_id"], "status": "skipped_complete"}
        for pair in pairs
        if pair not in pending
    ]
    if not pending:
        return statuses
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        initializer=_worker_initialize,
        initargs=initializer_args,
    ) as executor:
        futures = {
            executor.submit(
                _run_pair,
                pair,
                str(output_dir),
                permutations,
                base_seed,
                semantic_term_cap,
                stage,
            ): pair["sample_id"]
            for pair in pending
        }
        for future in concurrent.futures.as_completed(futures):
            sample_id = futures[future]
            try:
                statuses.append(future.result())
            except Exception as exc:
                statuses.append(
                    {
                        "sample_id": sample_id,
                        "status": "error",
                        "error": repr(exc),
                    }
                )
    return sorted(statuses, key=lambda item: str(item["sample_id"]))


def load_screening_results(
    output_dir: str | Path,
) -> dict[str, list[dict[str, Any]]]:
    results = {}
    for path in sorted(
        (Path(output_dir) / "gene_reports").glob("*/ENSEMBLE.json")
    ):
        with path.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
        results[path.parent.name] = report.get("individual_methods", [])
    return results


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run label-blind 50-to-999 semantic inference"
    )
    parser.add_argument("--reference-dir", required=True)
    parser.add_argument("--gene-annotations", required=True)
    parser.add_argument("--condition-terms", required=True)
    parser.add_argument("--universe-terms", required=True)
    parser.add_argument("--ancestors", required=True)
    parser.add_argument("--ic", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--screening-output", required=True)
    parser.add_argument("--formal-output", required=True)
    parser.add_argument("--screening-permutations", type=int, default=50)
    parser.add_argument("--formal-permutations", type=int, default=999)
    parser.add_argument("--selection-p", type=float, default=0.10)
    parser.add_argument("--semantic-term-cap", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--stage",
        choices=("screening", "formal", "both"),
        default="both",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.screening_permutations != 50:
        parser.error("screening-permutations must be exactly 50")
    if args.formal_permutations < 999:
        parser.error("formal-permutations must be at least 999")
    pairs = load_pairs_from_reference(args.reference_dir)
    initializer_args = (
        args.gene_annotations,
        args.condition_terms,
        args.universe_terms,
        args.ancestors,
        args.ic,
        args.namespace,
    )
    if args.stage in {"screening", "both"}:
        statuses = run_stage(
            pairs,
            args.screening_output,
            args.screening_permutations,
            args.seed,
            args.semantic_term_cap or None,
            "screening",
            args.workers,
            initializer_args,
        )
        print(
            "screening:",
            sum(item["status"] in {"complete", "skipped_complete"} for item in statuses),
            "complete;",
            sum(item["status"] == "error" for item in statuses),
            "errors",
        )

    screening = load_screening_results(args.screening_output)
    selection = select_formal_candidates(
        screening,
        p_threshold=args.selection_p,
    )
    formal_root = Path(args.formal_output)
    formal_root.mkdir(parents=True, exist_ok=True)
    selection_path = formal_root / "selection_manifest.json"
    selection_path.write_text(
        json.dumps(selection, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"selected: {selection['selected_count']}/{selection['screened_count']}"
    )

    if args.stage in {"formal", "both"}:
        pair_map = {pair["sample_id"]: pair for pair in pairs}
        selected_pairs = [
            pair_map[sample_id]
            for sample_id in selection["selected_sample_ids"]
            if sample_id in pair_map
        ]
        statuses = run_stage(
            selected_pairs,
            args.formal_output,
            args.formal_permutations,
            args.seed,
            args.semantic_term_cap or None,
            "formal",
            args.workers,
            initializer_args,
        )
        print(
            "formal:",
            sum(item["status"] in {"complete", "skipped_complete"} for item in statuses),
            "complete;",
            sum(item["status"] == "error" for item in statuses),
            "errors",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
