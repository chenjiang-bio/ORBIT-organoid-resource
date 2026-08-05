"""Expression-matrix → DE → top-k → protein map → biomarker scoring pipeline."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Union

import pandas as pd

from orbit_ocsp.expression_de import (
    VALID_DATA_TYPES,
    add_full_table_de_rank,
    filter_and_topk,
    normalize_data_type,
    read_expression_matrix,
    read_group_table,
    resolve_data_type,
    run_differential_expression,
    subset_matrix_to_groups,
)
from orbit_ocsp.protein_lookup import map_gene_ids_to_proteins, project_root
from orbit_ocsp.b_terms_schema import (
    DEFAULT_MODEL,
    DEFAULT_PATHWAY_SOURCES,
    count_condition_datasets,
    normalize_b_term_filters,
    resolve_min_dataset_freq,
)

_PKG_ROOT = project_root()

ScoreFn = Callable[..., Optional[dict]]


def _resolve_default(relpath: str) -> str:
    from orbit_ocsp.data_manager import resolve_data_path

    return resolve_data_path(relpath)


def _go_url(tid: str) -> str:
    tid = str(tid)
    if not tid.startswith("GO:"):
        return ""
    return f"https://amigo.geneontology.org/amigo/term/{tid}"


def _kegg_url(pid: str) -> str:
    return f"https://www.kegg.jp/pathway/{pid}"


def _safe_pair_directory(gene: str, condition: str) -> str:
    safe_condition = re.sub(r"[^\w\s-]", "", condition).strip()
    safe_condition = re.sub(r"[-\s]+", "_", safe_condition)
    return f"{gene}__{safe_condition}"


def load_gene_pathways(merged_result_file: Union[str, Path]) -> Dict[str, List[str]]:
    """Load gene → pathway terms from ``all_merged_result.json``.

    Indexed by gene symbol, upper-cased symbol, and Entrez ID when available.
    """
    with open(merged_result_file, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    gene_pathways: Dict[str, List[str]] = {}
    for item in data:
        pathways = item.get("pathway", [])
        if not pathways:
            continue
        pathway_list = list(pathways)
        gene_name = str(item.get("similarity_gene_name", "")).strip()
        entrez = str(item.get("ENTREZ_ID", "")).strip()
        if gene_name:
            gene_pathways.setdefault(gene_name, pathway_list)
            gene_pathways.setdefault(gene_name.upper(), pathway_list)
        if entrez:
            gene_pathways.setdefault(entrez, pathway_list)
    return gene_pathways


def _pathways_for_gene(
    gene_pathways: Dict[str, List[str]],
    query_id: str,
    protein: dict,
) -> List[str]:
    """Resolve pathways using symbol / Entrez / original query ID."""
    candidates = [
        protein.get("gene_symbol"),
        (protein.get("gene_symbol") or "").upper() or None,
        protein.get("entrez_id"),
        query_id,
        query_id.upper(),
    ]
    for key in candidates:
        if key and key in gene_pathways:
            return gene_pathways[key]
    return []


def load_condition_terms(
    b_terms_file: Union[str, Path],
    condition: str,
    *,
    category: Optional[str] = None,
    model: Optional[str] = DEFAULT_MODEL,
    model_condition: Optional[str] = None,
    model_control: Optional[str] = None,
    organ: Optional[str] = None,
    organ_condition: Optional[str] = None,
    organ_control: Optional[str] = None,
    organ_system_condition: Optional[str] = None,
    organ_system_control: Optional[str] = None,
    factor: Optional[str] = None,
    source: Optional[str] = None,
    source_condition: Optional[str] = None,
    source_control: Optional[str] = None,
    cell_type: Optional[str] = None,
    time: Optional[str] = None,
    time_condition: Optional[str] = None,
    time_control: Optional[str] = None,
    additional_condition: Optional[str] = None,
    comparison_control: Optional[str] = None,
    comparison_condition: Optional[str] = None,
    pathway_mode: str = "majority",
    min_record_freq: int = 1,
    min_dataset_freq: Optional[int] = None,
    pathway_sources: Sequence[str] = DEFAULT_PATHWAY_SOURCES,
) -> List[str]:
    """Load pathway terms for one condition from current B_terms JSON.

    Supports paired filters: organ_condition/organ_control,
    source_condition/source_control, time_condition/time_control,
    model_condition/model_control. Pathway default: all of
    ``pathway.{enrich,gsea,gsva}``. Model defaults to ``Organoid``.
    ``min_dataset_freq=None`` auto-selects 6 for data-rich conditions, else 1.
    """
    from orbit_ocsp.b_terms_schema import load_condition_pathways

    with open(b_terms_file, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError(f"Unexpected B_terms format: {b_terms_file}")
    return load_condition_pathways(
        data,
        condition,
        category=category,
        model=model,
        model_condition=model_condition,
        model_control=model_control,
        organ=organ,
        organ_condition=organ_condition,
        organ_control=organ_control,
        organ_system_condition=organ_system_condition,
        organ_system_control=organ_system_control,
        factor=factor,
        source=source,
        source_condition=source_condition,
        source_control=source_control,
        cell_type=cell_type,
        time=time,
        time_condition=time_condition,
        time_control=time_control,
        additional_condition=additional_condition,
        comparison_control=comparison_control,
        comparison_condition=comparison_condition,
        pathway_sources=pathway_sources,
        pathway_mode=pathway_mode,
        min_record_freq=min_record_freq,
        min_dataset_freq=min_dataset_freq,
    )


def load_universe_and_meta(species: str = "hsa") -> tuple[Set[str], dict, dict]:
    """Load U terms plus GO/KEGG metadata for a species code (hsa/mmu)."""
    species = species.strip().lower()
    if species in {"human"}:
        species = "hsa"
    elif species in {"mouse"}:
        species = "mmu"
    if species not in {"hsa", "mmu"}:
        raise ValueError(f"Unsupported scoring species {species!r}")

    u_path = _resolve_default(f"data/data_u/U_terms_GO_KEGG_{species}.json")
    with open(u_path, "r", encoding="utf-8") as handle:
        u_data = json.load(handle)
    u_terms = set(u_data) if isinstance(u_data, list) else set()

    go_meta: dict = {}
    try:
        with open(_resolve_default("data/meta/go_meta.json"), "r", encoding="utf-8") as handle:
            go_meta = json.load(handle)
    except OSError:
        pass

    kegg_meta: dict = {}
    try:
        kegg_path = _resolve_default(f"data/meta/kegg_meta_{species}.json")
        with open(kegg_path, "r", encoding="utf-8") as handle:
            kegg_meta = json.load(handle)
    except OSError:
        pass
    return u_terms, go_meta, kegg_meta


def annotation_links(pathways: Sequence[str], max_links: int = 8) -> dict:
    """Build AmiGO / KEGG / NCBI-ready annotation link bundles."""
    go_ids = [p for p in pathways if str(p).upper().startswith("GO:")]
    kegg_ids = [
        p
        for p in pathways
        if re.match(r"^(hsa|mmu|map|ko)\d{5}$", str(p), flags=re.IGNORECASE)
    ]
    return {
        "go_links": [
            {"term": tid, "url": _go_url(tid)} for tid in go_ids[:max_links]
        ],
        "kegg_links": [
            {"term": pid, "url": _kegg_url(pid)} for pid in kegg_ids[:max_links]
        ],
    }


def default_score_gene(
    gene: str,
    condition: str,
    gene_pathways: Dict[str, List[str]],
    b_terms_file: Union[str, Path],
    u_terms: Set[str],
    go_meta: dict,
    kegg_meta: dict,
    output_dir: Path,
    species: str = "hsa",
    alpha: float = 0.005,
    seed: int = 42,
    semantic_term_cap: int = 100,
    pathway_mode: str = "majority",
    pathway_sources: Sequence[str] = DEFAULT_PATHWAY_SOURCES,
    min_dataset_freq: Optional[int] = None,
    model: Optional[str] = DEFAULT_MODEL,
    category: Optional[str] = None,
    b_filters: Optional[Mapping[str, Any]] = None,
) -> Optional[dict]:
    """Score one gene with label-blind 50→999 semantic inference.

    ``b_filters`` carries optional B_terms metadata filters (factor, organ_*,
    source_*, cell_type, time_*, comparison_*, additional_condition, …).
    ``category`` / ``model`` remain first-class for backward compatibility.
    """
    from orbit_ocsp.permutation_test_terms import (
        _configure_go_resources,
        _ensemble_calculate_consensus,
        _ensemble_generate_report,
        _run_ensemble_analysis_core,
    )
    from orbit_ocsp.semantic_two_stage import formal_selection_decision

    a_terms = set(gene_pathways.get(gene, [])) & u_terms
    if not a_terms:
        return None

    filter_kwargs = dict(b_filters or {})
    if category is not None and "category" not in filter_kwargs:
        filter_kwargs["category"] = category
    if (
        model is not None
        and "model" not in filter_kwargs
        and "model_condition" not in filter_kwargs
    ):
        filter_kwargs["model"] = model
    filters = normalize_b_term_filters(**filter_kwargs)

    b_terms = set(
        load_condition_terms(
            b_terms_file,
            condition,
            pathway_mode=pathway_mode,
            pathway_sources=pathway_sources or DEFAULT_PATHWAY_SOURCES,
            min_dataset_freq=min_dataset_freq,
            **filters,
        )
    ) & u_terms
    if not b_terms:
        return None

    gene_dir = output_dir / "gene_reports" / _safe_pair_directory(gene, condition)
    gene_dir.mkdir(parents=True, exist_ok=True)
    semantic_root = Path(_resolve_default("data/semantic_resources_v2"))
    _configure_go_resources(
        str(semantic_root / "go_ancestors.json"),
        str(semantic_root / "go_ic.json"),
        str(semantic_root / "go_namespace.json"),
    )
    methods = ["hypergeometric", "jaccard", "overlap", "resnik_bma", "lin_bma"]
    r_values = {
        "hypergeometric": 0,
        "jaccard": 200,
        "overlap": 200,
        "resnik_bma": 50,
        "lin_bma": 50,
    }
    config = {
        "condition": condition,
        "gene_name": gene,
        "species": species if species in {"hsa", "mmu"} else "hsa",
        "ensemble_methods": methods,
        "alpha": alpha,
        "seed": seed,
    }
    result = _run_ensemble_analysis_core(
        A=a_terms,
        B=b_terms,
        U=u_terms,
        methods=methods,
        r_values=r_values,
        alpha=alpha,
        seed=seed,
        go_meta=go_meta,
        kegg_meta=kegg_meta,
        output_dir=str(gene_dir),
        config=config,
        level_label=f"Gene: {gene}, Condition: {condition}",
        parallel=False,
        component_tests=False,
        semantic_term_cap=semantic_term_cap,
    )
    screening_semantic = [
        {
            "method": item.method,
            "p_value": item.p_value,
            "effect_size": item.effect_size,
        }
        for item in result.individual_results
        if item.method in {"resnik_bma", "lin_bma"}
    ]
    selected_formal, passing_methods = formal_selection_decision(
        screening_semantic, p_threshold=0.10
    )
    semantic_stage = "screening"
    semantic_permutations = 50
    if selected_formal:
        formal = _run_ensemble_analysis_core(
            A=a_terms,
            B=b_terms,
            U=u_terms,
            methods=["resnik_bma", "lin_bma"],
            r_values={"resnik_bma": 999, "lin_bma": 999},
            alpha=alpha,
            seed=seed,
            go_meta=go_meta,
            kegg_meta=kegg_meta,
            output_dir=str(gene_dir),
            config=config,
            level_label=f"Formal gene: {gene}, Condition: {condition}",
            parallel=False,
            component_tests=False,
            semantic_term_cap=semantic_term_cap,
        )
        formal_by_method = {
            item.method: item for item in formal.individual_results
        }
        result.individual_results = [
            formal_by_method.get(item.method, item)
            for item in result.individual_results
        ]
        verdict, consensus, agreement, confidence, primary_p = (
            _ensemble_calculate_consensus(result.individual_results, alpha=alpha)
        )
        result.verdict = verdict
        result.consensus_score = consensus
        result.agreement = agreement
        result.confidence = confidence
        result.primary_p_value = primary_p
        result.combined_p_value = primary_p
        semantic_stage = "formal"
        semantic_permutations = 999
    _ensemble_generate_report(
        ensemble_result=result,
        output_dir=str(gene_dir),
        config=config,
        method_details={},
        A_terms=list(a_terms),
        B_terms=list(b_terms),
        U_size=len(u_terms),
        go_meta=go_meta,
        kegg_meta=kegg_meta,
        group_metadata=None,
        gene_data={"gene_name": gene, "pathway": list(a_terms)},
    )
    overlapping = sorted(a_terms & b_terms)
    ordered_methods = sorted(
        result.individual_results, key=lambda item: (item.p_value, item.method)
    )
    return {
        "verdict": result.verdict,
        "confidence": result.confidence,
        "consensus_score": result.consensus_score,
        "agreement": result.agreement,
        "total_methods": result.total_methods,
        "primary_p_value": getattr(result, "primary_p_value", None)
        or result.combined_p_value,
        # BH-adjusted across candidates once the whole list is scored; filled
        # in by ``apply_primary_fdr`` before the outputs are written.
        "primary_q_value": None,
        "report_dir": str(Path("gene_reports") / _safe_pair_directory(gene, condition)),
        "n_a_terms": len(a_terms),
        "n_b_terms": len(b_terms),
        "n_overlap_terms": len(overlapping),
        "overlap_terms": overlapping[:20],
        "semantic_stage": semantic_stage,
        "semantic_permutations": semantic_permutations,
        "formal_selection_methods": passing_methods,
        "semantic_resource": "data/semantic_resources_v2",
        "individual_methods": [
            {
                "method": item.method,
                "observed_statistic": item.s_obs,
                "p_value": item.p_value,
                "effect_size": item.effect_size,
                "verdict": item.verdict,
                "inference_stage": item.metadata.get("inference_stage"),
                "rank": rank,
                "permutations": item.metadata.get("R"),
                "metadata": item.metadata,
            }
            for rank, item in enumerate(ordered_methods, start=1)
        ],
        **annotation_links(overlapping or sorted(a_terms)[:8]),
    }


def run_expression_biomarker_pipeline(
    matrix_path: Union[str, Path],
    groups_path: Union[str, Path],
    data_type: Optional[str] = None,
    condition: str = "",
    species: str = "hsa",
    top_k: int = 20,
    padj_max: float = 0.05,
    abs_log2fc_min: float = 1.0,
    outdir: Union[str, Path] = "out_expression_biomarker",
    merged_result: Optional[Union[str, Path]] = None,
    b_terms: Optional[Union[str, Path]] = None,
    protein_root: Optional[Union[str, Path]] = None,
    de_backend: Union[str, Callable] = "r",
    de_results_path: Optional[Union[str, Path]] = None,
    score_fn: Optional[ScoreFn] = None,
    skip_scoring: bool = False,
    alpha: float = 0.005,
    seed: int = 42,
    pathway_mode: str = "majority",
    pathway_sources: Sequence[str] = DEFAULT_PATHWAY_SOURCES,
    min_dataset_freq: Optional[int] = None,
    model: Optional[str] = DEFAULT_MODEL,
    category: Optional[str] = None,
    b_filters: Optional[Mapping[str, Any]] = None,
) -> List[dict]:
    """Run the full expression → biomarker prioritization pipeline.

    ``data_type`` may be omitted: it is inferred from the matrix (and
    count-like matrices wrongly labeled ``normalized``/``microarray`` are
    corrected to ``rnaseq_count``).

    ``b_filters`` optionally restricts the B_terms background (factor,
    organ_condition/organ_control, source_*, cell_type, time_*, …).
    """
    pathway_sources = (
        tuple(pathway_sources) if pathway_sources else DEFAULT_PATHWAY_SOURCES
    )
    # Empty string disables the model filter; None keeps the Organoid default.
    if model is None:
        model = DEFAULT_MODEL
    model = str(model).strip()
    category = (str(category).strip() or None) if category is not None else None
    filter_kwargs = dict(b_filters or {})
    if category is not None and "category" not in filter_kwargs:
        filter_kwargs["category"] = category
    if "model" not in filter_kwargs and "model_condition" not in filter_kwargs:
        filter_kwargs["model"] = model
    b_filters_resolved = normalize_b_term_filters(**filter_kwargs)

    factor = str((b_filters_resolved or {}).get("factor") or "").strip()
    if not str(condition or "").strip() and not factor:
        raise ValueError("either condition or factor is required")

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    species_key = species.strip().lower()
    scoring_species = (
        "hsa"
        if species_key in {"hsa", "human"}
        else "mmu"
        if species_key in {"mmu", "mouse"}
        else species_key
    )

    # Resolve once up front so pipeline_summary records the effective type,
    # including auto-inference / count-mismatch correction.
    if de_results_path is None:
        matrix = read_expression_matrix(matrix_path)
        groups = read_group_table(groups_path)
        matrix, groups = subset_matrix_to_groups(matrix, groups)
        data_type, _scale = resolve_data_type(matrix, data_type)
    elif data_type is None or not str(data_type).strip():
        data_type = "rnaseq_count"  # unused for DE when results are precomputed
    else:
        data_type = normalize_data_type(data_type)

    de_table = run_differential_expression(
        matrix_path=matrix_path,
        groups_path=groups_path,
        data_type=data_type,
        outdir=outdir,
        backend=de_backend,
        de_results_path=de_results_path,
        seed=seed,
        # Already resolved above; avoid double-warning on count overrides.
        check_data_type=False,
    )
    top_genes = filter_and_topk(
        de_table,
        padj_max=padj_max,
        abs_log2fc_min=abs_log2fc_min,
        k=top_k,
    )
    # Rank across the whole DE table so rank_gain measures the move from the
    # gene's original differential-expression position, not its position
    # within the already-filtered shortlist.
    full_ranked = add_full_table_de_rank(de_table)
    de_rank_full_by_gene = dict(
        zip(full_ranked["gene"].astype(str), full_ranked["de_rank_full"])
    )
    top_path = outdir / "topk_de_genes.tsv"
    top_genes.to_csv(top_path, sep="\t", index=False)

    query_ids = top_genes["gene"].astype(str).tolist()
    protein_rows = map_gene_ids_to_proteins(
        query_ids,
        species=species_key,
        protein_root=protein_root or "data/protein",
    )
    protein_by_query = {row["query_id"]: row for row in protein_rows}

    gene_pathways: Dict[str, List[str]] = {}
    u_terms: Set[str] = set()
    go_meta: dict = {}
    kegg_meta: dict = {}
    b_terms_path: Optional[Path] = None
    n_condition_datasets = 0
    resolved_min_dataset_freq: Optional[int] = None
    if not skip_scoring:
        merged_path = Path(
            merged_result
            or _resolve_default("data/protein/all_merged_result.json")
        )
        if not merged_path.exists():
            raise FileNotFoundError(f"Merged pathway file not found: {merged_path}")
        gene_pathways = load_gene_pathways(merged_path)
        default_b = f"data/data_b/B_terms_{scoring_species}.json"
        b_terms_path = Path(b_terms or _resolve_default(default_b))
        if not b_terms_path.exists():
            raise FileNotFoundError(f"B_terms file not found: {b_terms_path}")
        u_terms, go_meta, kegg_meta = load_universe_and_meta(scoring_species)
        with open(b_terms_path, "r", encoding="utf-8") as handle:
            b_records = json.load(handle)
        if isinstance(b_records, dict):
            b_records = [b_records]
        n_condition_datasets = count_condition_datasets(
            b_records,
            condition,
            model=b_filters_resolved.get("model"),
            **{
                k: v
                for k, v in b_filters_resolved.items()
                if k not in {"model"}
            },
        )
        resolved_min_dataset_freq = resolve_min_dataset_freq(
            n_condition_datasets, min_dataset_freq
        )

    scorer = score_fn or default_score_gene
    ranked: List[dict] = []
    for _, de_row in top_genes.iterrows():
        query_id = str(de_row["gene"])
        protein = protein_by_query.get(query_id, {})
        # Pathway / report gene key prefers resolved symbol, then query ID.
        score_gene_key = protein.get("gene_symbol") or query_id
        record = {
            "de_rank": int(de_row["de_rank"]),
            "de_rank_full": (
                int(de_rank_full_by_gene[query_id])
                if query_id in de_rank_full_by_gene
                else None
            ),
            "query_id": query_id,
            "id_type": protein.get("id_type"),
            "gene_symbol": protein.get("gene_symbol"),
            "ensembl_id": protein.get("ensembl_id"),
            "log2FoldChange": float(de_row["log2FoldChange"]),
            "padj": float(de_row["padj"]),
            "entrez_id": protein.get("entrez_id"),
            "mapping_status": protein.get("mapping_status"),
            "fasta_relpath": protein.get("fasta_relpath"),
            "n_isoforms": protein.get("n_isoforms", 0),
            "sequence_preview": (
                (protein.get("sequence") or "")[:60] or None
            ),
            "ncbi_gene_url": (
                f"https://www.ncbi.nlm.nih.gov/gene/{protein['entrez_id']}"
                if protein.get("entrez_id")
                else None
            ),
            "condition": condition,
            "biomarker_score": None,
            "scoring_status": "skipped" if skip_scoring else "pending",
        }

        if skip_scoring:
            ranked.append(record)
            continue

        pathways = _pathways_for_gene(gene_pathways, query_id, protein)
        if not pathways:
            record["scoring_status"] = "no_pathway_annotation"
            ranked.append(record)
            continue

        # Ensure scorer can find pathways under the key we pass as gene=.
        gene_pathways.setdefault(score_gene_key, pathways)

        try:
            score = scorer(
                gene=score_gene_key,
                condition=condition,
                gene_pathways=gene_pathways,
                b_terms_file=b_terms_path,
                u_terms=u_terms,
                go_meta=go_meta,
                kegg_meta=kegg_meta,
                output_dir=outdir,
                species=scoring_species,
                alpha=alpha,
                seed=seed,
                pathway_mode=pathway_mode,
                pathway_sources=pathway_sources,
                min_dataset_freq=resolved_min_dataset_freq,
                model=b_filters_resolved.get("model", model or None),
                category=b_filters_resolved.get("category", category),
                b_filters=b_filters_resolved,
            )
        except TypeError:
            # Allow simpler mock scorers used in tests.
            score = scorer(gene, condition)  # type: ignore[misc]
        except Exception as exc:  # pragma: no cover - surfaced in output row
            record["scoring_status"] = f"error: {exc}"
            ranked.append(record)
            continue

        if score is None:
            record["scoring_status"] = "score_unavailable"
        else:
            record["scoring_status"] = "ok"
            record["biomarker_score"] = score
            if score.get("ncbi_gene_url") is None and record["ncbi_gene_url"]:
                score["ncbi_gene_url"] = record["ncbi_gene_url"]
        ranked.append(record)

    # Rank final biomarker list: scored genes first by consensus/primary p, then DE rank.
    def _sort_key(row: dict):
        """Rank by the primary hypergeometric p-value, ties broken by consensus.

        The primary test decides the enriched call, so it also drives the
        ranking; ``consensus_score`` only separates equal p-values. It takes
        just a few discrete values (agreement counts over five methods), so
        ordering by it first would collapse the ranking into plateaus.
        """
        score = row.get("biomarker_score") or {}
        consensus = score.get("consensus_score")
        primary_p = score.get("primary_p_value", score.get("combined_p_value"))
        has_score = 0 if row.get("scoring_status") == "ok" else 1
        return (
            has_score,
            float(primary_p) if primary_p is not None else 1.0,
            -float(consensus) if consensus is not None else 0.0,
            int(row.get("de_rank") or 10**9),
        )

    ranked.sort(key=_sort_key)
    for index, row in enumerate(ranked, start=1):
        row["biomarker_rank"] = index

    summary = {
        "mode": "expression",
        "n_de_genes_input": int(len(de_table)),
        "n_topk": int(len(top_genes)),
        "n_ranked": int(len(ranked)),
        "condition": condition,
        "category": b_filters_resolved.get("category", category),
        "b_filters": b_filters_resolved,
        "model": b_filters_resolved.get("model", model or None),
        "species": species_key,
        "data_type": data_type,
        "padj_max": padj_max,
        "abs_log2fc_min": abs_log2fc_min,
        "top_k": top_k,
        "pathway_mode": pathway_mode,
        "pathway_sources": list(pathway_sources),
        "min_dataset_freq_requested": min_dataset_freq,
        "min_dataset_freq": resolved_min_dataset_freq,
        "n_condition_datasets": int(n_condition_datasets),
        "outputs": {
            "de_results": str(outdir / "de_results.tsv"),
            "topk_de_genes": str(top_path),
        },
    }
    write_biomarker_outputs(ranked, outdir, summary)
    return ranked


def apply_primary_fdr(ranked: List[dict]) -> List[dict]:
    """BH-adjust the primary p-value across all scored candidates, in place.

    The methods section states the primary hypergeometric probability is
    "adjusted across candidates by the Benjamini-Hochberg procedure". The
    adjustment spans candidates, not the five within-candidate methods, which
    are correlated sensitivity analyses rather than independent hypotheses.
    """
    from orbit_ocsp.permutation_test_terms import _calculate_q_values

    scored = [
        row
        for row in ranked
        if (row.get("biomarker_score") or {}).get("primary_p_value") is not None
    ]
    if not scored:
        return ranked
    q_values = _calculate_q_values(
        [float(row["biomarker_score"]["primary_p_value"]) for row in scored]
    )
    for row, q_value in zip(scored, q_values):
        row["biomarker_score"]["primary_q_value"] = float(q_value)
    return ranked


def write_biomarker_outputs(
    ranked: List[dict],
    outdir: Union[str, Path],
    summary: dict,
) -> dict:
    """Write biomarker_ranked.json/.tsv, method_scores.tsv, pipeline_summary.json."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    apply_primary_fdr(ranked)
    results_json = outdir / "biomarker_ranked.json"
    results_tsv = outdir / "biomarker_ranked.tsv"
    results_json.write_text(json.dumps(ranked, indent=2), encoding="utf-8")

    flat_rows = []
    method_rows = []
    for row in ranked:
        score = row.get("biomarker_score") or {}
        by_method = {
            detail.get("method"): detail
            for detail in score.get("individual_methods", [])
        }
        for detail in score.get("individual_methods", []):
            method_rows.append(
                {
                    "biomarker_rank": row["biomarker_rank"],
                    "gene": row.get("gene_symbol") or row.get("query_id"),
                    "condition": row.get("condition"),
                    **{
                        key: value
                        for key, value in detail.items()
                        if key != "metadata"
                    },
                    # Repeated per row so this file is readable on its own:
                    # these are the gene-level call the methods feed into.
                    "gene_verdict": score.get("verdict"),
                    "gene_confidence": score.get("confidence"),
                    "consensus_score": score.get("consensus_score"),
                    "metadata_json": json.dumps(
                        detail.get("metadata", {}), ensure_ascii=False
                    ),
                }
            )
        de_rank_full = row.get("de_rank_full")
        flat_rows.append(
            {
                "biomarker_rank": row["biomarker_rank"],
                "de_rank": row.get("de_rank"),
                "de_rank_full": de_rank_full,
                # Positions gained by context-guided reranking, relative to the
                # gene's position in the full DE ranking. Positive = promoted.
                # Only defined when a DE ranking exists (expression mode).
                "rank_gain": (
                    int(de_rank_full) - int(row["biomarker_rank"])
                    if de_rank_full is not None and de_rank_full == de_rank_full
                    else None
                ),
                "query_id": row.get("query_id"),
                "id_type": row.get("id_type"),
                "gene_symbol": row.get("gene_symbol"),
                "ensembl_id": row.get("ensembl_id"),
                "entrez_id": row.get("entrez_id"),
                "log2FoldChange": row.get("log2FoldChange"),
                "padj": row.get("padj"),
                "mapping_status": row.get("mapping_status"),
                "fasta_relpath": row.get("fasta_relpath"),
                "scoring_status": row.get("scoring_status"),
                "verdict": score.get("verdict"),
                "confidence": score.get("confidence"),
                "consensus_score": score.get("consensus_score"),
                "primary_p_value": score.get("primary_p_value"),
                "primary_q_value": score.get("primary_q_value"),
                # Figure 5C sizes dots by the shared-pathway count and the 5D
                # table reports it, so it belongs in the flat view.
                "n_shared_pathways": score.get("n_overlap_terms"),
                **{
                    f"{method}_p_value": (by_method.get(method) or {}).get("p_value")
                    for method in [
                        "hypergeometric", "jaccard", "overlap",
                        "resnik_bma", "lin_bma",
                    ]
                },
                **{
                    f"{method}_effect_size": (by_method.get(method) or {}).get(
                        "effect_size"
                    )
                    for method in [
                        "hypergeometric", "jaccard", "overlap",
                        "resnik_bma", "lin_bma",
                    ]
                },
                "ncbi_gene_url": row.get("ncbi_gene_url"),
                "report_dir": score.get("report_dir"),
            }
        )
    pd.DataFrame(flat_rows).to_csv(results_tsv, sep="\t", index=False)
    method_columns = [
        "biomarker_rank", "gene", "condition", "method",
        "observed_statistic", "p_value", "effect_size", "verdict",
        "inference_stage", "rank", "permutations",
        "gene_verdict", "gene_confidence", "consensus_score",
        "metadata_json",
    ]
    pd.DataFrame(method_rows, columns=method_columns).to_csv(
        outdir / "method_scores.tsv", sep="\t", index=False
    )

    outputs = dict(summary.get("outputs") or {})
    outputs.update(
        {
            "biomarker_ranked_json": str(results_json),
            "biomarker_ranked_tsv": str(results_tsv),
            "method_scores": str(outdir / "method_scores.tsv"),
        }
    )
    summary = {**summary, "n_ranked": int(len(ranked)), "outputs": outputs}
    (outdir / "pipeline_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def run_genes_biomarker_pipeline(
    genes: Sequence[str],
    condition: str,
    species: str = "hsa",
    outdir: Union[str, Path] = "out_genes_biomarker",
    merged_result: Optional[Union[str, Path]] = None,
    b_terms: Optional[Union[str, Path]] = None,
    protein_root: Optional[Union[str, Path]] = None,
    score_fn: Optional[ScoreFn] = None,
    alpha: float = 0.005,
    seed: int = 42,
    pathway_mode: str = "majority",
    pathway_sources: Sequence[str] = DEFAULT_PATHWAY_SOURCES,
    min_dataset_freq: Optional[int] = None,
    model: Optional[str] = DEFAULT_MODEL,
    category: Optional[str] = None,
    b_filters: Optional[Mapping[str, Any]] = None,
) -> List[dict]:
    """Gene-list → pathway lookup → ensemble biomarker scoring (no DE)."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    pathway_sources = (
        tuple(pathway_sources) if pathway_sources else DEFAULT_PATHWAY_SOURCES
    )
    if model is None:
        model = DEFAULT_MODEL
    model = str(model).strip()
    category = (str(category).strip() or None) if category is not None else None
    filter_kwargs = dict(b_filters or {})
    if category is not None and "category" not in filter_kwargs:
        filter_kwargs["category"] = category
    if "model" not in filter_kwargs and "model_condition" not in filter_kwargs:
        filter_kwargs["model"] = model
    b_filters_resolved = normalize_b_term_filters(**filter_kwargs)

    factor = str((b_filters_resolved or {}).get("factor") or "").strip()
    if not str(condition or "").strip() and not factor:
        raise ValueError("either condition or factor is required")

    species_key = species.strip().lower()
    scoring_species = (
        "hsa"
        if species_key in {"hsa", "human"}
        else "mmu"
        if species_key in {"mmu", "mouse"}
        else species_key
    )

    query_ids = [str(g).strip() for g in genes if str(g).strip()]
    if not query_ids:
        raise ValueError("No genes provided")

    protein_rows = map_gene_ids_to_proteins(
        query_ids,
        species=species_key,
        protein_root=protein_root or "data/protein",
    )
    protein_by_query = {row["query_id"]: row for row in protein_rows}

    merged_path = Path(
        merged_result or _resolve_default("data/protein/all_merged_result.json")
    )
    if not merged_path.exists():
        raise FileNotFoundError(f"Merged pathway file not found: {merged_path}")
    gene_pathways = load_gene_pathways(merged_path)
    default_b = f"data/data_b/B_terms_{scoring_species}.json"
    b_terms_path = Path(b_terms or _resolve_default(default_b))
    if not b_terms_path.exists():
        raise FileNotFoundError(f"B_terms file not found: {b_terms_path}")
    u_terms, go_meta, kegg_meta = load_universe_and_meta(scoring_species)
    with open(b_terms_path, "r", encoding="utf-8") as handle:
        b_records = json.load(handle)
    if isinstance(b_records, dict):
        b_records = [b_records]
    n_condition_datasets = count_condition_datasets(
        b_records,
        condition,
        model=b_filters_resolved.get("model"),
        **{k: v for k, v in b_filters_resolved.items() if k != "model"},
    )
    resolved_min_dataset_freq = resolve_min_dataset_freq(
        n_condition_datasets, min_dataset_freq
    )

    scorer = score_fn or default_score_gene
    ranked: List[dict] = []
    for query_id in query_ids:
        protein = protein_by_query.get(query_id, {})
        score_gene_key = protein.get("gene_symbol") or query_id
        record = {
            "de_rank": None,
            "query_id": query_id,
            "id_type": protein.get("id_type"),
            "gene_symbol": protein.get("gene_symbol"),
            "ensembl_id": protein.get("ensembl_id"),
            "log2FoldChange": None,
            "padj": None,
            "entrez_id": protein.get("entrez_id"),
            "mapping_status": protein.get("mapping_status"),
            "fasta_relpath": protein.get("fasta_relpath"),
            "n_isoforms": protein.get("n_isoforms", 0),
            "sequence_preview": (
                (protein.get("sequence") or "")[:60] or None
            ),
            "ncbi_gene_url": (
                f"https://www.ncbi.nlm.nih.gov/gene/{protein['entrez_id']}"
                if protein.get("entrez_id")
                else None
            ),
            "condition": condition,
            "biomarker_score": None,
            "scoring_status": "pending",
        }

        pathways = _pathways_for_gene(gene_pathways, query_id, protein)
        if not pathways:
            record["scoring_status"] = "no_pathway_annotation"
            ranked.append(record)
            continue

        gene_pathways.setdefault(score_gene_key, pathways)
        try:
            score = scorer(
                gene=score_gene_key,
                condition=condition,
                gene_pathways=gene_pathways,
                b_terms_file=b_terms_path,
                u_terms=u_terms,
                go_meta=go_meta,
                kegg_meta=kegg_meta,
                output_dir=outdir,
                species=scoring_species,
                alpha=alpha,
                seed=seed,
                pathway_mode=pathway_mode,
                pathway_sources=pathway_sources,
                min_dataset_freq=resolved_min_dataset_freq,
                model=b_filters_resolved.get("model", model or None),
                category=b_filters_resolved.get("category", category),
                b_filters=b_filters_resolved,
            )
        except TypeError:
            score = scorer(score_gene_key, condition)  # type: ignore[misc]
        except Exception as exc:  # pragma: no cover
            record["scoring_status"] = f"error: {exc}"
            ranked.append(record)
            continue

        if score is None:
            record["scoring_status"] = "score_unavailable"
        else:
            record["scoring_status"] = "ok"
            record["biomarker_score"] = score
            if score.get("ncbi_gene_url") is None and record["ncbi_gene_url"]:
                score["ncbi_gene_url"] = record["ncbi_gene_url"]
        ranked.append(record)

    def _sort_key(row: dict):
        """Rank by primary p-value, ties broken by consensus. See expression."""
        score = row.get("biomarker_score") or {}
        consensus = score.get("consensus_score")
        primary_p = score.get("primary_p_value", score.get("combined_p_value"))
        has_score = 0 if row.get("scoring_status") == "ok" else 1
        return (
            has_score,
            float(primary_p) if primary_p is not None else 1.0,
            -float(consensus) if consensus is not None else 0.0,
            str(row.get("gene_symbol") or row.get("query_id") or ""),
        )

    ranked.sort(key=_sort_key)
    for index, row in enumerate(ranked, start=1):
        row["biomarker_rank"] = index

    summary = {
        "mode": "genes",
        "n_input": int(len(query_ids)),
        "n_ranked": int(len(ranked)),
        "condition": condition,
        "category": b_filters_resolved.get("category", category),
        "b_filters": b_filters_resolved,
        "model": b_filters_resolved.get("model", model or None),
        "species": species_key,
        "alpha": alpha,
        "pathway_mode": pathway_mode,
        "pathway_sources": list(pathway_sources),
        "min_dataset_freq_requested": min_dataset_freq,
        "min_dataset_freq": resolved_min_dataset_freq,
        "n_condition_datasets": int(n_condition_datasets),
        "outputs": {},
    }
    write_biomarker_outputs(ranked, outdir, summary)
    return ranked


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Expression matrix + case/control groups → R DE → top-k genes → "
            "pathway lookup → ensemble biomarker scoring.\n\n"
            "Requires orbit-ocsp reference data (B_terms, U, protein maps). Install with:\n"
            "  orbit-ocsp-download-data"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--matrix", required=True, help="Expression matrix TSV/CSV")
    parser.add_argument(
        "--groups",
        required=True,
        help="Sample grouping TSV/CSV with sample_id,group (case/control)",
    )
    parser.add_argument(
        "--data-type",
        default=None,
        choices=sorted(VALID_DATA_TYPES | {"rnaseq"}),
        help=(
            "Expression data type (rnaseq → rnaseq_count). Optional: when omitted, "
            "inferred from the matrix (counts→rnaseq_count, negatives→microarray, "
            "else normalized). Count-like matrices declared as normalized/"
            "microarray are auto-corrected to rnaseq_count. R engine then "
            "auto-selects by sample size: 1vs1→edgeR; both n>8→Wilcoxon; else "
            "DESeq2 (counts) or limma"
        ),
    )
    parser.add_argument(
        "--condition",
        required=True,
        help="B_terms condition filter (exact match, case-insensitive)",
    )
    parser.add_argument(
        "--category",
        default=None,
        help='B_terms category filter (e.g. "Drug Screening"); omit for all',
    )
    parser.add_argument(
        "--model",
        default="Organoid",
        help="B_terms model_condition filter (default: Organoid; empty to disable)",
    )
    parser.add_argument(
        "--species",
        default="hsa",
        help="Species code or name (hsa/human or mmu/mouse)",
    )
    parser.add_argument("--top-k", type=int, default=20, help="Top DE genes to keep")
    parser.add_argument("--padj-max", type=float, default=0.05)
    parser.add_argument("--abs-log2fc-min", type=float, default=1.0)
    parser.add_argument(
        "--outdir",
        default="out_expression_biomarker",
        help="Output directory",
    )
    parser.add_argument(
        "--merged-result",
        default=None,
        help="Path to all_merged_result.json (default: data/protein/all_merged_result.json)",
    )
    parser.add_argument(
        "--b-terms",
        default=None,
        help="Path to B_terms JSON (default: data/data_b/B_terms_<species>.json)",
    )
    parser.add_argument(
        "--protein-root",
        default="data/protein",
        help="Relative path to local protein annotation/FASTA root",
    )
    parser.add_argument(
        "--de-backend",
        default="r",
        choices=["r", "mock"],
        help="DE backend: R (DESeq2/limma/edgeR/Wilcoxon by sample size), or mock",
    )
    parser.add_argument(
        "--de-results",
        default=None,
        help="Optional precomputed DE TSV (skips DE engine)",
    )
    parser.add_argument(
        "--skip-scoring",
        action="store_true",
        help="Only run DE + protein mapping (no ensemble scoring)",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.005,
        help="Primary hypergeometric significance threshold (product default 0.005)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--pathway-mode",
        choices=["union", "majority"],
        default="majority",
        help="Per-record pathway combine: majority (default, paper) or union; then min-dataset-freq",
    )
    parser.add_argument(
        "--pathway-sources",
        default="enrich,gsea,gsva",
        help="Comma-separated B_terms pathway keys (default: enrich,gsea,gsva)",
    )
    parser.add_argument(
        "--min-dataset-freq",
        type=int,
        default=None,
        help=(
            "Minimum datasets a pathway term must appear in "
            "(default: auto — 6 if condition has >=30 datasets, else 1)"
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    from orbit_ocsp.data_manager import ensure_data_available

    try:
        ensure_data_available(args.species)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    pathway_sources = [
        p.strip() for p in str(args.pathway_sources).split(",") if p.strip()
    ] or list(DEFAULT_PATHWAY_SOURCES)

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
        protein_root=args.protein_root,
        de_backend=args.de_backend,
        de_results_path=args.de_results,
        skip_scoring=args.skip_scoring,
        alpha=args.alpha,
        seed=args.seed,
        pathway_mode=args.pathway_mode,
        pathway_sources=pathway_sources,
        min_dataset_freq=args.min_dataset_freq,
        model=args.model,
        category=getattr(args, "category", None),
    )
    print(f"Ranked {len(ranked)} biomarker candidates")
    print(f"Results: {Path(args.outdir) / 'biomarker_ranked.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
