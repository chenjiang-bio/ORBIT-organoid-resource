#!/usr/bin/env python3

# -*- coding: utf-8 -*-
from __future__ import annotations

"""
permutation_test_terms.py
-------------------------
This tool performs permutation-based statistical tests to evaluate whether the functional
terms (e.g., GO terms, KEGG pathways) associated with a user-provided gene set (A_terms)
overlap or resemble those from a disease/background set (B_terms) more than expected
by chance under a defined universe (U_terms).

Key features:
- Supports both GO and KEGG analyses (ontology-specific statistics).
- Allows flexible filtering of B_ter by condition, organ, model, and additional metadata.
- Provides semantic similarity statistics (GO semantic similarity with IC, KEGG topology-aware) and hypergeometric testing.
- Outputs group-level and per-gene results, with optional multiple-testing correction.
- Can generate biological interpretation reports (Markdown) using LLMs via unified API gateway or local models.
"""


def _norm_eq(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    return a.strip().lower() == b.strip().lower()


from orbit_ocsp.b_terms_schema import (  # noqa: E402
    b_categories,
    b_category_match,
    b_get,
    b_list_values,
    b_pathway_terms,
    b_record_matches,
)


# --- Utility: sanitize name for filenames ---
def _sanitize_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "NONE"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


# --- Helper: Load JSON items robustly ---
def _load_json_items(path: str) -> list[dict]:
    """Load a JSON file that may be a dict or a list of dicts; return a list of dicts."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    raise ValueError("Expected JSON object or array of objects.")


def _match_filters(
    obj: dict,
    cond_filter: str = "",
    add_cond_filter: str = "",
    organ_filter: str = "",
    model_filter: str = "",
    category_filter: str = "",
    cmp_ctrl_filter: str = "",
    cmp_cond_filter: str = "",
    cell_type_filter: str = "",
    day_filter: str = "",
    factor_filter: str = "",
    source_filter: str = "",
    organ_condition_filter: str = "",
    organ_control_filter: str = "",
    organ_system_condition_filter: str = "",
    organ_system_control_filter: str = "",
    model_condition_filter: str = "",
    model_control_filter: str = "",
    source_condition_filter: str = "",
    source_control_filter: str = "",
    time_condition_filter: str = "",
    time_control_filter: str = "",
) -> bool:
    """Return True if obj matches all non-empty filters (case-insensitive exact match).

    Paired B fields are independent filters including organ_system_*.
    Legacy organ/model/source/day map to the *_condition arm when the explicit
    *_condition filter is empty. Never uses organ_candidates_*.
    """
    return b_record_matches(
        obj,
        condition=cond_filter,
        additional_condition=add_cond_filter,
        organ=organ_filter,
        organ_condition=organ_condition_filter,
        organ_control=organ_control_filter,
        organ_system_condition=organ_system_condition_filter,
        organ_system_control=organ_system_control_filter,
        model=model_filter,
        model_condition=model_condition_filter,
        model_control=model_control_filter,
        category=category_filter,
        comparison_control=cmp_ctrl_filter,
        comparison_condition=cmp_cond_filter,
        cell_type=cell_type_filter,
        day=day_filter,
        time_condition=time_condition_filter,
        time_control=time_control_filter,
        factor=factor_filter,
        source=source_filter,
        source_condition=source_condition_filter,
        source_control=source_control_filter,
        allow_additional_all=False,
    )


# --- Module-level helpers for GO/KEGG URLs ---
def _go_url(tid: str) -> str:
    tid = str(tid)
    if not tid.startswith("GO:"):
        return ""
    return f"https://amigo.geneontology.org/amigo/term/{tid}"


def _kegg_url(pid: str) -> str:
    # Canonical KEGG pathway URL pattern
    return f"https://www.kegg.jp/pathway/{pid}"


# --- Utility: Write unique, sorted lines to text file with trailing newline ---
def _write_sorted_lines_txt(path: str, lines: list[str]) -> None:
    """Write unique, sorted lines to a UTF-8 text file with a final newline. No-op if empty."""
    if not lines:
        return
    dirn = os.path.dirname(path)
    if dirn:
        os.makedirs(dirn, exist_ok=True)
    with open(path, "w", encoding="utf-8") as g:
        g.write("\n".join(sorted(set(lines))) + "\n")


def read_B_from_json(
    path: str,
    cond_filter: str,
    add_cond_filter: str,
    organ_filter: str,
    model_filter: str,
    allowed_kegg: tuple[str, ...],
    log_dir: str | None = None,
    category_filter: str = "",
    cmp_ctrl_filter: str = "",
    cmp_cond_filter: str = "",
    cell_type_filter: str = "",
    day_filter: str = "",
    factor_filter: str = "",
    source_filter: str = "",
    organ_condition_filter: str = "",
    organ_control_filter: str = "",
    organ_system_condition_filter: str = "",
    organ_system_control_filter: str = "",
    model_condition_filter: str = "",
    model_control_filter: str = "",
    source_condition_filter: str = "",
    source_control_filter: str = "",
    time_condition_filter: str = "",
    time_control_filter: str = "",
) -> tuple[set[str], list[str], list[str]]:
    """
    Read B_terms from a JSON array.
    Filters map to current B fields (organ_condition/organ_control/organ_system_*, etc.).
    Legacy organ/model/source/day map to the *_condition arm.
    """
    items = _load_json_items(path)

    kept = []
    dropped = []
    duplicates = []
    seen = set()

    filter_kwargs = dict(
        organ_filter=organ_filter,
        model_filter=model_filter,
        category_filter=category_filter,
        cmp_ctrl_filter=cmp_ctrl_filter,
        cmp_cond_filter=cmp_cond_filter,
        cell_type_filter=cell_type_filter,
        day_filter=day_filter,
        factor_filter=factor_filter,
        source_filter=source_filter,
        organ_condition_filter=organ_condition_filter,
        organ_control_filter=organ_control_filter,
        organ_system_condition_filter=organ_system_condition_filter,
        organ_system_control_filter=organ_system_control_filter,
        model_condition_filter=model_condition_filter,
        model_control_filter=model_control_filter,
        source_condition_filter=source_condition_filter,
        source_control_filter=source_control_filter,
        time_condition_filter=time_condition_filter,
        time_control_filter=time_control_filter,
    )

    for obj in items:
        if not isinstance(obj, dict):
            continue
        # Fast filter pass using unified matcher
        want_add_all = (add_cond_filter.strip().lower() == "all") and bool(
            cond_filter.strip()
        )
        if not want_add_all:
            if not _match_filters(
                obj,
                cond_filter,
                add_cond_filter,
                **filter_kwargs,
            ):
                continue
        else:
            # When 'all', ignore additional_condition disparity while enforcing other filters
            if not _match_filters(
                obj,
                cond_filter,
                "",
                **filter_kwargs,
            ):
                continue

        terms_raw = b_pathway_terms(obj)

        local_seen = set()
        for raw in terms_raw:
            nid = norm_id(raw, allowed_kegg=allowed_kegg)
            if nid is None:
                dropped.append(str(raw))
                continue
            if nid in local_seen:
                # duplicate within the same item
                pass
            local_seen.add(nid)

            if nid in seen:
                duplicates.append(nid)
            else:
                seen.add(nid)
                kept.append(nid)

    kept_set = set(kept)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        with open(
            os.path.join(log_dir, "cleaned_B_terms.txt"), "w", encoding="utf-8"
        ) as g:
            for t in sorted(kept_set):
                g.write(t + "\n")
        _write_sorted_lines_txt(
            os.path.join(log_dir, "B_dropped_non_GO_KEGG.txt"), dropped
        )
        _write_sorted_lines_txt(
            os.path.join(log_dir, "B_duplicates_removed.txt"), duplicates
        )

    return kept_set, dropped, duplicates


# --- Grouped B-sets builder ---
def build_B_groups_from_json(
    path: str,
    cond_filter: str | None = None,
    add_cond_filter: str | None = None,
    organ_filter: str | None = None,
    model_filter: str | None = None,
    category_filter: str | None = None,
    cmp_ctrl_filter: str | None = None,
    cmp_cond_filter: str | None = None,
    cell_type_filter: str | None = None,
    day_filter: str | None = None,
    factor_filter: str | None = None,
    source_filter: str | None = None,
    organ_condition_filter: str | None = None,
    organ_control_filter: str | None = None,
    organ_system_condition_filter: str | None = None,
    organ_system_control_filter: str | None = None,
    model_condition_filter: str | None = None,
    model_control_filter: str | None = None,
    source_condition_filter: str | None = None,
    source_control_filter: str | None = None,
    time_condition_filter: str | None = None,
    time_control_filter: str | None = None,
    allowed_kegg: tuple[str, ...] = ("hsa", "mmu", "map", "ko"),
    log_dir: str | None = None,
) -> tuple[dict[tuple[str, str, str, str], set[str]], dict[tuple[str, str, str, str], dict]]:
    """
    Build groups of B terms keyed by (condition, additional_condition, organ_condition, model_condition).
    Paired control/condition filters (incl. organ_system_*) are independent when provided.
    """
    items = _load_json_items(path)

    want_cond = (cond_filter or "").strip()
    want_add = (add_cond_filter or "").strip()
    want_add_all = want_add.lower() == "all" and want_add != ""

    filter_kwargs = dict(
        organ_filter=organ_filter or "",
        model_filter=model_filter or "",
        category_filter=category_filter or "",
        cmp_ctrl_filter=cmp_ctrl_filter or "",
        cmp_cond_filter=cmp_cond_filter or "",
        cell_type_filter=cell_type_filter or "",
        day_filter=day_filter or "",
        factor_filter=factor_filter or "",
        source_filter=source_filter or "",
        organ_condition_filter=organ_condition_filter or "",
        organ_control_filter=organ_control_filter or "",
        organ_system_condition_filter=organ_system_condition_filter or "",
        organ_system_control_filter=organ_system_control_filter or "",
        model_condition_filter=model_condition_filter or "",
        model_control_filter=model_control_filter or "",
        source_condition_filter=source_condition_filter or "",
        source_control_filter=source_control_filter or "",
        time_condition_filter=time_condition_filter or "",
        time_control_filter=time_control_filter or "",
    )

    groups: dict[tuple[str, str, str, str], set[str]] = {}
    group_metadata: dict[tuple[str, str, str, str], dict] = {}
    dropped_all: list[str] = []
    dupes_all: list[str] = []

    def add_term(
        cond_key: str, add_key: str, organ_key: str, model_key: str, term: str, metadata: dict = None
    ):
        key = (cond_key, add_key, organ_key, model_key)
        if key not in groups:
            groups[key] = set()
            group_metadata[key] = metadata or {}
        groups[key].add(term)

    for obj in items:
        if not isinstance(obj, dict):
            continue
        cond = str(obj.get("condition", "") or "")
        addc = str(obj.get("additional_condition", "") or "")

        # Pre-filter condition/additional (supports additional=all merge)
        if want_cond and not _norm_eq(cond, want_cond):
            continue
        if want_add and not want_add_all and not _norm_eq(addc, want_add):
            continue
        if not _match_filters(
            obj,
            "",  # condition already applied
            "",  # additional already applied / all
            **filter_kwargs,
        ):
            continue

        organ = b_get(obj, "organ_condition")
        organ_control = b_get(obj, "organ_control")
        organ_system_condition = ", ".join(b_list_values(obj, "organ_system_condition"))
        organ_system_control = ", ".join(b_list_values(obj, "organ_system_control"))
        model = b_get(obj, "model_condition")
        model_control = b_get(obj, "model_control")
        category = ", ".join(b_categories(obj))
        comparison_control = str(obj.get("comparison_control", "") or "")
        comparison_condition = str(obj.get("comparison_condition", "") or "")
        cell_type = str(obj.get("cell_type", "") or "")
        time_condition = b_get(obj, "time_condition")
        time_control = b_get(obj, "time_control")
        factor = str(obj.get("factor", "") or "")
        source_condition = b_get(obj, "source_condition")
        source_control = b_get(obj, "source_control")

        metadata = {
            "category": category,
            "comparison_control": comparison_control,
            "comparison_condition": comparison_condition,
            "cell_type": cell_type,
            "day": time_condition,
            "time_condition": time_condition,
            "time_control": time_control,
            "factor": factor,
            "source": source_condition,
            "source_condition": source_condition,
            "source_control": source_control,
            "organ": organ,
            "organ_condition": organ,
            "organ_control": organ_control,
            "organ_system_condition": organ_system_condition,
            "organ_system_control": organ_system_control,
            "model": model,
            "model_condition": model,
            "model_control": model_control,
            "condition": cond,
            "additional_condition": addc,
        }

        terms_raw = b_pathway_terms(obj)

        seen_local = set()
        for raw in terms_raw:
            nid = norm_id(raw, allowed_kegg=allowed_kegg)
            if nid is None:
                dropped_all.append(str(raw))
                continue
            if nid in seen_local:
                dupes_all.append(nid)
            seen_local.add(nid)

            # Decide grouping key
            # - cond set, add='all'     -> merge all additional_condition under the given condition
            # - cond set, add empty     -> keep groups by actual additional_condition (no merge)
            # - cond set, add specific  -> keep that (cond, add)
            # - only add specific set   -> merge across ALL conditions for that add
            # - neither set             -> group by (cond, add) as-is in data
            if want_cond and want_add_all:
                # Explicit merge across all additional_condition for this condition
                add_term(cond, "ALL", organ, model, nid, metadata)
            elif want_cond and want_add and not want_add_all:
                # Filter to the specified additional_condition for this condition
                add_term(cond, addc, organ, model, nid, metadata)
            elif (not want_cond) and want_add and not want_add_all:
                # Only additional_condition filter given: merge across all conditions
                add_term("ALL", addc, organ, model, nid, metadata)
            else:
                # Default: preserve (condition, additional_condition) as in data
                add_term(cond, addc, organ, model, nid, metadata)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        _write_sorted_lines_txt(
            os.path.join(log_dir, "B_dropped_non_GO_KEGG_all_groups.txt"), dropped_all
        )
        _write_sorted_lines_txt(
            os.path.join(log_dir, "B_duplicates_within_item_all_groups.txt"), dupes_all
        )

    return groups, group_metadata


# Standard library imports
import argparse
import concurrent.futures as _fut
import hashlib
import yaml
import json
import logging
import math
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from functools import lru_cache, wraps

import pickle
from pathlib import Path
from statistics import mean, pstdev
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from multiprocessing import cpu_count
from typing import List, Optional, Callable

# Import topology-enhanced statistics
TOPOLOGY_AVAILABLE = False
KEGGTopologyAnalyzer = None
load_topology_data = None
enhanced_semantic_kegg_component = None

try:
    from orbit_ocsp.topology_enhanced_stats import (  # type: ignore
        KEGGTopologyAnalyzer,
        load_topology_data,
        enhanced_semantic_kegg_component
    )
    TOPOLOGY_AVAILABLE = True
except ImportError:
    TOPOLOGY_AVAILABLE = False

# Import parallel acceleration
try:
    from orbit_ocsp.parallel_acceleration import (  # type: ignore
        ParallelAccelerator,
        NumbaAccelerator,
        MemoryEfficientProcessor,
        create_accelerator,
        estimate_optimal_workers,
        PerformanceMonitor
    )
    PARALLEL_ACCELERATION_AVAILABLE = True
except ImportError:
    PARALLEL_ACCELERATION_AVAILABLE = False

# Try to import tqdm for progress bars
try:
    from tqdm import tqdm

    _TQDM_AVAILABLE = True
except ImportError:
    _TQDM_AVAILABLE = False


# =============================================================================
# ENSEMBLE ANALYSIS - Data Classes and Core Functions  
# =============================================================================
from dataclasses import dataclass, field as dataclass_field

# For FDR correction (q-values)
try:
    from statsmodels.stats.multitest import multipletests
    STATSMODELS_AVAILABLE = True
except ImportError:
    # statsmodels is intentionally not a dependency. The built-in
    # Benjamini-Hochberg implementation below is exact — it agrees with
    # statsmodels to floating-point precision, including on ties (see
    # tests/unit/test_output_field_vocabulary.py) — so there is nothing for the
    # user to act on and no warning is emitted.
    STATSMODELS_AVAILABLE = False
    logging.debug("statsmodels not installed; using the built-in BH implementation")

@dataclass
class MethodResult:
    """Individual method result for ensemble analysis"""
    method: str
    verdict: str  # 'enriched', 'depleted', 'not_sig'
    p_value: float
    q_value: float = None  # FDR-adjusted p-value
    effect_size: float = 0.0
    s_obs: float = 0.0
    runtime: float = 0.0
    weight: float = 1.0  # Dynamic weight for voting
    metadata: dict = dataclass_field(default_factory=dict)

@dataclass
class EnsembleResult:
    """Candidate-prioritization consensus result.

    ``combined_p_value`` is retained for backward-compatible serialization but
    now stores the pre-specified primary hypergeometric p-value. It is not a
    Fisher-combined p-value.
    """
    verdict: str
    confidence: str  # 'HIGH', 'MEDIUM', 'LOW'
    consensus_score: float
    agreement: int
    total_methods: int
    individual_results: list
    combined_p_value: float
    combined_p_value_go: float = None
    combined_p_value_kegg: float = None
    primary_p_value: float = None
    primary_q_value: float = None
    timestamp: str = ""


def _adjust_ensemble_results_across_candidates(results: list) -> list:
    """Apply BH correction to primary p-values across candidate hypotheses.

    This is intentionally separate from within-candidate method consensus:
    correlated methods are sensitivity analyses, not independent hypotheses.
    """
    valid = [
        (index, result)
        for index, result in enumerate(results)
        if getattr(result, "primary_p_value", None) is not None
    ]
    q_values = _calculate_q_values(
        [float(result.primary_p_value) for _, result in valid]
    )
    for (_, result), q_value in zip(valid, q_values):
        result.primary_q_value = q_value
    return results


def _calculate_q_values(p_values: list, method: str = 'fdr_bh') -> list:
    """
    Calculate FDR-adjusted q-values using Benjamini-Hochberg method

    Args:
        p_values: List of p-values
        method: 'fdr_bh' for Benjamini-Hochberg (default)

    Returns:
        List of q-values (FDR-corrected p-values)
    
    Note:
        Q-values control the False Discovery Rate (FDR) in multiple testing.
        A q-value of 0.05 means that among all discoveries with q≤0.05,
        we expect 5% to be false positives.
    """
    import numpy as np
    
    # Handle edge cases
    if len(p_values) == 0:
        return []
    if len(p_values) == 1:
        return list(p_values)
    
    p_array = np.array(p_values, dtype=float)
    
    # Use statsmodels if available (more robust)
    if STATSMODELS_AVAILABLE:
        try:
            reject, q_values, alphacSidak, alphacBonf = multipletests(
                p_array, 
                alpha=0.05, 
                method=method
            )
            return q_values.tolist()
        except Exception as e:
            logging.warning(f"statsmodels multipletests failed: {e}, using fallback")
    
    # Fallback: manual Benjamini-Hochberg implementation
    n = len(p_array)
    
    # Sort p-values and track original indices
    sorted_indices = np.argsort(p_array)
    sorted_p = p_array[sorted_indices]
    
    # Calculate q-values using BH procedure
    # q_i = min(n/i × p_i, 1) for each i in sorted order
    # Then enforce monotonicity: q_i = min(q_i, q_{i+1})
    q_values = np.zeros(n)
    
    # Calculate raw q-values
    for i in range(n):
        rank = i + 1  # 1-indexed rank
        q_values[i] = min(n / rank * sorted_p[i], 1.0)
    
    # Enforce monotonicity (backward pass)
    for i in range(n - 2, -1, -1):
        q_values[i] = min(q_values[i], q_values[i + 1])
    
    # Restore original order
    original_order = np.argsort(sorted_indices)
    q_values = q_values[original_order]
    
    return q_values.tolist()


# Static method weights (theory-based priors)
STATIC_METHOD_WEIGHTS = {
    'resnik_bma': 1.5,      # Semantic similarity + IC weighting
    'lin_bma': 1.5,         # Semantic similarity + normalization  
    'jaccard': 1.2,         # Normalized overlap (size-aware)
    'hypergeometric': 1.0,  # Classic statistical test (baseline)
    'overlap': 0.8          # Simple count (size-agnostic)
}

# Global variables for trained weights (can override STATIC_METHOD_WEIGHTS)
TRAINED_METHOD_WEIGHTS = None  # Will be set if trained weights are loaded
TRAINED_Q_FACTOR = 0.3  # Default q_factor
TRAINED_EFFECT_FACTOR = 0.2  # Default effect_factor


def _load_trained_weights(weights_path: str):
    """
    Load trained weights from file and set global variables.

    Args:
        weights_path: Path to trained weights file (.json or .pkl)
    """
    global TRAINED_METHOD_WEIGHTS, TRAINED_Q_FACTOR, TRAINED_EFFECT_FACTOR

    try:
        from orbit_ocsp.weight_training import WeightTrainer
        trained_weights = WeightTrainer.load_weights(weights_path)

        TRAINED_METHOD_WEIGHTS = trained_weights.base_weights
        TRAINED_Q_FACTOR = trained_weights.q_factor
        TRAINED_EFFECT_FACTOR = trained_weights.effect_factor

        logging.info(f"Loaded trained weights from {weights_path}")
        logging.info(f"Base weights: {TRAINED_METHOD_WEIGHTS}")
        logging.info(f"Q factor: {TRAINED_Q_FACTOR:.4f}, Effect factor: {TRAINED_EFFECT_FACTOR:.4f}")

    except Exception as e:
        logging.warning(f"Failed to load trained weights from {weights_path}: {e}")
        logging.warning("Falling back to static weights")
        TRAINED_METHOD_WEIGHTS = None


def _calculate_dynamic_weight(method_result, q_factor: float = None, effect_factor: float = None) -> float:
    """
    Calculate dynamic weight based on statistical evidence

    Args:
        method_result: MethodResult object with q_value and effect_size
        q_factor: Weight coefficient for q-value component (default: use trained or 0.3)
        effect_factor: Weight coefficient for effect size component (default: use trained or 0.2)

    Returns:
        Dynamic weight combining base method weight and evidence strength

    Formula:
        weight = base_weight × (1 + q_factor×[-log10(q)] + effect_factor×effect_size)

    Rationale:
        - Lower q-value → Higher weight (stronger statistical evidence)
        - Higher effect size → Higher weight (larger biological effect)
        - Base weight reflects method sophistication (or trained weights if available)
    """
    import numpy as np

    # Use trained weights if available, otherwise use static weights
    if TRAINED_METHOD_WEIGHTS is not None:
        base_weight = TRAINED_METHOD_WEIGHTS.get(method_result.method, 1.0)
    else:
        base_weight = STATIC_METHOD_WEIGHTS.get(method_result.method, 1.0)

    # Use trained factors if available and not explicitly provided
    if q_factor is None:
        q_factor = TRAINED_Q_FACTOR
    if effect_factor is None:
        effect_factor = TRAINED_EFFECT_FACTOR
    
    # Q-value component: -log10(q) measures statistical significance
    # q=0.001 → -log10=3.0, q=0.01 → -log10=2.0, q=0.05 → -log10=1.3
    if method_result.q_value is not None and method_result.q_value > 0:
        q_component = -np.log10(method_result.q_value + 1e-10)
        q_component = max(0, min(q_component, 10))  # Cap between [0, 10]
    else:
        q_component = 0
    
    # Effect size component: larger effect → more weight
    effect_component = max(0, min(method_result.effect_size, 10))  # Cap at 10
    
    # Combined weight
    weight = base_weight * (1 + q_factor * q_component + effect_factor * effect_component)
    
    return weight


_SEMANTIC_DEPTH_BINS = (0, 5, 10, 20, 50, float("inf"))
_SEMANTIC_IC_BINS = (float("-inf"), 1, 2, 4, 8, float("inf"))


def _semantic_bin(value: float, boundaries: tuple[float, ...]) -> int:
    for index in range(len(boundaries) - 1):
        if boundaries[index] <= value < boundaries[index + 1]:
            return index
    return len(boundaries) - 2


def _build_semantic_strata(
    universe_go: set[str],
    ns_map: dict[str, str],
    ancestors: dict[str, set[str]],
    ic_map: dict[str, float],
) -> tuple[dict[tuple[str, int, int], tuple[str, ...]], dict[str, tuple[str, int, int]]]:
    """Index GO terms by namespace, ontology-depth proxy, and information content."""
    mutable: dict[tuple[str, int, int], list[str]] = {}
    term_to_stratum: dict[str, tuple[str, int, int]] = {}
    for term in sorted(universe_go):
        namespace = ns_map.get(term, "UNK")
        if namespace not in {"BP", "MF", "CC"}:
            namespace = "UNK"
        key = (
            namespace,
            _semantic_bin(float(len(ancestors.get(term, set()))), _SEMANTIC_DEPTH_BINS),
            _semantic_bin(float(ic_map.get(term, 0.0)), _SEMANTIC_IC_BINS),
        )
        mutable.setdefault(key, []).append(term)
        term_to_stratum[term] = key
    return (
        {key: tuple(values) for key, values in mutable.items()},
        term_to_stratum,
    )


def _sample_semantic_matched(
    reference: set[str],
    strata: dict[tuple[str, int, int], tuple[str, ...]],
    term_to_stratum: dict[str, tuple[str, int, int]],
    rng: random.Random,
) -> set[str]:
    """Sample a GO set with the reference's namespace/depth/IC composition."""
    counts: dict[tuple[str, int, int], int] = {}
    for term in reference:
        key = term_to_stratum.get(term)
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
    sampled: set[str] = set()
    for key, count in sorted(counts.items()):
        pool = list(strata.get(key, ()))
        if not pool:
            continue
        sampled.update(
            rng.sample(pool, count)
            if count <= len(pool)
            else rng.choices(pool, k=count)
        )
    return sampled


def _stratified_semantic_cap(
    terms: set[str],
    cap: int | None,
    term_to_stratum: dict[str, tuple[str, int, int]],
    seed: int,
    method: str,
) -> set[str]:
    """Deterministically cap terms without allowing one semantic stratum to dominate."""
    if not cap or len(terms) <= cap:
        return set(terms)
    ordered = sorted(
        terms,
        key=lambda term: hashlib.sha256(
            f"{seed}:shared-semantic-screen:{term}".encode("utf-8")
        ).digest(),
    )
    grouped: dict[tuple[str, int, int], list[str]] = {}
    for term in ordered:
        grouped.setdefault(term_to_stratum.get(term, ("UNK", -1, -1)), []).append(term)
    selected: list[str] = []
    keys = sorted(grouped)
    while len(selected) < cap and keys:
        remaining_keys = []
        for key in keys:
            if grouped[key] and len(selected) < cap:
                selected.append(grouped[key].pop(0))
            if grouped[key]:
                remaining_keys.append(key)
        keys = remaining_keys
    return set(selected)


def _ensemble_run_single_method(
    method: str, 
    A: set, 
    B: set, 
    U: set, 
    R_value: int, 
    alpha: float, 
    seed: int,
    A_GO: set = None,
    B_GO: set = None,
    A_KEGG: set = None,
    B_KEGG: set = None,
    component_tests: bool = True,
    semantic_term_cap: int | None = None,
) -> MethodResult:
    """
    Run a single method for ensemble analysis (REAL PERMUTATION TEST)
    
    Parameters
    ----------
    method : str
        Method name (hypergeometric, jaccard, overlap, resnik_bma, lin_bma)
    A, B, U : set
        Term sets
    R_value : int
        Number of permutations
    alpha : float
        Significance level
    seed : int
        Random seed
    A_GO, B_GO, A_KEGG, B_KEGG : set, optional
        GO and KEGG specific term sets for breakdown

    Returns
    -------
    MethodResult
        Result from this method with detailed metadata
    """
    start_time = time.time()
    rng = random.Random(seed)
    
    try:
        # Prepare term sets (always restrict to the permutation universe)
        A_u = A & U
        B_u = B & U
        n_A = len(A_u)
        n_B = len(B_u)
        n_U = len(U)
        A_B = A_u & B_u
        intersection_size = len(A_B)
        enriched_terms = list(A_B)
        
        # Define GO and KEGG universes for structure-preserving permutation
        U_GO = {t for t in U if t.startswith('GO:')}
        U_KEGG = {t for t in U if t.startswith(('hsa', 'mmu', 'map', 'ko'))}
        
        # Define B_GO and B_KEGG if not provided
        if A_GO is None:
            A_GO = {t for t in A_u if t.startswith('GO:')}
        if B_GO is None:
            B_GO = {t for t in B_u if t.startswith('GO:')}
        if A_KEGG is None:
            A_KEGG = {t for t in A_u if t.startswith(('hsa', 'mmu', 'map', 'ko'))}
        if B_KEGG is None:
            B_KEGG = {t for t in B_u if t.startswith(('hsa', 'mmu', 'map', 'ko'))}
        
        U_GO_list = tuple(U_GO)
        U_KEGG_list = tuple(U_KEGG)

        # Define stat function based on method
        analytic_p_value = None
        if method == 'hypergeometric':
            # Pre-specified primary test: exact right-tailed hypergeometric test.
            def stat_fn(a_set, b_set):
                return len(a_set & b_set)
            s_obs = intersection_size
            analytic_p_value = hypergeometric_enrichment(A_u, B_u, U)["p_value"]
            
        elif method == 'jaccard':
            # Jaccard coefficient
            def stat_fn(a_set, b_set):
                return jaccard(a_set, b_set)
            s_obs = jaccard(A_u, B_u)
            
        elif method == 'overlap':
            # Overlap count
            def stat_fn(a_set, b_set):
                return overlap(a_set, b_set)
            s_obs = intersection_size
            
        elif method == 'resnik_bma' or method == 'lin_bma':
            # Semantic similarity methods (proper implementation like --stat semantic)
            # Load necessary data files using cached resources
            go_anc, ic_map, ns_map = _cached_go_resources()
            semantic_strata, semantic_term_to_stratum = _build_semantic_strata(
                U_GO, ns_map, go_anc, ic_map
            )
            B_GO_effective = _stratified_semantic_cap(
                set(B_GO) & U_GO,
                semantic_term_cap,
                semantic_term_to_stratum,
                seed,
                method,
            )
            
            # Define stat function for semantic similarity
            def stat_fn(a_set, b_set):
                # Split into GO and KEGG
                a_go = {t for t in a_set if t.startswith('GO:')}
                a_kegg = {t for t in a_set if t.startswith(('hsa', 'mmu', 'map', 'ko'))}
                b_go = {t for t in b_set if t.startswith('GO:')}
                b_kegg = {t for t in b_set if t.startswith(('hsa', 'mmu', 'map', 'ko'))}
                # GO semantic similarity
                if a_go and b_go:
                    mode = (
                        "resnik" if method == "resnik_bma" else "lin"
                    )
                    # Random permutation sets are effectively unique, so the
                    # disk-cache wrapper adds serialization and file-I/O cost
                    # without producing cache hits.
                    s_go = _semantic_go_resnik_bma(
                        a_go,
                        b_go,
                        go_anc,
                        ic_map,
                        ns_map=ns_map,
                        mode=mode,
                    )
                else:
                    s_go = 0.0

                # Resnik and Lin are GO semantic statistics. Mixing their IC
                # scale with KEGG Jaccard changes the statistic's meaning.
                return s_go
            
            # Calculate observed statistic
            s_obs = stat_fn(A_u, B_GO_effective | set(B_KEGG))
        else:
            raise ValueError(f"Unknown method: {method}")
        
        # Structure-preserving permutation with size limits
        B_GO_size = len(B_u & U_GO)
        B_KEGG_size = len(B_u & U_KEGG)

        null_stats = []
        if method != 'hypergeometric':
            for _ in range(R_value):
                if method in ('resnik_bma', 'lin_bma'):
                    B_GO_rand = _sample_semantic_matched(
                        B_GO_effective,
                        semantic_strata,
                        semantic_term_to_stratum,
                        rng,
                    )
                    B_KEGG_rand = set()
                else:
                    B_GO_rand = set(rng.sample(U_GO_list, min(B_GO_size, len(U_GO_list)))) if B_GO_size > 0 else set()
                    B_KEGG_rand = set(rng.sample(U_KEGG_list, min(B_KEGG_size, len(U_KEGG_list)))) if B_KEGG_size > 0 else set()
                B_rand = B_GO_rand | B_KEGG_rand
                null_stats.append(stat_fn(A_u, B_rand))
        
        # Calculate statistics
        import numpy as np
        if method == 'hypergeometric':
            mu = n_A * n_B / n_U if n_U else 0.0
            # The primary test is analytic, so its null spread is the exact
            # hypergeometric standard deviation rather than a permutation one.
            if n_U > 1:
                variance = (
                    n_A
                    * (n_B / n_U)
                    * (1.0 - n_B / n_U)
                    * ((n_U - n_A) / (n_U - 1))
                )
                sd = float(math.sqrt(variance)) if variance > 0 else 0.0
            else:
                sd = 0.0
            p_value = float(analytic_p_value)
            effect_size = (
                float((s_obs - mu) / sd) if sd > 0 else float(s_obs - mu)
            )
        else:
            mu = np.mean(null_stats) if null_stats else 0.0
            sd = np.std(null_stats, ddof=1) if len(null_stats) > 1 else 0.0
            count_ge = sum(1 for x in null_stats if x >= s_obs)
            p_value = (count_ge + 1) / (R_value + 1)
            # Effect size is the standardized deviation of the observed
            # statistic from its permutation null, so it is comparable across
            # methods whose raw statistics live on different scales. Falls back
            # to the raw deviation when the null has no spread.
            effect_size = (
                float((s_obs - mu) / sd) if sd > 0 else float(s_obs - mu)
            )
        raw_deviation = float(s_obs - mu)

        # Verdict uses one vocabulary for every method: enriched / not_sig.
        # Whether a semantic method is still at the screening stage is carried
        # separately by ``inference_stage``, not folded into the verdict.
        verdict = 'enriched' if (p_value < alpha and s_obs > mu) else 'not_sig'
        inference_stage = (
            ('screening' if R_value < 199 else 'formal')
            if method in ('resnik_bma', 'lin_bma')
            else 'final'
        )
        
        # Build metadata
        metadata = {
            'R': 0 if method == 'hypergeometric' else R_value,
            'test_type': (
                'exact_hypergeometric'
                if method == 'hypergeometric'
                else 'empirical_permutation'
            ),
            'A_size': n_A,
            'B_size': n_B,
            'U_size': n_U,
            'intersection_size': len(A_B),
            'enriched_terms': enriched_terms,
            'mu': mu,
            'sd': sd,
            'raw_deviation': raw_deviation,
            'inference_stage': inference_stage,
            'component_tests': 'included' if component_tests else 'skipped',
        }
        if method in ('resnik_bma', 'lin_bma'):
            metadata['semantic_term_cap'] = semantic_term_cap
            metadata['B_GO_size_evaluated'] = len(B_GO_effective)
            metadata['semantic_subset_sha256'] = hashlib.sha256(
                "\n".join(sorted(B_GO_effective)).encode("utf-8")
            ).hexdigest()
            metadata['semantic_null_model'] = 'namespace_depth_ic_matched'
            metadata['semantic_scope'] = 'GO_only'
            metadata['semantic_subset_policy'] = 'shared_across_resnik_and_lin'
            metadata['inference_status'] = (
                'screening_only' if R_value < 199 else 'final'
            )

        
        # GO/KEGG breakdown using proper permutation tests
        if component_tests and A_GO is not None and B_GO is not None:
            # Define GO universe
            U_GO = {t for t in U if t.startswith('GO:')}
            
            # GO-specific stat function
            if method == 'hypergeometric':
                s_obs_go = len(A_GO & B_GO)
            elif method == 'jaccard':
                s_obs_go = jaccard(A_GO, B_GO)
            elif method == 'overlap':
                s_obs_go = len(A_GO & B_GO)
            elif method in ['resnik_bma', 'lin_bma']:
                if go_anc and ic_map and ns_map:
                    s_obs_go = semantic_go_similarity(
                        A_GO,
                        B_GO,
                        go_anc,
                        ic_map,
                        ns_map,
                        method=method,
                    )
                else:
                    s_obs_go = 0.0
            else:
                s_obs_go = len(A_GO & B_GO)
            
            # Run ontology-specific test using the same definition as the
            # overall method.
            null_stats_go = []
            if method == 'hypergeometric':
                p_go = hypergeometric_enrichment(A_GO, B_GO, U_GO)['p_value']
                mu_go = (
                    len(A_GO) * len(B_GO) / len(U_GO) if U_GO else 0.0
                )
                verdict_go = (
                    'enriched'
                    if p_go < alpha and s_obs_go > mu_go
                    else 'not_sig'
                )
            else:
                for _ in range(min(R_value, 200)):
                    B_GO_rand = set(random.sample(list(U_GO), min(len(B_GO), len(U_GO))))
                    if method == 'jaccard':
                        null_stats_go.append(jaccard(A_GO, B_GO_rand))
                    elif method == 'overlap':
                        null_stats_go.append(len(A_GO & B_GO_rand))
                    elif method in ['resnik_bma', 'lin_bma']:
                        if go_anc and ic_map and ns_map:
                            null_stats_go.append(
                                semantic_go_similarity(
                                    A_GO,
                                    B_GO_rand,
                                    go_anc,
                                    ic_map,
                                    ns_map,
                                    method=method,
                                )
                            )
                        else:
                            null_stats_go.append(0.0)
                    else:
                        null_stats_go.append(len(A_GO & B_GO_rand))

                if null_stats_go:
                    mu_go = np.mean(null_stats_go)
                    count_ge_go = sum(1 for x in null_stats_go if x >= s_obs_go)
                    p_go = (count_ge_go + 1) / (len(null_stats_go) + 1)
                    verdict_go = 'enriched' if (p_go < alpha and s_obs_go > mu_go) else 'not_sig'
                else:
                    mu_go = 0.0
                    p_go = 1.0
                    verdict_go = 'not_sig'
            
            metadata['go_stats'] = {
                's_obs': float(s_obs_go),
                'mu': mu_go,
                'p_right': p_go,
                'verdict': verdict_go,
                'A_size': len(A_GO),
                'B_size': len(B_GO)
            }
        
        if component_tests and A_KEGG is not None and B_KEGG is not None:
            # Define KEGG universe
            U_KEGG = {t for t in U if t.startswith(('hsa', 'mmu', 'map', 'ko'))}
            
            # KEGG-specific stat function (always use jaccard for KEGG)
            if method == 'hypergeometric':
                s_obs_kegg = len(A_KEGG & B_KEGG)
            elif method == 'jaccard':
                s_obs_kegg = jaccard(A_KEGG, B_KEGG)
            elif method == 'overlap':
                s_obs_kegg = len(A_KEGG & B_KEGG)
            elif method in ['resnik_bma', 'lin_bma']:
                # For semantic methods, use jaccard for KEGG
                s_obs_kegg = jaccard(A_KEGG, B_KEGG)
            else:
                s_obs_kegg = len(A_KEGG & B_KEGG)
            
            null_stats_kegg = []
            if method == 'hypergeometric':
                p_kegg = hypergeometric_enrichment(
                    A_KEGG, B_KEGG, U_KEGG
                )['p_value']
                mu_kegg = (
                    len(A_KEGG) * len(B_KEGG) / len(U_KEGG)
                    if U_KEGG
                    else 0.0
                )
                verdict_kegg = (
                    'enriched'
                    if p_kegg < alpha and s_obs_kegg > mu_kegg
                    else 'not_sig'
                )
            else:
                for _ in range(min(R_value, 200)):
                    B_KEGG_rand = set(random.sample(list(U_KEGG), min(len(B_KEGG), len(U_KEGG))))
                    if method == 'jaccard':
                        null_stats_kegg.append(jaccard(A_KEGG, B_KEGG_rand))
                    elif method == 'overlap':
                        null_stats_kegg.append(len(A_KEGG & B_KEGG_rand))
                    elif method in ['resnik_bma', 'lin_bma']:
                        null_stats_kegg.append(jaccard(A_KEGG, B_KEGG_rand))
                    else:
                        null_stats_kegg.append(len(A_KEGG & B_KEGG_rand))

                if null_stats_kegg:
                    mu_kegg = np.mean(null_stats_kegg)
                    count_ge_kegg = sum(1 for x in null_stats_kegg if x >= s_obs_kegg)
                    p_kegg = (count_ge_kegg + 1) / (len(null_stats_kegg) + 1)
                    verdict_kegg = 'enriched' if (p_kegg < alpha and s_obs_kegg > mu_kegg) else 'not_sig'
                else:
                    mu_kegg = 0.0
                    p_kegg = 1.0
                    verdict_kegg = 'not_sig'
            
            metadata['kegg_stats'] = {
                's_obs': float(s_obs_kegg),
                'mu': mu_kegg,
                'p_right': p_kegg,
                'verdict': verdict_kegg,
                'A_size': len(A_KEGG),
                'B_size': len(B_KEGG)
            }
        
        return MethodResult(
            method=method,
            verdict=verdict,
            p_value=p_value,
            effect_size=effect_size,
            s_obs=float(s_obs),
            runtime=time.time() - start_time,
            metadata=metadata
        )
    
    except Exception as e:
        return MethodResult(
            method=method,
            verdict='error',
            p_value=1.0,
            effect_size=0.0,
            s_obs=0.0,
            runtime=time.time() - start_time,
            metadata={'error': str(e)}
        )


def _ensemble_calculate_consensus(
    results: list, fisher_p: float = None, alpha: float = 0.05
) -> tuple:
    """Decide enrichment from the primary hypergeometric test only.

    Hypergeometric enrichment is the pre-specified primary test and the sole
    determinant of ``enriched`` / ``not_sig``. Other methods are retained as
    equal-weight sensitivity analyses: their agreement is summarized in
    ``consensus_score`` / ``agreement`` / agreement tier, but they do **not**
    veto or rescue the primary call. P-values are never Fisher-combined.
    ``fisher_p`` is accepted only for API compatibility and ignored.

    Confidence tier (when primary is enriched), for the usual five methods:
    HIGH if enriched_count >= 4 (consensus >= 0.8); MEDIUM if == 3
    (consensus >= 0.6); else LOW.

    Args:
        results: List of MethodResult objects
        fisher_p: Deprecated and ignored.
        alpha: Significance threshold (default 0.05; product default often 0.005)

    Returns:
        (final_verdict, consensus_score, agreement, agreement_tier, primary_p)
    """
    valid_results = [r for r in results if r.verdict != 'error']

    if not valid_results:
        return 'not_sig', 0.0, 0, 'N/A', 1.0

    for result in valid_results:
        result.q_value = None
        result.weight = 1.0

    enriched_count = sum(r.verdict == 'enriched' for r in valid_results)
    consensus_score = enriched_count / len(valid_results)
    primary = next(
        (r for r in valid_results if r.method == 'hypergeometric'), None
    )
    primary_p = primary.p_value if primary is not None else 1.0
    primary_significant = bool(
        primary is not None
        and primary.verdict == 'enriched'
        and primary_p < alpha
    )
    final_verdict = 'enriched' if primary_significant else 'not_sig'

    # Confidence tier: primary call combined with method agreement. HIGH when
    # the primary test is significant and consensus >= 0.8 (>=4 of 5 methods);
    # MEDIUM at consensus >= 0.6 (3 of 5); LOW otherwise.
    if final_verdict == 'enriched' and enriched_count >= 4:
        agreement_tier = 'HIGH'
    elif final_verdict == 'enriched' and enriched_count == 3:
        agreement_tier = 'MEDIUM'
    elif final_verdict == 'enriched':
        agreement_tier = 'LOW'
    else:
        agreement_tier = 'N/A'

    return (
        final_verdict,
        consensus_score,
        enriched_count,
        agreement_tier,
        primary_p,
    )


def _ensemble_combine_p_values(results: list) -> float:
    """
    Combine p-values using Fisher's method
    
    Fisher's method: χ² = -2 × Σ ln(p_i), df = 2k
    Returns combined p-value from chi-squared distribution
    """
    import numpy as np
    
    valid_p = [r.p_value for r in results if r.verdict != 'error' and r.p_value > 0]
    
    if not valid_p:
        return 1.0
    
    # Fisher's combined test statistic
    test_stat = -2 * sum(np.log(valid_p))
    df = 2 * len(valid_p)

    # Try SciPy first; if unavailable, fall back to mpmath; else return conservative 1.0
    try:
        from scipy import stats as scipy_stats  # type: ignore
        return scipy_stats.chi2.sf(test_stat, df)
    except Exception:
        try:
            import mpmath as mp  # type: ignore
            # upper-tail p = 1 - F(x); F via regularized gamma
            return float(1 - mp.gammainc(df/2, 0, test_stat/2) / mp.gamma(df/2))
        except Exception:
            import logging
            logging.warning("SciPy/mpmath not available; returning conservative p-value 1.0 for Fisher's combination")
            return 1.0


def _ensemble_combine_p_values_ontology(results: list, ontology: str) -> float:
    """
    Combine p-values for a specific ontology (GO or KEGG) using Fisher's method
    
    Args:
        results: List of MethodResult objects
        ontology: 'go' or 'kegg'
    
    Returns:
        Combined p-value from Fisher's method
    """
    import numpy as np
    
    valid_p = []
    for r in results:
        if r.verdict == 'error':
            continue
        
        # Extract p-value for the specific ontology
        if ontology == 'go' and 'go_stats' in r.metadata:
            p_val = r.metadata['go_stats'].get('p_right', None)
            if p_val is not None and p_val > 0:
                valid_p.append(p_val)
        elif ontology == 'kegg' and 'kegg_stats' in r.metadata:
            p_val = r.metadata['kegg_stats'].get('p_right', None)
            if p_val is not None and p_val > 0:
                valid_p.append(p_val)
    
    if not valid_p:
        return 1.0
    
    # Fisher's combined test statistic
    test_stat = -2 * sum(np.log(valid_p))
    df = 2 * len(valid_p)
    
    # Try SciPy first; if unavailable, fall back to mpmath; else return conservative 1.0
    try:
        from scipy import stats as scipy_stats  # type: ignore
        return scipy_stats.chi2.sf(test_stat, df)
    except Exception:
        try:
            import mpmath as mp  # type: ignore
            # upper-tail p = 1 - F(x); F via regularized gamma
            return float(1 - mp.gammainc(df/2, 0, test_stat/2) / mp.gamma(df/2))
        except Exception:
            import logging
            logging.warning("SciPy/mpmath not available; returning conservative p-value 1.0 for Fisher's combination")
            return 1.0


def _format_p_value(p: float) -> str:
    """
    Format p-value for display
    Always uses scientific notation for consistency
    """
    return f"{p:.2e}"


def _format_p_value_safe(p) -> str:
    """
    Safely format p-value for display (handles N/A or numeric values)
    Always uses scientific notation for numeric values
    """
    if isinstance(p, (int, float)):
        return f"{p:.2e}"
    else:
        return str(p)  # Return as-is if not numeric (e.g., 'N/A')


def _format_p_value_tsv(p: float) -> str:
    """
    Format p-value for TSV output
    Always uses scientific notation with 6 significant figures for consistency
    """
    return f"{p:.6e}"


def _check_llm_guard_ensemble(ensemble_result, config) -> tuple[bool, str]:
    """
    Check if LLM generation should proceed based on llm_guard conditions for ensemble analysis.
    
    Args:
        ensemble_result: EnsembleResult object
        config: Configuration dictionary
    
    Returns:
        tuple: (should_call_llm: bool, reason: str)
    """
    if not config.get('llm_guard', False):
        return True, "llm_guard disabled"
    
    # Get guard parameters
    required_verdict = config.get('llm_guard_verdict', 'enriched')
    min_confidence = config.get('llm_guard_confidence', None)
    max_qvalue = config.get('llm_guard_max_qvalue', None)
    min_consensus = config.get('llm_guard_min_consensus', None)
    alpha = config.get('alpha', 0.05)
    
    # If max_qvalue not specified, use alpha
    if max_qvalue is None:
        max_qvalue = alpha
    
    reasons = []
    
    # Check verdict
    if required_verdict != 'any' and ensemble_result.verdict != required_verdict:
        reasons.append(f"verdict='{ensemble_result.verdict}' (required: '{required_verdict}')")
    
    # Check p-value
    if ensemble_result.combined_p_value >= max_qvalue:
        reasons.append(f"combined_p={ensemble_result.combined_p_value:.3e} >= {max_qvalue:.3e}")
    
    # Check confidence level (if specified)
    if min_confidence:
        confidence_levels = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
        current_level = confidence_levels.get(ensemble_result.confidence, 0)
        required_level = confidence_levels.get(min_confidence, 0)
        if current_level < required_level:
            reasons.append(f"confidence='{ensemble_result.confidence}' < '{min_confidence}'")
    
    # Check consensus score (if specified)
    if min_consensus is not None and ensemble_result.consensus_score < min_consensus:
        reasons.append(f"consensus_score={ensemble_result.consensus_score:.3f} < {min_consensus:.3f}")
    
    if reasons:
        guard_reason = f"llm_guard: {', '.join(reasons)}"
        return False, guard_reason
    
    return True, "llm_guard passed"


def _make_ensemble_group_dir_name(condition, add_cond, organ, model, factor, comp_ctrl='', comp_cond='', cell_type='', day=''):
    """
    Create group directory name for ensemble analysis
    """
    parts = []
    if condition:
        parts.append(f"condition={_sanitize_name(condition)}")
    if add_cond:
        parts.append(f"additional={_sanitize_name(add_cond)}")
    if organ:
        parts.append(f"organ={_sanitize_name(organ)}")
    if model:
        parts.append(f"model={_sanitize_name(model)}")
    if factor:
        parts.append(f"factor={_sanitize_name(factor)}")
    if comp_ctrl:
        parts.append(f"comparison_control={_sanitize_name(comp_ctrl)}")
    if comp_cond:
        parts.append(f"comparison_condition={_sanitize_name(comp_cond)}")
    if cell_type:
        parts.append(f"cell_type={_sanitize_name(cell_type)}")
    if day:
        parts.append(f"day={_sanitize_name(day)}")
    
    return "__".join(parts) if parts else "default_group"


def _run_ensemble_analysis_core(
    A: set,
    B: set,
    U: set,
    methods: list,
    r_values: dict,
    alpha: float,
    seed: int,
    go_meta: dict,
    kegg_meta: dict,
    output_dir: str,
    config: dict,
    level_label: str = "",
    parallel: bool = True,
    group_metadata: dict = None,  # B_terms group metadata
    gene_data: dict = None,  # Gene data for TSV generation
    component_tests: bool = True,
    semantic_term_cap: int | None = None,
) -> EnsembleResult:
    """
    Core ensemble analysis function (reusable for all levels)
    
    Parameters
    ----------
    A, B, U : set
        Term sets
    methods : list
        Methods to run
    r_values : dict
        R values for each method
    alpha : float
        Significance level
    seed : int
        Random seed
    go_meta, kegg_meta : dict
        Metadata dictionaries
    output_dir : str
        Output directory
    config : dict
        Configuration
    level_label : str
        Label for progress (e.g., "Gene: ADA", "Group: High_Wnt")
    parallel : bool
        Whether to run methods in parallel
        
    Returns
    -------
    EnsembleResult
        Ensemble analysis result
    """
    import concurrent.futures
    
    # Prepare GO/KEGG splits
    U_GO = {t for t in U if t.startswith("GO:")}
    # Note: allowed_kegg is not available here, use simple prefix check
    U_KEGG = {t for t in U if t.startswith('hsa') or t.startswith('mmu') or t.startswith('map') or t.startswith('ko')}
    A_GO = A & U_GO
    A_KEGG = A & U_KEGG
    B_GO = B & U_GO
    B_KEGG = B & U_KEGG
    
    # Run all methods
    method_results = []
    
    if parallel and len(methods) > 1:
        # Parallel execution
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(methods)) as executor:
            futures = {}
            for method in methods:
                R_value = r_values.get(method, 1000)
                future = executor.submit(
                    _ensemble_run_single_method,
                    method, A, B, U, R_value, alpha, seed,
                    A_GO, B_GO, A_KEGG, B_KEGG, component_tests,
                    semantic_term_cap,
                )
                futures[future] = method
            
            for future in concurrent.futures.as_completed(futures):
                method = futures[future]
                result = future.result()
                method_results.append(result)
    else:
        # Sequential execution
        for method in methods:
            R_value = r_values.get(method, 1000)
            result = _ensemble_run_single_method(
                method, A, B, U, R_value, alpha, seed,
                A_GO, B_GO, A_KEGG, B_KEGG, component_tests,
                semantic_term_cap,
            )
            method_results.append(result)
    
    # Sort results by method name for consistency
    method_results.sort(key=lambda r: r.method)
    
    # Correlated sensitivity methods are not separate hypotheses. Do not apply
    # BH across methods and do not combine their p-values with Fisher's method.
    primary_result = next(
        (r for r in method_results if r.method == 'hypergeometric'), None
    )
    primary_go_p = (
        primary_result.metadata.get('go_stats', {}).get('p_right')
        if primary_result is not None
        else None
    )
    primary_kegg_p = (
        primary_result.metadata.get('kegg_stats', {}).get('p_right')
        if primary_result is not None
        else None
    )

    final_verdict, consensus_score, agreement, confidence, primary_p = (
        _ensemble_calculate_consensus(method_results, alpha=alpha)
    )
    
    # Create ensemble result
    ensemble_result = EnsembleResult(
        verdict=final_verdict,
        confidence=confidence,
        consensus_score=consensus_score,
        agreement=agreement,
        total_methods=len([r for r in method_results if r.verdict != 'error']),
        individual_results=method_results,
        combined_p_value=primary_p,
        combined_p_value_go=primary_go_p,
        combined_p_value_kegg=primary_kegg_p,
        primary_p_value=primary_p,
        timestamp=time.strftime('%Y-%m-%d %H:%M:%S')
    )
    
    # Generate reports
    _ensemble_generate_report(
        ensemble_result, 
        output_dir, 
        config,
        method_details={},
        A_terms=list(A),
        B_terms=list(B),
        U_size=len(U),
        go_meta=go_meta,
        kegg_meta=kegg_meta,
        group_metadata=group_metadata,
        gene_data=gene_data
    )
    
    return ensemble_result


def _ensemble_generate_report(
    ensemble_result: EnsembleResult, 
    output_dir: str, 
    config: dict,
    method_details: dict,  # Details from each method's full run
    A_terms: list,
    B_terms: list,
    U_size: int,
    go_meta: dict,
    kegg_meta: dict,
    group_metadata: dict = None,  # B_terms group metadata
    gene_data: dict = None  # Gene data for TSV generation
) -> str:
    """Generate comprehensive ensemble analysis Markdown report"""
    # If gene_name exists, we're already in a gene-specific directory
    # so just use "ENSEMBLE.md" instead of "GENE_ENSEMBLE.md"
    gene_name = config.get('gene_name', None)
    if gene_name:
        report_filename = "ENSEMBLE.md"
    else:
        report_filename = "ENSEMBLE_REPORT.md"
    
    report_path = os.path.join(output_dir, report_filename)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        # ============================================================
        # 1. Header Section
        # ============================================================
        f.write(f"""# Ensemble Enrichment Analysis Report

**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}  
**Strategy:** Primary hypergeometric test (auxiliary methods = sensitivity only)  
**Species:** {config.get('species', 'N/A')}  
**Condition:** {config.get('condition', 'N/A')}

---

## Executive Summary

""")
        
        f.write(f"""**{ensemble_result.verdict.upper()}** with **{ensemble_result.confidence} METHOD AGREEMENT**

- **Final Verdict**: {ensemble_result.verdict}
- **Consensus Score**: {ensemble_result.consensus_score:.3f} ({ensemble_result.agreement}/{ensemble_result.total_methods} methods agree)
- **Method-agreement tier**: {ensemble_result.confidence}
- **Primary hypergeometric P-value**: {_format_p_value_safe(ensemble_result.combined_p_value)}
  - GO primary P-value: {_format_p_value_safe(ensemble_result.combined_p_value_go)}
  - KEGG primary P-value: {_format_p_value_safe(ensemble_result.combined_p_value_kegg)}
- **Methods Used**: {', '.join([r.method for r in ensemble_result.individual_results])}

---

## Decision Strategy

**Primary test plus correlated sensitivity analyses**

### Stage 1: Pre-specified primary test
- Exact right-tailed hypergeometric test
- Primary p-value: **{ensemble_result.combined_p_value:.2e}**

### Stage 2: Unweighted robustness assessment (descriptive only)
- **{ensemble_result.agreement}/{ensemble_result.total_methods}** methods support enrichment
- Consensus score: **{ensemble_result.consensus_score:.1%}**
- Overlap, Jaccard, Resnik-BMA and Lin-BMA are correlated sensitivity analyses
- Their p-values are not combined, do not veto the primary call, and are not treated as independent hypotheses

### Final Decision
- Verdict follows the **primary hypergeometric** call only: **{ensemble_result.verdict}**
- Method-agreement tier (descriptive): **{ensemble_result.confidence}**

The method-agreement tier is descriptive and is not a calibrated probability.
Benjamini-Hochberg correction must be applied across candidate hypotheses,
using their primary hypergeometric p-values.

---

""")
        
        # ============================================================
        # 2. Inputs Section
        # ============================================================
        f.write(f"""## Inputs

- A file: `{config.get('A', 'N/A')}`
- B file: `{config.get('B', 'auto-selected')}`
- Species: `{config.get('species', 'N/A')}`
- Universe: |U| = {U_size}
- |A| terms: {len(A_terms)}
- |B| terms: {len(B_terms)}

---

""")
        
        # ============================================================
        # 3. Ensemble Settings
        # ============================================================
        f.write("""## Ensemble Settings

| Parameter | Value |
|-----------|-------|
""")
        f.write(f"| Alpha | {config.get('alpha', 0.05):.5f} |\n")
        f.write(f"| Seed | {config.get('seed', 42)} |\n")
        f.write(f"| Ensemble Strategy | Primary hypergeometric only; auxiliaries = sensitivity |\n")
        
        # R values per method
        for r in ensemble_result.individual_results:
            r_val = r.metadata.get('R', 'N/A')
            f.write(f"| R ({r.method}) | {r_val} |\n")
        
        f.write("""
---

""")
        
        # ============================================================
        # 4. Individual Methods Results (DETAILED TABLE)
        # ============================================================
        f.write("""## Individual Methods Results

### Summary Table

| Method | P-value | Q-value | S_obs | mu | sd | Effect Size | Weight | Verdict | Runtime | Agrees |
|--------|---------|---------|-------|----|----|-------------|--------|---------|---------|--------|
""")
        
        for r in ensemble_result.individual_results:
            agrees = 'YES' if r.verdict == ensemble_result.verdict else 'NO'
            mu_val = r.metadata.get('mu', float('nan'))
            sd_val = r.metadata.get('sd', float('nan'))
            q_val_str = _format_p_value(r.q_value) if r.q_value is not None else 'N/A'
            f.write(
                f"| **{r.method}** | {_format_p_value(r.p_value)} | {q_val_str} | {r.s_obs:.5f} | "
                f"{mu_val:.5f} | {sd_val:.5f} | {r.effect_size:.4f} | "
                f"**{r.weight:.2f}** | {r.verdict} | {r.runtime:.2f}s | {agrees} |\n"
            )
        
        f.write("""

**Note**: For detailed statistics (null mean, SD, z-score, GO/KEGG breakdown, runtime, etc.), see `ensemble_summary.tsv`. For per-method enriched terms and full analysis reports, see individual method reports in `method_reports/`.

---

""")
        
        # ============================================================
        # 6. Consensus Analysis
        # ============================================================
        f.write("""
---

## Consensus Analysis

**Voting Results:**
""")
        
        # Count verdicts
        verdict_counts = {}
        for r in ensemble_result.individual_results:
            verdict_counts[r.verdict] = verdict_counts.get(r.verdict, 0) + 1
        
        for verdict, count in sorted(verdict_counts.items(), key=lambda x: -x[1]):
            pct = 100 * count / ensemble_result.total_methods
            f.write(f"- **{verdict}**: {count}/{ensemble_result.total_methods} methods ({pct:.1f}%)\n")
        
        f.write(f"""

**Consensus Score**: {ensemble_result.consensus_score:.3f}  
**Sensitivity agreement grading** (among the five methods; descriptive only):
- HIGH: ≥4 methods enriched
- MODERATE: exactly 3 methods enriched
- LOW: ≤2 methods enriched (primary still enriched)

**Agreement tier**: {ensemble_result.confidence}

""")
        
        # ============================================================
        # 7. Primary test and sensitivity analysis
        # ============================================================
        f.write(f"""
---

## Primary Test and Sensitivity Analysis

**Primary exact hypergeometric test:**
- Primary p-value: **{ensemble_result.combined_p_value:.2e}**

**Sensitivity-analysis p-values:**
- {', '.join([f"{r.method}={_format_p_value(r.p_value)}" for r in ensemble_result.individual_results])}

**By Ontology:**

*GO Terms:*
- Primary p-value: **{_format_p_value_safe(ensemble_result.combined_p_value_go)}**

*KEGG Pathways:*
- Primary p-value: **{_format_p_value_safe(ensemble_result.combined_p_value_kegg)}**

""")
        
        # ============================================================
        # 8. Enriched Terms Reference (Combined)
        # ============================================================
        # Collect all enriched terms across methods
        all_go_terms = set()
        all_kegg_terms = set()
        
        for r in ensemble_result.individual_results:
            if 'enriched_terms' in r.metadata:
                for term in r.metadata['enriched_terms']:
                    if term.startswith('GO:'):
                        all_go_terms.add(term)
                    elif term.startswith('hsa') or term.startswith('mmu'):
                        all_kegg_terms.add(term)
        
        if all_go_terms or all_kegg_terms:
            f.write("""
---

## Enriched Terms Reference

""")
            
            if all_go_terms:
                f.write(f"### GO Terms ({len(all_go_terms)})\n\n")
                for go_id in sorted(all_go_terms)[:50]:  # Limit to 50
                    go_name = go_meta.get(go_id, {}).get('name', 'Unknown')
                    go_url = f"http://amigo.geneontology.org/amigo/term/{go_id}"
                    f.write(f"- [{go_id}]({go_url}) — {go_name}\n")
                if len(all_go_terms) > 50:
                    f.write(f"\n*(Showing top 50 of {len(all_go_terms)} total)*\n")
                f.write("\n")
            
            if all_kegg_terms:
                f.write(f"### KEGG Pathways ({len(all_kegg_terms)})\n\n")
                for kegg_id in sorted(all_kegg_terms)[:50]:
                    kegg_name = kegg_meta.get(kegg_id, {}).get('name', 'Unknown')
                    kegg_url = f"https://www.kegg.jp/entry/{kegg_id}"
                    f.write(f"- [{kegg_id}]({kegg_url}) — {kegg_name}\n")
                if len(all_kegg_terms) > 50:
                    f.write(f"\n*(Showing top 50 of {len(all_kegg_terms)} total)*\n")
                f.write("\n")
        
        # ============================================================
        # 9. LLM Interpretation (if enabled)
        # ============================================================
        llm_interpretation_text = None  # Store formatted Markdown for JSON output
        llm_interpretation_structured = None  # Store structured JSON (preferred)
        llm_interpretation_raw = None  # Store raw model response (JSON string when available)
        llm_model_info = None
        llm_response = ""
        
        if config.get('llm_explain', False):
            # Determine LLM mode (MoE or single model)
            is_moe = config.get('llm_moe', False) and config.get('llm_expert_models_parsed')
            
            if is_moe:
                model_info = f"MoE ({len(config.get('llm_expert_models_parsed', []))} experts + reviewer)"
            else:
                model_info = f"{config.get('llm_model', 'N/A')} (via {config.get('llm_base_url', 'N/A')})"
            
            llm_model_info = model_info  # Store for JSON
            
            f.write(f"""
---

## LLM-based Interpretation

**Model:** {model_info}

""")
            
            # Import ensemble LLM prompt builder
            try:
                from orbit_ocsp.ensemble_llm_prompts import (
                    build_ensemble_llm_prompt,
                    build_moe_reviewer_prompt,
                )
                
                # Prepare ensemble result dict
                ensemble_dict = {
                    'verdict': ensemble_result.verdict,
                    'confidence': ensemble_result.confidence,
                    'consensus_score': ensemble_result.consensus_score,
                    'agreement': ensemble_result.agreement,
                    'total_methods': ensemble_result.total_methods,
                    'combined_p_value': ensemble_result.combined_p_value
                }
                
                # Prepare individual results list
                individual_list = []
                for r in ensemble_result.individual_results:
                    individual_list.append({
                        'method': r.method,
                        'verdict': r.verdict,
                        'p_right': r.p_value,
                        'p_value': r.p_value,
                        'q_value': r.q_value,
                        'effect_size': r.effect_size,
                        'weight': r.weight,
                        'metadata': r.metadata
                    })
                
                # Prepare experimental context from B_terms group metadata
                exp_context = {
                    'organ': config.get('organ', 'N/A'),
                    'model': config.get('model', 'N/A'),
                    'factor': config.get('factor', 'N/A'),
                    'gene_name': config.get('gene_name', 'N/A'),
                    'group_key': config.get('group_key', None)
                }
                
                # If group_metadata is available, use it to get real B_terms information
                if group_metadata and config.get('group_key'):
                    group_key = config.get('group_key')
                    if group_key in group_metadata:
                        real_metadata = group_metadata[group_key]
                        exp_context.update({
                            'organ': real_metadata.get('organ', config.get('organ', 'N/A')),
                            'model': real_metadata.get('model', config.get('model', 'N/A')),
                            'factor': real_metadata.get('factor', config.get('factor', 'N/A')),
                            'additional_condition': real_metadata.get('additional_condition', config.get('additional_condition', 'N/A')),
                            'category': real_metadata.get('category', 'N/A'),
                            'comparison_control': real_metadata.get('comparison_control', 'N/A'),
                            'comparison_condition': real_metadata.get('comparison_condition', 'N/A'),
                            'cell_type': real_metadata.get('cell_type', 'N/A'),
                            'day': real_metadata.get('day', 'N/A'),
                            'source': real_metadata.get('source', 'N/A')
                        })
                elif group_metadata:
                    # For gene-level analysis, try to get common information from all groups
                    # Find the most common values across all groups
                    all_organs = set()
                    all_models = set()
                    all_factors = set()
                    all_categories = set()
                    all_sources = set()
                    
                    for group_key, metadata in group_metadata.items():
                        if metadata.get('organ'):
                            all_organs.add(metadata['organ'])
                        if metadata.get('model'):
                            all_models.add(metadata['model'])
                        if metadata.get('factor'):
                            all_factors.add(metadata['factor'])
                        if metadata.get('category'):
                            all_categories.add(metadata['category'])
                        if metadata.get('source'):
                            all_sources.add(metadata['source'])
                    
                    # Use the most common values or first available
                    if all_organs:
                        exp_context['organ'] = list(all_organs)[0] if len(all_organs) == 1 else f"Multiple: {', '.join(sorted(all_organs))}"
                    if all_models:
                        exp_context['model'] = list(all_models)[0] if len(all_models) == 1 else f"Multiple: {', '.join(sorted(all_models))}"
                    if all_factors:
                        exp_context['factor'] = list(all_factors)[0] if len(all_factors) == 1 else f"Multiple: {', '.join(sorted(all_factors))}"
                    if all_categories:
                        exp_context['category'] = list(all_categories)[0] if len(all_categories) == 1 else f"Multiple: {', '.join(sorted(all_categories))}"
                    if all_sources:
                        exp_context['source'] = list(all_sources)[0] if len(all_sources) == 1 else f"Multiple: {', '.join(sorted(all_sources))}"
                
                # Prepare enriched terms (from method_details)
                enriched_go = []
                enriched_kegg = []
                
                # Collect unique enriched terms across all methods
                seen_terms = set()
                for r in ensemble_result.individual_results:
                    if r.verdict == 'enriched':
                        terms = r.metadata.get('enriched_terms', [])
                        for term in terms:
                            if term not in seen_terms:
                                seen_terms.add(term)
                                if term.startswith('GO:'):
                                    go_name = go_meta.get(term, {}).get('name', term)
                                    enriched_go.append({'id': term, 'name': go_name})
                                else:
                                    kegg_name = kegg_meta.get(term, {}).get('name', term)
                                    enriched_kegg.append({'id': term, 'name': kegg_name})
                
                enriched_terms_dict = {
                    'go_terms': enriched_go[:config.get('llm_max_terms', 20)],
                    'kegg_pathways': enriched_kegg[:config.get('llm_max_terms', 10)]
                }
                
                # Load protein evidence if available (using _load_gene_evidence like single-method analysis)
                protein_evidence_text = None
                gene_name = config.get('gene_name')
                evidence_dir = config.get('evidence_dir')
                
                if gene_name and evidence_dir:
                    # Use the same function as single-method analysis
                    ev = _load_gene_evidence(evidence_dir, gene_name)
                    if ev:
                        # Use _summarize_evidence to format (same as single-method)
                        try:
                            protein_evidence_text = _summarize_evidence(
                                ev,
                                max_interpro=5,  # Show top 5 InterPro entries
                                max_hits_per_db=2,
                                max_pathways=3,
                                summarize_by_desc=True,
                                max_desc_per_db=5,
                                header_only=False
                            )
                            if protein_evidence_text:
                                protein_evidence_text = protein_evidence_text.strip()
                        except Exception as e:
                            import sys
                            print(f"[WARN] Failed to format protein evidence for {gene_name}: {e}", file=sys.stderr)
                
                # Build ensemble LLM prompt + structured parser metadata
                prompt_spec = build_ensemble_llm_prompt(
                    ensemble_result=ensemble_dict,
                    individual_results=individual_list,
                    disease=config.get('condition', 'unspecified condition'),
                    experimental_context=exp_context,
                    enriched_terms=enriched_terms_dict,
                    protein_evidence=protein_evidence_text
                )
                llm_prompt = prompt_spec.get("prompt", "")
                llm_structured_parser = prompt_spec.get("parser")
                llm_system_prompt_override = prompt_spec.get("system_prompt")
                
                # Create llm_reports directory
                llm_reports_dir = os.path.join(output_dir, "llm_reports")
                os.makedirs(llm_reports_dir, exist_ok=True)
                
                # Save main prompt (MD format)
                with open(os.path.join(llm_reports_dir, "expert_prompt.md"), 'w', encoding='utf-8') as pf:
                    pf.write(llm_prompt)
                
                # Check llm_guard: only call LLM if conditions are met
                safe_to_call_llm, guard_reason = _check_llm_guard_ensemble(ensemble_result, config)
                
                # Call LLM (MoE or single model) only if guard allows
                if not safe_to_call_llm:
                    # Guard blocked the call - write explanation
                    alpha = config.get('alpha', 0.05)
                    guard_details = []
                    if config.get('llm_guard_verdict'):
                        guard_details.append(f"verdict='{config.get('llm_guard_verdict')}'")
                    if config.get('llm_guard_confidence'):
                        guard_details.append(f"confidence>='{config.get('llm_guard_confidence')}'")
                    if config.get('llm_guard_max_qvalue') is not None:
                        qval_thresh = config.get('llm_guard_max_qvalue')
                        guard_details.append(f"p<{qval_thresh:.3e}")
                    elif config.get('llm_guard'):
                        guard_details.append(f"p<{alpha:.3e}")
                    if config.get('llm_guard_min_consensus'):
                        guard_details.append(f"consensus>={config.get('llm_guard_min_consensus'):.3f}")
                    
                    guard_cond_text = ', '.join(guard_details) if guard_details else "llm_guard conditions"
                    f.write(f"*LLM interpretation skipped ({guard_reason}). Required conditions: {guard_cond_text}.*\n\n")
                    llm_interpretation_text = None
                    llm_interpretation_structured = None
                elif is_moe:
                    # MoE mode: call ensemble-adapted MoE
                    llm_response, moe_details = _ensemble_llm_moe_call_with_details(
                        prompt=llm_prompt,
                        expert_models=config.get('llm_expert_models_parsed'),
                        reviewer_model=config.get('llm_reviewer_model'),
                        reviewer_base_url=config.get('llm_reviewer_base_url'),
                        api_key=config.get('llm_api_key'),
                        parallel=config.get('llm_moe_parallel', True),
                        timeout=config.get('llm_timeout', 60),
                        show_experts=config.get('llm_moe_show_experts', False),
                        parser=llm_structured_parser,
                        system_prompt=llm_system_prompt_override,
                    )
                    
                    reviewer_structured = None
                    # Save expert responses and reviewer details (MD + JSON)
                    if moe_details:
                        expert_responses_json = []
                        for i, expert in enumerate(moe_details.get('experts', []), 1):
                            # MD format
                            formatted_output = expert.get('formatted_output', '') or expert.get('raw_output', '')
                            with open(os.path.join(llm_reports_dir, f"expert{i}_response.md"), 'w', encoding='utf-8') as ef:
                                ef.write(f"# Expert {i} Response\n\n")
                                ef.write(f"**Model:** {expert['model']}\n\n")
                                ef.write(f"**Role:** {expert['role']}\n\n")
                                ef.write(f"---\n\n{formatted_output}\n")
                            
                            # Collect for JSON
                            expert_responses_json.append(expert)
                        
                        # Save all expert responses as JSON with structured parsing
                        structured_experts = []
                        for expert in expert_responses_json:
                            structured_payload = expert.get('structured_output')
                            formatted_output = expert.get('formatted_output', '') or expert.get('raw_output', '')
                            if structured_payload is None:
                                structured_payload = _parse_expert_output(formatted_output)
                            structured_expert = {
                                'role': expert['role'],
                                'model': expert['model'],
                                'raw_output': expert.get('raw_output', ''),
                                'formatted_output': formatted_output,
                                'structured_output': structured_payload,
                            }
                            structured_experts.append(structured_expert)
                        
                        with open(os.path.join(llm_reports_dir, "experts.json"), 'w', encoding='utf-8') as ejf:
                            json.dump(structured_experts, ejf, indent=2, ensure_ascii=False)
                        
                        # Save reviewer prompt and response
                        reviewer_prompt = moe_details.get('reviewer_prompt', '')
                        reviewer_response = moe_details.get('reviewer_response', '')
                        reviewer_raw = moe_details.get('reviewer_raw', '')
                        reviewer_structured = moe_details.get('reviewer_structured', {})
                        if reviewer_prompt:
                            with open(os.path.join(llm_reports_dir, "reviewer_prompt.md"), 'w', encoding='utf-8') as rpf:
                                rpf.write(reviewer_prompt)
                        if reviewer_response or reviewer_raw:
                            with open(os.path.join(llm_reports_dir, "reviewer_response.md"), 'w', encoding='utf-8') as rrf:
                                rrf.write(f"# Reviewer Response\n\n{reviewer_response or reviewer_raw}")

                            structured_payload = reviewer_structured if isinstance(reviewer_structured, dict) else {}
                            structured_payload = {
                                "raw_response": reviewer_raw,
                                "formatted_response": reviewer_response,
                                "sections": structured_payload,
                            }
                            with open(os.path.join(llm_reports_dir, "reviewer_response.json"), 'w', encoding='utf-8') as rrjf:
                                json.dump(structured_payload, rrjf, indent=2, ensure_ascii=False)

                    if llm_response:
                        llm_interpretation_structured = reviewer_structured if isinstance(reviewer_structured, dict) else None
                        llm_interpretation_raw = reviewer_raw or llm_response
                else:
                    # Single model mode
                    llm_raw, llm_structured = _llm_call(
                        prompt=llm_prompt,
                        model=config.get('llm_model', 'gpt-4'),
                        api_key=config.get('llm_api_key'),
                        base_url=config.get('llm_base_url'),
                        timeout=config.get('llm_timeout', 60),
                        llm_enabled=True,
                        structured_parser=llm_structured_parser,
                        return_structured=True,
                        system_prompt=llm_system_prompt_override,
                    )

                    if llm_structured:
                        llm_formatted = _format_structured_ensemble_response(llm_structured)
                        llm_interpretation_structured = llm_structured
                    else:
                        llm_formatted = ""

                    llm_display = llm_formatted.strip() or (llm_raw or "").strip()
                    llm_interpretation_raw = llm_raw or llm_display

                    # Save single model response (MD + JSON)
                    with open(os.path.join(llm_reports_dir, "response.md"), 'w', encoding='utf-8') as rf:
                        rf.write("# LLM Response\n\n")
                        rf.write(llm_display or "No response")

                    response_payload = {
                        "raw_response": llm_raw or "",
                    }
                    if llm_structured:
                        response_payload["parsed_response"] = llm_structured

                    with open(os.path.join(llm_reports_dir, "response.json"), 'w', encoding='utf-8') as rjf:
                        json.dump(response_payload, rjf, indent=2, ensure_ascii=False)
                    
                    llm_response = llm_display
                
                # Write LLM response to report (only if guard allowed the call)
                if safe_to_call_llm:
                    formatted_llm_output = (llm_response or "").strip()
                    if (not formatted_llm_output) and llm_interpretation_structured:
                        formatted_llm_output = _format_structured_ensemble_response(llm_interpretation_structured)
                    if formatted_llm_output:
                        f.write(formatted_llm_output + "\n\n")
                        llm_interpretation_text = formatted_llm_output
                    else:
                        f.write("*LLM response not available.*\n\n")
                        llm_interpretation_text = None
                    
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"LLM interpretation failed: {e}\n{error_trace}")
                f.write(f"*LLM interpretation failed: {e}*\n\n")
                llm_interpretation_text = f"Error: {e}"
                llm_interpretation_structured = None
                llm_interpretation_raw = None
        
        # ============================================================
        # 10. Footer
        # ============================================================
        f.write("""
---

## Notes

- **Primary inference**: Exact hypergeometric enrichment is the pre-specified primary test.
- **Sensitivity analyses**: Overlap, Jaccard, Resnik-BMA and Lin-BMA assess robustness under complementary but correlated statistics.
- **Consensus Score**: Descriptive fraction of methods supporting enrichment; it is not a probability.
- **Multiple testing**: Apply BH correction across candidate genes or gene-condition hypotheses, not across methods.

*For method-specific details, refer to individual method sections above.*

---

*Generated by orbit-ocsp v2.0 — Ensemble Enrichment Analysis*
""")
    
    # ============================================================
    # Generate Additional Output Files
    # ============================================================
    
    # 1. Generate individual method reports
    # If this is a gene-specific analysis, put method reports in a subdirectory
    if gene_name:
        method_reports_dir = os.path.join(output_dir, "method_reports")
        os.makedirs(method_reports_dir, exist_ok=True)
    else:
        method_reports_dir = output_dir
    
    for r in ensemble_result.individual_results:
        method_name = r.method
        method_report_path = os.path.join(method_reports_dir, f"{method_name}_REPORT.md")
        
        with open(method_report_path, 'w', encoding='utf-8') as mf:
            mf.write(f"# {method_name.upper()} Method Report\n\n")
            mf.write(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}  \n")
            mf.write(f"**Part of Ensemble Analysis**\n\n")
            mf.write("---\n\n")
            
            mf.write("## Statistical Summary\n\n")
            mf.write(f"- Statistic: {method_name}\n")
            mf.write(f"- Observed S: {r.s_obs:.5f}\n")
            mf.write(f"- Null mean: {r.metadata.get('mu', 'N/A')}\n")
            mf.write(f"- Null SD: {r.metadata.get('sd', 'N/A')}\n")
            mf.write(f"- p_right: {_format_p_value(r.p_value)}\n")
            mf.write(f"- Effect size: {r.effect_size:.4f}\n")
            mf.write(f"- Verdict: {r.verdict}\n")
            mf.write(f"- Confidence (rule-based): {_confidence_label(r.p_value, r.verdict)}\n")
            mf.write(f"- Runtime: {r.runtime:.2f}s\n\n")
            
            mf.write("## Dataset Sizes\n\n")
            mf.write(f"- |A| = {r.metadata.get('A_size', 'N/A')}\n")
            mf.write(f"- |B| = {r.metadata.get('B_size', 'N/A')}\n")
            mf.write(f"- |A ∩ B| = {r.metadata.get('intersection_size', 'N/A')}\n")
            mf.write(f"- |U| = {r.metadata.get('U_size', 'N/A')}\n\n")
            
            if 'go_stats' in r.metadata or 'kegg_stats' in r.metadata:
                mf.write("## Ontology Breakdown\n\n")
                
                if 'go_stats' in r.metadata:
                    go_stats = r.metadata['go_stats']
                    mf.write(f"### GO Terms\n\n")
                    mf.write(f"- S_obs: {go_stats.get('s_obs', 'N/A'):.5f}\n")
                    mf.write(f"- mu: {go_stats.get('mu', 'N/A')}\n")
                    mf.write(f"- p_right: {_format_p_value_safe(go_stats.get('p_right', 'N/A'))}\n")
                    if 'q_value' in go_stats:
                        mf.write(f"- q_value (FDR): {_format_p_value_safe(go_stats.get('q_value'))}\n")
                    mf.write(f"- Verdict: {go_stats.get('verdict', 'N/A')}\n")
                    mf.write(f"- |A_GO| = {go_stats.get('A_size', 'N/A')}\n")
                    mf.write(f"- |B_GO| = {go_stats.get('B_size', 'N/A')}\n\n")
                
                if 'kegg_stats' in r.metadata:
                    kegg_stats = r.metadata['kegg_stats']
                    mf.write(f"### KEGG Pathways\n\n")
                    mf.write(f"- S_obs: {kegg_stats.get('s_obs', 'N/A'):.5f}\n")
                    mf.write(f"- mu: {kegg_stats.get('mu', 'N/A')}\n")
                    mf.write(f"- p_right: {_format_p_value_safe(kegg_stats.get('p_right', 'N/A'))}\n")
                    if 'q_value' in kegg_stats:
                        mf.write(f"- q_value (FDR): {_format_p_value_safe(kegg_stats.get('q_value'))}\n")
                    mf.write(f"- Verdict: {kegg_stats.get('verdict', 'N/A')}\n")
                    mf.write(f"- |A_KEGG| = {kegg_stats.get('A_size', 'N/A')}\n")
                    mf.write(f"- |B_KEGG| = {kegg_stats.get('B_size', 'N/A')}\n\n")
            
            if 'enriched_terms' in r.metadata:
                enriched = r.metadata['enriched_terms']
                go_terms = [t for t in enriched if t.startswith('GO:')]
                kegg_terms = [t for t in enriched if t.startswith('hsa') or t.startswith('mmu')]
                
                mf.write("## Enriched Terms\n\n")
                if go_terms:
                    mf.write(f"### GO Terms ({len(go_terms)})\n\n")
                    for term in go_terms[:100]:  # Limit to 100
                        term_name = go_meta.get(term, {}).get('name', 'Unknown')
                        mf.write(f"- {term} — {term_name}\n")
                    if len(go_terms) > 100:
                        mf.write(f"\n*(+ {len(go_terms) - 100} more)*\n")
                    mf.write("\n")
                
                if kegg_terms:
                    mf.write(f"### KEGG Pathways ({len(kegg_terms)})\n\n")
                    for term in kegg_terms[:100]:
                        term_name = kegg_meta.get(term, {}).get('name', 'Unknown')
                        mf.write(f"- {term} — {term_name}\n")
                    if len(kegg_terms) > 100:
                        mf.write(f"\n*(+ {len(kegg_terms) - 100} more)*\n")
                    mf.write("\n")
    
    # 2. Generate comprehensive summary TSV (integrated with GO/KEGG breakdown)
    tsv_path = os.path.join(output_dir, "ensemble_summary.tsv")
    with open(tsv_path, 'w', encoding='utf-8') as tf:
        # Comprehensive header (similar to single-method analysis)
        header = [
            "gene_name", "similarity_gene_name", "ENTREZ_ID", "pathway", "condition", 
            "additional_condition", "organ", "model", "category", "comparison_control", 
            "comparison_condition", "cell_type", "day", "factor", "source", "statistic",
            "P_value", "Q_value", "S_obs", "mu", "sd", "z_score", "Effect_Size", 
            "Weight", "Verdict", "Runtime", "R", "A_size", "B_size", "U_size", "Intersection",
            # GO breakdown
            "A_GO_size", "B_GO_size", "S_obs_GO", "mu_GO", "p_right_GO", "q_value_GO",
            "effect_size_GO", "verdict_GO",
            # KEGG breakdown
            "A_KEGG_size", "B_KEGG_size", "S_obs_KEGG", "mu_KEGG", "p_right_KEGG", "q_value_KEGG",
            "effect_size_KEGG", "verdict_KEGG"
        ]
        tf.write("\t".join(header) + "\n")
        
        # Data rows
        for r in ensemble_result.individual_results:
            row = []
            
            # Gene and pathway information (from gene_data)
            gene_name = config.get('gene_name', 'N/A')
            similarity_gene_name = ''
            entrez_id = ''
            gene_pathways = []
            
            # Use gene_data if available, otherwise fall back to A_terms
            if gene_data:
                similarity_gene_name = gene_data.get('similarity_gene_name', '')
                entrez_id = gene_data.get('ENTREZ_ID', '')
                gene_pathways = gene_data.get('pathway', [])
            elif A_terms:
                # Fallback: find gene information from A_terms
                for gene_info in A_terms:
                    if isinstance(gene_info, dict) and gene_info.get('gene_name') == gene_name:
                        similarity_gene_name = gene_info.get('similarity_gene_name', '')
                        entrez_id = gene_info.get('ENTREZ_ID', '')
                        gene_pathways = gene_info.get('pathway', [])
                        break
            
            row.append(gene_name)  # gene_name
            row.append(similarity_gene_name)  # similarity_gene_name
            row.append(entrez_id)  # ENTREZ_ID
            row.append(','.join(gene_pathways))  # pathway
            
            # Use group_metadata if available, fallback to config
            if group_metadata:
                # Get the first group's metadata (they should all be the same for ensemble)
                group_key = next(iter(group_metadata.keys())) if group_metadata else None
                meta = group_metadata.get(group_key, {}) if group_key else {}
                row.append(meta.get('condition', config.get('condition', 'N/A')))  # condition
                row.append(meta.get('additional_condition', config.get('additional_condition', 'N/A')))  # additional_condition
                row.append(meta.get('organ', config.get('organ', 'N/A')))  # organ
                row.append(meta.get('model', config.get('model', 'N/A')))  # model
            else:
                row.append(config.get('condition', 'N/A'))  # condition
                row.append(config.get('additional_condition', 'N/A'))  # additional_condition
                row.append(config.get('organ', 'N/A'))  # organ
                row.append(config.get('model', 'N/A'))  # model
            # Use group_metadata for other fields if available
            if group_metadata and group_key:
                meta = group_metadata.get(group_key, {})
                row.append(meta.get('category', ''))  # category
                row.append(meta.get('comparison_control', ''))  # comparison_control
                row.append(meta.get('comparison_condition', ''))  # comparison_condition
                row.append(meta.get('cell_type', ''))  # cell_type
                row.append(meta.get('day', ''))  # day
            else:
                row.append('')  # category
                row.append('')  # comparison_control
                row.append('')  # comparison_condition
                row.append('')  # cell_type
                row.append('')  # day
            # Use group_metadata for factor and source if available
            if group_metadata and group_key:
                meta = group_metadata.get(group_key, {})
                row.append(meta.get('factor', config.get('factor', 'N/A')))  # factor
                row.append(meta.get('source', ''))  # source
            else:
                row.append(config.get('factor', 'N/A'))  # factor
                row.append('')  # source
            row.append(r.method)  # statistic (method name)
            
            # Method-specific information
            row.append(_format_p_value_tsv(r.p_value))
            row.append(_format_p_value_tsv(r.q_value) if r.q_value is not None else 'NA')
            row.append(f"{r.s_obs:.5f}")
            row.append(str(r.metadata.get('mu', 'NA')))
            row.append(str(r.metadata.get('sd', 'NA')))
            
            # Z-score
            mu = r.metadata.get('mu', 0)
            sd = r.metadata.get('sd', 0)
            if isinstance(mu, (int, float)) and isinstance(sd, (int, float)) and sd > 0:
                z_score = (r.s_obs - mu) / sd
                row.append(f"{z_score:.4f}")
            else:
                row.append("NA")
            
            row.append(f"{r.effect_size:.4f}")
            row.append(f"{r.weight:.2f}")
            row.append(r.verdict)
            row.append(f"{r.runtime:.2f}")
            row.append(str(r.metadata.get('R', 'NA')))
            row.append(str(r.metadata.get('A_size', 'NA')))
            row.append(str(r.metadata.get('B_size', 'NA')))
            row.append(str(r.metadata.get('U_size', 'NA')))
            row.append(str(r.metadata.get('intersection_size', 'NA')))
            
            # GO breakdown
            if 'go_stats' in r.metadata:
                go_stats = r.metadata['go_stats']
                row.append(str(go_stats.get('A_size', 'NA')))
                row.append(str(go_stats.get('B_size', 'NA')))
                row.append(f"{go_stats.get('s_obs', 'NA')}")
                row.append(str(go_stats.get('mu', 'NA')))
                p_right_go = go_stats.get('p_right', 'NA')
                row.append(_format_p_value_tsv(p_right_go) if isinstance(p_right_go, (int, float)) else 'NA')
                # Q-value for GO
                q_value_go = go_stats.get('q_value', 'NA')
                row.append(_format_p_value_tsv(q_value_go) if isinstance(q_value_go, (int, float)) else 'NA')
                # Effect size for GO
                s_go = go_stats.get('s_obs', 0)
                mu_go = go_stats.get('mu', 0)
                if isinstance(s_go, (int, float)) and isinstance(mu_go, (int, float)) and mu_go > 0:
                    eff_go = (s_go - mu_go) / mu_go if mu_go > 0 else 0
                    row.append(f"{eff_go:.4f}")
                else:
                    row.append("NA")
                row.append(go_stats.get('verdict', 'NA'))
            else:
                row.extend(['NA'] * 8)
            
            # KEGG breakdown
            if 'kegg_stats' in r.metadata:
                kegg_stats = r.metadata['kegg_stats']
                row.append(str(kegg_stats.get('A_size', 'NA')))
                row.append(str(kegg_stats.get('B_size', 'NA')))
                row.append(f"{kegg_stats.get('s_obs', 'NA')}")
                row.append(str(kegg_stats.get('mu', 'NA')))
                p_right_kegg = kegg_stats.get('p_right', 'NA')
                row.append(_format_p_value_tsv(p_right_kegg) if isinstance(p_right_kegg, (int, float)) else 'NA')
                # Q-value for KEGG
                q_value_kegg = kegg_stats.get('q_value', 'NA')
                row.append(_format_p_value_tsv(q_value_kegg) if isinstance(q_value_kegg, (int, float)) else 'NA')
                # Effect size for KEGG
                s_kegg = kegg_stats.get('s_obs', 0)
                mu_kegg = kegg_stats.get('mu', 0)
                if isinstance(s_kegg, (int, float)) and isinstance(mu_kegg, (int, float)) and mu_kegg > 0:
                    eff_kegg = (s_kegg - mu_kegg) / mu_kegg if mu_kegg > 0 else 0
                    row.append(f"{eff_kegg:.4f}")
                else:
                    row.append("NA")
                row.append(kegg_stats.get('verdict', 'NA'))
            else:
                row.extend(['NA'] * 8)
            
            tf.write("\t".join(row) + "\n")
    
    # 4. Generate JSON report
    if gene_name:
        json_filename = "ENSEMBLE.json"
    else:
        json_filename = "ENSEMBLE_REPORT.json"
    json_path = os.path.join(output_dir, json_filename)
    # Convert config to JSON-serializable format
    json_config = config.copy()
    if 'group_key' in json_config and isinstance(json_config['group_key'], tuple):
        json_config['group_key'] = str(json_config['group_key'])
    if 'group_metadata' in json_config and isinstance(json_config['group_metadata'], dict):
        # Convert group_metadata keys to strings
        json_group_metadata = {}
        for key, value in json_config['group_metadata'].items():
            if isinstance(key, tuple):
                json_group_metadata[str(key)] = value
            else:
                json_group_metadata[key] = value
        json_config['group_metadata'] = json_group_metadata
    
    # Helper function to format p-values
    def format_pvalue(p):
        if p is None:
            return "NA"
        return f"{p:.2e}"
    
    # Helper function to add formatted fields to method results
    def _add_formatted_fields(result, fmt_func):
        method_dict = {
            "method": result.method,
            "verdict": result.verdict,
            "p_value": result.p_value,
            "p_value_formatted": fmt_func(result.p_value),
            "q_value": result.q_value,
            "q_value_formatted": fmt_func(result.q_value) if result.q_value is not None else "NA",
            "effect_size": result.effect_size,
            "s_obs": result.s_obs,
            "runtime": result.runtime,
            "metadata": {}
        }
        
        # Copy metadata and add formatted versions
        for key, value in result.metadata.items():
            if key == "go_stats" and isinstance(value, dict):
                method_dict["metadata"]["go_stats"] = {
                    **value,
                    "p_right_formatted": fmt_func(value.get("p_right")),
                    "q_value_formatted": fmt_func(value.get("q_value")) if "q_value" in value else "NA"
                }
            elif key == "kegg_stats" and isinstance(value, dict):
                method_dict["metadata"]["kegg_stats"] = {
                    **value,
                    "p_right_formatted": fmt_func(value.get("p_right")),
                    "q_value_formatted": fmt_func(value.get("q_value")) if "q_value" in value else "NA"
                }
            else:
                method_dict["metadata"][key] = value
        
        return method_dict
    
    json_data = {
        "metadata": {
            "title": "Ensemble Enrichment Analysis Report",
            "generated": ensemble_result.timestamp,
            "type": "ensemble_report",
            "strategy": "primary_hypergeometric_only"
        },
        "config": json_config,
        "ensemble_result": {
            "verdict": ensemble_result.verdict,
            "confidence": ensemble_result.confidence,
            "consensus_score": ensemble_result.consensus_score,
            "agreement": ensemble_result.agreement,
            "total_methods": ensemble_result.total_methods,
            "primary_test": "exact_hypergeometric",
            "primary_p_value": ensemble_result.primary_p_value,
            "primary_q_value": ensemble_result.primary_q_value,
            "agreement_tier": ensemble_result.confidence,
            "agreement_tier_note": "Descriptive; not a calibrated probability.",
            "multiple_testing_note": "Apply BH across candidate hypotheses using primary p-values.",
            # Deprecated aliases retained for consumers of pre-0.4 reports.
            "combined_p_value": ensemble_result.combined_p_value,
            "combined_p_value_formatted": format_pvalue(ensemble_result.combined_p_value),
            "combined_p_value_go": ensemble_result.combined_p_value_go,
            "combined_p_value_go_formatted": format_pvalue(ensemble_result.combined_p_value_go),
            "combined_p_value_kegg": ensemble_result.combined_p_value_kegg,
            "combined_p_value_kegg_formatted": format_pvalue(ensemble_result.combined_p_value_kegg)
        },
        "individual_methods": [
            _add_formatted_fields(r, format_pvalue)
            for r in ensemble_result.individual_results
        ],
        "dataset_sizes": {
            "A": len(A_terms),
            "B": len(B_terms),
            "U": U_size
        }
    }
    
    # Add Enriched Terms Reference (same as in Markdown report)
    all_go_terms = set()
    all_kegg_terms = set()
    
    for r in ensemble_result.individual_results:
        if 'enriched_terms' in r.metadata:
            for term in r.metadata['enriched_terms']:
                if term.startswith('GO:'):
                    all_go_terms.add(term)
                elif term.startswith('hsa') or term.startswith('mmu'):
                    all_kegg_terms.add(term)
    
    enriched_terms_reference = {}
    if all_go_terms:
        enriched_terms_reference["go_terms"] = []
        for go_id in sorted(all_go_terms):
            go_name = go_meta.get(go_id, {}).get('name', 'Unknown')
            go_url = f"http://amigo.geneontology.org/amigo/term/{go_id}"
            enriched_terms_reference["go_terms"].append({
                "id": go_id,
                "name": go_name,
                "url": go_url
            })
    
    if all_kegg_terms:
        enriched_terms_reference["kegg_pathways"] = []
        for kegg_id in sorted(all_kegg_terms):
            kegg_name = kegg_meta.get(kegg_id, {}).get('name', 'Unknown')
            kegg_url = f"https://www.kegg.jp/entry/{kegg_id}"
            enriched_terms_reference["kegg_pathways"].append({
                "id": kegg_id,
                "name": kegg_name,
                "url": kegg_url
            })
    
    if enriched_terms_reference:
        json_data["enriched_terms_reference"] = enriched_terms_reference
    
    # Add LLM interpretation if available (structured)
    if (llm_interpretation_text is not None) or (llm_interpretation_structured is not None):
        raw_payload = llm_interpretation_raw if llm_interpretation_raw is not None else llm_interpretation_text
        structured_payload = llm_interpretation_structured

        # If structured_payload is None or empty, try to parse from raw_payload
        if (not structured_payload or (isinstance(structured_payload, dict) and not any(structured_payload.values()))) and raw_payload:
            try:
                structured_candidate = json.loads(raw_payload)
                if isinstance(structured_candidate, dict):
                    # Check if it's a reviewer-style JSON (with lists for each section)
                    if any(key in structured_candidate for key in ['consensus_findings', 'unique_insights', 'resolution_of_disagreements', 'final_recommendations']):
                        # Normalize it using the same logic
                        structured_payload = _normalize_reviewer_structured(structured_candidate)
                    else:
                        structured_payload = structured_candidate
            except Exception:
                structured_payload = None

        # If still None, try legacy Markdown parser
        if (not structured_payload or (isinstance(structured_payload, dict) and not any(structured_payload.values()))) and llm_interpretation_text:
            # Fallback to legacy Markdown parser for older formats
            structured_payload = _parse_llm_ensemble_response(llm_interpretation_text or "")

        json_data["llm_interpretation"] = {
            "model": llm_model_info,
            "raw_content": raw_payload,
            "markdown": llm_interpretation_text,
            "structured": structured_payload or {}
        }
    
    with open(json_path, 'w', encoding='utf-8') as jf:
        json.dump(json_data, jf, indent=2, ensure_ascii=False)
    
    return report_path

    # Fallback function
    def tqdm(iterable, desc="", **kwargs):
        return iterable


# Logging setup


def setup_logging(level=logging.INFO):
    """Setup logging configuration."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler("orbit_ocsp.log"),
        ],
    )
    return logging.getLogger("orbit_ocsp")


# Global logger
logger = setup_logging()

# Cache management
_cache_dir = None
_cache_enabled = True

def _get_cache_dir():
    """Get or create cache directory."""
    global _cache_dir
    if _cache_dir is None:
        _cache_dir = os.path.join(os.getcwd(), ".orbit_ocsp_cache")
    os.makedirs(_cache_dir, exist_ok=True)
    return _cache_dir

def _get_cache_key(*args, **kwargs):
    """Generate cache key from function arguments."""
    # Create a hash of the arguments
    key_data = str(args) + str(sorted(kwargs.items()))
    return hashlib.md5(key_data.encode()).hexdigest()

def cached_computation(cache_name, max_age_hours=24):
    """Decorator for caching expensive computations."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _cache_enabled:
                return func(*args, **kwargs)
                
            cache_dir = _get_cache_dir()
            cache_file = os.path.join(cache_dir, f"{cache_name}_{_get_cache_key(*args, **kwargs)}.pkl")
            
            # Check if cache exists and is fresh
            if os.path.exists(cache_file):
                try:
                    cache_time = os.path.getmtime(cache_file)
                    if time.time() - cache_time < max_age_hours * 3600:
                        with open(cache_file, 'rb') as f:
                            return pickle.load(f)
                except Exception:
                    # If cache is corrupted, remove it
                    try:
                        os.remove(cache_file)
                    except Exception:
                        pass
            
            # Compute result and cache it
            result = func(*args, **kwargs)
            try:
                with open(cache_file, 'wb') as f:
                    pickle.dump(result, f)
            except Exception:
                # If caching fails, just continue without cache
                pass
                
            return result
        return wrapper
    return decorator

def clear_cache(cache_name=None):
    """Clear cache files."""
    cache_dir = _get_cache_dir()
    if cache_name:
        pattern = f"{cache_name}_*.pkl"
        for file in os.listdir(cache_dir):
            if file.startswith(f"{cache_name}_") and file.endswith(".pkl"):
                os.remove(os.path.join(cache_dir, file))
    else:
        for file in os.listdir(cache_dir):
            if file.endswith(".pkl"):
                os.remove(os.path.join(cache_dir, file))

# Optional NumPy acceleration
try:
    import numpy as _np

    _NP_AVAILABLE = True
except Exception:
    _NP_AVAILABLE = False


def _summarize_null(
    null_stats: list[float], S_obs: float, R: int
) -> tuple[float, float, float, float, float, float]:
    """Return (mu, sd, p_right, p_left, p_two, effect_size) with optional NumPy acceleration.
    - sd follows population stdev semantics used in pstdev; when <2 points, returns NaN.
    - Empirical p-values use +1 smoothing: (extremes+1)/(R+1) consistent with the rest of the script.
    """
    if not null_stats:
        mu = 0.0
        sd = float("nan")
        p_right = p_left = p_two = 1.0
        return mu, sd, p_right, p_left, p_two, (0.0 - mu)
    if _NP_AVAILABLE:
        arr = _np.asarray(null_stats, dtype=float)
        mu = float(arr.mean()) if arr.size else 0.0
        sd = float(arr.std(ddof=0)) if arr.size > 1 else float("nan")
        right_extreme = int((arr >= S_obs).sum())
        left_extreme = int((arr <= S_obs).sum())
    else:
        mu = mean(null_stats)
        sd = pstdev(null_stats) if len(null_stats) > 1 else float("nan")
        right_extreme = sum(1 for s in null_stats if s >= S_obs)
        left_extreme = sum(1 for s in null_stats if s <= S_obs)
    p_right = (right_extreme + 1) / (R + 1) if R > 0 else 1.0
    p_left = (left_extreme + 1) / (R + 1) if R > 0 else 1.0
    p_two = min(1.0, 2.0 * min(p_right, p_left))
    effect_size = S_obs - mu
    return mu, sd, p_right, p_left, p_two, effect_size


# --- KEGG allowed set helper ---
@lru_cache(maxsize=32)
def _allowed_kegg_set_cached(keys: tuple[str, ...]) -> set[str]:
    return set(x.lower() for x in keys)

#
# --- HOW TO USE GO-STRUCTURED NULL ---
# Example:
#   go_depth_map = _approx_go_depth_map_from_ancestors(go_ancestors)
#   go_buckets = stratify_go_multi(
#       u_terms=[t for t in U if t.startswith("GO:")],
#       size_map=term_size_map,
#       size_bins=parse_bins,
#       ns_map=go_namespace_map,
#       depth_map=go_depth_map,
#       depth_bins=[0,5,10,20,50,999999],
#   )
#   null_sets = make_B_randoms(
#       B=B_GO,
#       U_list=list(U),
#       U_buckets=go_buckets,               # dict triggers structured sampling
#       size_map=term_size_map,
#       bins=parse_bins,
#       rng=rng,
#       R=R,
#       go_ns_map=go_namespace_map,
#       go_depth_map=go_depth_map,
#       go_depth_bins=[0,5,10,20,50,999999],
#   )
@cached_computation("permutation_generation", max_age_hours=12)
def _generate_permutations_cached(B, U_list, bins, rng, R, desc):
    """Cached version of permutation generation."""
    return make_B_randoms(B, U_list, None, None, bins, rng, R, desc)

@cached_computation("semantic_computation", max_age_hours=24)
def _semantic_go_component_cached(A_GO, B_GO, go_anc, ic_map):
    """Cached version of semantic GO computation."""
    return _semantic_go_component(A_GO, B_GO, go_anc, ic_map)

@cached_computation("semantic_kegg_computation", max_age_hours=24)
def _semantic_kegg_component_cached(A_KEGG, B_KEGG, base):
    """Cached version of semantic KEGG computation."""
    return _semantic_kegg_component(A_KEGG, B_KEGG, base)


# --- Robustness helpers ---


def _fmt5(x: float) -> str:
    """Format float to 5 decimals; return 'nan' if not a finite float."""
    try:
        if x is None:
            return "nan"
        xf = float(x)
        if math.isnan(xf) or math.isinf(xf):
            return "nan"
        return f"{xf:.5f}"
    except Exception:
        return "nan"


def _cap01(x: float) -> float:
    """Cap value into [0,1] if numeric; else return nan."""
    try:
        xf = float(x)
        if xf < 0.0:
            return 0.0
        if xf > 1.0:
            return 1.0
        return xf
    except Exception:
        return float("nan")


def _normalize_llm_text(s: str) -> str:
    """Normalize LLM text for nicer Markdown rendering.
    - Ensures a line break before/after a trailing 'Confidence: <High|Moderate|Low>' line.
    - Ensures the block ends with a blank line.
    Safe no-op on empty or malformed input.
    """
    try:
        t = (s or "").strip()
        if not t:
            return ""
        # Ensure 'Confidence: ...' starts on its own line
        t = re.sub(r"(?i)(?<!\n)(Confidence:\s*(Very High|High|Moderate|Low|Very Low))", r"\n\1", t)
        # Ensure a newline after the Confidence line
        t = re.sub(r"(?i)(Confidence:\s*(Very High|High|Moderate|Low|Very Low))(?!\n)", r"\1\n", t)
        return t + "\n\n"
    except Exception:
        return (s or "").strip() + "\n\n"


# --- Evidence loading and summarization ---
def _load_gene_evidence(evidence_dir: str | None, gene_name: str) -> dict | None:
    if not evidence_dir:
        return None
    try:
        fn = os.path.join(evidence_dir, f"{gene_name}.evidence.json")
        if os.path.exists(fn):
            with open(fn, "r", encoding="utf-8") as f:
                return json.load(f)
        fn_sanitize = os.path.join(
            evidence_dir, f"{_sanitize_name(gene_name)}.evidence.json"
        )
        if fn_sanitize != fn and os.path.exists(fn_sanitize):
            with open(fn_sanitize, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return None
    return None


def _try_float(x):
    try:
        return float(str(x))
    except Exception:
        return None


def _summarize_evidence(
    ev: dict | None,
    max_interpro: int = 0,
    max_hits_per_db: int = 2,
    max_pathways: int = 5,
    analyses: tuple[str, ...] = (
        "Pfam",
        "CDD",
        "NCBIfam",
        "PANTHER",
        "Gene3D",
        "ProSitePatterns",
        "ProSiteProfiles",
        "SUPERFAMILY",
    ),
    summarize_by_desc: bool = False,
    max_desc_per_db: int = 5,
    header_only: bool = False,
) -> str:
    if not ev or not isinstance(ev, dict):
        return ""
    lines = []
    # Header: accessions / length / coverage
    accs = ev.get("protein_accessions") or []
    if accs:
        head = ", ".join(accs[:2]) + (" …" if len(accs) > 2 else "")
        lines.append(f"- Accessions: {head} (n={len(accs)})")
    if ev.get("sequence_length"):
        lines.append(f"- Length: {ev.get('sequence_length')}")
    cov = ev.get("coverage") or {}
    if cov.get("fraction_covered") is not None:
        frac = cov.get("fraction_covered")
        span = cov.get("approx_span") or []
        span_s = f"{span[0]}–{span[1]}" if len(span) == 2 else "NA"
        lines.append(f"- Coverage: {frac} (span {span_s})")
    if header_only:
        return "\n".join(lines)

    # InterPro (summarized by description with counts)
    ipr = ev.get("interpro") or []
    ipr = [
        it
        for it in ipr
        if str(it.get("accession", "") or "") not in ("", "-")
        and str(it.get("description", "") or "") not in ("", "-")
    ]
    if ipr:
        ip_counts: dict[str, int] = {}
        for it in ipr:
            desc = str(it.get("description", "") or "").strip()
            if not desc:
                continue
            ip_counts[desc] = ip_counts.get(desc, 0) + 1
        if ip_counts:
            items = sorted(ip_counts.items(), key=lambda x: (-x[1], x[0]))
            if max_interpro and max_interpro > 0:
                items = items[:max_interpro]
            joined = "; ".join([f"{d} (n={c})" for d, c in items])
            lines.append(f"- InterPro (descriptions): {joined}")
    # Hits per analysis (either pick best few or summarize by description)
    hits = ev.get("hits") or []
    if hits:
        by_db: dict[str, list[dict]] = {}
        for h in hits:
            db = str(h.get("analysis", "") or "")
            if analyses and db not in analyses:
                continue
            by_db.setdefault(db, []).append(h)
        for db, arr in by_db.items():
            if summarize_by_desc:
                # group by normalized description and count occurrences
                counts: dict[str, int] = {}
                for h in arr:
                    desc = str(h.get("description", "") or "").strip()
                    if not desc:
                        desc = "(unknown)"
                    counts[desc] = counts.get(desc, 0) + 1
                # sort by count desc, then alpha; cap
                items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
                if max_desc_per_db and max_desc_per_db > 0:
                    items = items[:max_desc_per_db]
                if items:
                    joined = "; ".join([f"{d} (n={c})" for d, c in items])
                    lines.append(f"- {db} (descriptions): {joined}")
            else:
                # sort by numeric score if possible (ascending), otherwise keep order, then cap per db
                arr2 = sorted(
                    arr,
                    key=lambda x: (
                        _try_float(x.get("score")) is None,
                        _try_float(x.get("score")) or 0.0,
                    ),
                )[:max_hits_per_db]
                for h in arr2:
                    sig = h.get("signature", "")
                    desc = h.get("description", "")
                    s = h.get("start", "")
                    e = h.get("stop", "")
                    sc = h.get("score", "")
                    lines.append(f"- {db}: {sig} — {desc} ({s}-{e}; {sc})")
    # Pathways raw (Reactome/MetaCyc subset)
    pws = [
        p
        for p in (ev.get("pathways_raw") or [])
        if (p.startswith("Reactome:") or p.startswith("MetaCyc:"))
    ]
    if pws:
        for p in pws[:max_pathways]:
            lines.append(f"- Pathway: {p}")
        if len(pws) > max_pathways:
            lines.append(f"- Pathway: (+{len(pws)-max_pathways} more)")
    return "\n".join(lines)


def _summarize_evidence_multi(
    evs: list[dict] | None,
    max_interpro: int = 5,
    analyses: tuple[str, ...] = (
        "Pfam",
        "CDD",
        "NCBIfam",
        "PANTHER",
        "Gene3D",
        "ProSitePatterns",
        "ProSiteProfiles",
        "SUPERFAMILY",
    ),
    max_desc_per_db: int = 5,
) -> str:
    if not evs:
        return ""
    # Aggregate InterPro descriptions
    ip_counts: dict[str, int] = {}
    for ev in evs:
        for it in ev.get("interpro") or []:
            acc = str(it.get("accession", "") or "")
            desc = str(it.get("description", "") or "")
            if acc in ("", "-") or desc in ("", "-"):
                continue
            ip_counts[desc] = ip_counts.get(desc, 0) + 1
    lines = []
    if ip_counts:
        items = sorted(ip_counts.items(), key=lambda x: (-x[1], x[0]))
        if max_interpro and max_interpro > 0:
            items = items[:max_interpro]
        joined = "; ".join([f"{d} (n={c})" for d, c in items])
        lines.append(f"- InterPro (descriptions): {joined}")

    # Aggregate per-analysis descriptions from hits
    db_desc_counts: dict[str, dict[str, int]] = {}
    for ev in evs:
        for h in ev.get("hits") or []:
            db = str(h.get("analysis", "") or "")
            if analyses and db not in analyses:
                continue
            desc = str(h.get("description", "") or "").strip() or "(unknown)"
            db_desc_counts.setdefault(db, {})
            db_desc_counts[db][desc] = db_desc_counts[db].get(desc, 0) + 1
    for db, cnts in db_desc_counts.items():
        items = sorted(cnts.items(), key=lambda x: (-x[1], x[0]))
        if max_desc_per_db and max_desc_per_db > 0:
            items = items[:max_desc_per_db]
        joined = "; ".join([f"{d} (n={c})" for d, c in items])
        lines.append(f"- {db} (descriptions): {joined}")
    return "\n".join(lines)


def _summarize_evidence_detailed_multi(
    evs: list[dict] | None,
    max_interpro: int = 5,
    analyses: tuple[str, ...] = (
        "Pfam",
        "CDD",
        "NCBIfam",
        "PANTHER",
        "Gene3D",
        "ProSitePatterns",
        "ProSiteProfiles",
        "SUPERFAMILY",
    ),
    max_desc_per_db: int = 5,
) -> str:
    """Generate detailed protein evidence summary for multiple genes, showing per-gene information."""
    if not evs:
        return ""

    lines = []
    for ev in evs:
        if not ev or not isinstance(ev, dict):
            continue

        gene_name = str(ev.get("gene_name", "") or "UNKNOWN")
        lines.append(f"**Gene: {gene_name}**")

        # Gene-specific header information
        accs = ev.get("protein_accessions") or []
        if accs:
            head = ", ".join(accs[:2]) + (" …" if len(accs) > 2 else "")
            lines.append(f"- Accessions: {head} (n={len(accs)})")
        if ev.get("sequence_length"):
            lines.append(f"- Length: {ev.get('sequence_length')}")
        cov = ev.get("coverage") or {}
        if cov.get("fraction_covered") is not None:
            frac = cov.get("fraction_covered")
            span = cov.get("approx_span") or []
            span_s = f"{span[0]}–{span[1]}" if len(span) == 2 else "NA"
            lines.append(f"- Coverage: {frac} (span {span_s})")

        # InterPro results for this gene
        ipr = ev.get("interpro") or []
        ipr = [
            it
            for it in ipr
            if str(it.get("accession", "") or "") not in ("", "-")
            and str(it.get("description", "") or "") not in ("", "-")
        ]
        if ipr:
            if max_interpro and max_interpro > 0:
                ipr = ipr[:max_interpro]
            ipr_items = []
            for it in ipr:
                acc = str(it.get("accession", "") or "")
                desc = str(it.get("description", "") or "")
                ipr_items.append(f"{acc} — {desc}")
            lines.append(f"- InterPro: {'; '.join(ipr_items)}")

        # Analysis results for this gene
        hits = ev.get("hits") or []
        db_hits = {}
        for h in hits:
            db = str(h.get("analysis", "") or "")
            if analyses and db not in analyses:
                continue
            desc = str(h.get("description", "") or "").strip() or "(unknown)"
            if db not in db_hits:
                db_hits[db] = []
            db_hits[db].append(desc)

        for db, descs in db_hits.items():
            if max_desc_per_db and max_desc_per_db > 0:
                descs = descs[:max_desc_per_db]
            unique_descs = list(
                dict.fromkeys(descs)
            )  # Remove duplicates while preserving order
            lines.append(f"- {db}: {'; '.join(unique_descs)}")

        lines.append("")  # Empty line between genes

    return "\n".join(lines)


def _parse_bins(bins_str: str) -> list[int]:
    """Parse comma-separated bins string into a strictly increasing integer list with basic sanity checks.
    Falls back to a safe default if parsing fails."""
    default_bins = [0, 20, 50, 100, 200, 999999]
    try:
        parts = [int(p.strip()) for p in str(bins_str).split(",") if str(p).strip()]
        parts = sorted(set(parts))
        if len(parts) < 2 or parts[0] != 0:
            print(
                f"[WARN] bins invalid -> fallback to default {default_bins}",
                file=sys.stderr,
            )
            return default_bins
        return parts
    except Exception:
        print(
            f"[WARN] bins parse failed -> fallback to default {default_bins}",
            file=sys.stderr,
        )
        return default_bins


# Resolve project root (one level above this package directory)
_PKG_ROOT = Path(__file__).resolve().parents[1]


def _resolve_default(relpath: str) -> str:
    """Resolve bundled data paths via ``orbit_ocsp.data_manager``."""
    from orbit_ocsp.data_manager import resolve_data_path

    return resolve_data_path(relpath)


# Accept GO IDs with 1–7 digits, normalize with zero-padding to 7
GO_PAT = re.compile(r"^GO:\d{1,7}$", re.IGNORECASE)
# NOTE: KEGG IDs allowed: hsa/mmu (species-specific) and map/ko (cross-species reference). Other prefixes are rejected.
KEGG_PAT = re.compile(r"^(hsa|mmu|map|ko)\d{5}$", re.IGNORECASE)


# Safe JSON loader used for metadata (GO/KEGG)
def _load_json_safe(path: str | None) -> dict:
    try:
        if not path:
            return {}
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# --- KEGG helpers ---
def _kegg_prefix(s: str) -> str:
    m = re.match(r"^([A-Za-z]{2,3})(\d{5})$", str(s))
    return m.group(1).lower() if m else ""


def _is_kegg_allowed(t: str, allowed_kegg: tuple[str, ...]) -> bool:
    t = str(t)
    if not t or len(t) < 7:
        return False
    prefix = t[:3].lower()
    if prefix not in _allowed_kegg_set_cached(tuple(allowed_kegg)):
        # fallback to regex for other valid 2-letter codes
        m = re.match(r"^([A-Za-z]{2,3})(\d{5})$", t)
        return bool(
            m and m.group(1).lower() in _allowed_kegg_set_cached(tuple(allowed_kegg))
        )
    return bool(re.match(r"^[A-Za-z]{2,3}\d{5}$", t))


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _estimate_memory_usage(A_size: int, B_size: int, U_size: int, R: int) -> str:
    """Estimate memory usage for permutation test."""
    # Rough estimate: each permutation stores a set of size B_size
    # Each string is ~50 bytes on average
    bytes_per_permutation = B_size * 50
    total_bytes = R * bytes_per_permutation
    total_mb = total_bytes / (1024 * 1024)

    if total_mb < 100:
        return f"~{total_mb:.1f}MB"
    elif total_mb < 1000:
        return f"~{total_mb:.1f}MB"
    else:
        return f"~{total_mb/1024:.1f}GB"


def _validate_parameters(args) -> List[str]:
    """Validate command line parameters and return list of errors."""
    errors = []

    # Check required parameters
    if (
        not args.A
        and not args.condition_list
        and not args.organ_list
        and not args.model_list
        and not args.llm_list
    ):
        errors.append(
            "--A is required unless using --condition-list, --organ-list, --model-list, or --llm-list"
        )

    if (
        not args.species
        and not args.condition_list
        and not args.organ_list
        and not args.model_list
        and not args.llm_list
    ):
        errors.append(
            "--species is required unless using --condition-list, --organ-list, --model-list, or --llm-list"
        )

    # Validate numeric parameters
    if args.R <= 0:
        errors.append("--R must be positive")

    if not 0 < args.alpha < 1:
        errors.append("--alpha must be between 0 and 1")

    if args.seed < 0:
        errors.append("--seed must be non-negative")

    # Validate file paths
    if args.A and not os.path.exists(args.A):
        errors.append(f"File not found: {args.A}")

    if args.B and not os.path.exists(args.B):
        errors.append(f"File not found: {args.B}")
    
    # Validate output directory permissions
    if args.outdir:
        try:
            os.makedirs(args.outdir, exist_ok=True)
            # Test write permission
            test_file = os.path.join(args.outdir, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except (OSError, PermissionError) as e:
            errors.append(f"Cannot write to output directory {args.outdir}: {e}")
    
    # Validate species format
    if args.species and not re.match(r'^[a-z]{3}$', args.species):
        errors.append(f"Invalid species format: {args.species}. Expected 3-letter code (e.g., 'hsa', 'mmu')")

    # Validate LLM parameters
    if args.llm_explain:
        if args.llm_timeout <= 0:
            errors.append("--llm-timeout must be positive")

        if args.llm_max_terms <= 0:
            errors.append("--llm-max-terms must be positive")

    return errors


# --- Confidence label helper (rule-based) ---
def _confidence_label(p_right: float | None, verdict: str | None) -> str:
    try:
        pr = float(p_right) if p_right is not None else float("nan")
    except Exception:
        pr = float("nan")
    v = (verdict or "").strip().lower()
    if v == "enriched" and pr < 0.01:
        return "High"
    if v == "enriched" and pr < 0.05:
        return "Moderate"
    return "Low"


# --- RNG helper for per-group reproducibility ---
def make_group_rng(seed: int, scope: str):
    """Return a function rng_for_group((cond, add, organ, model)) -> random.Random
    scope: 'global' uses a shared RNG; 'per-group' derives a stable seed from key+seed.
    """
    shared = random.Random(seed)

    def _rng_for_group(key: tuple[str, str, str, str]):
        if scope == "per-group":
            s = "|".join(key) + f"#{seed}"
            h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]
            return random.Random(int(h, 16))
        return shared

    return _rng_for_group


def norm_id(x: str, allowed_kegg: tuple[str, ...] = ("hsa",)) -> str | None:
    """
    Normalize a term ID.
    - Keep GO:#######.
    - Keep KEGG with prefixes in allowed_kegg (default: ('hsa',)).
      Common prefixes include 'hsa','mmu','map','ko'. Use ('hsa','mmu',...) to allow more.
    - Drop everything else (Reactome R-HSA-, PANTHER P000xx, Disease H00xxx, pure numbers, etc.)
    """
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() == "nan":
        return None
    if s.lower().startswith("path:"):
        s = s.split(":", 1)[1].strip()
    s = s.replace(" ", "")

    # GO
    if GO_PAT.match(s):
        return "GO:" + s.split(":")[1].zfill(7)

    # KEGG (restricted)
    m = KEGG_PAT.match(s)
    if m:
        prefix = s[:3].lower()
        if prefix in _allowed_kegg_set_cached(tuple(allowed_kegg)):
            digits = re.findall(r"\d{5}", s)[0]
            return f"{prefix}{digits}"
        return None

    return None


def read_terms_txt(
    path: str,
    allowed_kegg: tuple[str, ...],
    log_dir: str | None = None,
    label: str = "A",
) -> tuple[set[str], List[str], List[str]]:
    """
    Read a plain txt of terms, keep only GO and KEGG with allowed prefixes,
    normalize, de-duplicate. Optionally write dropped and duplicates logs.
    Returns: (kept_set, dropped_list, duplicates_list)
    """
    seen = set()
    kept = []
    dropped = []
    duplicates = []

    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            raw = ln.strip()
            if not raw:
                continue
            nid = norm_id(raw, allowed_kegg=allowed_kegg)
            if nid is None:
                dropped.append(raw)
                continue
            if nid in seen:
                duplicates.append(nid)
            else:
                seen.add(nid)
                kept.append(nid)

    kept_set = set(kept)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        _write_sorted_lines_txt(
            os.path.join(log_dir, f"{label}_dropped_non_GO_KEGG.txt"), dropped
        )
        _write_sorted_lines_txt(
            os.path.join(log_dir, f"{label}_duplicates_removed.txt"), duplicates
        )

        # also dump cleaned terms for auditing
        with open(
            os.path.join(log_dir, f"cleaned_{label}_terms.txt"), "w", encoding="utf-8"
        ) as g:
            for t in sorted(kept_set):
                g.write(t + "\n")

    return kept_set, dropped, duplicates


# --- New helpers for A JSON input ---
def _to_list_from_mixed(value) -> List[str]:
    """
    Convert various representations to a flat list of strings:
    - list/tuple/set -> list of strings
    - comma-separated string -> split by comma
    - brace-enclosed string (e.g., "{a,b,c}") -> strip braces then split
    - otherwise: single string as one-element list
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x) for x in value]
    s = str(value).strip()
    if not s:
        return []
    # strip surrounding braces
    if (s.startswith("{") and s.endswith("}")) or (
        s.startswith("[") and s.endswith("]")
    ):
        s = s[1:-1]
    # split by comma
    parts = [p.strip() for p in s.split(",") if p.strip()]
    # If nothing remains after stripping/splitting, return empty list
    return parts if parts else ([] if not s.strip() else [s])


def read_A_from_json(
    path: str, allowed_kegg: tuple[str, ...], log_dir: str | None = None
) -> tuple[set[str], List[str], List[str], List[dict]]:
    """
    Read A_terms from a JSON file that contains a list of gene objects.
    Each object should include a 'pathway' (or 'pathways') field, which may be:
      - a list/array,
      - a comma-separated string,
      - or a brace-enclosed list-like string.
    Non-GO/KEGG IDs are dropped; remaining terms are normalized and deduplicated.
    Returns (kept_set, dropped_list, duplicates_list).
    Also writes a per-gene cleaned mapping to debug/A_cleaned_by_gene.json if log_dir is set.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # allow single dict or list of dicts
    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("JSON must be an object or a list of objects.")

    all_seen = set()
    kept = []
    dropped = []
    duplicates = []

    per_gene = []

    for obj in items:
        if not isinstance(obj, dict):
            continue
        gene = (
            obj.get("gene_name")
            or obj.get("Gene")
            or obj.get("gene")
            or obj.get("name")
            or ""
        )
        # also accept 'similarity_gene_name' or common typos
        simg = obj.get("similarity_gene_name") or obj.get("simality_gene_name") or ""
        entrez = obj.get("ENTREZ_ID") or obj.get("entrez_id") or obj.get("ENTREZ") or ""
        pathways = obj.get("pathway")
        if pathways is None:
            pathways = obj.get("pathways")
        terms_raw = _to_list_from_mixed(pathways)

        gene_kept = []
        gene_dropped = []
        gene_dupes = []

        local_seen = set()
        for raw in terms_raw:
            nid = norm_id(raw, allowed_kegg=allowed_kegg)
            if nid is None:
                gene_dropped.append(str(raw))
                dropped.append(str(raw))
                continue
            if nid in local_seen:
                gene_dupes.append(nid)
            local_seen.add(nid)

            if nid in all_seen:
                duplicates.append(nid)
            else:
                all_seen.add(nid)
                kept.append(nid)
                gene_kept.append(nid)

        per_gene.append(
            {
                "gene_name": gene,
                "similarity_gene_name": simg,  # for back-compat in debug
                "ENTREZ_ID": str(entrez),
                "pathway": sorted(set(gene_kept)),
                "dropped_terms": sorted(set(gene_dropped)),
                "duplicates_within_gene": sorted(set(gene_dupes)),
            }
        )

    kept_set = set(kept)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        with open(
            os.path.join(log_dir, "A_cleaned_by_gene.json"), "w", encoding="utf-8"
        ) as g:
            json.dump(per_gene, g, indent=2, ensure_ascii=False)
        if dropped:
            with open(
                os.path.join(log_dir, "A_dropped_non_GO_KEGG.json"),
                "w",
                encoding="utf-8",
            ) as g:
                json.dump(sorted(set(dropped)), g, indent=2, ensure_ascii=False)
        _write_sorted_lines_txt(
            os.path.join(log_dir, "A_duplicates_removed.txt"), duplicates
        )

        # also dump the union of cleaned A terms, for auditing
        with open(
            os.path.join(log_dir, "cleaned_A_terms.txt"), "w", encoding="utf-8"
        ) as g:
            for t in sorted(kept_set):
                g.write(t + "\n")

    return kept_set, dropped, duplicates, per_gene


def read_A_terms_auto(
    path: str, allowed_kegg: tuple[str, ...], log_dir: str | None = None
) -> tuple[set[str], List[str], List[str], List[dict]]:
    """
    Read A_terms from TXT or JSON depending on file extension.
    - .json/.JSON -> JSON mode (multiple genes with 'pathway')
    - otherwise   -> TXT mode (one term per line)
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return read_A_from_json(path, allowed_kegg=allowed_kegg, log_dir=log_dir)
    kept_set, dropped, duplicates = read_terms_txt(
        path, allowed_kegg=allowed_kegg, log_dir=log_dir, label="A"
    )
    pseudo = [
        {
            "gene_name": "ALL_GENES",
            "similarity_gene_name": "",
            "ENTREZ_ID": "",
            "pathway": sorted(kept_set),
        }
    ]
    return kept_set, dropped, duplicates, pseudo


def read_u_json(
    path: str, allowed_kegg: tuple[str, ...], log_dir: str | None = None
) -> set[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    terms = set()
    dropped = []
    for x in data:
        nid = norm_id(x, allowed_kegg=allowed_kegg)
        if nid:
            terms.add(nid)
        else:
            dropped.append(str(x))
    if log_dir and dropped:
        os.makedirs(log_dir, exist_ok=True)
        _write_sorted_lines_txt(
            os.path.join(log_dir, "U_dropped_non_GO_KEGG.txt"), dropped
        )
    return terms


def read_term_size_tsv(path: str) -> dict[str, int]:
    sizes = {}
    with open(path, "r", encoding="utf-8") as f:
        for idx, ln in enumerate(f, start=1):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = re.split(r"\t|,", ln)
            if len(parts) < 2:
                print(
                    f"[WARN] term-size: line {idx} has <2 fields, skipped: {ln}",
                    file=sys.stderr,
                )
                continue
            tid = norm_id(parts[0], allowed_kegg=("hsa", "mmu", "map", "ko"))
            if not tid:
                print(
                    f"[WARN] term-size: line {idx} non-GO/KEGG or disallowed prefix: {parts[0]}",
                    file=sys.stderr,
                )
                continue
            try:
                sz = int(str(parts[1]).strip())
            except Exception:
                print(
                    f"[WARN] term-size: line {idx} invalid size '{parts[1]}', skipped",
                    file=sys.stderr,
                )
                continue
            sizes[tid] = sz
    return sizes


def jaccard(a: set[str], b: set[str]) -> float:
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def overlap(a: set[str], b: set[str]) -> int:
    return len(a & b)


def hypergeometric_enrichment(gene_terms: set[str], disease_terms: set[str], universe: set[str]) -> dict:
    """
    Hypergeometric test for gene functional enrichment in disease.
    
    Args:
        gene_terms: Set of functional terms associated with the gene
        disease_terms: Set of functional terms associated with the disease
        universe: Universal set of all possible functional terms
    
    Returns:
        dict: {
            'p_value': float,
            'odds_ratio': float,
            'enrichment_score': float,
            'overlap_count': int,
            'gene_terms_count': int,
            'disease_terms_count': int,
            'universe_size': int,
            'contingency_table': dict
        }
    """
    try:
        from scipy.stats import hypergeom
        _SCIPY_AVAILABLE = True
    except ImportError:
        _SCIPY_AVAILABLE = False
        print("[WARN] scipy not available. Hypergeometric test will use approximation.")
    
    # Calculate 2x2 contingency table elements
    overlap_count = len(gene_terms & disease_terms)  # a
    gene_only = len(gene_terms - disease_terms)      # c  
    disease_only = len(disease_terms - gene_terms)   # b
    neither = len(universe - gene_terms - disease_terms)  # d
    
    # Hypergeometric test parameters
    N = len(universe)           # Population size
    K = len(disease_terms)      # Total number of successes
    n = len(gene_terms)         # Sample size
    x = overlap_count           # Observed number of successes
    
    if _SCIPY_AVAILABLE:
        # Use scipy for hypergeometric test (right-tailed, test for enrichment)
        p_value = hypergeom.sf(x-1, N, K, n)
    else:
        # Approximation when scipy is not available
        if x == 0:
            p_value = 1.0
        else:
            # Use binomial approximation
            p = K / N if N > 0 else 0
            from math import comb
            p_value = sum(comb(n, i) * (p**i) * ((1-p)**(n-i)) for i in range(x, n+1))
    
    # Calculate odds ratio
    if gene_only > 0 and disease_only > 0:
        odds_ratio = (overlap_count * neither) / (gene_only * disease_only)
    else:
        odds_ratio = float('inf') if overlap_count > 0 else 0.0
    
    # Calculate enrichment score
    expected = (K * n) / N if N > 0 else 0
    enrichment_score = overlap_count / expected if expected > 0 else 0.0
    
    return {
        'p_value': p_value,
        'odds_ratio': odds_ratio,
        'enrichment_score': enrichment_score,
        'overlap_count': overlap_count,
        'gene_terms_count': len(gene_terms),
        'disease_terms_count': len(disease_terms),
        'universe_size': N,
        'contingency_table': {
            'a': overlap_count, 'b': disease_only,
            'c': gene_only, 'd': neither
        }
    }


def stratify(u_terms: list[str], size_map: dict[str, int], bins: list[int]):
    """Stratify terms by term size, return [bucket_terms...]"""
    buckets = [[] for _ in range(len(bins) - 1)]
    for t in u_terms:
        sz = size_map.get(t, 0)
        for i in range(len(bins) - 1):
            if bins[i] <= sz < bins[i + 1]:
                buckets[i].append(t)
                break
    return buckets


# --- Multi-dimensional stratification for GO (namespace, depth, size) ---
def _bin_index(value: int, bins: list[int]) -> int:
    """Return the index i such that bins[i] <= value < bins[i+1]; -1 if not found."""
    for i in range(len(bins) - 1):
        if bins[i] <= value < bins[i + 1]:
            return i
    return -1

def _approx_go_depth_map_from_ancestors(ancestors: dict[str, set[str]]) -> dict[str, int]:
    """
    Approximate GO depth using ancestor count as a proxy when true parent-depth is unavailable.
    Depth(t) := len(Ancestors(t)). This is monotonic and adequate for binning.
    """
    if not isinstance(ancestors, dict):
        return {}
    out: dict[str, int] = {}
    for t, ancs in ancestors.items():
        try:
            out[str(t)] = len(ancs) if isinstance(ancs, (set, list, tuple)) else 0
        except Exception:
            out[str(t)] = 0
    return out

def stratify_go_multi(
    u_terms: list[str],
    size_map: dict[str, int],
    size_bins: list[int],
    ns_map: dict[str, str] | None,
    depth_map: dict[str, int] | None,
    depth_bins: list[int] | None,
) -> dict[tuple[str, int, int], list[str]]:
    """
    Build multi-dimensional GO buckets keyed by (namespace, depth_bin, size_bin).
    - namespace: 'BP'/'MF'/'CC' (or 'UNK' if ns_map missing)
    - depth_bin: index into depth_bins (or -1 if no depth_bins/depth_map)
    - size_bin : index into size_bins
    Returns: { (ns, d_bin, s_bin) : [term, ...] }
    Terms not matching any size bin are skipped.
    """
    buckets: dict[tuple[str, int, int], list[str]] = {}
    for t in u_terms:
        if not str(t).startswith("GO:"):
            # Only stratify GO in this routine
            continue
        sz = size_map.get(t, 0)
        s_idx = _bin_index(sz, size_bins)
        if s_idx < 0:
            continue
        ns = "UNK"
        if ns_map:
            ns = ns_map.get(t, "") or "UNK"
            ns = ns if ns in ("BP", "MF", "CC") else "UNK"
        d_idx = -1
        if depth_map and depth_bins:
            d_val = int(depth_map.get(t, 0))
            d_idx = _bin_index(d_val, depth_bins)
        key = (ns, d_idx, s_idx)
        buckets.setdefault(key, []).append(t)
    return buckets

def sample_like_go_multi(
    ref_set: set[str],
    u_buckets: dict[tuple[str, int, int], list[str]],
    size_map: dict[str, int],
    size_bins: list[int],
    ns_map: dict[str, str] | None,
    depth_map: dict[str, int] | None,
    depth_bins: list[int] | None,
    rng: random.Random,
) -> set[str]:
    """
    Stratified sampling that matches ref_set's counts per (namespace, depth_bin, size_bin).
    Non-GO terms in ref_set are ignored here (handled by other routines, e.g., KEGG).
    Falls back to sampling within available bucket if needed.
    """
    # Count ref_set per key
    counts: dict[tuple[str, int, int], int] = {}
    for t in ref_set:
        if not str(t).startswith("GO:"):
            continue
        sz = size_map.get(t, 0)
        s_idx = _bin_index(sz, size_bins)
        if s_idx < 0:
            continue
        ns = "UNK"
        if ns_map:
            ns = ns_map.get(t, "") or "UNK"
            ns = ns if ns in ("BP", "MF", "CC") else "UNK"
        d_idx = -1
        if depth_map and depth_bins:
            d_val = int(depth_map.get(t, 0))
            d_idx = _bin_index(d_val, depth_bins)
        key = (ns, d_idx, s_idx)
        counts[key] = counts.get(key, 0) + 1

    # Sample per key
    out: list[str] = []
    for key, need in counts.items():
        pool = u_buckets.get(key, [])
        if need <= 0:
            continue
        if not pool:
            # If bucket empty, relax depth constraint first, then namespace
            ns, d_idx, s_idx = key
            fallback_keys = []
            # same ns, any depth, same size
            for dk in set(k[1] for k in u_buckets.keys() if k[0] == ns and k[2] == s_idx):
                fallback_keys.append((ns, dk, s_idx))
            # any ns, any depth, same size
            for ns2 in set(k[0] for k in u_buckets.keys() if k[2] == s_idx):
                for dk in set(k[1] for k in u_buckets.keys() if k[2] == s_idx and k[0] == ns2):
                    fallback_keys.append((ns2, dk, s_idx))
            # aggregate fallback pool
            agg = []
            for fk in fallback_keys:
                agg.extend(u_buckets.get(fk, []))
            pool = agg
        if not pool:
            continue
        if need > len(pool):
            out.extend(rng.choices(pool, k=need))
        else:
            out.extend(rng.sample(pool, k=need))
    return set(out)


def sample_like(
    ref_set: set[str],
    u_buckets: list[list[str]],
    size_map: dict[str, int],
    bins: list[int],
    rng: random.Random,
):
    """Stratified sample from u_buckets matching ref_set's bucket counts"""
    # Count ref_set in each bucket
    counts = [0] * (len(bins) - 1)
    for t in ref_set:
        sz = size_map.get(t, 0)
        for i in range(len(bins) - 1):
            if bins[i] <= sz < bins[i + 1]:
                counts[i] += 1
                break
    # Sample same count from each bucket
    out = []
    for bucket, need in zip(u_buckets, counts):
        if need <= 0:
            continue
        if need > len(bucket):
            # fallback: with replacement
            out.extend(rng.choices(bucket, k=need))
        else:
            out.extend(rng.sample(bucket, k=need))
    return set(out)


def make_B_randoms(
    B: set[str],
    U_list: list[str],
    U_buckets: list[list[str]] | dict[tuple[str, int, int], list[str]] | None,
    size_map: dict[str, int] | None,
    bins: list[int],
    rng: random.Random,
    R: int,
    desc: str = "Generating permutations",
    *,
    go_ns_map: dict[str, str] | None = None,
    go_depth_map: dict[str, int] | None = None,
    go_depth_bins: list[int] | None = None,
) -> list[set[str]]:
    """
    Precompute R random B-like sets for a given B.
    - If U_buckets is None             -> uniform sampling over U_list (legacy)
    - If U_buckets is list[list[str]]  -> size-only stratification (legacy)
    - If U_buckets is dict[(ns,d,s)]   -> GO structured stratification (size × namespace × depth)
    Returns a list of sets length R (empty list when R<=0 or B empty).
    """
    if not B or R <= 0:
        return []
    out: list[set[str]] = []
    n = len(B)

    iterator = tqdm(range(R), desc=desc, disable=True)

    # Case 1: No buckets -> uniform sampling
    if U_buckets is None:
        with_repl = 0
        for _ in iterator:
            if n <= len(U_list):
                out.append(set(rng.sample(U_list, n)))
            else:
                out.append(set(rng.choices(U_list, k=n)))
                with_repl += 1
        if with_repl > 0:
            logger.info(
                f"make_B_randoms: used with-replacement {with_repl}/{R} times (n={n} > |U|={len(U_list)})"
            )
        return out

    # Case 2: Legacy size-only buckets (list of lists)
    if isinstance(U_buckets, list):
        assert size_map is not None
        for _ in iterator:
            out.append(sample_like(B, U_buckets, size_map, bins, rng))
        return out

    # Case 3: GO structured buckets (dict of (ns, depth_bin, size_bin) -> terms)
    if isinstance(U_buckets, dict):
        for _ in iterator:
            sample_go = sample_like_go_multi(
                B,  # non-GO terms ignored here; sample KEGG separately upstream if needed
                U_buckets,
                size_map or {},
                bins,
                go_ns_map,
                go_depth_map,
                go_depth_bins,
                rng,
            )
            out.append(set(sample_go))
        return out

    # Fallback (should not happen)
    for _ in iterator:
        out.append(set(rng.sample(U_list, n)) if n <= len(U_list) else set(rng.choices(U_list, k=n)))
    return out


def _bh_fdr(pvals: list[float]) -> list[float]:
    """Benjamini–Hochberg FDR adjustment (monotone, correct order). Returns q-values in original order."""
    n = len(pvals)
    if n == 0:
        return []
    # Replace None with 1.0 for safety
    pairs = sorted(
        [(float(p) if p is not None else 1.0, i) for i, p in enumerate(pvals)],
        key=lambda x: x[0],
    )
    # Compute raw adjusted values p_i * n / i (i = rank), then apply cumulative min in reverse
    raw = [min(1.0, max(0.0, pv * n / (i + 1))) for i, (pv, idx) in enumerate(pairs)]
    cummin = [0.0] * n
    mn = 1.0
    for i in range(n - 1, -1, -1):
        mn = min(mn, raw[i])
        cummin[i] = mn
    # Map back to original order
    q = [0.0] * n
    for (pv, idx), val in zip(pairs, cummin):
        q[idx] = min(1.0, max(0.0, val))
    return q


def _norm_ppf(u: float) -> float:
    """Inverse standard normal CDF (Acklam's approximation). u in (0,1)."""
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow = 0.02425
    phigh = 1 - plow
    if u <= 0.0:
        return float("-inf")
    if u >= 1.0:
        return float("inf")
    if u < plow:
        q = math.sqrt(-2 * math.log(u))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if u > phigh:
        q = math.sqrt(-2 * math.log(1 - u))
        return -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = u - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def _phi_cdf(z: float) -> float:
    """Standard normal CDF using math.erf."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _combine_min(values: list[float]) -> float:
    return min(values) if values else float("nan")


def _combine_simes(values: list[float]) -> float:
    if not values:
        return float("nan")
    m = len(values)
    xs = sorted(values)
    simes = min((m * xs[i] / (i + 1)) for i in range(m))
    return min(1.0, max(0.0, simes))


def _combine_stouffer(values: list[float]) -> float:
    if not values:
        return float("nan")
    m = len(values)
    zs = [_norm_ppf(1.0 - max(min(p, 1 - 1e-15), 1e-15)) for p in values]
    z = sum(zs) / math.sqrt(m)
    return max(0.0, min(1.0, 1.0 - _phi_cdf(z)))


def _verdict_from_pvalues(
    p_right: float,
    p_left: float,
    p_two: float,
    effect_size: float,
    alpha: float,
    rule: str,
) -> str:
    rule = (rule or "right").lower()
    if rule == "left":
        if (p_left < alpha) and (effect_size < 0):
            return "depleted"
        return "not_significant"
    if rule == "two":
        if (p_two < alpha) and (effect_size > 0):
            return "enriched"
        if (p_two < alpha) and (effect_size < 0):
            return "depleted"
        return "not_significant"
    # default: right
    if (p_right < alpha) and (effect_size > 0):
        return "enriched"
    return "not_significant"


# === Semantic helpers ===
_go_resource_paths: dict[str, str | None] = {
    "ancestors": None,
    "ic": None,
    "namespace": None,
}

@lru_cache(maxsize=None)
def _cached_go_resources() -> tuple[dict[str, set[str]], dict[str, float], dict[str, str]]:
    """
    Cached function to load all GO semantic resources at once.
    Returns (ancestors, ic_map, namespace_map) to avoid repeated file I/O.
    """
    # Resolve resource paths with fallbacks to packaged defaults
    anc_cfg = (
        _go_resource_paths.get("ancestors")
        or "data/semantic_resources_v2/go_ancestors.json"
    )
    ns_cfg = (
        _go_resource_paths.get("namespace")
        or "data/semantic_resources_v2/go_namespace.json"
    )
    ic_cfg = (
        _go_resource_paths.get("ic")
        or "data/semantic_resources_v2/go_ic.json"
    )

    anc_path = _resolve_default(anc_cfg)
    go_anc = _load_go_ancestors(anc_path)
    
    ic_path = _resolve_default(ic_cfg)
    with open(ic_path, 'r', encoding='utf-8') as f:
        ic_map = json.load(f)
    _validate_semantic_hierarchy(go_anc, ic_map)
    
    ns_path = _resolve_default(ns_cfg)
    ns_map = _load_go_namespace(ns_path)
    
    return go_anc, ic_map, ns_map


def _validate_semantic_hierarchy(
    ancestors: dict[str, set[str]],
    ic_map: dict[str, float],
) -> None:
    """Reject reversed closures and IC values incompatible with true ancestors."""
    roots = {"GO:0008150", "GO:0003674", "GO:0005575"}
    for root in roots:
        if root in ancestors and ancestors[root] != {root}:
            raise ValueError(
                f"GO root {root} has non-self ancestors; resource direction is reversed"
            )
    tolerance = 1e-12
    for term, term_ancestors in ancestors.items():
        term_ic = float(ic_map.get(term, 0.0))
        for ancestor in term_ancestors:
            if float(ic_map.get(ancestor, 0.0)) > term_ic + tolerance:
                raise ValueError(
                    "GO IC is not ancestor-monotone: "
                    f"IC({ancestor}) > IC({term})"
                )


def _configure_go_resources(
    ancestors_path: str | None,
    ic_path: str | None,
    namespace_path: str | None,
) -> None:
    """
    Update cached GO resource locations and reset memoized data.
    """
    _go_resource_paths["ancestors"] = ancestors_path
    _go_resource_paths["ic"] = ic_path
    _go_resource_paths["namespace"] = namespace_path
    _cached_go_resources.cache_clear()


def _load_go_ancestors(path: str | None) -> dict[str, set[str]]:
    if not path:
        return {}
    if not os.path.exists(path):
        raise FileNotFoundError(f"--go-ancestors file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    anc: dict[str, set[str]] = {}
    for k, v in data.items():
        if isinstance(v, list):
            anc[str(k)] = set(str(x) for x in v)
        elif isinstance(v, set):
            anc[str(k)] = set(str(x) for x in v)
        else:
            anc[str(k)] = {str(v)}
    return anc


# --- GO namespace loader and Resnik/Lin BMA similarity ---
def _load_go_namespace(path: str | None) -> dict[str, str]:
    """
    Optional helper: load GO term namespaces mapping from JSON like {"GO:0008150":"BP", ...}.
    Accepts long forms and normalizes to short codes ("BP","MF","CC"). Returns {} on failure.
    """
    if not path:
        return {}
    if not os.path.exists(path):
        raise FileNotFoundError(f"--go-namespace file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        out: dict[str, str] = {}
        def _norm_ns(x: str) -> str:
            s = (x or "").strip().lower()
            if s in ("bp", "biological_process"): return "BP"
            if s in ("mf", "molecular_function"): return "MF"
            if s in ("cc", "cellular_component"): return "CC"
            return ""
        for k, v in data.items():
            ns = _norm_ns(str(v))
            if ns:
                out[str(k)] = ns
        return out
    except Exception:
        return {}

# --- Resnik / Lin pairwise GO similarity and BMA aggregation ---
def _mica_ic(t1: str, t2: str, ancestors: dict[str, set[str]], ic_map: dict[str, float]) -> float:
    """Return IC(MICA) for two GO terms; 0 if no common ancestor."""
    a1 = ancestors.get(t1, set()) | {t1}
    a2 = ancestors.get(t2, set()) | {t2}
    common = a1 & a2
    if not common:
        return 0.0
    return max(ic_map.get(a, 0.0) for a in common)

def _resnik_pair(t1: str, t2: str, ancestors: dict[str, set[str]], ic_map: dict[str, float]) -> float:
    return _mica_ic(t1, t2, ancestors, ic_map)

def _lin_pair(t1: str, t2: str, ancestors: dict[str, set[str]], ic_map: dict[str, float]) -> float:
    ic_mica = _mica_ic(t1, t2, ancestors, ic_map)
    if ic_mica <= 0.0:
        return 0.0
    ic1 = ic_map.get(t1, 0.0)
    ic2 = ic_map.get(t2, 0.0)
    den = ic1 + ic2
    if den <= 0.0:
        return 0.0
    return min(1.0, max(0.0, 2.0 * ic_mica / den))

def _best_match_avg(A: set[str], B: set[str], sim_fn) -> float:
    """
    Best-Match Average aggregation for two sets given a pairwise similarity function.
    Computes mean over A of max-to-B and mean over B of max-to-A, then averages the two.
    Optimized version with memoization for repeated calculations.
    """
    if not A or not B:
        return 0.0
    A_list = list(A)
    B_list = list(B)
    
    # Pre-compute all pairwise similarities to avoid redundant calculations
    sim_matrix = {}
    for a in A_list:
        for b in B_list:
            key = (a, b) if a <= b else (b, a)  # Use consistent ordering for memoization
            if key not in sim_matrix:
                sim_matrix[key] = sim_fn(a, b)
    
    # A -> B
    acc1 = 0.0
    for a in A_list:
        max_sim = 0.0
        for b in B_list:
            key = (a, b) if a <= b else (b, a)
            sim_val = sim_matrix[key]
            if sim_val > max_sim:
                max_sim = sim_val
        acc1 += max_sim
    acc1 /= len(A_list)
    
    # B -> A
    acc2 = 0.0
    for b in B_list:
        max_sim = 0.0
        for a in A_list:
            key = (a, b) if a <= b else (b, a)
            sim_val = sim_matrix[key]
            if sim_val > max_sim:
                max_sim = sim_val
        acc2 += max_sim
    acc2 /= len(B_list)
    
    return 0.5 * (acc1 + acc2)

def _compute_namespace_similarity(A_ns: set[str], B_ns: set[str], ancestors: dict[str, set[str]], ic_map: dict[str, float], mode: str) -> float:
    """Helper function for parallel computation of namespace-specific similarity."""
    if not A_ns or not B_ns:
        return 0.0
    sim_fn = (lambda x, y: _resnik_pair(x, y, ancestors, ic_map)) if mode == "resnik" else (lambda x, y: _lin_pair(x, y, ancestors, ic_map))
    return _best_match_avg(A_ns, B_ns, sim_fn)

def _semantic_go_resnik_bma(
    A_GO: set[str],
    B_GO: set[str],
    ancestors: dict[str, set[str]],
    ic_map: dict[str, float],
    ns_map: dict[str, str] | None = None,
    mode: str = "resnik",  # "resnik" or "lin"
    parallel: bool = False,
    max_workers: int = None,
) -> float:
    """
    Compute GO set similarity using Resnik (or Lin) pairwise similarity aggregated by BMA.
    If ns_map provided, comparisons are restricted within the same namespace (BP/MF/CC) and averaged.
    """
    if not A_GO or not B_GO or not ancestors or not ic_map:
        return 0.0
    mode = (mode or "resnik").lower()
    
    if ns_map:
        parts = []
        if parallel and len(A_GO) * len(B_GO) > 1000:  # Only parallelize for large sets
            # Prepare namespace data for parallel processing
            namespace_data = []
            for ns in ("BP", "MF", "CC"):
                A_ns = {t for t in A_GO if ns_map.get(t, "") == ns}
                B_ns = {t for t in B_GO if ns_map.get(t, "") == ns}
                if A_ns and B_ns:
                    namespace_data.append((A_ns, B_ns, ns))
            
            if namespace_data:
                # Use ThreadPoolExecutor for I/O-bound operations
                workers = max_workers or min(len(namespace_data), cpu_count())
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = [
                        executor.submit(_compute_namespace_similarity, A_ns, B_ns, ancestors, ic_map, mode)
                        for A_ns, B_ns, ns in namespace_data
                    ]
                    parts = [future.result() for future in futures]
        else:
            # Sequential processing
            for ns in ("BP", "MF", "CC"):
                A_ns = {t for t in A_GO if ns_map.get(t, "") == ns}
                B_ns = {t for t in B_GO if ns_map.get(t, "") == ns}
                if A_ns and B_ns:
                    parts.append(_compute_namespace_similarity(A_ns, B_ns, ancestors, ic_map, mode))
        
        return sum(parts) / len(parts) if parts else 0.0
    
    # Without namespace restriction
    sim_fn = (lambda x, y: _resnik_pair(x, y, ancestors, ic_map)) if mode == "resnik" else (lambda x, y: _lin_pair(x, y, ancestors, ic_map))
    return _best_match_avg(A_GO, B_GO, sim_fn)

@cached_computation("semantic_go_bma", max_age_hours=24)
def _semantic_go_bma_cached(
    A_GO: set[str],
    B_GO: set[str],
    ancestors: dict[str, set[str]],
    ic_map: dict[str, float],
    ns_map: dict[str, str] | None,
    mode: str = "resnik",
    parallel: bool = False,
    max_workers: int = None,
) -> float:
    return _semantic_go_resnik_bma(A_GO, B_GO, ancestors, ic_map, ns_map=ns_map, mode=mode, parallel=parallel, max_workers=max_workers)

def semantic_go_similarity(
    A_GO: set[str],
    B_GO: set[str],
    ancestors: dict[str, set[str]] | None,
    ic_map: dict[str, float] | None,
    ns_map: dict[str, str] | None = None,
    method: str = "closure_jaccard",
    parallel: bool = False,
    max_workers: int = None,
) -> float:
    """
    Public dispatcher for GO set similarity:
    - method="closure_jaccard" -> current behavior (ancestor-closure Jaccard; fallback to IC-weighted Jaccard)
    - method="resnik_bma"      -> Resnik pairwise + BMA aggregation
    - method="lin_bma"         -> Lin pairwise + BMA aggregation
    """
    m = (method or "closure_jaccard").lower()
    if m == "resnik_bma":
        return _semantic_go_bma_cached(A_GO, B_GO, ancestors or {}, ic_map or {}, ns_map, mode="resnik", parallel=parallel, max_workers=max_workers)
    if m == "lin_bma":
        return _semantic_go_bma_cached(A_GO, B_GO, ancestors or {}, ic_map or {}, ns_map, mode="lin", parallel=parallel, max_workers=max_workers)
    # default: original behavior
    return _semantic_go_component(A_GO, B_GO, ancestors or {}, ic_map or {})


def _ic_map_from_term_size(size_map: dict[str, int]) -> dict[str, float]:
    # IC = -log( (size+1) / (max_size+1) )
    if not size_map:
        return {}
    max_sz = max(size_map.values()) if size_map else 0
    denom = max_sz + 1.0
    out: dict[str, float] = {}
    for t, sz in size_map.items():
        out[t] = -math.log((sz + 1.0) / denom) if denom > 0 else 0.0
    return out


def _weighted_jaccard(a: set[str], b: set[str], w: dict[str, float]) -> float:
    if not a and not b:
        return 0.0
    inter = a & b
    union = a | b
    num = sum(w.get(t, 1.0) for t in inter)
    den = sum(w.get(t, 1.0) for t in union)
    return (num / den) if den > 0 else 0.0


def _closure(term_set: set[str], ancestors: dict[str, set[str]]) -> set[str]:
    out: set[str] = set()
    for t in term_set:
        out.add(t)
        if t in ancestors:
            out.update(ancestors[t])
    return out


def _semantic_go_component(
    A_GO: set[str],
    B_GO: set[str],
    ancestors: dict[str, set[str]],
    ic_map: dict[str, float],
    fallback_mode: str = "ic",
) -> float:
    # If ancestors provided, use closure Jaccard; else fallback to IC-weighted Jaccard on raw sets
    if ancestors:
        A_cl = _closure(A_GO, ancestors)
        B_cl = _closure(B_GO, ancestors)
        if not A_cl and not B_cl:
            return 0.0
        return jaccard(A_cl, B_cl)
    # fallback to IC-weighted Jaccard
    if fallback_mode == "ic":
        return _weighted_jaccard(A_GO, B_GO, ic_map or {})
    return jaccard(A_GO, B_GO)


def _semantic_kegg_component(
    A_KEGG: set[str], B_KEGG: set[str], base: str = "jaccard"
) -> float:
    if base == "overlap":
        return overlap(A_KEGG, B_KEGG)
    return jaccard(A_KEGG, B_KEGG)


def _semantic_kegg_component_enhanced(
    A_KEGG: set[str], 
    B_KEGG: set[str], 
    base: str = "jaccard",
    topology_analyzer: Optional[KEGGTopologyAnalyzer] = None,
    topology_method: str = "basic"
) -> float:
    """
    Enhanced semantic KEGG component with optional topology awareness.
    
    This function provides a drop-in replacement for _semantic_kegg_component
    that can utilize topology information when available.
    """
    if topology_analyzer is not None and topology_method != "basic" and TOPOLOGY_AVAILABLE:
        return enhanced_semantic_kegg_component(
            A_KEGG, B_KEGG, topology_analyzer, topology_method, base
        )
    else:
        # Fallback to original implementation
        return _semantic_kegg_component(A_KEGG, B_KEGG, base)


def _combine_go_kegg(
    go_score: float,
    kegg_score: float,
    A_GO: set[str],
    B_GO: set[str],
    A_KEGG: set[str],
    B_KEGG: set[str],
    base: str,
) -> float:
    # Weight by union sizes of each component to avoid biasing empty parts
    w_go = len((A_GO | B_GO))
    w_kegg = len((A_KEGG | B_KEGG))
    tot = w_go + w_kegg
    if tot == 0:
        return 0.0
    return (go_score * w_go + kegg_score * w_kegg) / tot


def _compute_permutations_optimized(
    A: set[str],
    B: set[str],
    U: set[str],
    stat_fn: Callable,
    R: int,
    accelerator: Optional[ParallelAccelerator] = None,
    progress_callback: Optional[Callable] = None
) -> List[float]:
    """
    Compute permutations using optimized parallel processing.
    
    Parameters
    ----------
    A : set[str]
        Query set
    B : set[str]
        Background set
    U : set[str]
        Universe set
    stat_fn : Callable
        Statistical function to compute
    R : int
        Number of permutations
    accelerator : Optional[ParallelAccelerator]
        Parallel accelerator instance
    progress_callback : Optional[Callable]
        Progress callback function
        
    Returns
    -------
    List[float]
        List of permutation statistics
    """
    if R <= 0:
        return []
    
    if accelerator is not None and R > 100:
        # Use parallel acceleration
        return accelerator.compute_permutations_parallel(
            A, B, U, stat_fn, R, progress_callback
        )
    else:
        # Fallback to sequential processing
        results = []
        for i in range(R):
            B_rand = set(random.sample(list(U), len(B)))
            result = stat_fn(A, B_rand)
            results.append(result)
            
            if progress_callback and (i + 1) % max(1, R // 20) == 0:
                progress_callback(i + 1, R)
        
        return results


def _create_semantic_stat_function(
    A_GO: set[str],
    A_KEGG: set[str],
    go_anc: dict,
    ic_map: dict,
    args,
    topology_analyzer: Optional[KEGGTopologyAnalyzer] = None
) -> Callable:
    """
    Create a semantic statistical function for parallel processing.
    
    Parameters
    ----------
    A_GO : set[str]
        GO query set
    A_KEGG : set[str]
        KEGG query set
    go_anc : dict
        GO ancestors mapping
    ic_map : dict
        Information content mapping
    args
        Command line arguments
    topology_analyzer : Optional[KEGGTopologyAnalyzer]
        Topology analyzer for KEGG enhancement
        
    Returns
    -------
    Callable
        Statistical function that takes (A, B) and returns similarity score
    """
    def semantic_stat_fn(A: set[str], B: set[str]) -> float:
        """Semantic statistical function for parallel processing."""
        B_GO = B & {term for term in B if term.startswith("GO:")}
        B_KEGG = B & {term for term in B if term.startswith(("hsa", "mmu", "ko"))}
        
        if args.semantic_method == "closure_jaccard":
            s_go = _semantic_go_component(A_GO, B_GO, go_anc, ic_map)
        elif args.semantic_method == "resnik_bma":
            ns_map = _load_go_namespace(args.go_namespace)
            s_go = semantic_go_similarity(A_GO, B_GO, go_anc, ic_map, ns_map, method="resnik_bma")
        elif args.semantic_method == "lin_bma":
            ns_map = _load_go_namespace(args.go_namespace)
            s_go = semantic_go_similarity(A_GO, B_GO, go_anc, ic_map, ns_map, method="lin_bma")
        else:
            s_go = 0.0
        
        s_ke = _semantic_kegg_component_enhanced(
            A_KEGG, B_KEGG,
            base=args.semantic_kegg_base,
            topology_analyzer=topology_analyzer,
            topology_method=args.kegg_topology_method
        )
        
        return _combine_go_kegg(
            s_go, s_ke, A_GO, B_GO, A_KEGG, B_KEGG, args.semantic_kegg_base
        )
    
    return semantic_stat_fn


# === LLM helpers (Gemini) ===


def _make_llm_prompt(
    disease: str,
    group_keys: tuple[str, str, str, str],
    go_ids: list[str],
    kegg_ids: list[str],
    go_meta: dict,
    kegg_meta: dict,
    language: str = "en",
    # analysis linkage
    statistic: str | None = None,
    S_obs: float | None = None,
    null_mean: float | None = None,
    null_sd: float | None = None,
    p_right: float | None = None,
    verdict: str | None = None,
    effect_size: float | None = None,
    A_size: int | None = None,
    B_size: int | None = None,
    U_size: int | None = None,
    top_overlap_ids: list[str] | None = None,
    # ontology-specific linkage (optional)
    S_obs_GO: float | None = None,
    null_mean_GO: float | None = None,
    p_right_GO: float | None = None,
    verdict_GO: str | None = None,
    effect_size_GO: float | None = None,
    A_GO_size: int | None = None,
    B_GO_size: int | None = None,
    U_GO_size: int | None = None,
    S_obs_KEGG: float | None = None,
    null_mean_KEGG: float | None = None,
    p_right_KEGG: float | None = None,
    verdict_KEGG: str | None = None,
    effect_size_KEGG: float | None = None,
    A_KEGG_size: int | None = None,
    B_KEGG_size: int | None = None,
    U_KEGG_size: int | None = None,
    # optional protein evidence block (per gene)
    evidence_text: str | None = None,
) -> str:
    """Build a domain-aware prompt that links to observed stats + overlapping terms."""
    cond, addc, organ, model = group_keys

    def _fmt5s(x):
        try:
            if x is None:
                return "NA"
            xf = float(x)
            if math.isnan(xf) or math.isinf(xf):
                return "NA"
            return f"{xf:.5f}"
        except Exception:
            return "NA"

    def _go_line(tid: str) -> str:
        m = go_meta.get(tid, {}) if isinstance(go_meta, dict) else {}
        name = str(m.get("name", "")).strip()
        defin = str(m.get("def", "")).strip()
        defin = (defin.split(".")[0] + ".") if defin else ""
        ns = str(m.get("ns", "")).strip().lower()
        ns_map = {
            "biological_process": "Biological process (BP)",
            "molecular_function": "Molecular function (MF)",
            "cellular_component": "Cellular component (CC)",
        }
        ns_str = ns_map.get(ns, ns.title() if ns else "")
        ns_block = f"\n  Namespace: {ns_str}" if ns_str else ""
        return f"- {tid} — {name}{ns_block}\n  Definition: {defin}".rstrip()

    def _kegg_line(pid: str) -> str:
        m = kegg_meta.get(pid, {}) if isinstance(kegg_meta, dict) else {}
        name = str(m.get("name", "")).strip()
        klass = str(m.get("class", "")).strip()
        subc = str(m.get("subcategory", "")).strip()
        defin = str(m.get("definition", "")).strip()
        defin = (defin.split(".")[0] + ".") if defin else ""
        ko_map = str(m.get("ko_pathway", "")).strip()
        url = str(m.get("url", "")).strip()
        extra = "; ".join([x for x in [klass, subc] if x])
        extra = f" ({extra})" if extra else ""
        url_block = f"\n  URL: {url}" if url else ""
        ko_block = f"\n  KO map: {ko_map}" if ko_map else ""
        return f"- {pid} — {name}{extra}\n  Definition: {defin}{ko_block}{url_block}".rstrip()

    go_block = "\n".join(_go_line(t) for t in go_ids) if go_ids else "(none)"
    kegg_block = "\n".join(_kegg_line(t) for t in kegg_ids) if kegg_ids else "(none)"

    # Top-overlap block: IDs → names
    top_overlap_ids = top_overlap_ids or []

    def _id_to_name(t: str) -> str:
        if t.startswith("GO:"):
            nm = (go_meta.get(t, {}) or {}).get("name", "")
            return f"{t} — {nm}".strip()
        else:
            nm = (kegg_meta.get(t, {}) or {}).get("name", "")
            return f"{t} — {nm}".strip()

    top_overlap_names = (
        "\n".join(f"- {_id_to_name(t)}" for t in top_overlap_ids)
        if top_overlap_ids
        else "(none)"
    )

    # Always include a Protein evidence block so prompts are self-explanatory
    if evidence_text is not None:
        ev_txt = str(evidence_text).strip()
    else:
        ev_txt = ""
    ev_display = ev_txt if ev_txt else "(none)"

    prompt = f"""
You are a biomedical domain expert. Write concise, cautious, publication-style explanations in {language}.

**Disease/background:** {disease}
**Group context:** condition={cond}; additional_condition={addc}; organ={organ}; model={model}

**Analysis summary (link to stats):**
- Statistic: {statistic or 'NA'}
- Observed S: {_fmt5s(S_obs)}  |  Null mean: {_fmt5s(null_mean)}  |  Null SD: {_fmt5s(null_sd)}
- p_right (empirical): {_fmt5s(p_right)}  |  Effect size (S - mu): {_fmt5s(effect_size)}  |  Verdict: {verdict or 'NA'}
- Sizes: |A|={A_size or 'NA'}, |B|={B_size or 'NA'}, |U|={U_size or 'NA'}

**Statistical background:**
These results are derived from **permutation-based randomization tests** under the given universe U.
The chosen statistic is: {statistic or 'NA'} (e.g., overlap count, Jaccard index, or GO semantic similarity).
Empirical p-values are computed from the null distribution as the fraction of permutations with statistic ≥ observed (right-tail) or ≤ observed (left-tail). Interpret cautiously and avoid causal language.

**Top overlapping/enriched terms (IDs → names):**
{top_overlap_names}

**Protein evidence (summary):**
{ev_display}

**GO terms to explain:**
{go_block}

**KEGG pathways to explain:**
{kegg_block}

**Ontology-specific summary (if available):**
GO: S_obs={_fmt5s(S_obs_GO)} | mu={_fmt5s(null_mean_GO)} | effect={_fmt5s(effect_size_GO)} | p_right={_fmt5s(p_right_GO)} | verdict={verdict_GO or 'NA'} | sizes: |A_GO|={A_GO_size or 'NA'}, |B_GO|={B_GO_size or 'NA'}, |U_GO|={U_GO_size or 'NA'}
KEGG: S_obs={_fmt5s(S_obs_KEGG)} | mu={_fmt5s(null_mean_KEGG)} | effect={_fmt5s(effect_size_KEGG)} | p_right={_fmt5s(p_right_KEGG)} | verdict={verdict_KEGG or 'NA'} | sizes: |A_KEGG|={A_KEGG_size or 'NA'}, |B_KEGG|={B_KEGG_size or 'NA'}, |U_KEGG|={U_KEGG_size or 'NA'}

Task: For each GO/KEGG term above, output two bullets, and finish with a short summary:
1) **Function (with ID):** 1–2 sentences in plain language describing the term's biological meaning. Always include the term ID (e.g., GO:..., hsa....). For GO, note the namespace (BP/MF/CC) when relevant. For KEGG, use the provided class/subcategory; if a `KO map` is given, acknowledge it as a reference (cross-species) pathway.
2) **Relevance to this group:** 1–2 sentences cautiously linking the term to this disease/group context (condition/additional_condition/organ/model), avoiding strong causal claims. If a pathway is broad/umbrella (e.g., generic metabolic map), avoid over-interpretation and suggest more specific child pathways if applicable.

Then write a brief summary (≤3 sentences) on how these terms collectively relate to the group and whether the evidence supports a plausible link. Do NOT include numeric statistics (S_obs, mu, p-values, effect) or the verdict text in this summary; those are displayed elsewhere in the report. After the summary, add a single line `Confidence: <Very High|High|Moderate|Low|Very Low>` where:

**Confidence Assessment Criteria:**
- **Very High**: p_right < 0.001 AND effect_size > 0.7 AND strong protein evidence AND highly specific biological relevance
- **High**: p_right < 0.01 AND effect_size > 0.5 AND good protein evidence AND clear biological relevance  
- **Moderate**: p_right < 0.05 AND effect_size > 0.3 AND some protein evidence AND reasonable biological relevance
- **Low**: p_right < 0.05 AND effect_size ≤ 0.3 OR limited protein evidence OR weak biological relevance
- **Very Low**: p_right ≥ 0.05 OR effect_size ≤ 0.2 OR no protein evidence OR unclear biological relevance

**Additional Considerations:**
- Consider the specificity of enriched terms (more specific = higher confidence)
- Evaluate the consistency between GO and KEGG results
- Assess the strength of protein evidence (InterPro domains, functional annotations)
- Consider the biological plausibility in the disease context
- Account for potential false positives from broad/umbrella terms

Do not fabricate IDs, names, or biology. If information is missing (e.g., empty definition), say so and rely only on known metadata or widely accepted knowledge. If evidence is weak, state that explicitly.

Example output format:

- GO:0008150 — biological_process (BP)
  - Function (GO:0008150): High‑level biological processes that occur at the organism or cellular level.
  - Relevance: In this group (condition=..., organ=...), this term may reflect broad activation; avoid over‑interpretation without more specific child terms.

- hsa04010 — MAPK signaling pathway (Signaling)
  - Function (hsa04010): A conserved cascade transmitting signals from receptors to transcriptional responses.
  - Relevance: The overlap suggests possible engagement of MAPK responses in {disease}; interpret cautiously given context and {statistic}.

Summary: The terms collectively point to [...].
Confidence: Moderate
""".strip()
    return prompt


def _llm_call(
    prompt: str,
    model: str,
    api_key: str | None,
    base_url: str | None = "https://jeniya.top/v1",
    timeout: float = 30.0,
    llm_enabled: bool = True,
    structured_parser=None,
    return_structured: bool = False,
    format_instructions: str | None = None,
    system_prompt: str | None = None,
):
    """
    Unified LLM call function using LangChain abstractions.

    Supports both OpenAI-compatible APIs and native Ollama endpoints while
    optionally enforcing structured outputs through LangChain parsers.

    Args:
        prompt: User prompt to send to the LLM.
        model: Model identifier (e.g., gpt-4o-mini, BioMistral:7B).
        api_key: API key for authentication (optional for local Ollama).
        base_url: Base URL for the API endpoint.
        timeout: Request timeout in seconds.
        llm_enabled: Whether the LLM call should be executed.
        structured_parser: Optional LangChain output parser to enforce structure.
        return_structured: When True, returns a tuple (raw_text, parsed_result).
        format_instructions: Optional explicit format instructions appended to the prompt.
        system_prompt: Optional system prompt override.

    Returns:
        Raw text response or (raw text, parsed result) when `return_structured` is True.
        Returns empty string (and None) on failure.
    """
    if not llm_enabled:
        return ("", None) if return_structured else ""

    try:
        from langchain_openai import ChatOpenAI
        from langchain_community.chat_models import ChatOllama
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_core.exceptions import OutputParserException
    except Exception as exc:  # pragma: no cover - import guard
        logger.error(f"LangChain modules are required for LLM usage: {exc}")
        return ("", None) if return_structured else ""

    system_prompt = (
        system_prompt
        or "You are a biomedical domain expert. Be concise, structured, and cautious."
    )
    base_url = base_url or "https://jeniya.top/v1"
    is_ollama_native = "/api/chat" in base_url

    key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not is_ollama_native and not key:
        logger.warning("No API key provided for LLM call")
        return ("", None) if return_structured else ""

    llm = None
    try:
        if is_ollama_native:
            ollama_base = base_url.rstrip("/")
            if ollama_base.endswith("/api/chat"):
                ollama_base = ollama_base[: -len("/api/chat")]
            llm = ChatOllama(
                base_url=ollama_base or "http://localhost:11434",
                model=model,
                temperature=0.2,
            )
        else:
            # Use httpx client for proper timeout configuration
            import httpx
            # Create a client with proper timeout and connection pooling
            # Use a longer timeout for connect to handle slow connections
            http_client = httpx.Client(
                timeout=httpx.Timeout(timeout, connect=30.0, read=timeout, write=30.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                follow_redirects=True,
            )
            llm = ChatOpenAI(
                api_key=key,
                base_url=base_url.rstrip("/"),
                model=model,
                temperature=0.2,
                http_client=http_client,
                max_retries=2,
            )
    except Exception as exc:
        logger.error(f"Failed to initialise LangChain chat model: {exc}")
        import traceback
        logger.debug(f"LangChain initialization error: {traceback.format_exc()}")
        return ("", None) if return_structured else ""

    instructions = ""
    parser = structured_parser
    if parser is not None:
        try:
            instructions = parser.get_format_instructions()
        except AttributeError:
            logger.warning("Structured parser lacks get_format_instructions method; ignoring parser.")
            parser = None
    if format_instructions:
        instructions = f"{instructions}\n{format_instructions}".strip() if instructions else format_instructions

    prompt_text = prompt.strip()
    if instructions:
        prompt_text = f"{prompt_text}\n\n{instructions}"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt_text),
    ]

    try:
        response = llm.invoke(messages)
    except Exception as exc:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"LLM invocation failed: {type(exc).__name__}: {exc}")
        logger.debug(f"LLM invocation error details: {error_details}")
        # Log more details for connection errors
        if "connection" in str(exc).lower() or "Connection" in str(type(exc).__name__):
            logger.error(f"Connection error details - base_url: {base_url}, model: {model}, timeout: {timeout}")
        return ("", None) if return_structured else ""

    content = (response.content or "").strip() if hasattr(response, "content") else ""
    if not content:
        logger.warning("LLM response was empty")
        return ("", None) if return_structured else ""

    logger.info(f"LLM response received ({len(content)} characters)")

    parsed = None
    if parser is not None:
        try:
            parsed = parser.parse(content)
        except OutputParserException as exc:
            logger.error(f"Failed to parse LLM output with structured parser: {exc}")
            parsed = None
        except Exception as exc:  # pragma: no cover
            logger.error(f"Unexpected error while parsing LLM output: {exc}")
            parsed = None

    if return_structured:
        return content, parsed
    return content


def _format_go_terms_for_prompt(
    go_ids: list[str], go_meta: dict, max_terms: int = 10
) -> str:
    """Format GO terms for LLM prompt."""
    if not go_ids:
        return "None"
    
    lines = []
    for go_id in go_ids[:max_terms]:
        meta = go_meta.get(go_id, {})
        name = meta.get("name", "Unknown")
        namespace = meta.get("namespace", "unknown")
        lines.append(f"  - {go_id}: {name} [{namespace}]")
    
    if len(go_ids) > max_terms:
        lines.append(f"  - ... and {len(go_ids) - max_terms} more terms")
    
    return "\n".join(lines)


def _format_kegg_terms_for_prompt(
    kegg_ids: list[str], kegg_meta: dict, max_terms: int = 10
) -> str:
    """Format KEGG terms for LLM prompt."""
    if not kegg_ids:
        return "None"
    
    lines = []
    for kegg_id in kegg_ids[:max_terms]:
        meta = kegg_meta.get(kegg_id, {})
        name = meta.get("name", "Unknown")
        lines.append(f"  - {kegg_id}: {name}")
    
    if len(kegg_ids) > max_terms:
        lines.append(f"  - ... and {len(kegg_ids) - max_terms} more pathways")
    
    return "\n".join(lines)


def _build_expert_prompt(
    expert_role: str,
    disease: str,
    condition: str,
    additional_condition: str,
    organ: str,
    model: str,
    factor: str,
    statistic_method: str,
    S_obs: float,
    null_mean: float,
    null_sd: float,
    p_right: float,
    effect_size: float,
    verdict: str,
    go_ids: list[str],
    kegg_ids: list[str],
    go_meta: dict,
    kegg_meta: dict,
    protein_evidence: str = "",
    top_n: int = 10,
) -> str:
    """
    Build expert prompt for MoE mode based on the proposal document.
    Expert receives comprehensive experiment data and statistical results.
    """
    
    go_terms_str = _format_go_terms_for_prompt(go_ids, go_meta, top_n)
    kegg_terms_str = _format_kegg_terms_for_prompt(kegg_ids, kegg_meta, top_n)
    
    total_pathways = len(go_ids) + len(kegg_ids)
    
    prompt = f"""You are a {expert_role}. Please analyze the following biological pathway enrichment results:

## EXPERIMENTAL INFORMATION
- Disease/Condition: {disease}
- Experimental Condition: {condition}
- Additional Information: {additional_condition or "N/A"}
- Organ: {organ or "N/A"}
- Model System: {model or "N/A"}
- Experimental Factor: {factor or "N/A"}

## STATISTICAL RESULTS
- Statistical Method: {statistic_method}
- Observed Score (S_obs): {S_obs:.4f}
- Null Distribution Mean: {null_mean:.4f}
- Null Distribution SD: {null_sd:.4f}
- P-value (right-tailed): {_format_p_value(p_right)}
- Effect Size: {effect_size:.4f}
- Verdict: {verdict}

## ENRICHED PATHWAYS
Total {total_pathways} significantly enriched pathways (Top {top_n} shown):

GO Terms:
{go_terms_str}

KEGG Pathways:
{kegg_terms_str}
"""
    
    if protein_evidence:
        prompt += f"""
## PROTEIN DOMAIN EVIDENCE
{protein_evidence}
"""
    
    prompt += f"""
---

Based on your expertise as a {expert_role}, please provide the following analysis:

1. **Biological Significance**: What is the biological significance of these enriched pathways in the context of this disease/condition?

2. **Molecular Mechanisms**: Based on the enriched pathways, what are the potential molecular mechanisms and regulatory networks?

3. **Disease Association**: How do these findings relate to disease progression, therapeutic targets, or clinical manifestations?

4. **Key Insights**: From your professional perspective, what are the most important discoveries?

5. **Uncertainties and Limitations**: Which conclusions should be interpreted with caution? What uncertainties exist?

Requirements:
- Maintain scientific rigor; avoid over-interpretation
- Clearly state when evidence is insufficient
- Evaluate credibility based on statistical significance (p={_format_p_value(p_right)})
- Consider the practical significance of effect size ({effect_size:.4f})
"""
    
    return prompt


def _build_reviewer_prompt(
    expert_outputs: list[tuple[str, str]],  # [(role, output), ...]
    disease: str,
    condition: str,
    organ: str,
    model: str,
    factor: str,
    statistic_method: str,
    p_right: float,
    effect_size: float,
    verdict: str,
    total_pathways: int,
    go_count: int,
    kegg_count: int,
) -> str:
    """
    Build reviewer prompt for MoE mode.
    Reviewer integrates multiple expert analyses into final report.
    """
    
    # Format expert sections
    expert_sections = []
    for i, (role, output) in enumerate(expert_outputs, 1):
        expert_sections.append(f"""### Expert {i} - {role}
{output}
""")
    
    expert_text = "\n".join(expert_sections)
    
    prompt = f"""You are a senior bioinformatics reviewer and scientific report integration expert.

Your task is to integrate analyses from three independent experts and generate a high-quality final report.

## ORIGINAL EXPERIMENTAL DATA

### Experimental Information
- Disease/Condition: {disease}
- Experimental Condition: {condition}
- Organ/Model: {organ or "N/A"}/{model or "N/A"}
- Experimental Factor: {factor or "N/A"}

### Statistical Results
- Statistical Method: {statistic_method}
- P-value: {_format_p_value(p_right)}
- Effect Size: {effect_size:.4f}
- Verdict: {verdict}

### Enriched Pathway Counts
- Total Pathways: {total_pathways}
- GO Terms: {go_count}
- KEGG Pathways: {kegg_count}

---

## INDEPENDENT ANALYSES FROM THREE EXPERTS

{expert_text}

---

## YOUR INTEGRATION TASK

Please analyze the above expert opinions and complete the following tasks:

### 1. Identify Consensus and Disagreements
- Identify **core conclusions agreed upon by ALL experts** (high credibility)
- Identify **views supported by MAJORITY of experts** (moderate credibility)
- Point out **content with disagreement among experts** (requires caution)

### 2. Integration Analysis
- Synthesize unique insights from each expert
- Construct a complete biological picture
- Assess the reliability of conclusions

### 3. Quality Control
- Filter obviously incorrect or contradictory information
- Verify biological plausibility
- Evaluate the strength of statistical evidence

### 4. Generate Final Report

Please output in the following format:

#### Core Findings (Expert Consensus)
[List main conclusions agreed upon by all experts, annotate with "Consensus: 3/3"]

#### Molecular Mechanism Analysis
[Integrate expert views to construct complete mechanistic explanation]
- Primary pathway roles
- Regulatory networks
- Interactions

#### Clinical Relevance
[Disease associations and clinical implications]
- Relationship to disease progression
- Potential therapeutic targets
- Biomarker value

#### Key Insights
[Integrate unique findings from experts]
- Novel perspectives (annotate source expert)
- Important associations
- Unexpected discoveries

#### Uncertainties and Limitations
[Content requiring careful interpretation]
- Inferences with insufficient evidence
- Points of expert disagreement (if any, annotate "Disagreement: Expert X believes..., Expert Y believes...")
- Statistical limitations
- Hypotheses requiring validation

#### Recommended Follow-up Research
[Research recommendations based on integrated analysis]
- Validation experimental designs
- Key questions to explore
- Technical methodology suggestions

---

## OUTPUT REQUIREMENTS

1. **Clearly indicate consensus level**: 
   - "All experts unanimously agree" (3/3)
   - "Majority of experts indicate" (2/3)
   - "One expert suggests" (1/3)

2. **Scientific Rigor**:
   - Do not overstate conclusions
   - Clearly state uncertainties
   - Base reasoning on evidence

3. **Readability**:
   - Clear structure
   - Logical coherence
   - Highlighted key points

4. **Balance**:
   - Integrate consensus while preserving valuable unique insights
   - Acknowledge findings while noting limitations

Please proceed to integrate and generate the final report.
"""
    
    return prompt


def _format_structured_ensemble_response(structured: dict) -> str:
    """
    Convert structured JSON-like ensemble interpretation into Markdown text.
    """
    if not isinstance(structured, dict):
        return ""

    lines: list[str] = []

    term_entries = structured.get("term_explanations") or []
    if isinstance(term_entries, list):
        for entry in term_entries:
            if not isinstance(entry, dict):
                continue
            term_id = str(entry.get("term_id", "")).strip() or "Unknown term"
            function_text = str(entry.get("function", "")).strip()
            relevance_text = str(entry.get("relevance", "")).strip()
            lines.append(f"- **{term_id}**")
            if function_text:
                lines.append(f"  - Function: {function_text}")
            if relevance_text:
                lines.append(f"  - Relevance: {relevance_text}")
        if term_entries:
            lines.append("")

    summary = structured.get("summary")
    if summary:
        lines.append("**Summary**")
        lines.append(str(summary).strip())
        lines.append("")

    confidence = structured.get("confidence")
    if isinstance(confidence, dict):
        level = str(confidence.get("level", "")).strip()
        justification = str(confidence.get("justification", "")).strip()
        conf_line = "Confidence:"
        if level:
            conf_line += f" {level}"
        if justification:
            conf_line += f" — {justification}"
        lines.append(conf_line)
    elif isinstance(confidence, str) and confidence:
        lines.append(f"Confidence: {confidence.strip()}")

    return "\n".join(line for line in lines if line is not None).strip()


def _normalize_reviewer_structured(parsed: dict) -> dict:
    """Normalize reviewer structured output into typed Python objects."""
    import json

    keys = [
        "consensus_findings",
        "unique_insights",
        "resolution_of_disagreements",
        "final_recommendations",
    ]
    normalized: dict[str, list] = {}
    for key in keys:
        raw = parsed.get(key, "[]") if isinstance(parsed, dict) else "[]"
        data = []
        if isinstance(raw, list):
            data = raw
        elif isinstance(raw, str):
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, list):
                    data = candidate
            except Exception:
                data = []
        normalized[key] = data
    return normalized


def _format_structured_reviewer_output(structured: dict) -> str:
    """Render reviewer structured sections into Markdown format matching expected style."""
    if not isinstance(structured, dict):
        return ""

    sections = []
    mapping = [
        ("1) Consensus findings", structured.get("consensus_findings", [])),
        ("2) Unique insights", structured.get("unique_insights", [])),
        ("3) Resolution of disagreements", structured.get("resolution_of_disagreements", [])),
        ("4) Final recommendations", structured.get("final_recommendations", [])),
    ]

    for title, entries in mapping:
        if not entries:
            continue
        lines = [title]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            category = str(entry.get("category", "")) or "Untitled"
            agreement = str(entry.get("agreement", "")).strip()
            heading = f"- {category}"
            if agreement:
                heading += f" (Agreement: {agreement})"
            lines.append(heading)
            details = entry.get("details") or []
            if isinstance(details, list):
                for detail in details:
                    detail_str = str(detail).strip()
                    if detail_str:
                        lines.append(f"  - {detail_str}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections).strip()


def _parse_llm_ensemble_response(llm_text: str) -> dict:
    """
    Parse LLM ensemble response into structured sections with hierarchical bullet points.
    
    Expected sections:
    1) Consensus findings
    2) Unique insights
    3) Resolution of disagreements
    4) Final recommendations
    
    Returns:
        dict with parsed sections and hierarchical bullet points
    """
    import re
    
    sections = {
        "consensus_findings": "",
        "unique_insights": "",
        "resolution_of_disagreements": "",
        "final_recommendations": ""
    }
    
    # Try to extract sections using patterns
    # Pattern 1: Numbered sections (1), 2), 3), 4))
    # Fixed: Use lookahead with newline to avoid matching digits in parentheses like (GO:0003682)
    pattern1 = re.compile(r'1\)\s*\*?\*?([Cc]onsensus findings?)\*?\*?\n(.+?)(?=\n\s*2\)|$)', re.DOTALL | re.IGNORECASE)
    pattern2 = re.compile(r'2\)\s*\*?\*?([Uu]nique insights?)\*?\*?\n(.+?)(?=\n\s*3\)|$)', re.DOTALL | re.IGNORECASE)
    pattern3 = re.compile(r'3\)\s*\*?\*?([Rr]esolution of disagreements?)\*?\*?\n(.+?)(?=\n\s*4\)|$)', re.DOTALL | re.IGNORECASE)
    pattern4 = re.compile(r'4\)\s*\*?\*?([Ff]inal recommendations?)\*?\*?\n(.+?)$', re.DOTALL | re.IGNORECASE)
    
    match1 = pattern1.search(llm_text)
    if match1:
        sections["consensus_findings"] = match1.group(2).strip()
    
    match2 = pattern2.search(llm_text)
    if match2:
        sections["unique_insights"] = match2.group(2).strip()
    
    match3 = pattern3.search(llm_text)
    if match3:
        sections["resolution_of_disagreements"] = match3.group(2).strip()
    
    match4 = pattern4.search(llm_text)
    if match4:
        sections["final_recommendations"] = match4.group(2).strip()
    
    # Fallback: if no sections found, put everything in consensus_findings
    if not any(sections.values()):
        sections["consensus_findings"] = llm_text.strip()
    
    # Further parse each section into hierarchical bullet points
    for key in sections:
        if sections[key]:
            structured_section = _parse_section_hierarchically(sections[key])
            sections[key] = structured_section
    
    return sections


def _parse_section_hierarchically(section_text: str) -> dict:
    """
    Parse a section into hierarchical bullet points with direct sub-categories as fields.
    
    This function identifies main categories (like "Enrichment verdict", "Core pathway")
    and creates them as direct fields in the result dictionary.
    
    For expert-based sections (e.g., "Expert 1:"), it creates structured items with insights lists.
    For hierarchical sections with sub-items, it creates structured items with sub-items list.
    
    Returns:
        dict with structured items for each category (with content and consensus)
    """
    import re
    
    # Structured items: each category becomes a dict with content and consensus
    items = {}
    
    # First, check if there's a "Shared interpretations across experts" section
    # and remove it temporarily to process separately
    shared_section = None
    shared_pattern = re.compile(r'\n\s*Shared interpretations across experts\s*\n(.*)', re.DOTALL)
    shared_match = shared_pattern.search(section_text)
    if shared_match:
        shared_section = shared_match.group(1).strip()
        # Remove shared section from main text
        section_text = section_text[:shared_match.start()]
    
    # Check if this is an expert-based section (contains "Expert 1:", "Expert 2:", etc.)
    expert_pattern = re.compile(r'^-\s*Expert\s+(\d+):?\s*$', re.MULTILINE)
    is_expert_section = bool(expert_pattern.search(section_text))
    
    if is_expert_section:
        # Parse expert-based sections with sub-items
        items = _parse_expert_section(section_text)
    else:
        # Parse general hierarchical sections (may have main items with sub-items)
        items = _parse_hierarchical_items(section_text)
    
    # Process shared interpretations section if exists
    if shared_section:
        shared_bullets = []
        bullet_pattern = re.compile(r'^-\s*(.+?)(?:\s+(Consensus|Majority|One expert):\s*(\d+/\d+))?$', re.MULTILINE)
        
        for match in bullet_pattern.finditer(shared_section):
            bullet_content = match.group(1).strip()
            agreement_type = match.group(2)
            agreement_value = match.group(3)
            
            bullet_item = {"content": bullet_content}
            if agreement_type and agreement_value:
                bullet_item["agreement_type"] = agreement_type
                bullet_item["agreement_value"] = agreement_value
            
            shared_bullets.append(bullet_item)
        
        if shared_bullets:
            items["shared_interpretations_across_experts"] = {
                "items": shared_bullets
            }
    
    return items


def _parse_hierarchical_items(section_text: str) -> dict:
    """
    Parse hierarchical Markdown items into a clean JSON structure.
    
    Markdown structure:
        - Main item (Agreement: X/Y)
          - Sub item 1
          - Sub item 2: detail
            - Deep item 1
    
    JSON structure:
        "main_item": {
          "agreement_type": "Agreement",
          "agreement_value": "X/Y",
          "category_detail": "detail if : present after main category",
          "items": ["Sub item 1 as plain text", {"category": "Sub item 2", "items": ["Deep item 1"]}]
        }
    """
    import re
    
    if not section_text:
        return {}
    
    lines = section_text.strip().split('\n')
    result = {}
    stack = []  # [(indent_level, parent_dict)]
    
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        
        # Measure indent (number of leading spaces)
        indent = len(line) - len(line.lstrip(' '))
        stripped = line.strip()
        
        if not stripped.startswith('-'):
            continue
        
        # Remove "- " prefix
        content = stripped[2:].strip()
        
        # Check if next line has deeper indent (i.e., this item has sub-items)
        has_sub_items = False
        for j in range(idx + 1, len(lines)):
            next_line = lines[j]
            if not next_line.strip():
                continue
            if next_line.strip().startswith('-'):
                next_indent = len(next_line) - len(next_line.lstrip(' '))
                has_sub_items = next_indent > indent
                break
        
        # Parse different patterns
        # Pattern 1: "Category: detail (Agreement: X/Y)" - handles optional "on resolution" text
        # This pattern matches: "Category: detail (Agreement: 3/3)" or "Category: detail (Agreement: 3/3 on resolution)"
        m1 = re.match(r'^(.+?):\s*(.+?)\s*\((\w+)(?:\s+on\s+\w+)?:\s*(\d+/\d+)(?:\s+on\s+\w+)?\)\s*$', content)
        # Pattern 2: "Category (Agreement: X/Y)" - handles optional "on resolution" text
        # This pattern matches: "Category (Agreement: 3/3)" or "Category (Agreement: 3/3 on resolution)"
        # Note: We extract only the X/Y part, ignoring any "on resolution" text
        m2 = re.match(r'^(.+?)\s*\((\w+)(?:\s+on\s+\w+)?:\s*(\d+/\d+)(?:\s+on\s+\w+)?\)\s*$', content)
        # Pattern 3: "Category:" (colon at end, has sub-items)
        m3 = re.match(r'^(.+?):$', content) if has_sub_items else None
        # Pattern 4: "Category: detail" (colon with content, has sub-items)
        m4 = re.match(r'^(.+?):\s*(.+)$', content) if has_sub_items else None
        
        # Pop stack to correct level
        while stack and stack[-1][0] >= indent:
            stack.pop()
        
        if indent == 0:
            # Main category - top level
            category = None
            item_dict = {}
            
            if m1:
                category = m1.group(1).strip()
                item_dict['category_detail'] = m1.group(2).strip()
                item_dict['agreement_type'] = m1.group(3).strip()
                item_dict['agreement_value'] = m1.group(4).strip()
            elif m2:
                category = m2.group(1).strip()
                item_dict['agreement_type'] = m2.group(2).strip()
                item_dict['agreement_value'] = m2.group(3).strip()
            elif m4:
                category = m4.group(1).strip()
                item_dict['category_detail'] = m4.group(2).strip()
            else:
                category = content
            
            field_name = _convert_to_snake_case(category)
            result[field_name] = item_dict
            stack.append((indent, item_dict))
        else:
            # Sub-item - add to parent
            if not stack:
                continue
            
            parent = stack[-1][1]
            if 'items' not in parent:
                parent['items'] = []
            
            # Determine structure based on patterns and sub-items
            if m3:
                # "Category:" with sub-items
                sub_dict = {
                    'category': m3.group(1).strip()
                }
                parent['items'].append(sub_dict)
                stack.append((indent, sub_dict))
            elif m4 and has_sub_items:
                # "Category: detail" with sub-items
                sub_dict = {
                    'category': m4.group(1).strip(),
                    'category_detail': m4.group(2).strip()
                }
                parent['items'].append(sub_dict)
                stack.append((indent, sub_dict))
            elif m1:
                # Has agreement and detail
                sub_dict = {
                    'category': m1.group(1).strip(),
                    'category_detail': m1.group(2).strip(),
                    'agreement_type': m1.group(3).strip(),
                    'agreement_value': m1.group(4).strip()
                }
                parent['items'].append(sub_dict)
                if has_sub_items:
                    stack.append((indent, sub_dict))
            elif m2:
                # Has agreement only
                sub_dict = {
                    'category': m2.group(1).strip(),
                    'agreement_type': m2.group(2).strip(),
                    'agreement_value': m2.group(3).strip()
                }
                parent['items'].append(sub_dict)
                if has_sub_items:
                    stack.append((indent, sub_dict))
            else:
                # Plain text item
                parent['items'].append(content)
    
    return result


def _parse_expert_section(section_text: str) -> dict:
    """
    Parse expert-based sections where each expert has sub-items.
    
    Example input:
    - Expert 1:
      - Insight A
      - Insight B
    - Expert 2:
      - Insight C
    
    Returns:
        dict with expert_1, expert_2, etc. as keys, each containing an "insights" list
    """
    import re
    
    experts = {}
    lines = section_text.split('\n')
    
    current_expert = None
    current_insights = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        
        # Check for expert header: "- Expert N:"
        expert_match = re.match(r'^-\s*Expert\s+(\d+):?\s*$', stripped)
        if expert_match:
            # Save previous expert if exists
            if current_expert and current_insights:
                experts[current_expert] = {"insights": current_insights}
            
            # Start new expert
            expert_num = expert_match.group(1)
            current_expert = f"expert_{expert_num}"
            current_insights = []
        
        # Check for sub-item: "  - Insight"
        elif stripped.startswith('-') and line.startswith('  '):
            # This is a sub-item under the current expert
            insight = stripped[1:].strip()  # Remove leading "-"
            if current_expert and insight:
                current_insights.append(insight)
    
    # Save last expert
    if current_expert and current_insights:
        experts[current_expert] = {"insights": current_insights}
    
    return experts


def _convert_to_snake_case(text: str) -> str:
    """
    Convert text to snake_case for field names.
    
    Examples:
    - "Enrichment decision" -> "enrichment_decision"
    - "Core pathway" -> "core_pathway"
    - "Transcriptional/chromatin axis" -> "transcriptional_chromatin_axis"
    """
    import re
    
    # Replace special characters with underscores
    text = re.sub(r'[^\w\s]', '_', text)
    # Replace multiple spaces/underscores with single underscore
    text = re.sub(r'[\s_]+', '_', text)
    # Remove leading/trailing underscores
    text = text.strip('_')
    # Convert to lowercase
    return text.lower()


def _extract_shared_interpretations(text: str) -> str:
    """
    Extract "Shared interpretations" section from text.
    
    This section appears as a standalone paragraph without bullet points.
    """
    import re
    
    # Look for "Shared interpretations" followed by content
    pattern = r'Shared interpretations\s*\n(.*?)(?=\n\s*\d+\)|$)'
    match = re.search(pattern, text, re.DOTALL)
    
    if match:
        content = match.group(1).strip()
        # Clean up the content - remove leading dashes and format
        lines = content.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith('-'):
                cleaned_lines.append(line[1:].strip())
            elif line:
                cleaned_lines.append(line)
        return '\n'.join(cleaned_lines)
    
    return ""

def _extract_enhanced_categories(text: str) -> dict:
    """
    Extract enhanced categories from text using specific patterns.
    
    Looks for patterns like:
    - Statistical consensus (Consensus: 3/3)
      - content...
    - Core biological findings (Consensus: 3/3)
      - content...
    - Expert 1
      - content...
    - Expert 2
      - content...
    """
    import re
    
    categories = {}
    
    # Split text into lines
    lines = text.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Look for main category lines (starting with -)
        if line.startswith('-') and not line.startswith('  -'):
            # Extract category name (everything after the first -)
            category_name = line[1:].strip()
            
            # Look for sub-items in the following lines
            sub_items = []
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith('  -'):
                sub_item = lines[j].strip()[2:].strip()  # Remove "  - "
                if sub_item:
                    sub_items.append(sub_item)
                j += 1
            
            # If we found sub-items, add them to the category
            if sub_items:
                categories[category_name] = '\n'.join(sub_items)
                i = j  # Skip the processed lines
            else:
                i += 1
        else:
            i += 1
    
    return categories


def _parse_expert_output(expert_output: str) -> dict:
    """
    Parse expert output into structured sections.
    
    Expected sections:
    - Consensus
    - Key Findings
    - Summary
    - Confidence
    
    Returns:
        dict with parsed sections
    """
    import re
    
    sections = {
        "consensus": "",
        "key_findings": "",
        "summary": "",
        "confidence": ""
    }
    
    # Try to extract sections using patterns
    consensus_pattern = re.compile(r'\*\*[Cc]onsensus\*\*\s*(.+?)(?=\*\*|$)', re.DOTALL | re.IGNORECASE)
    key_findings_pattern = re.compile(r'\*\*[Kk]ey [Ff]indings?\*\*\s*(.+?)(?=\*\*|$)', re.DOTALL | re.IGNORECASE)
    summary_pattern = re.compile(r'\*\*[Ss]ummary\*\*\s*(.+?)(?=\*\*|$)', re.DOTALL | re.IGNORECASE)
    confidence_pattern = re.compile(r'\*\*[Cc]onfidence\*\*\s*:?\s*(.+?)(?=\*\*|$)', re.DOTALL | re.IGNORECASE)
    
    # Try alternative patterns
    if not consensus_pattern.search(expert_output):
        consensus_pattern = re.compile(r'### [Cc]onsensus\s*(.+?)(?=###|$)', re.DOTALL | re.IGNORECASE)
    if not key_findings_pattern.search(expert_output):
        key_findings_pattern = re.compile(r'### [Kk]ey [Ff]indings?\s*(.+?)(?=###|$)', re.DOTALL | re.IGNORECASE)
    if not summary_pattern.search(expert_output):
        summary_pattern = re.compile(r'### [Ss]ummary\s*(.+?)(?=###|$)', re.DOTALL | re.IGNORECASE)
    if not confidence_pattern.search(expert_output):
        confidence_pattern = re.compile(r'### [Cc]onfidence\s*(.+?)(?=###|$)', re.DOTALL | re.IGNORECASE)
    
    match = consensus_pattern.search(expert_output)
    if match:
        sections["consensus"] = match.group(1).strip()
    
    match = key_findings_pattern.search(expert_output)
    if match:
        sections["key_findings"] = match.group(1).strip()
    
    match = summary_pattern.search(expert_output)
    if match:
        sections["summary"] = match.group(1).strip()
    
    match = confidence_pattern.search(expert_output)
    if match:
        sections["confidence"] = match.group(1).strip()
    
    # Parse each section into bullet points and sub-categories
    for key in sections:
        if sections[key]:
            structured_section = _parse_section_hierarchically(sections[key])
            sections[key] = structured_section
    
    return sections


def _ensemble_llm_moe_call_with_details(
    prompt: str,
    expert_models: list[dict],
    reviewer_model: str,
    reviewer_base_url: str,
    api_key: str | None,
    parallel: bool = True,
    timeout: float = 60.0,
    show_experts: bool = False,
    parser=None,
    system_prompt: str | None = None,
) -> tuple[str, dict]:
    # Import build_moe_reviewer_prompt
    try:
        from orbit_ocsp.ensemble_llm_prompts import build_moe_reviewer_prompt
    except ImportError:
        logger.error("Failed to import build_moe_reviewer_prompt")
        return "", {}
    """
    Ensemble-specific MoE LLM call that returns both response and details.
    
    Returns:
        tuple: (final_response, details_dict)
            details_dict contains:
                - experts: list of expert outputs
                - reviewer_prompt: the reviewer prompt
                - reviewer_response: the raw reviewer response
    """
    result = _ensemble_llm_moe_call(
        prompt,
        expert_models,
        reviewer_model,
        reviewer_base_url,
        api_key,
        parallel,
        timeout,
        show_experts,
        parser=parser,
        system_prompt=system_prompt,
    )
    
    # Re-run to get details (not ideal but works for now)
    # Better approach: modify _ensemble_llm_moe_call to return details
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    expert_outputs = []
    
    # Step 1: Call each expert model
    if parallel:
        with ThreadPoolExecutor(max_workers=len(expert_models)) as executor:
            future_to_expert = {}
            for expert in expert_models:
                future = executor.submit(
                    _llm_call,
                    prompt=prompt,
                    model=expert.get("model"),
                    api_key=api_key,
                    base_url=expert.get("base_url"),
                    timeout=timeout,
                    llm_enabled=True,
                    structured_parser=parser,
                    return_structured=True,
                    system_prompt=system_prompt,
                )
                future_to_expert[future] = expert
            
            for future in as_completed(future_to_expert):
                expert = future_to_expert[future]
                try:
                    raw_output, structured_output = future.result()
                    formatted_output = (
                        _format_structured_ensemble_response(structured_output)
                        if structured_output
                        else (raw_output or "")
                    )
                    expert_outputs.append({
                        'role': expert.get('role', 'Expert'),
                        'model': expert.get('model', 'Unknown'),
                        'raw_output': raw_output or "",
                        'structured_output': structured_output,
                        'formatted_output': formatted_output or "",
                    })
                except Exception as e:
                    expert_outputs.append({
                        'role': expert.get('role', 'Expert'),
                        'model': expert.get('model', 'Unknown'),
                        'raw_output': "",
                        'structured_output': None,
                        'formatted_output': f"[Error: {e}]",
                    })
    else:
        for expert in expert_models:
            raw_output, structured_output = _llm_call(
                prompt=prompt,
                model=expert.get("model"),
                api_key=api_key,
                base_url=expert.get("base_url"),
                timeout=timeout,
                llm_enabled=True,
                structured_parser=parser,
                return_structured=True,
                system_prompt=system_prompt,
            )
            formatted_output = (
                _format_structured_ensemble_response(structured_output)
                if structured_output
                else (raw_output or "")
            )
            expert_outputs.append({
                'role': expert.get('role', 'Expert'),
                'model': expert.get('model', 'Unknown'),
                'raw_output': raw_output or "",
                'structured_output': structured_output,
                'formatted_output': formatted_output or "",
            })
    
    reviewer_prompt_spec = build_moe_reviewer_prompt(expert_outputs)
    reviewer_prompt = reviewer_prompt_spec["prompt"]
    reviewer_parser = reviewer_prompt_spec.get("parser")
    reviewer_system_prompt = reviewer_prompt_spec.get("system_prompt")

    reviewer_raw, reviewer_parsed = _llm_call(
        prompt=reviewer_prompt,
        model=reviewer_model,
        api_key=api_key,
        base_url=reviewer_base_url,
        timeout=timeout,
        llm_enabled=True,
        structured_parser=reviewer_parser,
        return_structured=True,
        system_prompt=reviewer_system_prompt,
    )

    # If reviewer_parsed is None or empty, try to parse from reviewer_raw
    if not reviewer_parsed and reviewer_raw:
        try:
            parsed_candidate = json.loads(reviewer_raw)
            if isinstance(parsed_candidate, dict):
                reviewer_parsed = parsed_candidate
        except Exception:
            pass
    
    normalized_structured = _normalize_reviewer_structured(reviewer_parsed or {})
    reviewer_formatted = _format_structured_reviewer_output(normalized_structured)
    final_response = reviewer_formatted or (reviewer_raw or "")

    details = {
        "experts": expert_outputs,
        "reviewer_prompt": reviewer_prompt,
        "reviewer_response": final_response,
        "reviewer_raw": reviewer_raw or "",
        "reviewer_structured": normalized_structured,
    }

    return final_response, details


def _ensemble_llm_moe_call(
    prompt: str,
    expert_models: list[dict],
    reviewer_model: str,
    reviewer_base_url: str,
    api_key: str | None,
    parallel: bool = True,
    timeout: float = 60.0,
    show_experts: bool = False,
    parser=None,
    system_prompt: str | None = None,
) -> str:
    """
    Ensemble-specific MoE LLM call (simplified version).
    
    Args:
        prompt: Pre-built ensemble prompt
        expert_models: List of expert model configs
        reviewer_model: Reviewer model name
        reviewer_base_url: Reviewer base URL
        api_key: API key
        parallel: Whether to parallelize expert calls
        timeout: Request timeout
        show_experts: Whether to show individual expert outputs
    
    Returns:
        Final LLM response (with optional expert details)
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # Import build_moe_reviewer_prompt
    try:
        from orbit_ocsp.ensemble_llm_prompts import build_moe_reviewer_prompt
    except ImportError:
        logger.error("Failed to import build_moe_reviewer_prompt")
        return ""
    
    start_time = time.time()
    expert_outputs = []
    
    # Step 1: Call each expert model
    if parallel:
        with ThreadPoolExecutor(max_workers=len(expert_models)) as executor:
            future_to_expert = {}
            for expert in expert_models:
                future = executor.submit(
                    _llm_call,
                    prompt=prompt,
                    model=expert.get("model"),
                    api_key=api_key,
                    base_url=expert.get("base_url"),
                    timeout=timeout,
                    llm_enabled=True,
                    structured_parser=parser,
                    return_structured=True,
                    system_prompt=system_prompt,
                )
                future_to_expert[future] = expert
            
            for future in as_completed(future_to_expert):
                expert = future_to_expert[future]
                try:
                    raw_output, structured_output = future.result()
                    formatted_output = (
                        _format_structured_ensemble_response(structured_output)
                        if structured_output
                        else (raw_output or "")
                    )
                    expert_outputs.append({
                        'role': expert.get('role', 'Expert'),
                        'model': expert.get('model', 'Unknown'),
                        'raw_output': raw_output or "",
                        'structured_output': structured_output,
                        'formatted_output': formatted_output or "",
                    })
                except Exception as e:
                    expert_outputs.append({
                        'role': expert.get('role', 'Expert'),
                        'model': expert.get('model', 'Unknown'),
                        'raw_output': "",
                        'structured_output': None,
                        'formatted_output': f"[Error: {e}]",
                    })
    else:
        # Sequential execution
        for expert in expert_models:
            raw_output, structured_output = _llm_call(
                prompt=prompt,
                model=expert.get("model"),
                api_key=api_key,
                base_url=expert.get("base_url"),
                timeout=timeout,
                llm_enabled=True,
                structured_parser=parser,
                return_structured=True,
                system_prompt=system_prompt,
            )
            formatted_output = (
                _format_structured_ensemble_response(structured_output)
                if structured_output
                else (raw_output or "")
            )
            expert_outputs.append({
                'role': expert.get('role', 'Expert'),
                'model': expert.get('model', 'Unknown'),
                'raw_output': raw_output or "",
                'structured_output': structured_output,
                'formatted_output': formatted_output or "",
            })
    
    reviewer_prompt_spec = build_moe_reviewer_prompt(expert_outputs)
    reviewer_prompt = reviewer_prompt_spec["prompt"]
    reviewer_parser = reviewer_prompt_spec.get("parser")
    reviewer_system_prompt = reviewer_prompt_spec.get("system_prompt")

    reviewer_raw, reviewer_parsed = _llm_call(
        prompt=reviewer_prompt,
        model=reviewer_model,
        api_key=api_key,
        base_url=reviewer_base_url,
        timeout=timeout,
        llm_enabled=True,
        structured_parser=reviewer_parser,
        return_structured=True,
        system_prompt=reviewer_system_prompt,
    )

    # If reviewer_parsed is None or empty, try to parse from reviewer_raw
    if not reviewer_parsed and reviewer_raw:
        try:
            parsed_candidate = json.loads(reviewer_raw)
            if isinstance(parsed_candidate, dict):
                reviewer_parsed = parsed_candidate
        except Exception:
            pass
    
    normalized_structured = _normalize_reviewer_structured(reviewer_parsed or {})
    reviewer_formatted = _format_structured_reviewer_output(normalized_structured)
    final_report = reviewer_formatted or (reviewer_raw or "")
    
    # Step 4: Format response
    if show_experts and expert_outputs:
        response = final_report + "\n\n"
        response += "<details><summary><b>Individual Expert Analyses (click to expand)</b></summary>\n\n"
        for i, expert in enumerate(expert_outputs, 1):
            formatted_output = expert.get('formatted_output', '')
            if formatted_output.strip() and not formatted_output.startswith('[Error'):
                response += f"#### Expert {i} - {expert['role']} ({expert['model']})\n\n"
                response += formatted_output + "\n\n"
        response += "</details>\n"
        return response
    else:
        return final_report or ""


def _llm_moe_call(
    disease: str,
    condition: str,
    additional_condition: str,
    organ: str,
    model: str,
    factor: str,
    statistic_method: str,
    S_obs: float,
    null_mean: float,
    null_sd: float,
    p_right: float,
    effect_size: float,
    verdict: str,
    go_ids: list[str],
    kegg_ids: list[str],
    go_meta: dict,
    kegg_meta: dict,
    expert_models: list[dict],  # [{'model': str, 'base_url': str, 'role': str}, ...]
    reviewer_model: str,
    reviewer_base_url: str,
    api_key: str | None,
    parallel: bool = True,
    timeout: float = 60.0,
    protein_evidence: str = "",
    top_n: int = 10,
) -> dict:
    """
    MoE (Mixture of Experts) mode LLM call.
    
    Args:
        Multiple experimental and statistical parameters (see function signature)
        expert_models: List of expert model configs with 'model', 'base_url', 'role'
        reviewer_model: Model name for the reviewer
        reviewer_base_url: Base URL for the reviewer model
        api_key: API key for authentication
        parallel: Whether to call expert models in parallel
        timeout: Request timeout in seconds
        protein_evidence: Optional protein domain evidence text
        top_n: Number of top pathways to show in prompt
    
    Returns:
        {
            'final_report': str,              # Final integrated report
            'expert_outputs': list[dict],     # [{'role': str, 'output': str}, ...]
            'metadata': dict                  # Execution metadata
        }
    """
    
    import time
    start_time = time.time()
    
    # Step 1: Build expert prompts
    expert_prompts = []
    for expert in expert_models:
        role = expert.get("role", "Expert")
        prompt = _build_expert_prompt(
            expert_role=role,
            disease=disease,
            condition=condition,
            additional_condition=additional_condition,
            organ=organ,
                model=model,
            factor=factor,
            statistic_method=statistic_method,
            S_obs=S_obs,
            null_mean=null_mean,
            null_sd=null_sd,
            p_right=p_right,
            effect_size=effect_size,
            verdict=verdict,
            go_ids=go_ids,
            kegg_ids=kegg_ids,
            go_meta=go_meta,
            kegg_meta=kegg_meta,
            protein_evidence=protein_evidence,
            top_n=top_n,
        )
        expert_prompts.append((expert, prompt))
    
    # Step 2: Call expert models (parallel or sequential)
    expert_results = []
    
    if parallel:
        # Parallel execution using ThreadPoolExecutor
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        with ThreadPoolExecutor(max_workers=len(expert_models)) as executor:
            future_to_expert = {}
            for expert, prompt in expert_prompts:
                future = executor.submit(
                    _llm_call,
                prompt,
                    expert.get("model"),
                    api_key,
                    expert.get("base_url", "https://jeniya.top/v1"),
                    timeout,
                    True,  # llm_enabled
                )
                future_to_expert[future] = expert
            
            # Collect results as they complete
            for future in as_completed(future_to_expert):
                expert = future_to_expert[future]
                try:
                    output = future.result()
                    expert_results.append({
                        "role": expert.get("role", "Expert"),
                        "model": expert.get("model"),
                        "output": output,
                    })
                except Exception as e:
                    logger.error(f"Expert {expert.get('model')} failed: {e}")
                    expert_results.append({
                        "role": expert.get("role", "Expert"),
                        "model": expert.get("model"),
                        "output": "",
                    })
    else:
        # Sequential execution
        for expert, prompt in expert_prompts:
            output = _llm_call(
                prompt,
                expert.get("model"),
                api_key,
                expert.get("base_url", "https://jeniya.top/v1"),
                timeout,
                True,  # llm_enabled
            )
            expert_results.append({
                "role": expert.get("role", "Expert"),
                "model": expert.get("model"),
                "output": output,
            })
    
    expert_time = time.time() - start_time
    
    # Filter out empty outputs
    valid_experts = [e for e in expert_results if e["output"].strip()]
    
    if not valid_experts:
        logger.warning("All expert models returned empty outputs")
        return {
            "final_report": "",
            "expert_outputs": expert_results,
            "metadata": {
                "num_experts": len(expert_models),
                "num_valid_experts": 0,
                "reviewer_model": reviewer_model,
                "parallel": parallel,
                "expert_time": expert_time,
                "total_time": expert_time,
            },
        }
    
    # Step 3: Build reviewer prompt
    reviewer_prompt = _build_reviewer_prompt(
        expert_outputs=[(e["role"], e["output"]) for e in valid_experts],
        disease=disease,
        condition=condition,
        organ=organ,
                model=model,
        factor=factor,
        statistic_method=statistic_method,
        p_right=p_right,
        effect_size=effect_size,
        verdict=verdict,
        total_pathways=len(go_ids) + len(kegg_ids),
        go_count=len(go_ids),
        kegg_count=len(kegg_ids),
    )
    
    # Step 4: Call reviewer model
    reviewer_start = time.time()
    final_report = _llm_call(
        reviewer_prompt,
        reviewer_model,
        api_key,
        reviewer_base_url,
        timeout * 1.5,  # Give reviewer more time
        True,  # llm_enabled
    )
    reviewer_time = time.time() - reviewer_start
    
    total_time = time.time() - start_time
    
    return {
        "final_report": final_report,
        "expert_outputs": expert_results,
        "metadata": {
            "num_experts": len(expert_models),
            "num_valid_experts": len(valid_experts),
            "reviewer_model": reviewer_model,
            "parallel": parallel,
            "expert_time": expert_time,
            "reviewer_time": reviewer_time,
            "total_time": total_time,
        },
    }


def _parse_llm_output(llm_text: str) -> dict:
    """
    Parse LLM output into structured format with GO descriptions, KEGG descriptions, summary, and confidence.
    Handles both gene report format (- GO:...) and group report format (**GO:...**).
    """
    if not llm_text or not isinstance(llm_text, str):
        return {
            "go_descriptions": [],
            "kegg_descriptions": [],
            "summary": "",
            "confidence": "",
        }

    # Split by lines and process
    lines = llm_text.strip().split("\n")

    go_descriptions = []
    kegg_descriptions = []
    summary = ""
    confidence = ""

    current_section = None
    current_description = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for GO term descriptions (both formats)
        # Gene format: - GO:0001821 — histamine secretion (BP)
        # Group format: - **GO:0001821 — histamine secretion (BP)**
        go_match = re.match(r"^-\s*\*\*GO:\d+", line) or re.match(r"^-\s*GO:\d+", line)
        if go_match:
            current_section = "go"
            # Extract term ID, handling both formats
            if line.startswith("- **") and line.endswith("**"):
                term_id = (
                    line.replace("- **", "").replace("**", "").split("—")[0].strip()
                )
            elif line.startswith("- "):
                term_id = line.split("—")[0].strip().replace("- ", "")
            else:
                term_id = line.split("—")[0].strip()

            current_description = {"term_id": term_id, "function": "", "relevance": ""}
            go_descriptions.append(current_description)
        # Check for KEGG term descriptions (both formats)
        elif re.match(r"^-\s*\*\*(hsa\d+|map\d+|ko\d+)", line) or re.match(
            r"^-\s*(hsa\d+|map\d+|ko\d+)", line
        ):
            current_section = "kegg"
            # Extract term ID, handling both formats
            if line.startswith("- **") and line.endswith("**"):
                term_id = (
                    line.replace("- **", "").replace("**", "").split("—")[0].strip()
                )
            elif line.startswith("- "):
                term_id = line.split("—")[0].strip().replace("- ", "")
            else:
                term_id = line.split("—")[0].strip()

            current_description = {"term_id": term_id, "function": "", "relevance": ""}
            kegg_descriptions.append(current_description)
        # Check for function descriptions (both formats)
        elif line.startswith("- Function (") and current_description:
            # Extract function text, handling the term ID in parentheses
            function_text = line.replace("- Function (", "").split("):", 1)
            if len(function_text) > 1:
                current_description["function"] = function_text[1].strip()
            else:
                current_description["function"] = (
                    line.replace("- Function (", "").replace("):", "").strip()
                )
        # Check for relevance descriptions
        elif line.startswith("- Relevance:") and current_description:
            current_description["relevance"] = line.replace("- Relevance:", "").strip()
        # Check for summary
        elif line.startswith("Summary:"):
            summary = line.replace("Summary:", "").strip()
        # Check for confidence
        elif line.startswith("Confidence:"):
            confidence = line.replace("Confidence:", "").strip()

    return {
        "go_descriptions": go_descriptions,
        "kegg_descriptions": kegg_descriptions,
        "summary": summary,
        "confidence": confidence,
    }


def _parse_llm_prompt(prompt_text: str) -> dict:
    """
    Parse LLM prompt into structured format with detailed sections.
    """
    if not prompt_text or not isinstance(prompt_text, str):
        return {
            "disease_background": "",
            "group_context": "",
            "analysis_summary": {
                "statistic": "",
                "observed_s": "",
                "null_mean": "",
                "null_sd": "",
                "p_right": "",
                "effect_size": "",
                "verdict": "",
                "sizes": {"A_size": "", "B_size": "", "U_size": ""},
            },
            "statistical_background": "",
            "top_overlapping_terms": "",
            "protein_evidence": "",
            "go_terms": "",
            "kegg_pathways": "",
            "ontology_specific_summary": {
                "go": {
                    "S_obs": "",
                    "mu": "",
                    "effect": "",
                    "p_right": "",
                    "verdict": "",
                    "sizes": {"A_GO_size": "", "B_GO_size": "", "U_GO_size": ""},
                },
                "kegg": {
                    "S_obs": "",
                    "mu": "",
                    "effect": "",
                    "p_right": "",
                    "verdict": "",
                    "sizes": {"A_KEGG_size": "", "B_KEGG_size": "", "U_KEGG_size": ""},
                },
            },
            "task": "",
            "example": "",
        }

    # Split by double newlines to get sections, fallback to single newlines if no double newlines
    sections = prompt_text.strip().split("\n\n")
    if len(sections) == 1:
        # If no double newlines, try to split by section headers
        lines = prompt_text.strip().split("\n")
        sections = []
        current_section = []

        for line in lines:
            if (
                line.strip().startswith("**")
                and line.strip().endswith(":**")
                and current_section
            ):
                # Start of new section, save previous section
                sections.append("\n".join(current_section))
                current_section = [line]
            else:
                current_section.append(line)

        # Add the last section
        if current_section:
            sections.append("\n".join(current_section))

    result = {
        "disease_background": "",
        "group_context": "",
        "analysis_summary": {
            "statistic": "",
            "observed_s": "",
            "null_mean": "",
            "null_sd": "",
            "p_right": "",
            "effect_size": "",
            "verdict": "",
            "sizes": {"A_size": "", "B_size": "", "U_size": ""},
        },
        "statistical_background": "",
        "top_overlapping_terms": "",
        "protein_evidence": "",
        "go_terms": "",
        "kegg_pathways": "",
        "ontology_specific_summary": {
            "go": {
                "S_obs": "",
                "mu": "",
                "effect": "",
                "p_right": "",
                "verdict": "",
                "sizes": {"A_GO_size": "", "B_GO_size": "", "U_GO_size": ""},
            },
            "kegg": {
                "S_obs": "",
                "mu": "",
                "effect": "",
                "p_right": "",
                "verdict": "",
                "sizes": {"A_KEGG_size": "", "B_KEGG_size": "", "U_KEGG_size": ""},
            },
        },
        "task": "",
        "example": "",
    }

    # Process each section
    for section in sections:
        section = section.strip()
        if not section:
            continue

        lines = section.split("\n")
        first_line = lines[0].strip()

        # Check for section headers
        if first_line.startswith("**Disease/background:**"):
            content = first_line.replace("**Disease/background:**", "").strip()
            result["disease_background"] = content
        elif first_line.startswith("**Group context:**"):
            content = first_line.replace("**Group context:**", "").strip()
            result["group_context"] = content
        elif "**Group context:**" in first_line:
            # Handle case where Group context is in the middle of a line
            content = first_line.split("**Group context:**")[1].strip()
            result["group_context"] = content

        # Check if this section contains both Disease/background and Group context
        if "**Disease/background:**" in section and "**Group context:**" in section:
            lines = section.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("**Disease/background:**"):
                    content = line.replace("**Disease/background:**", "").strip()
                    result["disease_background"] = content
                elif line.startswith("**Group context:**"):
                    content = line.replace("**Group context:**", "").strip()
                    result["group_context"] = content
        elif first_line.startswith("**Analysis summary (link to stats):**"):
            # Parse analysis summary lines
            for line in lines[1:]:  # Skip header line
                line = line.strip()
                if line.startswith("- Statistic:"):
                    result["analysis_summary"]["statistic"] = line.replace(
                        "- Statistic:", ""
                    ).strip()
                elif "Observed S:" in line:
                    # Parse: - Observed S: 21.00000  |  Null mean: 9.13000  |  Null SD: 2.86515
                    parts = line.split("|")
                    for part in parts:
                        part = part.strip()
                        if "Observed S:" in part:
                            result["analysis_summary"]["observed_s"] = (
                                part.replace("Observed S:", "").replace("-", "").strip()
                            )
                        elif "Null mean:" in part:
                            result["analysis_summary"]["null_mean"] = part.replace(
                                "Null mean:", ""
                            ).strip()
                        elif "Null SD:" in part:
                            result["analysis_summary"]["null_sd"] = part.replace(
                                "Null SD:", ""
                            ).strip()
                elif "p_right (empirical):" in line:
                    # Parse: - p_right (empirical): 0.00200  |  Effect size (S - mu): 11.87000  |  Verdict: enriched
                    parts = line.split("|")
                    for part in parts:
                        part = part.strip()
                        if "p_right (empirical):" in part:
                            result["analysis_summary"]["p_right"] = (
                                part.replace("p_right (empirical):", "")
                                .replace("-", "")
                                .strip()
                            )
                        elif "Effect size (S - mu):" in part:
                            result["analysis_summary"]["effect_size"] = part.replace(
                                "Effect size (S - mu):", ""
                            ).strip()
                        elif "Verdict:" in part:
                            result["analysis_summary"]["verdict"] = part.replace(
                                "Verdict:", ""
                            ).strip()
                elif "Sizes:" in line:
                    # Parse: - Sizes: |A|=127, |B|=2914, |U|=40273
                    sizes_text = line.replace("- Sizes:", "").strip()
                    if "|A|=" in sizes_text:
                        result["analysis_summary"]["sizes"]["A_size"] = (
                            sizes_text.split("|A|=")[1].split(",")[0].strip()
                        )
                    if "|B|=" in sizes_text:
                        result["analysis_summary"]["sizes"]["B_size"] = (
                            sizes_text.split("|B|=")[1].split(",")[0].strip()
                        )
                    if "|U|=" in sizes_text:
                        result["analysis_summary"]["sizes"]["U_size"] = (
                            sizes_text.split("|U|=")[1].strip()
                        )
        elif first_line.startswith("**Statistical background:**"):
            content = "\n".join(lines[1:]).strip()  # Skip header line
            result["statistical_background"] = content
        elif first_line.startswith("**Top overlapping/enriched terms (IDs → names):**"):
            content = "\n".join(lines[1:]).strip()  # Skip header line
            result["top_overlapping_terms"] = content
        elif first_line.startswith("**Protein evidence (summary):**"):
            content = "\n".join(lines[1:]).strip()  # Skip header line
            # Parse protein evidence into structured format
            result["protein_evidence"] = _parse_protein_evidence(content)
        elif first_line.startswith("**GO terms to explain:**"):
            content = "\n".join(lines[1:]).strip()  # Skip header line
            result["go_terms"] = content
        elif first_line.startswith("**KEGG pathways to explain:**"):
            content = "\n".join(lines[1:]).strip()  # Skip header line
            result["kegg_pathways"] = content
        elif first_line.startswith("**Ontology-specific summary (if available):**"):
            # Parse ontology-specific summary
            for line in lines[1:]:  # Skip header line
                line = line.strip()
                if line.startswith("GO:"):
                    # Parse GO line: GO: S_obs=18.00000 | mu=7.65600 | effect=10.34400 | p_right=0.00200 | verdict=enriched | sizes: |A_GO|=107, |B_GO|=2835, |U_GO|=39906
                    go_parts = line.replace("GO:", "").strip().split("|")
                    for part in go_parts:
                        part = part.strip()
                        if "S_obs=" in part:
                            result["ontology_specific_summary"]["go"]["S_obs"] = (
                                part.replace("S_obs=", "").strip()
                            )
                        elif "mu=" in part:
                            result["ontology_specific_summary"]["go"]["mu"] = (
                                part.replace("mu=", "").strip()
                            )
                        elif "effect=" in part:
                            result["ontology_specific_summary"]["go"]["effect"] = (
                                part.replace("effect=", "").strip()
                            )
                        elif "p_right=" in part:
                            result["ontology_specific_summary"]["go"]["p_right"] = (
                                part.replace("p_right=", "").strip()
                            )
                        elif "verdict=" in part:
                            result["ontology_specific_summary"]["go"]["verdict"] = (
                                part.replace("verdict=", "").strip()
                            )
                        elif "sizes:" in part:
                            # Find the sizes part and extract the full sizes text from the current line
                            sizes_start = part.find("sizes:")
                            if sizes_start != -1:
                                sizes_text = part[
                                    sizes_start + 6 :
                                ].strip()  # Remove 'sizes:' prefix
                                # Look for the complete sizes text in the current line
                                for orig_line in lines:
                                    if (
                                        orig_line.strip().startswith("GO:")
                                        and "sizes:" in orig_line
                                    ):
                                        full_sizes_text = orig_line.split("sizes:")[
                                            1
                                        ].strip()
                                        if "|A_GO|=" in full_sizes_text:
                                            result["ontology_specific_summary"]["go"][
                                                "sizes"
                                            ]["A_GO_size"] = (
                                                full_sizes_text.split("|A_GO|=")[1]
                                                .split(",")[0]
                                                .strip()
                                            )
                                        if "|B_GO|=" in full_sizes_text:
                                            result["ontology_specific_summary"]["go"][
                                                "sizes"
                                            ]["B_GO_size"] = (
                                                full_sizes_text.split("|B_GO|=")[1]
                                                .split(",")[0]
                                                .strip()
                                            )
                                        if "|U_GO|=" in full_sizes_text:
                                            result["ontology_specific_summary"]["go"][
                                                "sizes"
                                            ]["U_GO_size"] = full_sizes_text.split(
                                                "|U_GO|="
                                            )[
                                                1
                                            ].strip()
                                        break
                elif line.startswith("KEGG:"):
                    # Parse KEGG line: KEGG: S_obs=3.00000 | mu=1.47400 | effect=1.52600 | p_right=0.20758 | verdict=not_significant | sizes: |A_KEGG|=20, |B_KEGG|=79, |U_KEGG|=367
                    kegg_parts = line.replace("KEGG:", "").strip().split("|")
                    for part in kegg_parts:
                        part = part.strip()
                        if "S_obs=" in part:
                            result["ontology_specific_summary"]["kegg"]["S_obs"] = (
                                part.replace("S_obs=", "").strip()
                            )
                        elif "mu=" in part:
                            result["ontology_specific_summary"]["kegg"]["mu"] = (
                                part.replace("mu=", "").strip()
                            )
                        elif "effect=" in part:
                            result["ontology_specific_summary"]["kegg"]["effect"] = (
                                part.replace("effect=", "").strip()
                            )
                        elif "p_right=" in part:
                            result["ontology_specific_summary"]["kegg"]["p_right"] = (
                                part.replace("p_right=", "").strip()
                            )
                        elif "verdict=" in part:
                            result["ontology_specific_summary"]["kegg"]["verdict"] = (
                                part.replace("verdict=", "").strip()
                            )
                        elif "sizes:" in part:
                            # Find the sizes part and extract the full sizes text from the current line
                            sizes_start = part.find("sizes:")
                            if sizes_start != -1:
                                sizes_text = part[
                                    sizes_start + 6 :
                                ].strip()  # Remove 'sizes:' prefix
                                # Look for the complete sizes text in the current line
                                for orig_line in lines:
                                    if (
                                        orig_line.strip().startswith("KEGG:")
                                        and "sizes:" in orig_line
                                    ):
                                        full_sizes_text = orig_line.split("sizes:")[
                                            1
                                        ].strip()
                                        if "|A_KEGG|=" in full_sizes_text:
                                            result["ontology_specific_summary"]["kegg"][
                                                "sizes"
                                            ]["A_KEGG_size"] = (
                                                full_sizes_text.split("|A_KEGG|=")[1]
                                                .split(",")[0]
                                                .strip()
                                            )
                                        if "|B_KEGG|=" in full_sizes_text:
                                            result["ontology_specific_summary"]["kegg"][
                                                "sizes"
                                            ]["B_KEGG_size"] = (
                                                full_sizes_text.split("|B_KEGG|=")[1]
                                                .split(",")[0]
                                                .strip()
                                            )
                                        if "|U_KEGG|=" in full_sizes_text:
                                            result["ontology_specific_summary"]["kegg"][
                                                "sizes"
                                            ]["U_KEGG_size"] = full_sizes_text.split(
                                                "|U_KEGG|="
                                            )[
                                                1
                                            ].strip()
                                        break
        elif first_line.startswith("Task:"):
            content = "\n".join(lines).strip()
            result["task"] = content
        elif first_line.startswith("Example output format:"):
            content = "\n".join(lines).strip()
            result["example"] = content

    return result


def _parse_protein_evidence(content: str) -> dict:
    """
    Parse protein evidence text into structured format.

    Handles both multi-gene format:
    **Gene: TCF7L2**
    - Accessions: TCF7L2_orf68 (n=1)
    - Length: 737
    - Coverage: 0.562 (span 140–553)
    - InterPro: IPR009071 — High mobility group box domain; IPR013558 — CTNNB1 binding, N-teminal
    - Pfam: N-terminal CTNNB1 binding; HMG (high mobility group) box

    And single-gene format:
    - Accessions: TCF7L2_orf68 (n=1)
    - Length: 737
    - Coverage: 0.562 (span 140–553)
    - InterPro (descriptions): CTNNB1 binding, N-teminal (n=1); High mobility group box domain (n=1)
    - Pfam (descriptions): HMG (high mobility group) box (n=1); N-terminal CTNNB1 binding (n=1)
    """
    if not content or content.strip() == "(none)":
        return {"genes": []}

    genes = []
    lines = content.strip().split("\n")
    current_gene = None

    for line in lines:
        line = line.strip()
        if line.startswith("**Gene: "):
            # Save previous gene if exists
            if current_gene:
                genes.append(current_gene)

            # Start new gene
            gene_name = line.replace("**Gene: ", "").replace("**", "").strip()
            current_gene = {
                "Gene": gene_name,
                "Accessions": [],
                "Length": None,
                "Coverage": {},
                "InterPro": [],
                "Hits": [],
            }
        elif line.startswith("- Accessions: ") and current_gene:
            # Parse accessions: "TCF7L2_orf68 (n=1)" -> ["TCF7L2_orf68"]
            acc_text = line.replace("- Accessions: ", "").strip()
            if " (n=" in acc_text:
                acc_name = acc_text.split(" (n=")[0].strip()
                current_gene["Accessions"] = [acc_name]
            else:
                current_gene["Accessions"] = [acc_text]
        elif line.startswith("- Length: ") and current_gene:
            # Parse length: "737" -> 737
            length_text = line.replace("- Length: ", "").strip()
            try:
                current_gene["Length"] = int(length_text)
            except ValueError:
                current_gene["Length"] = length_text
        elif line.startswith("- Coverage: ") and current_gene:
            # Parse coverage: "0.562 (span 140–553)" -> {"fraction_covered": 0.562, "approx_span": [140, 553]}
            cov_text = line.replace("- Coverage: ", "").strip()
            try:
                if " (span " in cov_text:
                    frac_text = cov_text.split(" (span ")[0].strip()
                    span_text = cov_text.split(" (span ")[1].replace(")", "").strip()
                    current_gene["Coverage"] = {
                        "fraction_covered": float(frac_text),
                        "approx_span": [int(x.strip()) for x in span_text.split("–")],
                    }
                else:
                    current_gene["Coverage"] = {"fraction_covered": float(cov_text)}
            except (ValueError, IndexError):
                current_gene["Coverage"] = {"fraction_covered": cov_text}
        elif line.startswith("- InterPro: ") and current_gene:
            # Parse InterPro: "IPR009071 — High mobility group box domain; IPR013558 — CTNNB1 binding, N-teminal"
            ipr_text = line.replace("- InterPro: ", "").strip()
            ipr_items = []
            for item in ipr_text.split(";"):
                item = item.strip()
                if " — " in item:
                    acc, desc = item.split(" — ", 1)
                    ipr_items.append(
                        {"accession": acc.strip(), "description": desc.strip()}
                    )
            current_gene["InterPro"] = ipr_items
        elif line.startswith("- InterPro (descriptions): ") and current_gene:
            # Parse InterPro descriptions format: "CTNNB1 binding, N-teminal (n=1); High mobility group box domain (n=1)"
            ipr_text = line.replace("- InterPro (descriptions): ", "").strip()
            ipr_items = []
            for item in ipr_text.split(";"):
                item = item.strip()
                if " (n=" in item:
                    desc = item.split(" (n=")[0].strip()
                    ipr_items.append({"description": desc})
                else:
                    ipr_items.append({"description": item})
            current_gene["InterPro"] = ipr_items
        elif line.startswith("- ") and current_gene:
            # Parse other hits (Pfam, etc.)
            hit_text = line.replace("- ", "").strip()
            if ": " in hit_text:
                analysis, desc = hit_text.split(": ", 1)
                current_gene["Hits"].append(
                    {"analysis": analysis.strip(), "description": desc.strip()}
                )
        elif line.startswith("- ") and not current_gene:
            # Handle single-gene format (no **Gene: header)
            # Create a default gene entry
            if not current_gene:
                current_gene = {
                    "Gene": "Unknown",
                    "Accessions": [],
                    "Length": None,
                    "Coverage": {},
                    "InterPro": [],
                    "Hits": [],
                }
            
            # Parse the line
            hit_text = line.replace("- ", "").strip()
            if ": " in hit_text:
                analysis, desc = hit_text.split(": ", 1)
                if analysis == "Accessions":
                    if " (n=" in desc:
                        acc_name = desc.split(" (n=")[0].strip()
                        current_gene["Accessions"] = [acc_name]
                    else:
                        current_gene["Accessions"] = [desc]
                elif analysis == "Length":
                    try:
                        current_gene["Length"] = int(desc)
                    except ValueError:
                        current_gene["Length"] = desc
                elif analysis == "Coverage":
                    try:
                        if " (span " in desc:
                            frac_text = desc.split(" (span ")[0].strip()
                            span_text = desc.split(" (span ")[1].replace(")", "").strip()
                            current_gene["Coverage"] = {
                                "fraction_covered": float(frac_text),
                                "approx_span": [int(x.strip()) for x in span_text.split("–")],
                            }
                        else:
                            current_gene["Coverage"] = {"fraction_covered": float(desc)}
                    except (ValueError, IndexError):
                        current_gene["Coverage"] = {"fraction_covered": desc}
                elif analysis == "InterPro (descriptions)":
                    ipr_items = []
                    for item in desc.split(";"):
                        item = item.strip()
                        if " (n=" in item:
                            desc_text = item.split(" (n=")[0].strip()
                            ipr_items.append({"description": desc_text})
                        else:
                            ipr_items.append({"description": item})
                    current_gene["InterPro"] = ipr_items
                elif analysis == "Pfam (descriptions)":
                    pfam_items = []
                    for item in desc.split(";"):
                        item = item.strip()
                        if " (n=" in item:
                            desc_text = item.split(" (n=")[0].strip()
                            pfam_items.append({"analysis": "Pfam", "description": desc_text})
                        else:
                            pfam_items.append({"analysis": "Pfam", "description": item})
                    current_gene["Hits"].extend(pfam_items)
                else:
                    current_gene["Hits"].append(
                        {"analysis": analysis.strip(), "description": desc.strip()}
                    )

    # Add last gene
    if current_gene:
        genes.append(current_gene)

    return {"genes": genes}


# === MD to JSON converter ===
def _convert_md_to_json(md_path: str) -> dict:
    """
    Convert a REPORT.md file into a structured JSON dict.
    Automatically detects the format and uses the appropriate parser.
    """
    if not os.path.exists(md_path):
        return {}

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        if not lines:
            return {}

        # Detect format based on the first line
        first_line = lines[0].strip()

        if first_line.startswith("# Gene report —") and "| condition=" in first_line:
            # Group gene report: # Gene report — TCF7L2 | condition=Colorectal Cancer | additional=Wnt pathway | organ=Colon | model=organoid
            return _convert_group_gene_report_md_to_json(lines)
        elif first_line.startswith("# Functional-term permutation test report") and "— Gene:" in first_line:
            # Main directory gene report: # Functional-term permutation test report — Gene: TCF7L2
            return _convert_gene_report_md_to_json(lines)
        elif (
            first_line.startswith("# Functional-term permutation test report")
            and "— Gene:" not in first_line
        ):
            return _convert_main_report_md_to_json(lines)
        elif first_line.startswith("# Interpretation —"):
            return _convert_group_report_md_to_json(lines)
        else:
            # Fallback to the original parser for backward compatibility
            return _convert_legacy_report_md_to_json(lines)

    except Exception as e:
        print(f"[WARN] Failed to convert MD to JSON: {e}", file=sys.stderr)
        return {}


def _convert_group_report_md_to_json(lines: list[str]) -> dict:
    """Convert group-level REPORT.md (Interpretation format) to JSON."""
    out: dict = {}

    # Title
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        out["metadata"] = {
            "title": title,
            "type": "group_report"
        }

    # Statistical summary
    s_begin, s_end = _find_section_indices(lines, "Statistical summary")
    if s_begin != -1:
        stat_map = {}
        for i in range(s_begin, s_end + 1):
            ln = lines[i].strip()
            if not ln.startswith("- "):
                continue
            kv = ln[2:].split(":", 1)
            if len(kv) != 2:
                continue
            key = (
                kv[0]
                .strip()
                .lower()
                .replace(" ", "_")
                .replace("(rule-based)", "rule_based")
            )
            val = kv[1].strip()
            # try to coerce numbers
            if key in {"observed_s", "null_mean", "null_sd", "p_right", "effect_size"}:
                try:
                    stat_map[key] = float(val)
                except Exception:
                    stat_map[key] = val
            else:
                stat_map[key] = val
        out["statistics"] = {
            "summary": stat_map,
            "groups": [],  # Group reports do not contain groups
            "per_gene": []  # Group reports do not contain per_gene
        }

    # Terms summarized
    t_begin, t_end = _find_section_indices(lines, "Terms summarized")
    if t_begin != -1:
        terms = {"go": [], "kegg": []}
        for i in range(t_begin, t_end + 1):
            ln = lines[i].strip()
            if ln.startswith("- GO:"):
                content = ln.split(":", 1)[1].strip()
                if content != "(none)":
                    terms["go"] = [x.strip() for x in content.split(",") if x.strip()]
            elif ln.startswith("- KEGG:"):
                content = ln.split(":", 1)[1].strip()
                if content != "(none)":
                    terms["kegg"] = [x.strip() for x in content.split(",") if x.strip()]
        out["ontology"] = {
            "breakdown": [],  # Group reports do not contain breakdown
            "terms": terms
        }

    # Conclusions
    c_begin, c_end = _find_section_indices(lines, "Conclusions")
    if c_begin != -1:
        concl_map: dict = {}
        for i in range(c_begin, c_end + 1):
            ln = lines[i].strip()
            if not ln.startswith("- "):
                continue
            try:
                label, rhs = ln[2:].split(":", 1)
                label = label.strip()
                parts = [p.strip() for p in rhs.split("|")]
                row = {}
                for p in parts:
                    if "=" not in p:
                        key = p.strip().lower().replace(" ", "_")
                        row[key] = True
                        continue
                    k, v = p.split("=", 1)
                    key = k.strip().lower().replace(" ", "_")
                    val = v.strip()
                    if key in {"s", "mu", "effect", "p_right"}:
                        try:
                            row[key] = float(val)
                        except Exception:
                            row[key] = val
                    else:
                        row[key] = val
                concl_map[label] = row
            except Exception:
                continue
        out["evidence"] = {
            "protein": {},  # Group reports do not contain protein evidence
            "conclusions": concl_map
        }

    # LLM interpretation - extract multiple views (combined, GO-only, KEGG-only)
    l_begin, l_end = _find_section_indices(lines, "LLM interpretation")
    if l_begin != -1:
        llm_data = {}

        # Look for different LLM view sections
        view_sections = {
            "combined": "## LLM interpretation",
            "go": "## GO-only LLM interpretation",
            "kegg": "## KEGG-only LLM interpretation",
        }

        for view_name, section_header in view_sections.items():
            view_begin, view_end = _find_section_indices(
                lines, section_header.replace("## ", "")
            )
            if view_begin != -1:
                view_lines = [lines[i] for i in range(view_begin, view_end + 1)]
                view_text = "\n".join(view_lines).strip()
                llm_data[view_name] = {
                    "parsed_output": _parse_llm_output(view_text),
                    "raw_text": view_text,
                }

        # If we found any LLM views, add them to the output
        if llm_data:
            out["llm"] = {
                "main": llm_data,  # Group reports LLM results are in main
                "groups": {}  # Group reports do not contain groups LLM
            }
        else:
            # Fallback to the original logic
            llm_lines = [lines[i] for i in range(l_begin, l_end + 1)]
            llm_text = "\n".join(llm_lines).strip()
            out["llm"] = {
                "main": {
                    "combined": {
                        "parsed_output": _parse_llm_output(llm_text),
                        "raw_text": llm_text,
                    }
                },
                "groups": {}
            }

    # Extract prompt data from LLM views
    for view_name, view_data in out.get("llm", {}).items():
        # Look for prompt sections in <details> tags
        prompt_sections = {
            "combined": "LLM prompt (audit)",
            "go": "Prompt (GO-only)",
            "kegg": "Prompt (KEGG-only)",
        }

        prompt_title = prompt_sections.get(view_name, f"Prompt ({view_name.title()})")

        # Find the <details><summary> tag with the prompt title
        prompt_lines = []
        in_details_block = False
        in_code_block = False
        has_code_block = False

        for i, line in enumerate(lines):
            if f"<details><summary>{prompt_title}</summary>" in line:
                in_details_block = True
                continue
            elif line.strip() == "</details>" and in_details_block:
                break
            elif in_details_block:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    has_code_block = True
                    continue
                if in_code_block:
                    prompt_lines.append(line)
                elif view_name == "combined" and not in_code_block:
                    # For combined prompts, extract content directly without code blocks
                    if i > 0:  # Skip the summary line itself
                        prompt_lines.append(line)
                elif (
                    not has_code_block and line.strip()
                ):  # If no code block, include all non-empty lines
                    prompt_lines.append(line)

        if prompt_lines:
            prompt_text = "\n".join(prompt_lines).strip()
            view_data["parsed_prompt"] = _parse_llm_prompt(prompt_text)
            view_data["raw_prompt"] = prompt_text

    return out


def _convert_gene_report_md_to_json(lines: list[str]) -> dict:
    """Convert gene-level REPORT.md to JSON."""
    out: dict = {}

    # Title
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        out["metadata"] = {
            "title": title,
            "type": "gene_report"
        }
        
        # Extract gene name from title
        if "— Gene:" in title:
            gene_name = title.split("— Gene:")[-1].strip()
            out["metadata"]["gene_name"] = gene_name

    # Statistical summary
    s_begin, s_end = _find_section_indices(lines, "Statistical summary")
    if s_begin != -1:
        stat_map = {}
        for i in range(s_begin, s_end + 1):
            ln = lines[i].strip()
            if not ln.startswith("- "):
                continue
            kv = ln[2:].split(":", 1)
            if len(kv) != 2:
                continue
            key = (
                kv[0]
                .strip()
                .lower()
                .replace(" ", "_")
                .replace("(rule-based)", "rule_based")
            )
            val = kv[1].strip()
            if key in {"observed_s", "null_mean", "null_sd", "p_right", "effect_size"}:
                try:
                    stat_map[key] = float(val)
                except Exception:
                    stat_map[key] = val
            else:
                stat_map[key] = val
        out["statistics"] = {
            "summary": stat_map,
            "groups": [],  # Will be filled later
            "per_gene": []  # Gene reports do not contain per_gene
        }

    # Group Results
    gr_begin, gr_end = _find_section_indices(lines, "Group Results")
    if gr_begin != -1:
        groups = []
        # Find the table header and data rows
        for i in range(gr_begin, gr_end + 1):
            ln = lines[i].strip()
            if ln.startswith("|") and "Condition" in ln and "Additional" in ln:
                # This is the header row, extract column names
                header_cols = [col.strip() for col in ln.split("|")[1:-1]]  # Remove first and last empty elements
                continue
            elif ln.startswith("|") and not ln.startswith("|---"):
                # This is a data row
                data_cols = [col.strip() for col in ln.split("|")[1:-1]]  # Remove first and last empty elements
                if len(data_cols) == len(header_cols):
                    group_data = {}
                    for j, col in enumerate(data_cols):
                        if j < len(header_cols):
                            key = header_cols[j].lower().replace(" ", "_").replace("(", "").replace(")", "")
                            val = col
                            # Try to convert numeric values
                            if key in {"a", "b", "s_obs", "mu", "sd", "effect", "p_right", "p_two"}:
                                try:
                                    group_data[key] = float(val)
                                except ValueError:
                                    group_data[key] = val
                            else:
                                group_data[key] = val
                    groups.append(group_data)
        # Put groups into statistics
        if "statistics" not in out:
            out["statistics"] = {"summary": {}, "groups": [], "per_gene": []}
        out["statistics"]["groups"] = groups

    # Gene info
    g_begin, g_end = _find_section_indices(lines, "Gene")
    if g_begin != -1:
        gene_map = {}
        for i in range(g_begin, g_end + 1):
            ln = lines[i].strip()
            if not ln.startswith("- "):
                continue
            kv = ln[2:].split(":", 1)
            if len(kv) != 2:
                continue
            key = kv[0].strip()
            val = kv[1].strip().strip("`")
            gene_map[key] = val
        # Put gene information into evidence
        if "evidence" not in out:
            out["evidence"] = {"protein": {}, "conclusions": {}}
        out["evidence"]["gene"] = gene_map

    # Ontology Breakdown (GO / KEGG)
    ob_begin, ob_end = _find_section_indices(lines, "Ontology Breakdown (GO / KEGG)")
    if ob_begin != -1:
        ontology_groups = []
        # Find the table header and data rows
        for i in range(ob_begin, ob_end + 1):
            ln = lines[i].strip()
            if ln.startswith("|") and "Condition" in ln and "A_GO" in ln:
                # This is the header row, extract column names
                header_cols = [col.strip() for col in ln.split("|")[1:-1]]  # Remove first and last empty elements
                continue
            elif ln.startswith("|") and not ln.startswith("|---"):
                # This is a data row
                data_cols = [col.strip() for col in ln.split("|")[1:-1]]  # Remove first and last empty elements
                if len(data_cols) == len(header_cols):
                    ontology_data = {}
                    for j, col in enumerate(data_cols):
                        if j < len(header_cols):
                            key = header_cols[j].lower().replace(" ", "_").replace("(", "").replace(")", "")
                            val = col
                            # Try to convert numeric values
                            if key in {"a_go", "b_go", "s_obs_go", "p_right_go", "a_kegg", "b_kegg", "s_obs_kegg", "p_right_kegg"}:
                                try:
                                    ontology_data[key] = float(val)
                                except ValueError:
                                    ontology_data[key] = val
                            else:
                                ontology_data[key] = val
                    ontology_groups.append(ontology_data)
        # Put ontology breakdown into ontology
        if "ontology" not in out:
            out["ontology"] = {"breakdown": [], "terms": {}}
        out["ontology"]["breakdown"] = ontology_groups

    # Terms summarized
    t_begin, t_end = _find_section_indices(lines, "Terms summarized")
    if t_begin != -1:
        terms = {"go": [], "kegg": []}
        for i in range(t_begin, t_end + 1):
            ln = lines[i].strip()
            if ln.startswith("- GO:"):
                content = ln.split(":", 1)[1].strip()
                if content != "(none)":
                    terms["go"] = [x.strip() for x in content.split(",") if x.strip()]
            elif ln.startswith("- KEGG:"):
                content = ln.split(":", 1)[1].strip()
                if content != "(none)":
                    terms["kegg"] = [x.strip() for x in content.split(",") if x.strip()]
        # Put terms into ontology
        if "ontology" not in out:
            out["ontology"] = {"breakdown": [], "terms": {}}
        out["ontology"]["terms"] = terms

    # Conclusions
    c_begin, c_end = _find_section_indices(lines, "Conclusions")
    if c_begin != -1:
        concl_map: dict = {}
        for i in range(c_begin, c_end + 1):
            ln = lines[i].strip()
            if not ln.startswith("- "):
                continue
            try:
                label, rhs = ln[2:].split(":", 1)
                label = label.strip()
                parts = [p.strip() for p in rhs.split("|")]
                row = {}
                for p in parts:
                    if "=" not in p:
                        key = p.strip().lower().replace(" ", "_")
                        row[key] = True
                        continue
                    k, v = p.split("=", 1)
                    key = k.strip().lower().replace(" ", "_")
                    val = v.strip()
                    if key in {"s", "mu", "effect", "p_right"}:
                        try:
                            row[key] = float(val)
                        except Exception:
                            row[key] = val
                    else:
                        row[key] = val
                concl_map[label] = row
            except Exception:
                continue
        # Put conclusions into evidence
        if "evidence" not in out:
            out["evidence"] = {"protein": {}, "conclusions": {}}
        out["evidence"]["conclusions"] = concl_map

    # LLM interpretation - extract per-group LLM results
    # The gene report has nested structure: ## LLM-based Interpretation -> ### Group -> #### Combined/GO-only/KEGG-only
    l_begin, l_end = _find_section_indices(lines, "LLM-based Interpretation")
    if l_begin != -1:
        llm_data = {}
        
        # Find all group sections (### Group Name)
        group_sections = []
        for i in range(l_begin, l_end + 1):
            line = lines[i].strip()
            if line.startswith("### ") and not line.startswith("#### "):
                # This is a group section
                group_name = line[4:].strip()  # Remove "### "
                group_sections.append((group_name, i))
        
        # Process each group
        for group_idx, (group_name, group_start) in enumerate(group_sections):
            # Find the end of this group (next ### or end of LLM section)
            group_end = l_end
            if group_idx + 1 < len(group_sections):
                group_end = group_sections[group_idx + 1][1] - 1
            
            group_llm = {}
            
            # Look for different LLM view sections within this group
            view_sections = {
                "combined": "#### Combined",
                "go": "#### GO-only", 
                "kegg": "#### KEGG-only",
            }
            
            for view_name, section_header in view_sections.items():
                view_begin = -1
                view_end = -1
                
                # Find the section within this group
                for i in range(group_start, group_end + 1):
                    if lines[i].strip().startswith(section_header):
                        view_begin = i
                        # Find the end of this section (next #### or ### or end of group)
                        for j in range(i + 1, group_end + 1):
                            if (
                                lines[j].strip().startswith("####")
                                or lines[j].strip().startswith("###")
                                or lines[j].strip().startswith("##")
                                or lines[j].strip().startswith("<details>")
                            ):
                                view_end = j - 1
                                break
                        if view_end == -1:
                            view_end = group_end
                        break
                
                if view_begin != -1 and view_end != -1:
                    view_lines = [lines[i] for i in range(view_begin, view_end + 1)]
                    view_text = "\n".join(view_lines).strip()
                    group_llm[view_name] = {
                        "parsed_output": _parse_llm_output(view_text),
                        "raw_text": view_text,
                    }
            
            # Add this group's LLM data
            if group_llm:
                llm_data[group_name] = group_llm
        
        # If we found any LLM data, add it to the output
        if llm_data:
            out["llm"] = {
                "main": {},  # Gene reports do not have main LLM
                "groups": llm_data
            }
        else:
            # Fallback to the original logic
            llm_lines = [lines[i] for i in range(l_begin, l_end + 1)]
            llm_text = "\n".join(llm_lines).strip()
            out["llm"] = {
                "main": {},
                "groups": {
                    "combined": {
                        "parsed_output": _parse_llm_output(llm_text),
                        "raw_text": llm_text,
                    }
                }
            }

    return out


def _convert_group_gene_report_md_to_json(lines: list[str]) -> dict:
    """Convert group-level gene REPORT.md to JSON (specialized for group gene reports)."""
    out: dict = {}

    # Title
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        out["metadata"] = {
            "title": title,
            "type": "group_gene_report"
        }

    # Statistical summary
    stat_begin, stat_end = _find_section_indices(lines, "Statistical summary")
    if stat_begin != -1:
        stat_lines = [lines[i] for i in range(stat_begin, stat_end + 1)]
        stat_map = {}
        for ln in stat_lines:
            if ln.strip().startswith("- "):
                kv = ln[2:].split(":", 1)
                if len(kv) == 2:
                    key = kv[0].strip()
                    val = kv[1].strip()
                    # Try to convert to number
                    if val.replace(".", "").replace("-", "").isdigit():
                        try:
                            stat_map[key] = float(val)
                        except ValueError:
                            stat_map[key] = val
                    else:
                        stat_map[key] = val
        out["statistics"] = {
            "summary": stat_map,
            "groups": [],  # Group gene reports do not contain groups
            "per_gene": []  # Group gene reports do not contain per_gene
        }

    # Gene info
    gene_begin, gene_end = _find_section_indices(lines, "Gene")
    if gene_begin != -1:
        gene_lines = [lines[i] for i in range(gene_begin, gene_end + 1)]
        gene_map = {}
        for ln in gene_lines:
            if ln.strip().startswith("- "):
                kv = ln[2:].split(":", 1)
                if len(kv) == 2:
                    key = kv[0].strip()
                    val = kv[1].strip().strip("`")
                    gene_map[key] = val
        out["evidence"] = {
            "protein": {},  # Group gene reports do not contain protein evidence
            "conclusions": {},  # Will be filled later
            "gene": gene_map
        }

    # Terms summarized
    terms_begin, terms_end = _find_section_indices(lines, "Terms summarized")
    if terms_begin != -1:
        terms_lines = [lines[i] for i in range(terms_begin, terms_end + 1)]
        terms_map = {}
        for ln in terms_lines:
            if ln.strip().startswith("- "):
                kv = ln[2:].split(":", 1)
                if len(kv) == 2:
                    key = kv[0].strip()
                    val = kv[1].strip()
                    # Split comma-separated values
                    terms_map[key] = [t.strip() for t in val.split(",")]
        out["ontology"] = {
            "breakdown": [],  # Group gene reports do not contain breakdown
            "terms": terms_map
        }

    # Conclusions
    concl_begin, concl_end = _find_section_indices(lines, "Conclusions")
    if concl_begin != -1:
        concl_lines = [lines[i] for i in range(concl_begin, concl_end + 1)]
        concl_map = {}
        for ln in concl_lines:
            if ln.strip().startswith("- "):
                kv = ln[2:].split(":", 1)
                if len(kv) == 2:
                    label = kv[0].strip()
                    row = kv[1].strip()
                    concl_map[label] = row
        # Put conclusions into evidence
        if "evidence" not in out:
            out["evidence"] = {"protein": {}, "conclusions": {}, "gene": {}}
        out["evidence"]["conclusions"] = concl_map

    # Protein evidence
    protein_begin, protein_end = _find_section_indices(lines, "Protein evidence (summary)")
    if protein_begin != -1:
        protein_lines = [lines[i] for i in range(protein_begin, protein_end + 1)]
        protein_map = {}
        for ln in protein_lines:
            if ln.strip().startswith("- "):
                kv = ln[2:].split(":", 1)
                if len(kv) == 2:
                    key = kv[0].strip()
                    val = kv[1].strip()
                    protein_map[key] = val
        # Put protein evidence into evidence
        if "evidence" not in out:
            out["evidence"] = {"protein": {}, "conclusions": {}, "gene": {}}
        out["evidence"]["protein"] = protein_map

    # LLM interpretation - extract multiple views (combined, GO-only, KEGG-only)
    # The group gene report has direct sections: ## LLM interpretation, ## GO-only LLM interpretation (per gene), ## KEGG-only LLM interpretation (per gene)
    llm_data = {}

    # Look for different LLM view sections
    view_sections = {
        "combined": "## LLM interpretation",
        "go": "## GO-only LLM interpretation (per gene)",
        "kegg": "## KEGG-only LLM interpretation (per gene)",
    }

    for view_name, section_header in view_sections.items():
        # Extract the section name from the header (remove ## prefix)
        section_name = section_header.replace("## ", "")
        view_begin, view_end = _find_section_indices(lines, section_name)
        if view_begin != -1 and view_end != -1:
            view_lines = [lines[i] for i in range(view_begin, view_end + 1)]
            view_text = "\n".join(view_lines).strip()
            
            # Check if the content is just an "unavailable" message
            if "*" in view_text and "unavailable" in view_text.lower():
                # This is an unavailable message, still include it but mark as unavailable
                llm_data[view_name] = {
                    "parsed_output": {"summary": "LLM interpretation unavailable", "confidence": "N/A"},
                    "raw_text": view_text,
                    "unavailable": True,
                }
            else:
                llm_data[view_name] = {
                    "parsed_output": _parse_llm_output(view_text),
                    "raw_text": view_text,
                    "unavailable": False,
                }

    # If we found any LLM views, add them to the output
    if llm_data:
        out["llm"] = {
                "main": llm_data,  # Group gene reports LLM results are in main
                "groups": {}  # Group gene reports do not contain groups LLM
        }

    # LLM prompt data (if available) - merge with existing llm_data
    if "llm" not in out:
        out["llm"] = {}

    # Look for prompt sections in <details> tags
    for i, line in enumerate(lines):
        if "<details><summary>Prompt" in line or "<details><summary>LLM prompt" in line:
            # Extract view name from summary
            if "Prompt (" in line:
                summary_match = line.split("Prompt (")[1].split(")")[0]
                view_name = summary_match.lower().replace(" per gene", "")
            elif "LLM prompt (audit)" in line:
                # This is the combined prompt from _write_report_md
                view_name = "combined"
            else:
                continue

            # Find the end of this details block
            details_end = i
            for j in range(i + 1, len(lines)):
                if "</details>" in lines[j]:
                    details_end = j
                    break

            # Extract prompt content from code block within details
            prompt_lines = []
            in_code_block = False
            for j in range(i, details_end + 1):
                current_line = lines[j].strip()
                if current_line.startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    prompt_lines.append(lines[j])
                elif view_name == "combined" and not in_code_block:
                    # For combined prompts, extract content directly without code blocks
                    if j > i:  # Skip the summary line itself
                        prompt_lines.append(lines[j])

            if prompt_lines:
                prompt_text = "\n".join(prompt_lines).strip()
                
                # Parse the prompt to get structured data including protein_evidence
                parsed_prompt = _parse_llm_prompt(prompt_text)
                
                # Add protein_evidence from the main report if not present in prompt
                if not parsed_prompt.get("protein_evidence") and out.get("protein_evidence"):
                    parsed_prompt["protein_evidence"] = out["protein_evidence"]

                if view_name == "combined":
                    if "combined" not in out["llm"]:
                        out["llm"]["combined"] = {}
                    out["llm"]["combined"]["parsed_prompt"] = parsed_prompt
                    out["llm"]["combined"]["raw_prompt"] = prompt_text
                elif view_name == "go-only":
                    if "go" not in out["llm"]:
                        out["llm"]["go"] = {}
                    out["llm"]["go"]["parsed_prompt"] = parsed_prompt
                    out["llm"]["go"]["raw_prompt"] = prompt_text
                elif view_name == "kegg-only":
                    if "kegg" not in out["llm"]:
                        out["llm"]["kegg"] = {}
                    out["llm"]["kegg"]["parsed_prompt"] = parsed_prompt
                    out["llm"]["kegg"]["raw_prompt"] = prompt_text

    return out


def _convert_main_report_md_to_json(lines: list[str]) -> dict:
    """Convert main REPORT.md to JSON."""
    out: dict = {}

    # Title
    if lines and lines[0].startswith("# "):
        out["title"] = lines[0][2:].strip()

    # Generated timestamp
    for line in lines:
        if line.startswith("**Generated:**"):
            out["generated"] = line.replace("**Generated:**", "").strip()
            break

    # Inputs
    i_begin, i_end = _find_section_indices(lines, "Inputs")
    if i_begin != -1:
        inputs = {}
        for i in range(i_begin, i_end + 1):
            ln = lines[i].strip()
            if not ln.startswith("- "):
                continue
            kv = ln[2:].split(":", 1)
            if len(kv) != 2:
                continue
            key = kv[0].strip()
            val = kv[1].strip()
            inputs[key] = val
        out["inputs"] = inputs

    # LLM-based Interpretation
    llm_begin, llm_end = _find_section_indices(lines, "LLM-based Interpretation")
    if llm_begin != -1:
        out["llm"] = {}

        # Find group-specific LLM sections
        group_sections = {}
        current_group = None
        current_section = None

        for i in range(llm_begin, llm_end + 1):
            line = lines[i].strip()

            # Group header: ### Colorectal Cancer / Wnt pathway / Colon / organoid
            if line.startswith("### ") and "/" in line:
                current_group = line[4:].strip()
                group_sections[current_group] = {}
                continue

            # View header: #### Combined, #### GO-only, #### KEGG-only
            if line.startswith("#### "):
                view_name = line[5:].strip().lower()
                if view_name in ["combined", "go-only", "kegg-only"]:
                    current_section = view_name.replace("-", "_")
                    if current_group and current_section:
                        group_sections[current_group][current_section] = {
                            "text": "",
                            "prompt": "",
                        }
                continue

            # Extract LLM output and prompt
            if (
                current_group
                and current_section
                and group_sections.get(current_group, {}).get(current_section)
            ):
                if line.startswith("**Provider/Model:**"):
                    continue  # Skip provider info
                elif line.startswith("<details><summary>Prompt ("):
                    # Extract prompt
                    prompt_lines = []
                    in_details = True
                    in_code_block = False
                    for j in range(
                        i + 1, min(i + 100, len(lines))
                    ):  # Look ahead for prompt
                        prompt_line = lines[j].strip()
                        if prompt_line == "</details>":
                            break
                        if in_details:
                            if prompt_line.startswith("```"):
                                in_code_block = not in_code_block
                                continue
                            if in_code_block or (not in_code_block and prompt_line):
                                prompt_lines.append(prompt_line)
                    if prompt_lines:
                        group_sections[current_group][current_section]["prompt"] = (
                            "\n".join(prompt_lines)
                        )
                elif line and not line.startswith("<") and not line.startswith("**"):
                    # This is LLM output text
                    if group_sections[current_group][current_section]["text"]:
                        group_sections[current_group][current_section]["text"] += (
                            "\n" + line
                        )
                    else:
                        group_sections[current_group][current_section]["text"] = line

        # Convert to the expected format
        for group_name, group_data in group_sections.items():
            for view_name, view_data in group_data.items():
                if view_data["text"] or view_data["prompt"]:
                    if view_name not in out["llm"]:
                        out["llm"][view_name] = {}
                    out["llm"][view_name] = {
                        "parsed_output": _parse_llm_output(view_data["text"]),
                        "parsed_prompt": _parse_llm_prompt(view_data["prompt"]),
                        "raw_text": view_data["text"],
                        "raw_prompt": view_data["prompt"],
                    }

    return out


def _convert_legacy_report_md_to_json(lines: list[str]) -> dict:
    """Legacy parser for backward compatibility."""

    # This is the original implementation
    def _section_indices(h: str) -> tuple[int, int]:
        start = -1
        end = len(lines)
        for i, ln in enumerate(lines):
            if ln.strip() == f"## {h}":
                start = i
                break
        if start == -1:
            return -1, -1
        for j in range(start + 1, len(lines)):
            if lines[j].startswith("## "):
                end = j - 1
                break
        return start + 1, end

    out: dict = {}

    # Title
    if lines and lines[0].startswith("# "):
        out["title"] = lines[0][2:].strip()

    # Statistical summary
    s_begin, s_end = _section_indices("Statistical summary")
    if s_begin != -1:
        stat_map = {}
        for i in range(s_begin, s_end + 1):
            ln = lines[i].strip()
            if not ln.startswith("- "):
                continue
            kv = ln[2:].split(":", 1)
            if len(kv) != 2:
                continue
            key = (
                kv[0]
                .strip()
                .lower()
                .replace(" ", "_")
                .replace("(rule-based)", "rule_based")
            )
            val = kv[1].strip()
            if key in {"observed_s", "null_mean", "null_sd", "p_right", "effect_size"}:
                try:
                    stat_map[key] = float(val)
                except Exception:
                    stat_map[key] = val
            else:
                stat_map[key] = val
        out["statistical_summary"] = stat_map

    return out


def _find_section_indices(lines: list[str], section_name: str) -> tuple[int, int]:
    """Find start and end indices for a section."""
    start = -1
    end = len(lines) - 1  # Fix: use len(lines) - 1 instead of len(lines)
    for i, ln in enumerate(lines):
        if ln.strip() == f"## {section_name}":
            start = i
            break
    if start == -1:
        return -1, -1
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j - 1
            break
    return start + 1, end


# Write JSON mirror from MD
def _write_report_json_from_md(md_path: str, json_path: str) -> None:
    """Parse md_path with _convert_md_to_json and write to json_path (UTF-8, indent=2)."""
    data = _convert_md_to_json(md_path)

    # For main reports, restructure the data to include main_report field
    # Only do this for actual main reports (not gene reports)
    if "llm" in data and "main_report" not in data and "gene" not in data:
        # This is a main report that needs restructuring
        main_report_data = {
            "llm": data.get("llm", {}),
            "protein_evidence": data.get("protein_evidence", {}),
        }
        data["main_report"] = main_report_data
        # Remove llm and protein_evidence from top level if they exist
        if "llm" in data:
            del data["llm"]
        if "protein_evidence" in data:
            del data["protein_evidence"]

    dirn = os.path.dirname(json_path)
    if dirn:
        os.makedirs(dirn, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --- REPORT.md writer for LLM/fallback explanations ---
def _extract_protein_evidence_from_prompt(prompt: str) -> str:
    """Extract Protein evidence (summary) section from LLM prompt."""
    lines = prompt.split("\n")
    in_protein_evidence = False
    protein_evidence_lines = []

    for line in lines:
        if line.strip() == "**Protein evidence (summary):**":
            in_protein_evidence = True
            continue
        elif in_protein_evidence:
            # Check if this is the start of a new major section (not just a gene header)
            if (
                line.startswith("**")
                and not line.startswith("**Gene:")
                and not line.startswith("**Protein evidence")
            ):
                break
            protein_evidence_lines.append(line)

    if protein_evidence_lines:
        # Remove leading empty lines
        while protein_evidence_lines and not protein_evidence_lines[0].strip():
            protein_evidence_lines.pop(0)
        # Remove trailing empty lines
        while protein_evidence_lines and not protein_evidence_lines[-1].strip():
            protein_evidence_lines.pop()
        # Only return if we have actual content
        if protein_evidence_lines:
            return "\n".join(protein_evidence_lines)

    return "(none)"


def _write_report_md(
    path: str,
    title: str,
    prompt: str,
    llm_text: str,
    dump_prompt: bool,
    group_core: dict,
    go_ids: list[str],
    kegg_ids: list[str],
):
    dirn = os.path.dirname(path)
    if dirn:
        os.makedirs(dirn, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write("## Statistical summary\n\n")
        conf = _confidence_label(group_core.get("p_right"), group_core.get("verdict"))
        f.write(
            "- Statistic: {stat}\n- Observed S: {S}\n- Null mean: {mu}\n- Null SD: {sd}\n- p_right: {p}\n- Effect size: {eff}\n- Verdict: {ver}\n- Confidence (rule-based): {conf}\n".format(
                stat=group_core.get("stat", "NA"),
                S=_fmt5(group_core.get("S_obs")),
                mu=_fmt5(group_core.get("mu")),
                sd=_fmt5(group_core.get("sd")),
                p=_fmt5(group_core.get("p_right")),
                eff=_fmt5(group_core.get("effect_size")),
                ver=str(group_core.get("verdict", "NA")),
                conf=conf,
            )
        )
        # Optional gene metadata block
        gnm = group_core.get("gene_name")
        gsim = group_core.get("similarity_gene_name")
        gid = group_core.get("ENTREZ_ID")
        if any([gnm, gsim, gid]):
            f.write("\n## Gene\n\n")
            if gnm:
                f.write(f"- gene_name: `{gnm}`\n")
            if gsim:
                f.write(f"- similarity_gene_name: `{gsim}`\n")
            if gid:
                f.write(f"- ENTREZ_ID: `{gid}`\n")

        f.write("\n## Terms summarized\n\n")
        gi = ", ".join(go_ids) if go_ids else "(none)"
        ki = ", ".join(kegg_ids) if kegg_ids else "(none)"
        f.write(f"- GO: {gi}\n- KEGG: {ki}\n\n")

        # Conclusions for combined / GO / KEGG with rule-based confidence
        def _row(label: str, S, mu, eff, p, ver) -> str:
            return (
                f"- {label}: S={_fmt5(S)} | mu={_fmt5(mu)} | effect={_fmt5(eff)} | "
                f"p_right={_fmt5(p)} | verdict={ver or 'NA'} | confidence={_confidence_label(p, ver)}\n"
            )

        f.write("## Conclusions\n\n")
        f.write(
            _row(
                "Combined",
                group_core.get("S_obs"),
                group_core.get("mu"),
                group_core.get("effect_size"),
                group_core.get("p_right"),
                group_core.get("verdict"),
            )
        )
        f.write(
            _row(
                "GO-only",
                group_core.get("S_obs_GO"),
                group_core.get("mu_GO"),
                group_core.get("effect_GO"),
                group_core.get("p_right_GO"),
                group_core.get("verdict_GO"),
            )
        )
        f.write(
            _row(
                "KEGG-only",
                group_core.get("S_obs_KEGG"),
                group_core.get("mu_KEGG"),
                group_core.get("effect_KEGG"),
                group_core.get("p_right_KEGG"),
                group_core.get("verdict_KEGG"),
            )
        )
        f.write("\n")

        # Extract Protein evidence (summary) from prompt if available
        if prompt.strip():
            protein_evidence = _extract_protein_evidence_from_prompt(prompt)
            if protein_evidence and protein_evidence != "(none)":
                f.write("## Protein evidence (summary)\n\n")
                f.write(protein_evidence)
                f.write("\n\n")

        if llm_text.strip():
            f.write("## LLM interpretation\n\n")
            f.write(_normalize_llm_text(llm_text))
        else:
            f.write("## LLM interpretation\n\n")
            f.write(
                "(Skipped or unavailable. Provide a valid API key and `--llm-explain` to enable automatic explanations.)\n\n"
            )
        if go_ids or kegg_ids:
            f.write("## Reference links\n\n")
            if go_ids:
                f.write("- GO:\n")
                for tid in go_ids:
                    f.write(f"  - {tid}: {_go_url(tid)}\n")
            if kegg_ids:
                f.write("- KEGG:\n")
                for pid in kegg_ids:
                    f.write(f"  - {pid}: {_kegg_url(pid)}\n")
            f.write("\n")
        if dump_prompt and prompt.strip():
            f.write("<details><summary>LLM prompt (audit)</summary>\n\n")
            f.write("\n\n" + prompt.strip() + "\n\n")
            f.write("</details>\n")

    # --- Auto-create JSON mirror next to the MD report ---
    try:
        _json_path = re.sub(r"\.md$", ".json", path, flags=re.IGNORECASE)
        _write_report_json_from_md(path, _json_path)
    except Exception as _e:
        # Don't fail the run if JSON mirroring has an issue; just log to stderr.
        print(f"[WARN] failed to write JSON mirror for {path}: {_e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Functional enrichment / ensemble scoring: compare gene pathways (A) "
            "against condition backgrounds (B) under universe U.\n\n"
            "B_terms filters use paired metadata fields (condition vs control arms): "
            "organ_condition/organ_control, model_condition/model_control, "
            "source_condition/source_control, time_condition/time_control, "
            "organ_system_* (list), plus category, factor, comparison_*, cell_type. "
            "Deprecated organ_candidates_* are ignored."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Data files (B_terms, U, meta) are not included in the pip wheel.\n"
            "  orbit-ocsp-download-data\n"
            "  export ORBIT_OCSP_DATA=~/.orbit_ocsp/data\n\n"
            "Discover valid B_terms filter values:\n"
            "  orbit-ocsp-list-fields --species hsa --field condition\n"
            "  orbit-ocsp-list-fields --species hsa --condition-tree\n"
            "  orbit-ocsp-list-fields --species hsa --all\n"
            "  orbit-ocsp-ensemble --condition-list --species hsa   # legacy shortcut\n\n"
            "Examples:\n"
            "  orbit-ocsp-ensemble --A A_terms.json --species hsa --stat semantic --semantic-method resnik_bma --additional_condition all --R 10000 --seed 42 --write-clean --alpha 0.05\n\n"
            "  orbit-ocsp-ensemble --A examples/data/genes/a_terms.json --species hsa --condition \"Colorectal Cancer\" "
            "--organ_condition Colon --model_condition Organoid --stat ensemble --outdir out_enrichment\n\n"
            "  orbit-ocsp-ensemble --config examples/config.no_llm.yaml\n"
        ),
    )
    ap.add_argument(
        "--config",
        help="(optional) YAML config file. CLI options override config values.",
    )
    ap.add_argument(
        "--A",
        required=False,
        help="(required unless --condition-list) Path to A_terms file. TXT: one term per line; JSON: list of gene objects with a 'pathway' field.",
    )
    ap.add_argument(
        "--B",
        default=None,
        help=(
            "(optional) Path to B_terms.json (default: data/data_b/B_terms_<species>.json). "
            "Each record uses paired filters: condition, additional_condition, factor, category, "
            "organ_condition/organ_control, model_condition/model_control, "
            "source_condition/source_control, time_condition/time_control, "
            "organ_system_condition/organ_system_control, comparison_*, cell_type, pathway."
        ),
    )
    ap.add_argument(
        "--condition",
        default="",
        help="(optional, default: empty) Filter B_terms by 'condition' (exact, case-insensitive). If empty, include all conditions.",
    )
    ap.add_argument(
        "--additional_condition",
        default="",
        help="(optional, default: empty) Filter by 'additional_condition' (exact, case-insensitive). Use 'all' to merge all additional_condition under the given condition.",
    )
    ap.add_argument(
        "--organ",
        default="",
        help="(optional) Alias for --organ_condition (experimental arm).",
    )
    ap.add_argument(
        "--organ_condition",
        default="",
        help="(optional) Filter B_terms by organ_condition.",
    )
    ap.add_argument(
        "--organ_control",
        default="",
        help="(optional) Filter B_terms by organ_control.",
    )
    ap.add_argument(
        "--organ_system_condition",
        default="",
        help="(optional) Filter B_terms by organ_system_condition (list membership).",
    )
    ap.add_argument(
        "--organ_system_control",
        default="",
        help="(optional) Filter B_terms by organ_system_control (list membership).",
    )
    ap.add_argument(
        "--model",
        default="",
        help="(optional) Alias for --model_condition (experimental arm).",
    )
    ap.add_argument(
        "--model_condition",
        default="",
        help="(optional) Filter B_terms by model_condition.",
    )
    ap.add_argument(
        "--model_control",
        default="",
        help="(optional) Filter B_terms by model_control.",
    )
    ap.add_argument(
        "--category",
        default="",
        help="(optional, default: empty) Filter B_terms by 'category' (exact, case-insensitive).",
    )
    ap.add_argument(
        "--comparison_control",
        default="",
        help="(optional, default: empty) Filter B_terms by 'comparison_control' (exact, case-insensitive).",
    )
    ap.add_argument(
        "--comparison_condition",
        default="",
        help="(optional, default: empty) Filter B_terms by 'comparison_condition' (exact, case-insensitive).",
    )
    ap.add_argument(
        "--cell_type",
        default="",
        help="(optional, default: empty) Filter B_terms by 'cell_type' (exact, case-insensitive).",
    )
    ap.add_argument(
        "--day",
        default="",
        help="(optional) Alias for --time_condition (legacy CLI name).",
    )
    ap.add_argument(
        "--time_condition",
        default="",
        help="(optional) Filter B_terms by time_condition.",
    )
    ap.add_argument(
        "--time_control",
        default="",
        help="(optional) Filter B_terms by time_control.",
    )
    ap.add_argument(
        "--factor",
        default="",
        help="(optional, default: empty) Filter B_terms by 'factor' (exact, case-insensitive).",
    )
    ap.add_argument(
        "--source",
        default="",
        help="(optional) Alias for --source_condition (experimental arm).",
    )
    ap.add_argument(
        "--source_condition",
        default="",
        help="(optional) Filter B_terms by source_condition.",
    )
    ap.add_argument(
        "--source_control",
        default="",
        help="(optional) Filter B_terms by source_control.",
    )
    ap.add_argument(
        "--species",
        required=False,
        choices=["hsa", "mmu"],
        help="(required unless --condition-list) Species selector. Chooses U and KEGG prefix automatically: hsa=human, mmu=mouse.",
    )
    ap.add_argument(
        "--term-size",
        default=None,
        help="(optional, default: None) TSV with two columns: term_id<TAB>gene_count, used for stratified sampling.",
    )
    ap.add_argument(
        "--bins",
        default="0,20,50,100,200,999999",
        help="(optional, default: 0,20,50,100,200,999999) Stratification bin edges for term sizes (used with --term-size).",
    )
    ap.add_argument(
        "--stat",
        choices=["semantic", "hypergeometric", "jaccard", "overlap"],
        default="semantic",
        help="Statistic to use: semantic (GO semantic similarity with IC + KEGG topology-aware analysis), hypergeometric (enrichment test), jaccard (Jaccard coefficient with permutation test), or overlap (overlap count with permutation test).",
    )
    ap.add_argument(
        "--go-ancestors",
        default=None,
        help="(optional) JSON mapping GO term -> list of ancestors (include self). Used when --stat semantic.",
    )
    ap.add_argument(
        "--go-namespace",
        default=None,
        help="(optional) JSON mapping GO term -> namespace (BP/MF/CC). Used for Resnik/Lin+BMA methods.",
    )
    ap.add_argument(
        "--go-structured-stratification",
        action="store_true",
        help="Use GO structured stratification (namespace × depth × size) instead of size-only stratification. Requires --go-ancestors and --go-namespace.",
    )
    ap.add_argument(
        "--go-ic",
        default=None,
        help="(optional) JSON mapping GO term -> information content. Used for Resnik/Lin+BMA methods.",
    )
    ap.add_argument(
        "--semantic-method",
        choices=["closure_jaccard", "resnik_bma", "lin_bma"],
        default="closure_jaccard",
        help="Semantic similarity method when --stat semantic: closure_jaccard (default), resnik_bma (Resnik+BMA), or lin_bma (Lin+BMA).",
    )
    ap.add_argument(
        "--parallel-semantic",
        action="store_true",
        help="Enable parallel computation for semantic similarity calculations (faster but uses more memory).",
    )
    ap.add_argument(
        "--semantic-workers",
        type=int,
        default=None,
        help="Number of parallel workers for semantic calculations (default: auto-detect).",
    )
    ap.add_argument(
        "--fast-mode",
        action="store_true",
        help="Enable fast mode: reduce R to 1000, enable parallel processing, and use optimized algorithms.",
    )
    ap.add_argument(
        "--semantic-kegg-base",
        choices=["jaccard", "overlap"],
        default="jaccard",
        help="Base measure for KEGG when --stat semantic (default: jaccard).",
    )
    ap.add_argument(
        "--kegg-topology-file",
        default=None,
        help="(optional) Path to KEGG topology data JSON file for enhanced similarity calculations. If not provided, auto-selects based on species: data/KEGG_count_topology/{species}_topology.json",
    )
    ap.add_argument(
        "--kegg-topology-method",
        choices=["basic", "topology_weighted", "centrality_weighted", "topology_distance", "hierarchical"],
        default="basic",
        help="KEGG topology enhancement method (default: basic). Auto-enables when topology file is available.",
    )
    ap.add_argument(
        "--R",
        type=int,
        default=5000,
        help="(optional, default: 5000) Number of permutations.",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=42,
        help="(optional, default: 42) Random seed for reproducibility.",
    )
    ap.add_argument(
        "--outdir",
        default="permutation_out",
        help="(optional, default: permutation_out) Output directory. Consolidated files and per-group folders will be created here.",
    )
    ap.add_argument(
        "--write-clean",
        action="store_true",
        help="(optional) Write cleaned A/U and logs to outdir/debug/ for auditing.",
    )
    ap.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        help="(optional, default: 0.05) Significance threshold. Verdict uses right/left-tail with alpha.",
    )
    ap.add_argument(
        "--verdict-rule",
        choices=["right", "left", "two"],
        default="right",
        help="(optional, default: right) Rule to decide verdict: right=use right-tail (enrichment) / left=use left-tail (depletion) / two=two-tailed with effect direction.",
    )
    ap.add_argument(
        "--adjust-scope",
        choices=["per-group", "global"],
        default="per-group",
        help="Scope of multiple-testing adjustment for per-gene p-values (default: per-group). 'per-group' applies within each (condition, additional_condition); 'global' applies across all groups combined.",
    )
    ap.add_argument(
        "--aggregate-q",
        choices=["none", "min", "simes", "stouffer"],
        default="none",
        help="Aggregate an overall q/p value per group from per-gene tests (default: none). When --adjust is BH, aggregate over per-gene q-values; otherwise over per-gene p_right. Methods: min, simes, stouffer.",
    )
    ap.add_argument(
        "--condition-list",
        action="store_true",
        help=(
            "(optional) Print condition values and their additional_condition sets, then exit. "
            "Prefer: orbit-ocsp-list-fields --species hsa --condition-tree"
        ),
    )
    ap.add_argument(
        "--organ-list",
        action="store_true",
        help="(optional) Print all unique organ values found in --B, then exit. When set, other parameters are ignored (A/species are not required).",
    )
    ap.add_argument(
        "--model-list",
        action="store_true",
        help="(optional) Print all unique model values found in --B, then exit. When set, other parameters are ignored (A/species are not required).",
    )
    ap.add_argument(
        "--factor-list",
        action="store_true",
        help="(optional) Print all unique factor values found in --B, then exit. When set, other parameters are ignored (A/species are not required).",
    )
    ap.add_argument(
        "--U",
        "--u",
        dest="U",
        default=None,
        help="(optional) Path to U_terms (universe) JSON file. Overrides species-based default.",
    )
    ap.add_argument(
        "--aggregate-q-report",
        choices=["auto", "both"],
        default="auto",
        help="Reporting mode for aggregated values. 'auto' (default) follows --adjust; 'both' reports both q-based and p-based aggregates.",
    )
    ap.add_argument(
        "--llm-explain",
        action="store_true",
        help="(optional) Use an LLM to generate biological interpretations in REPORT.md.",
    )
    ap.add_argument(
        "--llm-base-url",
        default="https://jeniya.top/v1",
        help="(optional, default: https://jeniya.top/v1) Base URL for LLM API. Supports: 1) OpenAI-compatible (appends /chat/completions), 2) Ollama native (URLs with /api/chat). Examples: https://jeniya.top/v1, http://192.168.20.47:11434/api/chat",
    )
    ap.add_argument(
        "--llm-model",
        default="gpt-4o-mini",
        help="(optional, default: gpt-4o-mini) Model name. Cloud: gpt-5, claude-3-5-sonnet-20241022, gemini-pro-latest, deepseek-v3.2-exp, qwen-max-latest. Local: BioMistral:7B, llama3.1, meditron.",
    )
    ap.add_argument(
        "--llm-max-terms",
        type=int,
        default=8,
        help="(optional, default: 8) Max number of GO/KEGG terms to include per group in the LLM prompt.",
    )
    ap.add_argument(
        "--llm-timeout",
        type=float,
        default=30.0,
        help="(optional, default: 30) Timeout (s) for LLM API calls (best-effort).",
    )
    ap.add_argument(
        "--llm-api-key",
        default=None,
        help="(optional) API key for LLM API. If omitted, falls back to env: LLM_API_KEY or OPENAI_API_KEY.",
    )
    ap.add_argument(
        "--llm-list",
        action="store_true",
        help="(optional) List supported LLM models and usage examples, then exit.",
    )
    ap.add_argument(
        "--per-gene-report",
        action="store_true",
        default=True,
        help="(default: on) Write a per-gene REPORT.md under each group directory (gene_reports/).",
    )
    ap.add_argument(
        "--no-per-gene-report",
        dest="per_gene_report",
        action="store_false",
        help="Disable per-gene report generation.",
    )
    ap.add_argument(
        "--llm-per-gene",
        action="store_true",
        help="(optional) Generate LLM interpretation for each gene report (combine with --per-gene-report).",
    )
    ap.add_argument(
        "--llm-views",
        choices=["all", "combined", "go", "kegg"],
        default="all",
        help="(optional, default: all) Which LLM views to include in reports: all (combined+GO-only+KEGG-only), combined, go, or kegg.",
    )
    # Deprecated flags kept for backward compatibility: map to --llm-views when provided and --llm-views not explicitly set in config/CLI
    ap.add_argument(
        "--llm-go-only",
        action="store_true",
        help="(deprecated) Use --llm-views go or all instead.",
    )
    ap.add_argument(
        "--llm-kegg-only",
        action="store_true",
        help="(deprecated) Use --llm-views kegg or all instead.",
    )
    ap.add_argument(
        "--light-output",
        action="store_true",
        help="(optional) Reduce output footprint by skipping per-group null/intersections and group REPORT (same as --skip-null --skip-intersections --skip-group-report).",
    )
    ap.add_argument(
        "--cache",
        action="store_true",
        default=True,
        help="(optional, default: True) Enable caching for expensive computations.",
    )
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="(optional) Disable caching for expensive computations.",
    )
    ap.add_argument(
        "--clear-cache",
        action="store_true",
        help="(optional) Clear all cached computations before running.",
    )
    ap.add_argument(
        "--skip-null",
        action="store_true",
        help="(optional) Skip per-group null_stats.tsv files.",
    )
    ap.add_argument(
        "--skip-intersections",
        action="store_true",
        help="(optional) Skip per-group intersections.txt files.",
    )
    ap.add_argument(
        "--skip-group-report",
        action="store_true",
        help="(optional) Skip per-group REPORT.md files.",
    )
    ap.add_argument(
        "--skip-group-summary",
        action="store_true",
        help="(optional) Skip per-group summary.tsv files (keep only top-level summaries).",
    )
    # JSON report: enabled by default; use --no-json-report to disable
    ap.add_argument(
        "--json-report",
        dest="json_report",
        action="store_true",
        default=True,
        help="(default: on) Also write JSON report alongside Markdown reports.",
    )
    ap.add_argument(
        "--no-json-report",
        dest="json_report",
        action="store_false",
        help="Disable writing report.json",
    )
    ap.add_argument(
        "--llm-guard",
        action="store_true",
        help="(optional) Only generate LLM for enriched results with q < alpha. Add --llm-guard-confidence or --llm-guard-min-consensus for stricter filtering.",
    )
    ap.add_argument(
        "--llm-guard-confidence",
        type=str,
        default=None,
        choices=["LOW", "MEDIUM", "HIGH"],
        help="(optional) Minimum confidence level for LLM generation (e.g., HIGH for high-confidence results only).",
    )
    ap.add_argument(
        "--llm-guard-min-consensus",
        type=float,
        default=None,
        help="(optional) Minimum consensus score for LLM generation, range 0.0-1.0 (e.g., 0.8 for 80%% agreement).",
    )
    ap.add_argument(
        "--llm-guard-verdict",
        type=str,
        default="enriched",
        choices=["enriched", "depleted", "not_sig", "any"],
        help="(advanced) Change required verdict. Use 'any' to include all verdicts, 'depleted' for depletion analysis. Default: enriched.",
    )
    ap.add_argument(
        "--llm-guard-max-qvalue",
        type=float,
        default=None,
        help="(advanced) Override q-value threshold (default: uses --alpha). Set lower for stricter filtering (e.g., 0.01).",
    )
    ap.add_argument(
        "--llm-dump-prompt",
        action="store_true",
        help="(optional) Dump the LLM prompt into REPORT.md (collapsed details) for auditing.",
    )
    
    # MoE (Mixture of Experts) arguments
    ap.add_argument(
        "--llm-moe",
        action="store_true",
        help="(optional) Enable MoE (Mixture of Experts) mode for LLM analysis. Uses multiple expert models and a reviewer to generate integrated reports. Requires --llm-expert-models and --llm-reviewer-model.",
    )
    ap.add_argument(
        "--llm-expert-models",
        type=str,
        default=None,
        help=(
            "(optional) JSON string or comma-separated model specifications for expert models in MoE mode. "
            'Format: \'[{"model":"gemini-2.5-pro","base_url":"https://jeniya.top/v1","role":"Biomedical Knowledge Expert"}, ...]\' '
            'or simple: "gemini-2.5-pro,grok-4-fast,gpt-oss-120b". '
            "Recommended: 2-3 expert models. See examples/config.moe_recommended.yaml for details."
        ),
    )
    ap.add_argument(
        "--llm-reviewer-model",
        type=str,
        default="gpt-5",
        help="(optional, default: gpt-5) Reviewer model for MoE mode. This model integrates expert outputs into a final report.",
    )
    ap.add_argument(
        "--llm-reviewer-base-url",
        type=str,
        default=None,
        help="(optional) Base URL for reviewer model. If not specified, uses --llm-base-url.",
    )
    ap.add_argument(
        "--llm-moe-parallel",
        action="store_true",
        help="(optional) Call expert models in parallel to reduce execution time in MoE mode.",
    )
    ap.add_argument(
        "--llm-moe-show-experts",
        action="store_true",
        help="(optional) Include individual expert outputs in the final report (in collapsed <details> section).",
    )
    ap.add_argument(
        "--rng-scope",
        choices=["global", "per-group"],
        default="global",
        help="(optional, default: global) RNG scope for permutations. 'global' reuses a single RNG across groups (current behavior). 'per-group' derives a stable seed from (condition, additional_condition, organ, model) so results are reproducible per-group regardless of iteration order.",
    )
    ap.add_argument(
        "--plot-null",
        action="store_true",
        help="(optional) Save a histogram of the null distribution per group with S_obs annotated.",
    )
    ap.add_argument(
        "--bitset",
        choices=["auto", "on", "off"],
        default="auto",
        help="(optional, default: auto) Use bitset backend for overlap/jaccard to speed up permutations. 'auto' enables for non-semantic stats; 'on' forces; 'off' disables.",
    )
    ap.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="(optional, default: 1) Parallel workers for per-gene computations (only used for non-semantic stats).",
    )
    ap.add_argument(
        "--group-jobs",
        type=int,
        default=1,
        help="(optional, default: 1) Parallel workers across groups for overall statistics and per-group outputs.",
    )
    ap.add_argument(
        "--use-gpu",
        action="store_true",
        help="Enable GPU acceleration for permutation calculations (requires CuPy).",
    )
    ap.add_argument(
        "--acceleration-mode",
        choices=["auto", "cpu", "gpu", "memory_efficient"],
        default="auto",
        help="Acceleration mode: auto (choose best), cpu (CPU only), gpu (GPU if available), memory_efficient (for large datasets).",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="(optional, default: 1000) Batch size for parallel processing of permutations.",
    )
    ap.add_argument(
        "--memory-limit",
        type=float,
        default=8.0,
        help="(optional, default: 8.0) Memory limit in GB for batch processing.",
    )

    # Optional InterPro evidence injection for per-gene LLM prompts
    ap.add_argument(
        "--evidence-dir",
        default=None,
        help="(optional) Directory with <gene>.evidence.json files to enrich per-gene LLM prompts (Protein evidence block).",
    )
    ap.add_argument(
        "--evidence-max-interpro",
        type=int,
        default=0,
        help="Max InterPro entries to list in evidence block (0=all; default: 0).",
    )
    ap.add_argument(
        "--evidence-max-hits-per-db",
        type=int,
        default=2,
        help="Max domain hits per analysis DB to list (default: 2).",
    )
    ap.add_argument(
        "--evidence-max-pathways",
        type=int,
        default=5,
        help="Max raw pathways (Reactome/MetaCyc) to list (default: 5).",
    )
    ap.add_argument(
        "--evidence-analyses",
        default="Pfam,CDD,NCBIfam,PANTHER,Gene3D,ProSitePatterns,ProSiteProfiles,SUPERFAMILY",
        help="Comma-separated analysis DBs to include (default: common high-quality libraries).",
    )
    ap.add_argument(
        "--evidence-db-summarize",
        action="store_true",
        help="Summarize per-DB domain hits by description counts instead of listing individual hits.",
    )
    ap.add_argument(
        "--evidence-max-desc-per-db",
        type=int,
        default=5,
        help="Max distinct descriptions per DB to include when summarizing (default: 5).",
    )

    # Optional: run InterPro aggregate+merge before analysis
    ap.add_argument(
        "--interpro-file",
        default=None,
        help="(optional) Single InterProScan TSV file (combined results). Merges GO into --A before analysis and writes go/evidence JSONs.",
    )
    ap.add_argument(
        "--interpro-dir",
        default=None,
        help="(optional) Directory containing InterProScan TSV files; merges GO into --A before analysis and writes go/evidence JSONs.",
    )
    ap.add_argument(
        "--interpro-out-dir",
        default=None,
        help="(optional) Output directory for InterPro go/evidence JSONs (default: <outdir>/interpro).",
    )
    ap.add_argument(
        "--interpro-keep-untrusted",
        action="store_true",
        help="(optional) Keep rows with Status != T when parsing InterPro TSVs.",
    )
    ap.add_argument(
        "--interpro-max-evalue",
        type=float,
        default=None,
        help="(optional) Drop InterPro hits with Score (e-value) greater than this value during pre-processing.",
    )
    ap.add_argument(
        "--interpro-min-domain-len",
        type=int,
        default=None,
        help="(optional) Drop InterPro hits with (stop-start+1) shorter than this length during pre-processing.",
    )
    ap.add_argument(
        "--interpro-analyses",
        default=None,
        help="(optional) Comma-separated Analysis DB names to include during pre-processing (e.g., Pfam,CDD).",
    )
    ap.add_argument(
        "--interpro-id-column",
        default="Query",
        help="(optional) Column to group combined TSV by (default: Query).",
    )
    ap.add_argument(
        "--interpro-id-map",
        default=None,
        help="(optional) JSON mapping from id (e.g., Protein_Accession) to gene_name for merging.",
    )
    ap.add_argument(
        "--interpro-tsv-has-header",
        action="store_true",
        help="(optional) Treat InterPro TSV as having a header line (override heuristic).",
    )
    ap.add_argument(
        "--interpro-tsv-no-header",
        action="store_true",
        help="(optional) Treat InterPro TSV as headerless; use expected InterPro header internally.",
    )

    ap.add_argument(
        "--go-meta",
        default=None,
        help="Path to GO metadata JSON (built via build_go_meta.py). Defaults to data/meta/go_meta.json if omitted.",
    )
    ap.add_argument(
        "--kegg-meta",
        default=None,
        help="Path to KEGG metadata JSON (species-specific). Defaults to data/meta/kegg_meta_<species>.json if omitted.",
    )
    
    # Ensemble analysis parameters
    ap.add_argument(
        "--ensemble",
        action="store_true",
        default=True,  # Enable ensemble by default
        help="Enable ensemble analysis mode (multi-method validation with confidence grading). Default: True. Use --no-ensemble to disable.",
    )
    ap.add_argument(
        "--no-ensemble",
        action="store_false",
        dest="ensemble",
        help="Disable ensemble analysis mode (use single method analysis instead).",
    )
    ap.add_argument(
        "--ensemble-level",
        choices=["gene", "group", "total", "all"],
        default="gene",
        help="Ensemble analysis level: 'gene' (default, per-gene only), 'group' (per-group only), 'total' (total-level only), 'all' (all levels).",
    )
    ap.add_argument(
        "--ensemble-methods",
        nargs='+',
        default=None,
        help="List of methods for ensemble analysis (default: hypergeometric jaccard overlap resnik_bma lin_bma). Available: hypergeometric, jaccard, overlap, resnik_bma, lin_bma, semantic_jaccard.",
    )
    ap.add_argument(
        "--ensemble-strategy",
        choices=["voting", "weighted", "p_value", "effect_size"],
        default="voting",
        help="Ensemble combination strategy: voting (simple majority), weighted (weighted voting), p_value (combine p-values), effect_size (combine effect sizes).",
    )
    ap.add_argument(
        "--ensemble-parallel",
        action="store_true",
        default=True,
        help="Run ensemble methods in parallel (default: True).",
    )
    ap.add_argument(
        "--ensemble-max-workers",
        type=int,
        default=4,
        help="Maximum number of parallel workers for ensemble analysis (default: 4).",
    )
    ap.add_argument(
        "--ensemble-r-hypergeometric",
        type=int,
        default=1000,
        help="Number of permutations for hypergeometric method in ensemble (default: 1000).",
    )
    ap.add_argument(
        "--ensemble-r-jaccard",
        type=int,
        default=1000,
        help="Number of permutations for jaccard method in ensemble (default: 1000).",
    )
    ap.add_argument(
        "--ensemble-r-overlap",
        type=int,
        default=1000,
        help="Number of permutations for overlap method in ensemble (default: 1000).",
    )
    ap.add_argument(
        "--ensemble-r-semantic",
        type=int,
        default=50,
        help="Number of permutations for semantic methods (resnik_bma, lin_bma) in ensemble (default: 50).",
    )
    ap.add_argument(
        "--ensemble-trained-weights",
        type=str,
        default=None,
        help="Path to trained weights file (.json or .pkl) to use instead of static weights. Use 'orbit-ocsp-train-weights' command to train weights.",
    )
    
    _defaults = ap.parse_args([])
    args = ap.parse_args()

    # Merge YAML config -> only fill values still equal to defaults (CLI has priority)
    if args.config:
        if not os.path.exists(args.config):
            raise FileNotFoundError(f"Config file not found: {args.config}")
        with open(args.config, "r", encoding="utf-8") as cf:
            cfg = yaml.safe_load(cf) or {}
        if not isinstance(cfg, dict):
            raise ValueError("Config must be a YAML mapping of options to values")
        for k, v in cfg.items():
            # Convert YAML key from hyphen to underscore format
            python_key = k.replace('-', '_')
            if hasattr(args, python_key):
                # For required parameters (A, species), always use YAML value if provided
                if python_key in ['A', 'species'] and v is not None:
                    setattr(args, python_key, v)
                # For other parameters, only override if CLI value equals default
                elif getattr(args, python_key) == getattr(_defaults, python_key):
                    setattr(args, python_key, v)
                    if python_key == 'go_structured_stratification':
                        print(f"[INFO] GO structured stratification enabled via YAML config")

    from orbit_ocsp.data_manager import ensure_data_available

    listing_mode = (
        args.condition_list
        or args.organ_list
        or args.model_list
        or args.factor_list
    )
    if not listing_mode:
        species_for_data = getattr(args, "species", None) or "hsa"
        try:
            ensure_data_available(species_for_data)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

    # Load trained weights if provided
    if args.ensemble_trained_weights:
        _load_trained_weights(args.ensemble_trained_weights)

    # Process MoE configuration
    if args.llm_moe:
        # Parse expert models
        if args.llm_expert_models:
            expert_models_input = args.llm_expert_models
            
            # Check if already parsed (from YAML config)
            if isinstance(expert_models_input, list):
                args.llm_expert_models_parsed = expert_models_input
            elif isinstance(expert_models_input, str):
                # Try to parse as JSON first
                try:
                    expert_models_data = json.loads(expert_models_input)
                    if isinstance(expert_models_data, list):
                        args.llm_expert_models_parsed = expert_models_data
                    else:
                        print("Error: --llm-expert-models must be a JSON array", file=sys.stderr)
                        sys.exit(1)
                except json.JSONDecodeError:
                    # Fall back to simple comma-separated format
                    model_names = [m.strip() for m in expert_models_input.split(',') if m.strip()]
                    if not model_names:
                        print("Error: --llm-expert-models is empty", file=sys.stderr)
                        sys.exit(1)
                    
                    # Create default expert configurations
                    default_roles = [
                        "Biomedical Knowledge Expert",
                        "Rapid Reasoning Expert", 
                        "Comprehensive Analysis Expert"
                    ]
                    args.llm_expert_models_parsed = []
                    for i, model_name in enumerate(model_names):
                        args.llm_expert_models_parsed.append({
                            "model": model_name,
                            "base_url": args.llm_base_url,
                            "role": default_roles[i] if i < len(default_roles) else f"Expert {i+1}"
                        })
            else:
                print("Error: --llm-expert-models must be a list or string", file=sys.stderr)
                sys.exit(1)
        else:
            # Use default recommended expert models
            args.llm_expert_models_parsed = [
                {
                    "model": "gemini-2.5-pro",
                    "base_url": args.llm_base_url,
                    "role": "Biomedical Knowledge Expert"
                },
                {
                    "model": "grok-4-fast",
                    "base_url": args.llm_base_url,
                    "role": "Rapid Reasoning Expert"
                },
                {
                    "model": "gpt-oss-120b",
                    "base_url": args.llm_base_url,
                    "role": "Comprehensive Analysis Expert"
                }
            ]
            print("[INFO] MoE enabled with default expert models: gemini-2.5-pro, grok-4-fast, gpt-oss-120b")
        
        # Set reviewer base URL if not specified
        if not args.llm_reviewer_base_url:
            args.llm_reviewer_base_url = args.llm_base_url
        
        # Validate MoE configuration
        if len(args.llm_expert_models_parsed) < 2:
            print("Error: MoE mode requires at least 2 expert models", file=sys.stderr)
            sys.exit(1)
        
        if not args.llm_reviewer_model:
            print("Error: --llm-reviewer-model is required for MoE mode", file=sys.stderr)
            sys.exit(1)
    else:
        args.llm_expert_models_parsed = []

    # Validate parameters
    validation_errors = _validate_parameters(args)
    if validation_errors:
        print("Parameter validation errors:", file=sys.stderr)
        for error in validation_errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    # Load KEGG topology data if specified or auto-select based on species
    topology_analyzer = None
    if args.kegg_topology_method != "basic" and TOPOLOGY_AVAILABLE:
        # Auto-select topology file based on species if not provided
        if not args.kegg_topology_file:
            if args.species:
                species = args.species.lower()
                auto_topology_file = f"data/KEGG_count_topology/{species}_topology.json"
                args.kegg_topology_file = auto_topology_file
                print(f"Auto-selecting KEGG topology file: {auto_topology_file}")
            else:
                print("Warning: Cannot auto-select KEGG topology file without species. Using basic methods.", file=sys.stderr)
        
        if args.kegg_topology_file:
            try:
                topology_file = _resolve_default(args.kegg_topology_file)
                if not os.path.exists(topology_file):
                    print(f"Warning: KEGG topology file not found: {topology_file}. Using basic methods.", file=sys.stderr)
                else:
                    topology_analyzer = load_topology_data(topology_file)
                    print(f"Loaded KEGG topology data from: {topology_file}")
            except Exception as e:
                print(f"Warning: Failed to load KEGG topology data: {e}. Using basic methods.", file=sys.stderr)
    elif args.kegg_topology_method != "basic" and not TOPOLOGY_AVAILABLE:
        print("Warning: Topology enhancement module not available. Falling back to basic KEGG methods.", file=sys.stderr)

    # Initialize parallel acceleration
    accelerator = None
    if PARALLEL_ACCELERATION_AVAILABLE and args.R > 100:
        try:
            # Determine acceleration mode
            if args.acceleration_mode == "auto":
                use_gpu = args.use_gpu and args.R > 1000
                max_workers = estimate_optimal_workers(len(U), args.R, args.memory_limit)
            elif args.acceleration_mode == "gpu":
                use_gpu = True
                max_workers = None
            elif args.acceleration_mode == "memory_efficient":
                use_gpu = False
                max_workers = 1
            else:  # cpu
                use_gpu = False
                max_workers = args.jobs if args.jobs > 1 else None
            
            accelerator = create_accelerator(
                use_gpu=use_gpu,
                max_workers=max_workers,
                memory_limit_gb=args.memory_limit
            )
            print(f"Parallel acceleration enabled: {args.acceleration_mode} mode, "
                  f"GPU: {accelerator.use_gpu}, Workers: {accelerator.max_workers}")
        except Exception as e:
            print(f"Warning: Failed to initialize parallel acceleration: {e}. Using sequential processing.", file=sys.stderr)
    else:
        print("Parallel acceleration not available or R too small. Using sequential processing.")

    # Map deprecated flags to --llm-views if user did not explicitly set llm_views
    # Priority: explicit --llm-views > deprecated flags
    if getattr(args, "llm_views", None) == getattr(_defaults, "llm_views", "all"):
        if args.llm_go_only and args.llm_kegg_only:
            args.llm_views = "all"
        elif args.llm_go_only:
            args.llm_views = "go"
        elif args.llm_kegg_only:
            args.llm_views = "kegg"

    # If listing values from B_terms.json, do it and exit
    if args.condition_list or args.organ_list or args.model_list or args.factor_list:
        # Resolve B path robustly when species is unknown in listing mode
        if args.B:
            b_path = _resolve_default(args.B)
            if not os.path.exists(b_path):
                raise FileNotFoundError(
                    f"B_terms.json not found at: {b_path}. You can override with --B <path>."
                )
        else:
            # Try species defaults inside packaged/installed data tree
            cand_hsa = _resolve_default("data/data_b/B_terms_hsa.json")
            cand_mmu = _resolve_default("data/data_b/B_terms_mmu.json")
            if os.path.exists(cand_hsa):
                b_path = cand_hsa
            elif os.path.exists(cand_mmu):
                b_path = cand_mmu
            else:
                raise FileNotFoundError(
                    "Default B_terms files not found. Run: orbit-ocsp-download-data"
                )
        with open(b_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            raise ValueError("B_terms.json must be a JSON array or single object.")

        if args.condition_list:
            cond_to_adds: dict[str, set[str]] = {}
            for obj in items:
                if not isinstance(obj, dict):
                    continue
                cond = str(obj.get("condition", "") or "").strip()
                addc = str(obj.get("additional_condition", "") or "").strip()
                if cond not in cond_to_adds:
                    cond_to_adds[cond] = set()
                cond_to_adds[cond].add(addc)

            print("B_terms conditions and additional_condition values:\n")
            for cond in sorted(cond_to_adds.keys(), key=lambda x: (x == "", x.lower())):
                adds = sorted(cond_to_adds[cond], key=lambda x: (x == "", x.lower()))
                adds_str = ", ".join(adds) if adds else "(none)"
                print(
                    f"- {cond if cond else '(empty condition)'}:\n    additional_condition: {adds_str}"
                )
            print("")

        if args.organ_list:
            organs: set[str] = set()
            for obj in items:
                if not isinstance(obj, dict):
                    continue
                organs.add(b_get(obj, "organ").strip())
            print("B_terms unique organ values (organ_condition):\n")
            for o in sorted(organs, key=lambda x: (x == "", x.lower())):
                print(f"- {o if o else '(empty organ)'}")
            print("")

        if args.model_list:
            models: set[str] = set()
            for obj in items:
                if not isinstance(obj, dict):
                    continue
                models.add(b_get(obj, "model").strip())
            print("B_terms unique model values (model_condition):\n")
            for m in sorted(models, key=lambda x: (x == "", x.lower())):
                print(f"- {m if m else '(empty model)'}")
            print("")

        if args.factor_list:
            factors = set()
            for obj in items:
                if not isinstance(obj, dict):
                    continue
                factors.add(str(obj.get("factor", "") or "").strip())
            print("B_terms unique factor values:\n")
            for f in sorted(factors, key=lambda x: (x == "", x.lower())):
                print(f"- {f if f else '(empty factor)'}")
            print("")

        sys.exit(0)

    # Validate required args for analysis mode
    if not (args.condition_list or args.organ_list or args.model_list or args.factor_list or args.llm_list):
        if not args.A:
            ap.error(
                "--A is required unless one of --condition-list/--organ-list/--model-list/--factor-list/--llm-list is set."
            )
        if not args.species:
            ap.error(
                "--species is required unless one of --condition-list/--organ-list/--model-list/--factor-list/--llm-list is set."
            )

    # List available LLM models and exit
    if args.llm_list:
        print("Supported LLM Models")
        print("=" * 70)
        print(f"\nDefault Base URL: {args.llm_base_url}")
        print(f"Default Model: {args.llm_model}")
        print(f"\nEnvironment Variable: LLM_API_KEY or OPENAI_API_KEY\n")
        
        print("=" * 70)
        print("CLOUD API MODELS (via Unified Gateway)")
        print("=" * 70)
        
        print("\nOpenAI Models:")
        print("  - gpt-5                       (Latest GPT-5, most advanced)")
        print("  - gpt-4o                      (Most capable, multimodal)")
        print("  - gpt-4o-mini                 (Fast and efficient, recommended default)")
        print("  - gpt-3.5-turbo               (Legacy, cost-effective)")
        
        print("\nAnthropic Claude Models:")
        print("  - claude-3-5-sonnet-20241022  (Best for complex reasoning)")
        print("  - claude-3-5-haiku-20241022   (Fast, good balance)")
        
        print("\nGoogle Gemini Models:")
        print("  - gemini-pro-latest           (Latest Gemini Pro)")
        print("  - gemini-2.0-flash-exp        (Fast, experimental)")
        print("  - gemini-1.5-pro              (Production ready)")
        print("  - gemini-1.5-flash            (Quick responses)")
        
        print("\nDeepSeek Models:")
        print("  - deepseek-v3.2-exp           (Latest DeepSeek v3.2 experimental)")
        print("  - deepseek-chat               (General purpose)")
        print("  - deepseek-coder              (Code-focused)")
        
        print("\nAlibaba Qwen Models:")
        print("  - qwen-max-latest             (Latest Qwen Max)")
        print("  - qwen-max                    (Advanced Qwen)")
        print("  - qwen-plus                   (Balanced performance)")
        
        print("\n" + "=" * 70)
        print("LOCAL MODELS (Ollama or Custom Server)")
        print("=" * 70)
        print("\nBiomedical Models:")
        print("  - BioMistral:7B               (Specialized for biomedical text)")
        print("  - meditron                    (Medical domain model)")
        
        print("\nGeneral Purpose Models:")
        print("  - llama3.1                    (Meta's Llama 3.1)")
        print("  - qwen2.5:7b-instruct         (Qwen 2.5 local)")
        print("  - mistral                     (Mistral AI)")
        print("  - phi3:mini                   (Microsoft Phi-3)")
        
        print("\n" + "=" * 70)
        print("USAGE EXAMPLES")
        print("=" * 70)
        
        print("\n1. Cloud API (Unified Gateway):")
        print("   orbit-ocsp-ensemble --A examples/data/genes/a_terms.json --species hsa \\")
        print("     --condition \"Colorectal Cancer\" --stat resnik_bma \\")
        print("     --llm-explain --llm-model gpt-4o-mini \\")
        print("     --llm-api-key your-api-key")
        
        print("\n2. Local Ollama (Native API):")
        print("   orbit-ocsp-ensemble --A examples/data/genes/a_terms.json --species hsa \\")
        print("     --condition \"Colorectal Cancer\" --stat resnik_bma \\")
        print("     --llm-explain \\")
        print("     --llm-base-url http://192.168.20.47:11434/api/chat \\")
        print("     --llm-model BioMistral:7B")
        
        print("\n3. Local Ollama (OpenAI-compatible):")
        print("   orbit-ocsp-ensemble --A examples/data/genes/a_terms.json --species hsa \\")
        print("     --condition \"Colorectal Cancer\" --stat resnik_bma \\")
        print("     --llm-explain \\")
        print("     --llm-base-url http://localhost:11434/v1 \\")
        print("     --llm-model llama3.1")
        
        print("\n" + "=" * 70)
        print("CONFIGURATION")
        print("=" * 70)
        print("  - API auto-detection: URLs with '/api/chat' use Ollama native API")
        print("  - OpenAI-compatible: All other URLs append '/chat/completions'")
        print("  - Local models: No API key required for Ollama native endpoints")
        print("  - Use --llm-dump-prompt to include full prompt in reports")
        print("  - See examples/config.ollama.yaml for local model configuration")
        return

    # Optional pre-processing: parse InterPro TSV(s) and merge GO into A_terms
    if getattr(args, "interpro_file", None) or getattr(args, "interpro_dir", None):
        tsv_files: list[str] = []
        if getattr(args, "interpro_file", None):
            tsv_files = [_resolve_default(args.interpro_file)]
        elif getattr(args, "interpro_dir", None):
            interpro_dir = _resolve_default(args.interpro_dir)
            if not os.path.isdir(interpro_dir):
                print(
                    f"[WARN] --interpro-dir not found or not a directory: {interpro_dir}",
                    file=sys.stderr,
                )
            else:
                try:
                    for fn in os.listdir(interpro_dir):
                        if fn.lower().endswith(".tsv"):
                            tsv_files.append(os.path.join(interpro_dir, fn))
                except Exception as e:
                    print(f"[WARN] Failed to list {interpro_dir}: {e}", file=sys.stderr)
                    tsv_files = []
        if not tsv_files:
            print("[WARN] No InterPro TSV files found to preprocess.", file=sys.stderr)
        else:
            interpro_out = args.interpro_out_dir or os.path.join(
                args.outdir, "interpro"
            )
            agg_script = os.path.join(
                _PKG_ROOT, "scripts", "interpro_aggregate_and_merge.py"
            )
            cmd = [
                "python3",
                agg_script,
                "--tsv",
                *tsv_files,
                "--a-terms",
                args.A,
                "--out-dir",
                interpro_out,
                "--out",  # Use --out instead of --in-place to avoid modifying A_terms.json
                os.path.join(interpro_out, "A_terms_with_interpro.json"),  # Write to separate file
            ]
            if args.interpro_max_evalue is not None:
                cmd.extend(["--max-evalue", str(args.interpro_max_evalue)])
            if args.interpro_min_domain_len is not None:
                cmd.extend(["--min-domain-len", str(args.interpro_min_domain_len)])
            if args.interpro_keep_untrusted:
                cmd.append("--keep-untrusted")
            if args.interpro_analyses:
                cmd.extend(["--analyses", str(args.interpro_analyses)])
            if getattr(args, "interpro_file", None):
                cmd.extend(
                    [
                        "--group-by-column",
                        str(getattr(args, "interpro_id_column", "Protein_Accession")),
                    ]
                )
                if getattr(args, "interpro_id_map", None):
                    cmd.extend(["--id-to-gene-map", str(args.interpro_id_map)])
            # TSV header overrides
            if getattr(args, "interpro_tsv_has_header", False):
                cmd.append("--tsv-has-header")
            if getattr(args, "interpro_tsv_no_header", False):
                cmd.append("--tsv-no-header")
            print(
                f"[{_now()}] Preprocessing InterPro TSVs (n={len(tsv_files)}) -> merging GO into A_terms",
                flush=True,
            )
            try:
                subprocess.run(cmd, check=True)
            except Exception as e:
                print(f"[WARN] InterPro pre-processing failed: {e}", file=sys.stderr)
            if not args.evidence_dir:
                args.evidence_dir = interpro_out

    # Resolve U file and KEGG allowed prefixes
    species = args.species.lower()
    if args.U:
        # User-provided universe file takes precedence
        U_path = _resolve_default(args.U)
        allowed_kegg = (species, "map", "ko")
    else:
        u_lookup = {
            "hsa": _resolve_default("data/data_u/U_terms_GO_KEGG_hsa.json"),
            "mmu": _resolve_default("data/data_u/U_terms_GO_KEGG_mmu.json"),
        }
        if species not in u_lookup:
            raise ValueError(f"Unsupported species: {species}")
        U_path = u_lookup[species]
        allowed_kegg = (species, "map", "ko")
    log_dir = os.path.join(args.outdir, "debug") if args.write_clean else None

    # Select B_terms file based on species unless user provided --B
    if args.B is None:
        # Default B: pick by species
        if species == "hsa":
            args.B = _resolve_default("data/data_b/B_terms_hsa.json")
        elif species == "mmu":
            args.B = _resolve_default("data/data_b/B_terms_mmu.json")
        else:
            args.B = _resolve_default("data/data_b/B_terms.json")
    else:
        args.B = _resolve_default(args.B)
    if not os.path.exists(args.B):
        raise FileNotFoundError(
            f"B_terms.json not found at: {args.B}. You can override with --B <path>."
        )

    # If --go-ancestors is not provided, set to default
    if not args.go_ancestors:
        args.go_ancestors = _resolve_default("data/DAG/go_ancestors.json")
    
    # If --go-namespace is not provided, set to default
    if not args.go_namespace:
        args.go_namespace = _resolve_default("data/DAG/go_namespace.json")
    
    # If --go-ic is not provided, set to default based on species
    if not args.go_ic:
        ic_file = "data/IC/go_ic_hsa.json" if args.species == "hsa" else "data/IC/go_ic_mmu.json"
        args.go_ic = _resolve_default(ic_file)
    
    # If --term-size is not provided, set to default based on species
    if not args.term_size:
        term_size_file = "data/annotations/term_size_human.tsv" if args.species == "hsa" else "data/annotations/term_size_mouse.tsv"
        args.term_size = _resolve_default(term_size_file)

    # Update cached GO resource locations for semantic calculations
    _configure_go_resources(args.go_ancestors, args.go_ic, args.go_namespace)
    
    # Apply fast mode optimizations
    if args.fast_mode:
        if args.R > 1000:
            print(f"[INFO] Fast mode: reducing R from {args.R} to 1000")
            args.R = 1000
        if not args.parallel_semantic:
            print("[INFO] Fast mode: enabling parallel semantic processing")
            args.parallel_semantic = True
        if args.semantic_workers is None:
            args.semantic_workers = min(4, cpu_count())
            print(f"[INFO] Fast mode: setting semantic workers to {args.semantic_workers}")

    if args.go_meta:
        args.go_meta = _resolve_default(args.go_meta)
    else:
        args.go_meta = _resolve_default("data/meta/go_meta.json")
    if not args.kegg_meta:
        args.kegg_meta = _resolve_default(f"data/meta/kegg_meta_{species}.json")
    else:
        args.kegg_meta = _resolve_default(args.kegg_meta)
    go_meta = _load_json_safe(args.go_meta)
    kegg_meta = _load_json_safe(args.kegg_meta)

    os.makedirs(args.outdir, exist_ok=True)

    try:
        print(f"[{_now()}] Starting permutation analysis", flush=True)
        print(f"  Input: {args.A} | Species: {species} | Stat: {args.stat} | R: {args.R}", flush=True)
        
        # Configure caching
        global _cache_enabled
        if args.clear_cache:
            clear_cache()
            print(f"[{_now()}] Cache cleared")
        if args.no_cache:
            _cache_enabled = False
            print(f"[{_now()}] Caching disabled")
        elif args.cache:
            _cache_enabled = True
            print(f"[{_now()}] Caching enabled")
        
        # Start timing
        start_time = time.time()

        # Read inputs
        A, A_dropped, A_dupes, A_per_gene_raw = read_A_terms_auto(
            args.A, allowed_kegg=allowed_kegg, log_dir=log_dir
        )
        U = read_u_json(U_path, allowed_kegg=allowed_kegg, log_dir=log_dir)
        groups, group_metadata = build_B_groups_from_json(
            args.B,
            cond_filter=args.condition,
            add_cond_filter=args.additional_condition,
            organ_filter=args.organ,
            model_filter=args.model,
            category_filter=args.category,
            cmp_ctrl_filter=args.comparison_control,
            cmp_cond_filter=args.comparison_condition,
            cell_type_filter=args.cell_type,
            day_filter=args.day,
            factor_filter=args.factor,
            source_filter=args.source,
            organ_condition_filter=getattr(args, "organ_condition", "") or "",
            organ_control_filter=getattr(args, "organ_control", "") or "",
            organ_system_condition_filter=getattr(args, "organ_system_condition", "") or "",
            organ_system_control_filter=getattr(args, "organ_system_control", "") or "",
            model_condition_filter=getattr(args, "model_condition", "") or "",
            model_control_filter=getattr(args, "model_control", "") or "",
            source_condition_filter=getattr(args, "source_condition", "") or "",
            source_control_filter=getattr(args, "source_control", "") or "",
            time_condition_filter=getattr(args, "time_condition", "") or "",
            time_control_filter=getattr(args, "time_control", "") or "",
            allowed_kegg=allowed_kegg,
            log_dir=log_dir,
        )

        print(f"[{_now()}] Loaded: A={len(A)}, U={len(U)}, Groups={len(groups)}")
        if len(A_dropped) > 0 or len(A_dupes) > 0:
            print(f"  Filtered: {len(A_dropped)} dropped, {len(A_dupes)} duplicates removed")
        
        # Estimate memory usage
        max_B_size = max(len(B_terms) for B_terms in groups.values()) if groups else 0
        memory_estimate = _estimate_memory_usage(len(A), max_B_size, len(U), args.R)
        print(f"  Estimated memory usage: {memory_estimate}")
        
        # Check available memory
        try:
            import psutil
            available_memory = psutil.virtual_memory().available / (1024**3)  # GB
            print(f"  Available memory: {available_memory:.1f}GB")
            if available_memory < 2.0:
                print("  [WARN] Low memory detected. Consider using --light-output or reducing --R")
        except ImportError:
            pass  # psutil not available

        # Build per-gene aligned records (keep only GO/KEGG present in U)
        per_gene_aligned = []
        for rec in A_per_gene_raw:
            pathways = rec.get("pathway", [])
            aligned_pw = sorted([t for t in pathways if t in U])
            per_gene_aligned.append(
                {
                    "gene_name": rec.get("gene_name", ""),
                    "similarity_gene_name": rec.get("similarity_gene_name", ""),
                    "ENTREZ_ID": rec.get("ENTREZ_ID", ""),
                    "pathway": aligned_pw,
                }
            )

        # =====================================================================
        # ENSEMBLE ANALYSIS MODE (if enabled, runs multi-method analysis and exits)
        # =====================================================================
        if args.ensemble:
            print(f"\n{'='*70}")
            print(f"ENSEMBLE ANALYSIS MODE (Level: {args.ensemble_level})")
            print(f"{'='*70}\n")
            
            # Determine which methods to run
            if args.ensemble_methods:
                methods = args.ensemble_methods
            else:
                # Default methods (excluding semantic_jaccard due to signal dilution)
                methods = ['hypergeometric', 'jaccard', 'overlap', 'resnik_bma', 'lin_bma']
            
            # Build configuration
            r_values = {
                'hypergeometric': args.ensemble_r_hypergeometric,
                'jaccard': args.ensemble_r_jaccard,
                'overlap': args.ensemble_r_overlap,
                'resnik_bma': args.ensemble_r_semantic,
                'lin_bma': args.ensemble_r_semantic,
                'semantic_jaccard': args.ensemble_r_semantic,
            }
            
            ensemble_config = {
                'A': args.A,
                'species': species,
                'ensemble_methods': methods,
                'alpha': args.alpha,
                'seed': args.seed,
                'condition': args.condition,
                'organ': args.organ,
                'model': args.model,
                'factor': args.factor,
                'additional_condition': args.additional_condition,
                'config_file': args.config if args.config else 'command-line',
                'group_metadata': group_metadata,  # Pass B_terms group metadata
                # LLM parameters (supports MoE)
                'llm_explain': args.llm_explain,
                'llm_guard': args.llm_guard if hasattr(args, 'llm_guard') else False,
                'llm_guard_verdict': args.llm_guard_verdict if hasattr(args, 'llm_guard_verdict') else 'enriched',
                'llm_guard_confidence': args.llm_guard_confidence if hasattr(args, 'llm_guard_confidence') else None,
                'llm_guard_max_qvalue': args.llm_guard_max_qvalue if hasattr(args, 'llm_guard_max_qvalue') else None,
                'llm_guard_min_consensus': args.llm_guard_min_consensus if hasattr(args, 'llm_guard_min_consensus') else None,
                'llm_moe': args.llm_moe if hasattr(args, 'llm_moe') else False,
                'llm_expert_models_parsed': args.llm_expert_models_parsed if hasattr(args, 'llm_expert_models_parsed') else None,
                'llm_reviewer_model': args.llm_reviewer_model if hasattr(args, 'llm_reviewer_model') else None,
                'llm_reviewer_base_url': args.llm_reviewer_base_url if hasattr(args, 'llm_reviewer_base_url') else None,
                'llm_moe_parallel': args.llm_moe_parallel if hasattr(args, 'llm_moe_parallel') else True,
                'llm_moe_show_experts': args.llm_moe_show_experts if hasattr(args, 'llm_moe_show_experts') else False,
                'llm_model': args.llm_model,
                'llm_base_url': args.llm_base_url,
                'llm_api_key': args.llm_api_key,
                'llm_timeout': args.llm_timeout,
                'llm_max_terms': args.llm_max_terms if hasattr(args, 'llm_max_terms') else 10,
                # InterProScan evidence parameters
                'evidence_dir': args.evidence_dir if hasattr(args, 'evidence_dir') else None,
                'interpro_file': args.interpro_file if hasattr(args, 'interpro_file') else None,
                'interpro_out_dir': args.interpro_out_dir if hasattr(args, 'interpro_out_dir') else None
            }
            
            # Load GO and KEGG metadata for reporting
            go_meta_dict = {}
            kegg_meta_dict = {}
            
            try:
                go_meta_path = _resolve_default("data/meta/go_meta.json")
                with open(go_meta_path, 'r', encoding='utf-8') as f:
                    go_meta_dict = json.load(f)
            except Exception as e:
                print(f"[WARN] Could not load GO metadata: {e}", file=sys.stderr)
            
            try:
                kegg_meta_path = _resolve_default(f"data/meta/kegg_meta_{species}.json")
                with open(kegg_meta_path, 'r', encoding='utf-8') as f:
                    kegg_meta_dict = json.load(f)
            except Exception as e:
                print(f"[WARN] Could not load KEGG metadata: {e}", file=sys.stderr)
            
            # Prepare gene data
            per_gene_ensemble_results = {}
            total_ensemble_tasks = 0
            completed_tasks = 0
            
            # Calculate total tasks
            if args.ensemble_level in ['gene', 'all']:
                if args.ensemble_level == 'gene':
                    total_ensemble_tasks += len(per_gene_aligned)  # only global gene analysis
                else:  # 'all'
                    total_ensemble_tasks += len(per_gene_aligned) * (1 + len(groups))  # gene × (global + per-group)
            if args.ensemble_level in ['group', 'all']:
                total_ensemble_tasks += len(groups)
            if args.ensemble_level in ['total', 'all']:
                total_ensemble_tasks += 1
            
            print(f"Total ensemble tasks: {total_ensemble_tasks}")
            print(f"Methods per task: {len(methods)}")
            print(f"Parallel execution: {args.ensemble_parallel}\n")
            
            # =================================================================
            # GENE-LEVEL ENSEMBLE (DEFAULT)
            # =================================================================
            if args.ensemble_level in ['gene', 'all']:
                print(f"[1/{3 if args.ensemble_level == 'all' else 1}] GENE-LEVEL ENSEMBLE")
                print(f"Analyzing {len(per_gene_aligned)} genes...")
                
                # Create gene_reports directory
                gene_reports_dir = os.path.join(args.outdir, "gene_reports")
                os.makedirs(gene_reports_dir, exist_ok=True)
                
                # Merge all B for global gene analysis
                B_merged = set()
                for group_terms in groups.values():
                    B_merged.update(group_terms)
                B_merged &= U
                
                # Analyze each gene (global, across all groups)
                for idx, gene_data in enumerate(per_gene_aligned, 1):
                    gene_name = gene_data['gene_name']
                    gene_A = set(gene_data['pathway']) & U
                    
                    if len(gene_A) == 0:
                        continue
                    
                    print(f"  [{idx}/{len(per_gene_aligned)}] {gene_name} (|A|={len(gene_A)})...", end='', flush=True)
                    
                    # Create gene-specific subdirectory
                    gene_subdir = os.path.join(gene_reports_dir, gene_name)
                    os.makedirs(gene_subdir, exist_ok=True)
                    
                    gene_config = ensemble_config.copy()
                    gene_config['gene_name'] = gene_name
                    
                    result = _run_ensemble_analysis_core(
                        A=gene_A,
                        B=B_merged,
                        U=U,
                        methods=methods,
                        r_values=r_values,
                        alpha=args.alpha,
                        seed=args.seed,
                        go_meta=go_meta_dict,
                        kegg_meta=kegg_meta_dict,
                        output_dir=gene_subdir,  # Use gene-specific subdirectory
                        config=gene_config,
                        level_label=f"Gene: {gene_name}",
                        parallel=args.ensemble_parallel,
                        group_metadata=group_metadata,
                        gene_data=gene_data  # Pass gene data for TSV generation
                    )
                    
                    per_gene_ensemble_results[gene_name] = result
                    completed_tasks += 1
                    print(f" {result.verdict} ({result.confidence})")
                
                # Analyze each gene in each group (ONLY if level='all', not in default 'gene' mode)
                if args.ensemble_level == 'all':
                    for group_key, group_B in groups.items():
                        # group_key might be a tuple or a single value
                        if isinstance(group_key, tuple) and len(group_key) >= 5:
                            add_cond, comp_ctrl, comp_cond, cell_type, day = group_key[0], group_key[1], group_key[2], group_key[3], group_key[4]
                        elif isinstance(group_key, tuple):
                            add_cond = group_key[0] if len(group_key) > 0 else ''
                            comp_ctrl = group_key[1] if len(group_key) > 1 else ''
                            comp_cond = group_key[2] if len(group_key) > 2 else ''
                            cell_type = group_key[3] if len(group_key) > 3 else ''
                            day = group_key[4] if len(group_key) > 4 else ''
                        else:
                            add_cond, comp_ctrl, comp_cond, cell_type, day = str(group_key), '', '', '', ''
                        
                        group_dir = _make_ensemble_group_dir_name(
                            args.condition, add_cond, args.organ, args.model, 
                            getattr(args, 'factor', ''), comp_ctrl, comp_cond, cell_type, day
                        )
                        group_full_dir = os.path.join(args.outdir, group_dir)
                        group_gene_reports_dir = os.path.join(group_full_dir, "gene_reports")
                        os.makedirs(group_gene_reports_dir, exist_ok=True)
                        
                        for gene_data in per_gene_aligned:
                            gene_name = gene_data['gene_name']
                            gene_A = set(gene_data['pathway']) & U
                            
                            if len(gene_A) == 0:
                                continue
                            
                            # Create gene-specific subdirectory in group
                            gene_in_group_subdir = os.path.join(group_gene_reports_dir, gene_name)
                            os.makedirs(gene_in_group_subdir, exist_ok=True)
                            
                            gene_config = ensemble_config.copy()
                            gene_config['gene_name'] = gene_name
                            gene_config['group_key'] = group_key
                            
                            _run_ensemble_analysis_core(
                                A=gene_A,
                                B=group_B,
                                U=U,
                                methods=methods,
                                r_values=r_values,
                                alpha=args.alpha,
                                seed=args.seed,
                                go_meta=go_meta_dict,
                                kegg_meta=kegg_meta_dict,
                                output_dir=gene_in_group_subdir,  # Use gene-specific subdirectory
                                config=gene_config,
                                level_label=f"Gene: {gene_name} in {group_dir}",
                                parallel=args.ensemble_parallel,
                                group_metadata=group_metadata
                            )
                            completed_tasks += 1
                
                print(f"✓ Gene-level ensemble complete\n")
            
            # =================================================================
            # GROUP-LEVEL ENSEMBLE (OPTIONAL)
            # =================================================================
            if args.ensemble_level in ['group', 'all']:
                print(f"[2/{3 if args.ensemble_level == 'all' else 1}] GROUP-LEVEL ENSEMBLE")
                print(f"Analyzing {len(groups)} groups...")
                
                for idx, (group_key, group_B) in enumerate(groups.items(), 1):
                    # group_key might be a tuple or a single value
                    if isinstance(group_key, tuple) and len(group_key) >= 5:
                        add_cond, comp_ctrl, comp_cond, cell_type, day = group_key[0], group_key[1], group_key[2], group_key[3], group_key[4]
                    elif isinstance(group_key, tuple):
                        add_cond = group_key[0] if len(group_key) > 0 else ''
                        comp_ctrl = group_key[1] if len(group_key) > 1 else ''
                        comp_cond = group_key[2] if len(group_key) > 2 else ''
                        cell_type = group_key[3] if len(group_key) > 3 else ''
                        day = group_key[4] if len(group_key) > 4 else ''
                    else:
                        add_cond, comp_ctrl, comp_cond, cell_type, day = str(group_key), '', '', '', ''
                    
                    group_dir = _make_ensemble_group_dir_name(
                        args.condition, add_cond, args.organ, args.model, 
                        getattr(args, 'factor', ''), comp_ctrl, comp_cond, cell_type, day
                    )
                    group_full_dir = os.path.join(args.outdir, group_dir)
                    os.makedirs(group_full_dir, exist_ok=True)
                    
                    print(f"  [{idx}/{len(groups)}] {group_dir}...", end='', flush=True)
                    
                    group_config = ensemble_config.copy()
                    group_config['group_key'] = group_key
                    
                    result = _run_ensemble_analysis_core(
                        A=A,
                        B=group_B,
                        U=U,
                        methods=methods,
                        r_values=r_values,
                        alpha=args.alpha,
                        seed=args.seed,
                        go_meta=go_meta_dict,
                        kegg_meta=kegg_meta_dict,
                        output_dir=group_full_dir,
                        config=group_config,
                        level_label=f"Group: {group_dir}",
                        parallel=args.ensemble_parallel,
                        group_metadata=group_metadata
                    )
                    completed_tasks += 1
                    print(f" {result.verdict} ({result.confidence})")
                
                print(f"✓ Group-level ensemble complete\n")
            
            # =================================================================
            # TOTAL-LEVEL ENSEMBLE (OPTIONAL)
            # =================================================================
            if args.ensemble_level in ['total', 'all']:
                print(f"[3/3] TOTAL-LEVEL ENSEMBLE")
                print(f"Analyzing merged data...")
                
                B_merged = set()
                for group_terms in groups.values():
                    B_merged.update(group_terms)
                B_merged &= U
                
                print(f"  Merged B from {len(groups)} groups: {len(B_merged)} terms")
                
                result = _run_ensemble_analysis_core(
                    A=A,
                    B=B_merged,
                    U=U,
                    methods=methods,
                    r_values=r_values,
                    alpha=args.alpha,
                    seed=args.seed,
                    go_meta=go_meta_dict,
                    kegg_meta=kegg_meta_dict,
                    output_dir=args.outdir,
                    config=ensemble_config,
                    level_label="Total",
                    parallel=args.ensemble_parallel,
                    group_metadata=group_metadata
                )
                completed_tasks += 1
                print(f"  Final verdict: {result.verdict} ({result.confidence})\n")
                print(f"✓ Total-level ensemble complete\n")
            
            # Print final summary
            elapsed_time = time.time() - start_time
            print(f"{'='*70}")
            print("ENSEMBLE ANALYSIS COMPLETE")
            print(f"{'='*70}")
            print(f"Level: {args.ensemble_level}")
            print(f"Tasks completed: {completed_tasks}/{total_ensemble_tasks}")
            print(f"Total Runtime: {elapsed_time:.1f}s ({elapsed_time/60:.1f} minutes)")
            print(f"\nOutputs ({args.outdir}):")
            
            if args.ensemble_level in ['gene', 'all']:
                print(f"  - Gene Reports: gene_reports/*.md ({len(per_gene_ensemble_results)} genes)")
                print(f"  - Group+Gene Reports: condition=*/gene_reports/*.md")
            if args.ensemble_level in ['group', 'all']:
                print(f"  - Group Reports: condition=*/ENSEMBLE_REPORT.md ({len(groups)} groups)")
            if args.ensemble_level in ['total', 'all']:
                print(f"  - Total Report: ENSEMBLE_REPORT.md")
            
            print(f"{'='*70}\n")
            
            return  # Exit after ensemble analysis
        
        # =====================================================================
        # Continue with standard single-method analysis (original code)
        # =====================================================================
        
        # Save per-gene cleaned info in main outdir
        with open(
            os.path.join(args.outdir, "A_genes_cleaned.json"), "w", encoding="utf-8"
        ) as fjson:
            json.dump(per_gene_aligned, fjson, indent=2, ensure_ascii=False)
        with open(
            os.path.join(args.outdir, "A_genes_cleaned.tsv"), "w", encoding="utf-8"
        ) as ftsv:
            ftsv.write("gene_name\tsimilarity_gene_name\tENTREZ_ID\tpathway\n")
            for rec in per_gene_aligned:
                ftsv.write(
                    f"{rec['gene_name']}\t{rec['similarity_gene_name']}\t{rec['ENTREZ_ID']}\t{','.join(rec['pathway'])}\n"
                )

        # Debug/clean logs: only A & U, not B
        if log_dir is not None:
            with open(os.path.join(log_dir, "U_used.txt"), "w", encoding="utf-8") as f:
                for x in sorted(U):
                    f.write(x + "\n")
            with open(os.path.join(log_dir, "A_used.txt"), "w", encoding="utf-8") as f:
                for x in sorted(A & U):
                    f.write(x + "\n")

        # --- Consolidated outputs across all groups ---
        # Align A to U once
        A = A & U
        overall_pathway_str = ",".join(sorted(A))

        # --- Ontology splits for overall and groups ---
        U_GO = {t for t in U if t.startswith("GO:")}
        U_KEGG = {t for t in U if _is_kegg_allowed(t, allowed_kegg)}
        A_GO = A & U_GO
        A_KEGG = A & U_KEGG

        # --- Bitset backend (optional, only for non-semantic) ---
        def _encode_bits(terms: set[str], index: dict[str, int]) -> int:
            bits = 0
            for t in terms:
                i = index.get(t)
                if i is not None:
                    bits |= 1 << i
            return bits

        def _overlap_bits(a_bits: int, b_bits: int) -> int:
            return (a_bits & b_bits).bit_count()

        def _jaccard_bits(a_bits: int, b_bits: int) -> float:
            inter = (a_bits & b_bits).bit_count()
            union = (a_bits | b_bits).bit_count()
            return (inter / union) if union else 0.0

        bitset_mode = False
        if args.stat in ("overlap", "jaccard"):
            if args.bitset == "on" or (args.bitset == "auto"):
                bitset_mode = True
        idx_map: dict[str, int] = {}
        GO_mask = 0
        KEGG_mask = 0
        A_bits = 0
        if bitset_mode:
            # stable order
            U_index_list = list(U)
            idx_map = {t: i for i, t in enumerate(U_index_list)}
            # ontology masks
            for t in U_GO:
                GO_mask |= 1 << idx_map[t]
            for t in U_KEGG:
                KEGG_mask |= 1 << idx_map[t]
            # A bits
            A_bits = _encode_bits(A, idx_map)

        # Prepare semantic resources
        if args.stat == "semantic":
            try:
                go_anc = _load_go_ancestors(args.go_ancestors)
            except FileNotFoundError as e:
                print(
                    f"[WARN] {e}. Proceeding without GO ancestors; semantic GO will fall back to IC-weighted/flat mode.",
                    file=sys.stderr,
                )
                go_anc = {}
        else:
            go_anc = {}
        if args.term_size is not None:
            size_map = read_term_size_tsv(args.term_size)
        else:
            size_map = {}
        if args.stat == "semantic":
            if args.semantic_method in ["resnik_bma", "lin_bma"]:
                # Load IC map from file for Resnik/Lin methods
                try:
                    with open(args.go_ic, "r", encoding="utf-8") as f:
                        ic_map = json.load(f)
                except FileNotFoundError as e:
                    print(f"[WARN] {e}. Proceeding without IC map.", file=sys.stderr)
                    ic_map = {}
            else:  # closure_jaccard
                ic_map = _ic_map_from_term_size(size_map)
        else:
            ic_map = {}

        # Prep GO/KEGG stratification buckets if needed (read size_map only once)
        bins = _parse_bins(args.bins)
        U_list = list(U)
        U_list_GO = list(U_GO)
        U_list_KEGG = list(U_KEGG)
        
        # Initialize buckets
        U_buckets = U_buckets_GO = U_buckets_KEGG = None
        
        if size_map:
            # Standard size-based stratification
            U_buckets = stratify(U_list, size_map, bins)
            U_buckets_KEGG = stratify(U_list_KEGG, size_map, bins)
            
            # GO structured stratification (namespace × depth × size)
            go_structured_enabled = getattr(args, 'go_structured_stratification', False)
            # Check if GO resources are available (either explicitly set or default paths exist)
            go_ancestors_available = args.go_ancestors and os.path.exists(args.go_ancestors)
            go_namespace_available = args.go_namespace and os.path.exists(args.go_namespace)
            if (args.stat in ["semantic", "overlap", "jaccard"] and go_ancestors_available and go_namespace_available and 
                go_structured_enabled):
                try:
                    # Load GO resources
                    go_anc = _load_go_ancestors(args.go_ancestors)
                    go_ns_map = _load_go_namespace(args.go_namespace)
                    
                    # Create depth map from ancestors
                    go_depth_map = _approx_go_depth_map_from_ancestors(go_anc)
                    
                    # Define depth bins (adjustable)
                    depth_bins = [0, 5, 10, 20, 50, 999999]  # Can be made configurable
                    
                    # Create GO structured buckets
                    U_buckets_GO = stratify_go_multi(
                        u_terms=U_list_GO,
                        size_map=size_map,
                        size_bins=bins,
                        ns_map=go_ns_map,
                        depth_map=go_depth_map,
                        depth_bins=depth_bins,
                    )
                    
                    print(f"[INFO] Using GO structured stratification: {len(U_buckets_GO)} buckets")
                    
                except Exception as e:
                    print(f"[WARN] Failed to create GO structured stratification: {e}")
                    print(f"[INFO] Falling back to size-only stratification for GO")
                    U_buckets_GO = stratify(U_list_GO, size_map, bins)
            else:
                # Fallback to size-only stratification for GO
                U_buckets_GO = stratify(U_list_GO, size_map, bins)

        summary_path = os.path.join(args.outdir, "summary.tsv")
        null_stats_path = os.path.join(args.outdir, "null_stats.tsv")
        intersections_path = os.path.join(args.outdir, "intersections.tsv")

        # Open combined files and write headers
        with (
            open(summary_path, "w", encoding="utf-8") as fsum,
            open(null_stats_path, "w", encoding="utf-8") as fnull,
            open(intersections_path, "w", encoding="utf-8") as finter,
        ):
            fsum.write(
                "gene_name\tsimilarity_gene_name\tENTREZ_ID\tpathway\tcondition\tadditional_condition\torgan\tmodel\tcategory\tcomparison_control\tcomparison_condition\tcell_type\tday\tfactor\tsource\tstatistic\tA_size\tB_size\tU_size\tS_obs\tnull_mean\tnull_sd\tz_score\tR\tp_right\tp_left\tp_two_tailed\tstratified\tbins\talpha\teffect_size\tverdict\tA_GO_size\tB_GO_size\tU_GO_size\tS_obs_GO\tnull_mean_GO\tp_right_GO\teffect_size_GO\tverdict_GO\tA_KEGG_size\tB_KEGG_size\tU_KEGG_size\tS_obs_KEGG\tnull_mean_KEGG\tp_right_KEGG\teffect_size_KEGG\tverdict_KEGG\n"
            )
            fnull.write(
                "condition\tadditional_condition\torgan\tmodel\tcategory\tcomparison_control\tcomparison_condition\tcell_type\tday\tfactor\titer\tstat\n"
            )
            finter.write(
                "condition\tadditional_condition\torgan\tmodel\tcategory\tcomparison_control\tcomparison_condition\tcell_type\tday\tfactor\tterm\n"
            )
            # groups.tsv and groups_summary.tsv are no longer written per requirement

            # Common settings
            # Removed overlap and jaccard statistics
            if args.stat == "hypergeometric":
                stat_fn = None  # hypergeometric handled explicitly
            else:
                stat_fn = None  # semantic handled explicitly below
            # RNG scope helper (global or per-group)
            rng_for_group = make_group_rng(
                args.seed, getattr(args, "rng_scope", "global")
            )
            use_strata = bool(size_map)

            groups_count = 0
            group_core: dict[tuple[str, str, str, str], dict] = {}

            def _compute_group(
                cond_val: str,
                add_val: str,
                organ_val: str,
                model_val: str,
                B_raw: set[str],
                metadata: dict = None,
                topology_analyzer: Optional[KEGGTopologyAnalyzer] = None,
            ):
                B = set(B_raw) & U
                B_GO = B & U_GO
                B_KEGG = B & U_KEGG
                if bitset_mode:
                    B_bits = _encode_bits(B, idx_map)
                print(f"[{_now()}] Processing: {cond_val} | {add_val} | {organ_val} | {model_val} (B={len(B)})")
                # Use metadata if available, otherwise fall back to args
                meta = metadata or {}
                res = {
                    "cond": cond_val,
                    "add": add_val,
                    "organ": organ_val,
                    "model": model_val,
                    "category": meta.get("category", args.category),
                    "comparison_control": meta.get("comparison_control", args.comparison_control),
                    "comparison_condition": meta.get("comparison_condition", args.comparison_condition),
                    "cell_type": meta.get("cell_type", args.cell_type),
                    "day": meta.get("day", args.day),
                    "factor": meta.get("factor", args.factor),
                    "B": B,
                    "B_GO": B_GO,
                    "B_KEGG": B_KEGG,
                }
                if not A or not B:
                    res.update(
                        {
                            "empty": True,
                            "S_obs": 0.0,
                            "mu": float("nan"),
                            "sd": float("nan"),
                            "z": float("nan"),
                            "p_right": 1.0,
                            "p_left": 1.0,
                            "p_two": 1.0,
                            "effect_size": 0.0,
                            "verdict": "not_significant",
                            "S_obs_GO": 0.0,
                            "mu_GO": 0.0,
                            "p_right_GO": 1.0,
                            "effect_GO": 0.0,
                            "verdict_GO": (
                                "not_applicable"
                                if not (A_GO and B_GO)
                                else "not_significant"
                            ),
                            "S_obs_KEGG": 0.0,
                            "mu_KEGG": 0.0,
                            "p_right_KEGG": 1.0,
                            "effect_KEGG": 0.0,
                            "verdict_KEGG": (
                                "not_applicable"
                                if not (A_KEGG and B_KEGG)
                                else "not_significant"
                            ),
                            "null_stats": [],
                            "intersections": sorted(A & B),
                        }
                    )
                    return res

                # Precompute and cache random B-like sets for reuse across overall/GO/KEGG/per-gene
                rng_group = rng_for_group((cond_val, add_val, organ_val, model_val))
                
                # Use GO structured stratification if available
                if (isinstance(U_buckets_GO, dict) and args.stat in ["semantic", "overlap", "jaccard"] and 
                    getattr(args, 'go_structured_stratification', False)):
                    # Use GO structured buckets for GO terms, regular buckets for others
                    B_randoms = make_B_randoms(
                        B,
                        U_list,
                        U_buckets_GO,  # Use GO structured buckets
                        size_map if use_strata else None,
                        bins,
                        rng_group,
                        args.R,
                        desc=f"Generating group permutations ({cond_val}/{add_val}/{organ_val}/{model_val})",
                        go_ns_map=go_ns_map if 'go_ns_map' in locals() else None,
                        go_depth_map=go_depth_map if 'go_depth_map' in locals() else None,
                        go_depth_bins=depth_bins if 'depth_bins' in locals() else None,
                    )
                else:
                    # Use standard stratification
                    B_randoms = make_B_randoms(
                        B,
                        U_list,
                        U_buckets,
                        size_map if use_strata else None,
                        bins,
                        rng_group,
                        args.R,
                        desc=f"Generating group permutations ({cond_val}/{add_val}/{organ_val}/{model_val})",
                    )
                if bitset_mode:
                    B_randoms_bits = [_encode_bits(br, idx_map) for br in B_randoms]

                # Precompute and cache random B-like subsets by ontology for reuse
                B_randoms_GO = [(br & U_GO) if br else set() for br in B_randoms]
                B_randoms_KEGG = [(br & U_KEGG) if br else set() for br in B_randoms]

                # --- GO-only stats (reuse cached B_randoms_GO) ---
                null_stats_GO = []
                if args.stat == "hypergeometric":
                    # Perform hypergeometric enrichment test for GO terms
                    if A_GO and B_GO:
                        hypergeometric_result_GO = hypergeometric_enrichment(A_GO, B_GO, U_GO)
                        S_obs_GO = hypergeometric_result_GO['enrichment_score']
                        p_value_GO = hypergeometric_result_GO['p_value']
                        odds_ratio_GO = hypergeometric_result_GO['odds_ratio']
                    else:
                        S_obs_GO = 0.0
                        p_value_GO = 1.0
                        odds_ratio_GO = 0.0
                elif args.stat == "semantic":
                    if args.semantic_method == "closure_jaccard":
                        for B_rand_GO in B_randoms_GO:
                            null_stats_GO.append(
                                _semantic_go_component(A_GO, B_rand_GO, go_anc, ic_map)
                            )
                        S_obs_GO = _semantic_go_component(A_GO, B_GO, go_anc, ic_map)
                    elif args.semantic_method == "resnik_bma":
                        ns_map = _load_go_namespace(args.go_namespace)
                        for B_rand_GO in B_randoms_GO:
                            null_stats_GO.append(
                                semantic_go_similarity(A_GO, B_rand_GO, go_anc, ic_map, ns_map, method="resnik_bma")
                            )
                        S_obs_GO = semantic_go_similarity(A_GO, B_GO, go_anc, ic_map, ns_map, method="resnik_bma")
                    elif args.semantic_method == "lin_bma":
                        ns_map = _load_go_namespace(args.go_namespace)
                        for B_rand_GO in B_randoms_GO:
                            null_stats_GO.append(
                                semantic_go_similarity(A_GO, B_rand_GO, go_anc, ic_map, ns_map, method="lin_bma")
                            )
                        S_obs_GO = semantic_go_similarity(A_GO, B_GO, go_anc, ic_map, ns_map, method="lin_bma")
                else:
                    if bitset_mode:
                        A_GO_bits = A_bits & GO_mask
                        null_stats_GO = [
                            (
                                _overlap_bits(A_GO_bits, br_bits & GO_mask)
                                if args.stat == "overlap"
                                else _jaccard_bits(A_GO_bits, br_bits & GO_mask)
                            )
                            for br_bits in B_randoms_bits
                        ]
                        S_obs_GO = (
                            (
                                _overlap_bits(A_GO_bits, B_bits & GO_mask)
                                if args.stat == "overlap"
                                else _jaccard_bits(A_GO_bits, B_bits & GO_mask)
                            )
                            if (A_GO and B_GO)
                            else 0.0
                        )
                    else:
                        for B_rand_GO in B_randoms_GO:
                            null_stats_GO.append(stat_fn(A_GO, B_rand_GO))
                        S_obs_GO = stat_fn(A_GO, B_GO) if (A_GO and B_GO) else 0.0
                if args.stat == "hypergeometric":
                    mu_GO = float("nan")
                    p_right_GO = p_value_GO
                elif _NP_AVAILABLE and null_stats_GO:
                    arr_go = _np.asarray(null_stats_GO, dtype=float)
                    mu_GO = float(arr_go.mean())
                    p_right_GO = (
                        ((int((arr_go >= S_obs_GO).sum()) + 1) / (args.R + 1))
                        if args.R > 0
                        else 1.0
                    )
                else:
                    mu_GO = mean(null_stats_GO) if null_stats_GO else 0.0
                    p_right_GO = (
                        (
                            (sum(1 for s in null_stats_GO if s >= S_obs_GO) + 1)
                            / (args.R + 1)
                        )
                        if args.R > 0
                        else 1.0
                    )
                effect_GO = S_obs_GO - mu_GO
                verdict_GO = (
                    "enriched"
                    if (p_right_GO < args.alpha and effect_GO > 0)
                    else (
                        "depleted"
                        if (S_obs_GO < mu_GO and (1 - p_right_GO) < args.alpha)
                        else "not_significant"
                    )
                )

                # --- KEGG-only stats (reuse cached B_randoms_KEGG) ---
                null_stats_KEGG = []
                if args.stat == "hypergeometric":
                    # Perform hypergeometric enrichment test for KEGG terms
                    if A_KEGG and B_KEGG:
                        hypergeometric_result_KEGG = hypergeometric_enrichment(A_KEGG, B_KEGG, U_KEGG)
                        S_obs_KEGG = hypergeometric_result_KEGG['enrichment_score']
                        p_value_KEGG = hypergeometric_result_KEGG['p_value']
                        odds_ratio_KEGG = hypergeometric_result_KEGG['odds_ratio']
                    else:
                        S_obs_KEGG = 0.0
                        p_value_KEGG = 1.0
                        odds_ratio_KEGG = 0.0
                elif args.stat == "semantic":
                    for B_rand_KEGG in B_randoms_KEGG:
                        null_stats_KEGG.append(
                            _semantic_kegg_component_enhanced(
                                A_KEGG, B_rand_KEGG, 
                                base=args.semantic_kegg_base,
                                topology_analyzer=topology_analyzer,
                                topology_method=args.kegg_topology_method
                            )
                        )
                    S_obs_KEGG = _semantic_kegg_component_enhanced(
                        A_KEGG, B_KEGG, 
                        base=args.semantic_kegg_base,
                        topology_analyzer=topology_analyzer,
                        topology_method=args.kegg_topology_method
                    )
                else:
                    if bitset_mode:
                        A_KEGG_bits = A_bits & KEGG_mask
                        null_stats_KEGG = [
                            (
                                _overlap_bits(A_KEGG_bits, br_bits & KEGG_mask)
                                if args.stat == "overlap"
                                else _jaccard_bits(A_KEGG_bits, br_bits & KEGG_mask)
                            )
                            for br_bits in B_randoms_bits
                        ]
                        S_obs_KEGG = (
                            (
                                _overlap_bits(A_KEGG_bits, B_bits & KEGG_mask)
                                if args.stat == "overlap"
                                else _jaccard_bits(A_KEGG_bits, B_bits & KEGG_mask)
                            )
                            if (A_KEGG and B_KEGG)
                            else 0.0
                        )
                    else:
                        for B_rand_KEGG in B_randoms_KEGG:
                            null_stats_KEGG.append(stat_fn(A_KEGG, B_rand_KEGG))
                        S_obs_KEGG = (
                            stat_fn(A_KEGG, B_KEGG) if (A_KEGG and B_KEGG) else 0.0
                        )
                if args.stat == "hypergeometric":
                    mu_KEGG = float("nan")
                    p_right_KEGG = p_value_KEGG
                elif _NP_AVAILABLE and null_stats_KEGG:
                    arr_ke = _np.asarray(null_stats_KEGG, dtype=float)
                    mu_KEGG = float(arr_ke.mean())
                    p_right_KEGG = (
                        ((int((arr_ke >= S_obs_KEGG).sum()) + 1) / (args.R + 1))
                        if args.R > 0
                        else 1.0
                    )
                else:
                    mu_KEGG = mean(null_stats_KEGG) if null_stats_KEGG else 0.0
                    p_right_KEGG = (
                        (
                            (sum(1 for s in null_stats_KEGG if s >= S_obs_KEGG) + 1)
                            / (args.R + 1)
                        )
                        if args.R > 0
                        else 1.0
                    )
                effect_KEGG = S_obs_KEGG - mu_KEGG
                verdict_KEGG = (
                    "enriched"
                    if (p_right_KEGG < args.alpha and effect_KEGG > 0)
                    else (
                        "depleted"
                        if (S_obs_KEGG < mu_KEGG and (1 - p_right_KEGG) < args.alpha)
                        else "not_significant"
                    )
                )

                # Permutations per group (use optimized parallel processing)
                null_stats = []
                if args.stat in ["hypergeometric"]:
                    # For hypergeometric test, we don't need permutations
                    # We'll handle this directly in the main logic
                    pass
                else:
                    # Use optimized parallel processing for large R values
                    if accelerator is not None and args.R > 1000:
                        print(f"  Using parallel acceleration for {args.R} permutations...")
                        
                        if args.stat == "semantic":
                            # Create semantic statistical function
                            semantic_stat_fn = _create_semantic_stat_function(
                                A_GO, A_KEGG, go_anc, ic_map, args, topology_analyzer
                            )
                            null_stats = _compute_permutations_optimized(
                                A, B, U, semantic_stat_fn, args.R, accelerator
                            )
                        else:
                            # Use standard statistical function
                            null_stats = _compute_permutations_optimized(
                                A, B, U, stat_fn, args.R, accelerator
                            )
                    else:
                        # Fallback to original sequential processing
                        for i, B_rand in enumerate(B_randoms, 1):
                            if args.stat == "semantic":
                                br_go = B_randoms_GO[i - 1]
                                br_ke = B_randoms_KEGG[i - 1]
                                s_go = _semantic_go_component(A_GO, br_go, go_anc, ic_map)
                                s_ke = _semantic_kegg_component_enhanced(
                                    A_KEGG, br_ke, 
                                    base=args.semantic_kegg_base,
                                    topology_analyzer=topology_analyzer,
                                    topology_method=args.kegg_topology_method
                                )
                                null_stats.append(
                                    _combine_go_kegg(
                                        s_go,
                                        s_ke,
                                        A_GO,
                                        br_go,
                                        A_KEGG,
                                        br_ke,
                                        args.semantic_kegg_base,
                                    )
                                )
                            else:
                                if bitset_mode:
                                    br_bits = B_randoms_bits[i - 1]
                                    if args.stat == "overlap":
                                        null_stats.append(_overlap_bits(A_bits, br_bits))
                                    else:
                                        null_stats.append(_jaccard_bits(A_bits, br_bits))
                                else:
                                    null_stats.append(stat_fn(A, B_rand))
                    # Progress output every 20% or every 100 iterations, whichever is more frequent
                    if (i % max(1, min(100, args.R // 5))) == 0:
                        progress_pct = int(100 * i / args.R)
                        print(f"  Progress: {progress_pct}% ({i}/{args.R})", flush=True)

                if args.stat == "hypergeometric":
                    # Perform hypergeometric enrichment test
                    hypergeometric_result = hypergeometric_enrichment(A, B, U)
                    S_obs = hypergeometric_result['enrichment_score']
                    p_value = hypergeometric_result['p_value']
                    odds_ratio = hypergeometric_result['odds_ratio']
                    overlap_count = hypergeometric_result['overlap_count']
                elif args.stat == "semantic":
                    if args.semantic_method == "closure_jaccard":
                        s_go_obs = _semantic_go_component(A_GO, B_GO, go_anc, ic_map)
                    elif args.semantic_method == "resnik_bma":
                        # Load namespace mapping for Resnik BMA
                        ns_map = _load_go_namespace(args.go_namespace)
                        s_go_obs = semantic_go_similarity(A_GO, B_GO, go_anc, ic_map, ns_map, method="resnik_bma", 
                                                         parallel=args.parallel_semantic, max_workers=args.semantic_workers)
                    elif args.semantic_method == "lin_bma":
                        # Load namespace mapping for Lin BMA
                        ns_map = _load_go_namespace(args.go_namespace)
                        s_go_obs = semantic_go_similarity(A_GO, B_GO, go_anc, ic_map, ns_map, method="lin_bma",
                                                         parallel=args.parallel_semantic, max_workers=args.semantic_workers)
                    
                    s_ke_obs = _semantic_kegg_component_enhanced(
                        A_KEGG, B_KEGG, 
                        base=args.semantic_kegg_base,
                        topology_analyzer=topology_analyzer,
                        topology_method=args.kegg_topology_method
                    )
                    S_obs = _combine_go_kegg(
                        s_go_obs,
                        s_ke_obs,
                        A_GO,
                        B_GO,
                        A_KEGG,
                        B_KEGG,
                        args.semantic_kegg_base,
                    )
                else:
                    if bitset_mode:
                        if args.stat == "overlap":
                            S_obs = _overlap_bits(A_bits, B_bits) if (A and B) else 0.0
                        else:
                            S_obs = _jaccard_bits(A_bits, B_bits) if (A and B) else 0.0
                    else:
                        S_obs = stat_fn(A, B) if (A and B) else 0.0
                if args.stat == "hypergeometric":
                    # For hypergeometric test, use the calculated p-value
                    mu = float("nan")
                    sd = float("nan")
                    z = float("nan")
                    p_right = p_value
                    p_left = 1.0 - p_value
                    p_two = 2 * min(p_value, 1.0 - p_value)
                    effect_size = odds_ratio
                    verdict = "enriched" if (p_value < args.alpha and odds_ratio > 1) else "not_significant"
                else:
                    mu, sd, p_right, p_left, p_two, effect_size = _summarize_null(
                        null_stats, S_obs, args.R
                    )
                    z = (effect_size / sd) if (sd and sd > 0) else float("nan")
                    verdict = _verdict_from_pvalues(
                        p_right, p_left, p_two, effect_size, args.alpha, args.verdict_rule
                    )
                res.update(
                    {
                        "empty": False,
                        "S_obs": S_obs,
                        "mu": mu,
                        "sd": sd,
                        "z": z,
                        "p_right": p_right,
                        "p_left": p_left,
                        "p_two": p_two,
                        "effect_size": effect_size,
                        "verdict": verdict,
                        "S_obs_GO": S_obs_GO,
                        "mu_GO": mu_GO,
                        "p_right_GO": p_right_GO,
                        "effect_GO": effect_GO,
                        "verdict_GO": verdict_GO,
                        "S_obs_KEGG": S_obs_KEGG,
                        "mu_KEGG": mu_KEGG,
                        "p_right_KEGG": p_right_KEGG,
                        "effect_KEGG": effect_KEGG,
                        "verdict_KEGG": verdict_KEGG,
                        "null_stats": null_stats,
                        "intersections": sorted(A & B),
                    }
                )
                return res

            # Initialize llm_group_map for JSON report (needed for group report generation)
            llm_group_map = {}

            # Compute group results (optionally in parallel), then write sequentially
            group_items = [(k[0], k[1], k[2], k[3], v, group_metadata.get(k, {})) for k, v in groups.items()]
            if getattr(args, "group_jobs", 1) and args.group_jobs > 1:
                print(f"  Using parallel processing with {args.group_jobs} workers")
                with _fut.ThreadPoolExecutor(max_workers=args.group_jobs) as ex:
                    # Use submit for better error handling and progress tracking
                    future_to_group = {
                        ex.submit(_compute_group, *tpl): tpl for tpl in group_items
                    }
                    results = []
                    for future in _fut.as_completed(future_to_group):
                        try:
                            result = future.result()
                            results.append(result)
                        except Exception as e:
                            group_info = future_to_group[future]
                            print(f"  [WARN] Group {group_info[0]} failed: {e}", file=sys.stderr)
                            # Create empty result for failed group
                            results.append({
                                "cond": group_info[0],
                                "add": group_info[1], 
                                "organ": group_info[2],
                                "model": group_info[3],
                                "empty": True,
                                "S_obs": 0.0,
                                "mu": float("nan"),
                                "sd": float("nan"),
                                "p_right": 1.0,
                                "p_left": 1.0,
                                "p_two": 1.0,
                                "effect": 0.0,
                                "z": float("nan"),
                                "B": set(),
                                "B_GO": set(),
                                "B_KEGG": set(),
                            })
            else:
                results = [_compute_group(*tpl, topology_analyzer) for tpl in group_items]

            for res in results:
                cond_val = res["cond"]
                add_val = res["add"]
                organ_val = res["organ"]
                model_val = res["model"]
                B = res["B"]
                B_GO = res["B_GO"]
                B_KEGG = res["B_KEGG"]
                S_obs = res["S_obs"]
                mu = res["mu"]
                sd = res["sd"]
                z = res.get("z", float("nan"))
                p_right = res["p_right"]
                p_left = res["p_left"]
                p_two = res["p_two"]
                effect_size = res["effect_size"]
                verdict = res["verdict"]
                S_obs_GO = res["S_obs_GO"]
                mu_GO = res["mu_GO"]
                p_right_GO = res["p_right_GO"]
                effect_GO = res["effect_GO"]
                verdict_GO = res["verdict_GO"]
                S_obs_KEGG = res["S_obs_KEGG"]
                mu_KEGG = res["mu_KEGG"]
                p_right_KEGG = res["p_right_KEGG"]
                effect_KEGG = res["effect_KEGG"]
                verdict_KEGG = res["verdict_KEGG"]
                null_stats = res["null_stats"]
                inter_list = res["intersections"]

                group_core[(cond_val, add_val, organ_val, model_val)] = {
                    # Combined
                    "S_obs": S_obs,
                    "mu": mu,
                    "sd": sd,
                    "p_right": p_right,
                    "p_left": p_left,
                    "p_two": p_two,
                    "effect_size": effect_size,
                    "verdict": verdict,
                    "A_size": len(A),
                    "B_size": len(B),
                    "U_size": len(U),
                    # GO-only
                    "S_obs_GO": S_obs_GO,
                    "mu_GO": mu_GO,
                    "p_right_GO": p_right_GO,
                    "effect_GO": effect_GO,
                    "verdict_GO": verdict_GO,
                    "A_GO_size": len(A_GO),
                    "B_GO_size": len(B_GO),
                    "U_GO_size": len(U_GO),
                    # KEGG-only
                    "S_obs_KEGG": S_obs_KEGG,
                    "mu_KEGG": mu_KEGG,
                    "p_right_KEGG": p_right_KEGG,
                    "effect_KEGG": effect_KEGG,
                    "verdict_KEGG": verdict_KEGG,
                    "A_KEGG_size": len(A_KEGG),
                    "B_KEGG_size": len(B_KEGG),
                    "U_KEGG_size": len(U_KEGG),
                }

                # Extract gene names from A_per_gene_raw
                gene_names = []
                for item in A_per_gene_raw:
                    if isinstance(item, dict) and "gene_name" in item:
                        gene_names.append(str(item["gene_name"]))
                gene_names_str = (
                    ",".join(sorted(set(gene_names))) if gene_names else "ALL_GENES"
                )

                # 1) summary row for this group
                fsum.write(
                    f"{gene_names_str}\t\t\t"
                    f"{overall_pathway_str}\t"
                    f"{cond_val}\t{add_val}\t{organ_val}\t{model_val}\t{res.get('category', '')}\t{res.get('comparison_control', '')}\t{res.get('comparison_condition', '')}\t{res.get('cell_type', '')}\t{res.get('day', '')}\t{res.get('factor', '')}\t{res.get('source', '')}\t"
                    f"{args.stat}\t{len(A)}\t{len(B)}\t{len(U)}\t"
                    f"{S_obs:.5f}\t{mu:.5f}\t{sd:.5f}\t{z:.5f}\t{args.R}\t"
                    f"{_format_p_value_tsv(p_right)}\t{_format_p_value_tsv(p_left)}\t{_format_p_value_tsv(p_two)}\t"
                    f'{use_strata}\t"{args.bins}"\t{args.alpha:.5f}\t{effect_size:.5f}\t{verdict}\t'
                    f"{len(A_GO)}\t{len(B_GO)}\t{len(U_GO)}\t{S_obs_GO:.5f}\t{mu_GO:.5f}\t{_format_p_value_tsv(p_right_GO)}\t{effect_GO:.5f}\t{verdict_GO}\t"
                    f"{len(A_KEGG)}\t{len(B_KEGG)}\t{len(U_KEGG)}\t{S_obs_KEGG:.5f}\t{mu_KEGG:.5f}\t{_format_p_value_tsv(p_right_KEGG)}\t{effect_KEGG:.5f}\t{verdict_KEGG}\n"
                )

                # 2) intersections for this group
                if not (args.light_output or args.skip_intersections):
                    for t in inter_list:
                        finter.write(
                            f"{cond_val}\t{add_val}\t{organ_val}\t{model_val}\t{res.get('category', '')}\t{res.get('comparison_control', '')}\t{res.get('comparison_condition', '')}\t{res.get('cell_type', '')}\t{res.get('day', '')}\t{res.get('factor', '')}\t{t}\n"
                        )

                # 3) null stats for this group
                if not (args.light_output or args.skip_null):
                    for i, s in enumerate(null_stats, 1):
                        fnull.write(
                            f"{cond_val}\t{add_val}\t{organ_val}\t{model_val}\t{res.get('category', '')}\t{res.get('comparison_control', '')}\t{res.get('comparison_condition', '')}\t{res.get('cell_type', '')}\t{res.get('day', '')}\t{res.get('factor', '')}\t{i}\t{s:.5f}\n"
                        )

                # groups.tsv and groups_summary.tsv are no longer written per requirement

                # --- Also write per-group outputs into a dedicated folder ---
                group_dirname = (
                    f"condition={_sanitize_name(cond_val)}"
                    f"__additional={_sanitize_name(add_val)}"
                    f"__organ={_sanitize_name(organ_val)}"
                    f"__model={_sanitize_name(model_val)}"
                    f"__factor={_sanitize_name(res.get('factor', ''))}"
                )
                group_dir = os.path.join(args.outdir, group_dirname)
                os.makedirs(group_dir, exist_ok=True)

                # (a) summary.tsv (single row with header)
                if not args.skip_group_summary:
                    group_summary = os.path.join(group_dir, "summary.tsv")
                    with open(group_summary, "w", encoding="utf-8") as gs:
                        gs.write(
                            "gene_name\tsimilarity_gene_name\tENTREZ_ID\tpathway\tcondition\tadditional_condition\torgan\tmodel\tcategory\tcomparison_control\tcomparison_condition\tcell_type\tday\tfactor\tsource\tstatistic\tA_size\tB_size\tU_size\tS_obs\tnull_mean\tnull_sd\tz_score\tR\tp_right\tp_left\tp_two_tailed\tstratified\tbins\talpha\teffect_size\tverdict\tA_GO_size\tB_GO_size\tU_GO_size\tS_obs_GO\tnull_mean_GO\tp_right_GO\teffect_size_GO\tverdict_GO\tA_KEGG_size\tB_KEGG_size\tU_KEGG_size\tS_obs_KEGG\tnull_mean_KEGG\tp_right_KEGG\teffect_size_KEGG\tverdict_KEGG\n"
                        )
                        gs.write(
                            f"{gene_names_str}\t\t\t"
                            f"{overall_pathway_str}\t"
                            f"{cond_val}\t{add_val}\t{organ_val}\t{model_val}\t{res.get('category', '')}\t{res.get('comparison_control', '')}\t{res.get('comparison_condition', '')}\t{res.get('cell_type', '')}\t{res.get('day', '')}\t{res.get('factor', '')}\t{res.get('source', '')}\t"
                            f"{args.stat}\t{len(A)}\t{len(B)}\t{len(U)}\t"
                            f"{S_obs:.5f}\t{mu:.5f}\t{sd:.5f}\t{z:.5f}\t{args.R}\t"
                            f"{_format_p_value_tsv(p_right)}\t{_format_p_value_tsv(p_left)}\t{_format_p_value_tsv(p_two)}\t"
                            f'{use_strata}\t"{args.bins}"\t{args.alpha:.5f}\t{effect_size:.5f}\t{verdict}\t'
                            f"{len(A_GO)}\t{len(B_GO)}\t{len(U_GO)}\t{S_obs_GO:.5f}\t{mu_GO:.5f}\t{_format_p_value_tsv(p_right_GO)}\t{effect_GO:.5f}\t{verdict_GO}\t"
                            f"{len(A_KEGG)}\t{len(B_KEGG)}\t{len(U_KEGG)}\t{S_obs_KEGG:.5f}\t{mu_KEGG:.5f}\t{_format_p_value_tsv(p_right_KEGG)}\t{effect_KEGG:.5f}\t{verdict_KEGG}\n"
                        )

                # (b) intersections.txt (one term per line)
                if not (args.skip_intersections or args.light_output):
                    group_inter = os.path.join(group_dir, "intersections.txt")
                    with open(group_inter, "w", encoding="utf-8") as gi:
                        for t in sorted(A & B):
                            gi.write(f"{t}\n")

                # (c) null_stats.tsv (permutation distribution for this group)
                if not (args.skip_null or args.light_output):
                    group_null = os.path.join(group_dir, "null_stats.tsv")
                    with open(group_null, "w", encoding="utf-8") as gn:
                        gn.write("iter\tstat\n")
                        for i, s in enumerate(null_stats, 1):
                            gn.write(f"{i}\t{s:.5f}\n")

                # (d) REPORT.md (LLM or fallback)
                if args.llm_explain and not (
                    args.skip_group_report or args.light_output
                ):
                    # choose TopN from overlap as the most intuitive linkage
                    overlap_terms = sorted(A & B)
                    top_ids = overlap_terms[: max(0, args.llm_max_terms)]

                    # Note: Evidence will be generated later after per-gene analysis is complete
                    # For now, use empty evidence in the prompt
                    ev_text_group = ""

                    # Build prompt
                    prompt = _make_llm_prompt(
                        disease=args.condition or "(unspecified)",
                        group_keys=(cond_val, add_val, organ_val, model_val),
                        go_ids=[t for t in top_ids if t.startswith("GO:")],
                        kegg_ids=[t for t in top_ids if not t.startswith("GO:")],
                        go_meta=go_meta,
                        kegg_meta=kegg_meta,
                        statistic=args.stat,
                        S_obs=S_obs,
                        null_mean=mu,
                        null_sd=sd,
                        p_right=p_right,
                        verdict=verdict,
                        effect_size=effect_size,
                        A_size=len(A),
                        B_size=len(B),
                        U_size=len(U),
                        top_overlap_ids=top_ids,
                        S_obs_GO=S_obs_GO,
                        null_mean_GO=mu_GO,
                        p_right_GO=p_right_GO,
                        verdict_GO=verdict_GO,
                        effect_size_GO=effect_GO,
                        A_GO_size=len(A_GO),
                        B_GO_size=len(B_GO),
                        U_GO_size=len(U_GO),
                        S_obs_KEGG=S_obs_KEGG,
                        null_mean_KEGG=mu_KEGG,
                        p_right_KEGG=p_right_KEGG,
                        verdict_KEGG=verdict_KEGG,
                        effect_size_KEGG=effect_KEGG,
                        A_KEGG_size=len(A_KEGG),
                        B_KEGG_size=len(B_KEGG),
                        U_KEGG_size=len(U_KEGG),
                        evidence_text=ev_text_group,
                    )
                    llm_text = ""
                    safe_to_call = True
                    if args.llm_guard and not (
                        verdict == "enriched"
                        and p_right < args.alpha
                        and effect_size > 0
                    ):
                        safe_to_call = False
                    if args.llm_explain and safe_to_call and args.llm_views in ("all", "combined"):
                        # MoE mode or single model mode
                        if args.llm_moe and args.llm_expert_models_parsed:
                            # MoE mode: multiple experts + reviewer
                            moe_result = _llm_moe_call(
                                disease=args.condition or "(unspecified)",
                                condition=cond_val,
                                additional_condition=add_val,
                                organ=organ_val,
                                model=model_val,
                                factor=args.factor or "",
                                statistic_method=args.stat,
                                S_obs=S_obs,
                                null_mean=mu,
                                null_sd=sd,
                                p_right=p_right,
                                effect_size=effect_size,
                                verdict=verdict,
                                go_ids=[t for t in top_ids if t.startswith("GO:")],
                                kegg_ids=[t for t in top_ids if t.startswith("hsa") or t.startswith("mmu")],
                                go_meta=go_meta,
                                kegg_meta=kegg_meta,
                                expert_models=args.llm_expert_models_parsed,
                                reviewer_model=args.llm_reviewer_model,
                                reviewer_base_url=args.llm_reviewer_base_url,
                                api_key=args.llm_api_key,
                                parallel=args.llm_moe_parallel,
                                timeout=args.llm_timeout,
                                protein_evidence=ev_text_group if ev_text_group else "",
                                top_n=args.llm_max_terms,
                            )
                            
                            llm_text = moe_result["final_report"]
                            
                            # Optionally append expert outputs
                            if args.llm_moe_show_experts and moe_result["expert_outputs"]:
                                llm_text += "\n\n<details><summary><b>Individual Expert Analyses (click to expand)</b></summary>\n\n"
                                for i, expert in enumerate(moe_result["expert_outputs"], 1):
                                    if expert["output"].strip():
                                        llm_text += f"#### Expert {i} - {expert['role']} ({expert['model']})\n\n"
                                        llm_text += expert["output"] + "\n\n"
                                llm_text += "</details>\n"
                            
                            # Add MoE metadata
                            meta = moe_result["metadata"]
                            llm_text += f"\n\n---\n*MoE Analysis: {meta['num_valid_experts']}/{meta['num_experts']} experts responded. "
                            llm_text += f"Total time: {meta['total_time']:.1f}s "
                            llm_text += f"(experts: {meta['expert_time']:.1f}s, reviewer: {meta['reviewer_time']:.1f}s). "
                            llm_text += f"Parallel: {meta['parallel']}*\n"
                        else:
                            # Single model mode (original behavior)
                            llm_text = _llm_call(
                                prompt=prompt,
                                model=args.llm_model,
                                api_key=args.llm_api_key,
                                base_url=args.llm_base_url,
                                timeout=args.llm_timeout,
                                llm_enabled=args.llm_explain,
                            )
                        
                        # Collect LLM outputs for JSON report
                        llm_group_map.setdefault(
                            (cond_val, add_val, organ_val, model_val), {}
                        )["combined"] = {
                            "text": (llm_text or "").strip(),
                            "prompt": (prompt if args.llm_dump_prompt else ""),
                        }
                    report_path = os.path.join(group_dir, "REPORT.md")

                    _write_report_md(
                        path=report_path,
                        title=f"Interpretation — condition={cond_val} | additional={add_val} | organ={organ_val} | model={model_val} | day={res.get('day', '')} | factor={res.get('factor', '')}",
                        prompt=prompt if args.llm_views in ("all", "combined") else "",
                        llm_text=(
                            llm_text
                            if (safe_to_call and args.llm_views in ("all", "combined"))
                            else ""
                        ),
                        dump_prompt=bool(args.llm_dump_prompt),
                        group_core={
                            "stat": args.stat,
                            "S_obs": S_obs,
                            "mu": mu,
                            "sd": sd,
                            "p_right": p_right,
                            "effect_size": effect_size,
                            "verdict": verdict,
                            "S_obs_GO": S_obs_GO,
                            "mu_GO": mu_GO,
                            "p_right_GO": p_right_GO,
                            "effect_GO": effect_GO,
                            "verdict_GO": verdict_GO,
                            "S_obs_KEGG": S_obs_KEGG,
                            "mu_KEGG": mu_KEGG,
                            "p_right_KEGG": p_right_KEGG,
                            "effect_KEGG": effect_KEGG,
                            "verdict_KEGG": verdict_KEGG,
                        },
                        go_ids=[t for t in top_ids if t.startswith("GO:")],
                        kegg_ids=[t for t in top_ids if not t.startswith("GO:")],
                    )

                    # Optionally append GO-only and KEGG-only LLM interpretations (controlled by --llm-views)
                    if args.llm_explain and args.llm_views in ("all", "go", "kegg"):
                        go_only_ids = [t for t in top_ids if t.startswith("GO:")]
                        kegg_only_ids = [t for t in top_ids if not t.startswith("GO:")]
                        with open(report_path, "a", encoding="utf-8") as rf:
                            if args.llm_views in ("all", "go") and go_only_ids:
                                go_safe = True
                                if args.llm_guard and not (
                                    verdict_GO == "enriched"
                                    and (p_right_GO < args.alpha)
                                    and (effect_GO > 0)
                                ):
                                    go_safe = False
                                go_text = ""
                                go_prompt = _make_llm_prompt(
                                    disease=args.condition or "(unspecified)",
                                    group_keys=(
                                        cond_val,
                                        add_val,
                                        organ_val,
                                        model_val,
                                    ),
                                    go_ids=go_only_ids,
                                    kegg_ids=[],
                                    go_meta=go_meta,
                                    kegg_meta=kegg_meta,
                                    statistic=args.stat,
                                    S_obs=S_obs_GO,
                                    null_mean=mu_GO,
                                    null_sd=float("nan"),
                                    p_right=p_right_GO,
                                    verdict=verdict_GO,
                                    effect_size=effect_GO,
                                    A_size=len(A_GO),
                                    B_size=len(B_GO),
                                    U_size=len(U_GO),
                                    top_overlap_ids=go_only_ids,
                                    S_obs_GO=S_obs_GO,
                                    null_mean_GO=mu_GO,
                                    p_right_GO=p_right_GO,
                                    verdict_GO=verdict_GO,
                                    effect_size_GO=effect_GO,
                                    A_GO_size=len(A_GO),
                                    B_GO_size=len(B_GO),
                                    U_GO_size=len(U_GO),
                                    evidence_text=ev_text_group,
                                )
                                if go_safe:
                                    go_text = _llm_call(
                                        prompt=go_prompt,
                                        model=args.llm_model,
                                        api_key=args.llm_api_key,
                                        base_url=args.llm_base_url,
                                        timeout=args.llm_timeout,
                                        llm_enabled=args.llm_explain,
                                    )
                                    # Collect GO-only LLM outputs for JSON report
                                    llm_group_map.setdefault(
                                        (cond_val, add_val, organ_val, model_val), {}
                                    )["go"] = {
                                        "text": (go_text or "").strip(),
                                        "prompt": (
                                            go_prompt if args.llm_dump_prompt else ""
                                        ),
                                    }
                                rf.write("\n## GO-only LLM interpretation\n\n")
                                if go_safe and go_text.strip():
                                    rf.write(_normalize_llm_text(go_text))
                                else:
                                    rf.write(
                                        "*GO-only interpretation unavailable (guarded or empty response).*\n\n"
                                    )
                                if args.llm_dump_prompt and go_prompt.strip():
                                    rf.write(
                                        "<details><summary>Prompt (GO-only)</summary>\n\n```\n"
                                        + go_prompt
                                        + "\n```\n</details>\n\n"
                                    )

                            if args.llm_views in ("all", "kegg") and kegg_only_ids:
                                ke_safe = True
                                if args.llm_guard and not (
                                    verdict_KEGG == "enriched"
                                    and (p_right_KEGG < args.alpha)
                                    and (effect_KEGG > 0)
                                ):
                                    ke_safe = False
                                ke_text = ""
                                ke_prompt = _make_llm_prompt(
                                    disease=args.condition or "(unspecified)",
                                    group_keys=(
                                        cond_val,
                                        add_val,
                                        organ_val,
                                        model_val,
                                    ),
                                    go_ids=[],
                                    kegg_ids=kegg_only_ids,
                                    go_meta=go_meta,
                                    kegg_meta=kegg_meta,
                                    statistic=args.stat,
                                    S_obs=S_obs_KEGG,
                                    null_mean=mu_KEGG,
                                    null_sd=float("nan"),
                                    p_right=p_right_KEGG,
                                    verdict=verdict_KEGG,
                                    effect_size=effect_KEGG,
                                    A_size=len(A_KEGG),
                                    B_size=len(B_KEGG),
                                    U_size=len(U_KEGG),
                                    top_overlap_ids=kegg_only_ids,
                                    S_obs_KEGG=S_obs_KEGG,
                                    null_mean_KEGG=mu_KEGG,
                                    p_right_KEGG=p_right_KEGG,
                                    verdict_KEGG=verdict_KEGG,
                                    effect_size_KEGG=effect_KEGG,
                                    A_KEGG_size=len(A_KEGG),
                                    B_KEGG_size=len(B_KEGG),
                                    U_KEGG_size=len(U_KEGG),
                                    evidence_text=ev_text_group,
                                )
                                if ke_safe:
                                    ke_text = _llm_call(
                                        prompt=ke_prompt,
                                        model=args.llm_model,
                                        api_key=args.llm_api_key,
                                        base_url=args.llm_base_url,
                                        timeout=args.llm_timeout,
                                        llm_enabled=args.llm_explain,
                                    )
                                    # Collect KEGG-only LLM outputs for JSON report
                                    llm_group_map.setdefault(
                                        (cond_val, add_val, organ_val, model_val), {}
                                    )["kegg"] = {
                                        "text": (ke_text or "").strip(),
                                        "prompt": (
                                            ke_prompt if args.llm_dump_prompt else ""
                                        ),
                                    }
                                rf.write("\n## KEGG-only LLM interpretation\n\n")
                                if ke_safe and ke_text.strip():
                                    rf.write(_normalize_llm_text(ke_text))
                                else:
                                    rf.write(
                                        "*KEGG-only interpretation unavailable (guarded or empty response).*\n\n"
                                    )
                                if args.llm_dump_prompt and ke_prompt.strip():
                                    rf.write(
                                        "<details><summary>Prompt (KEGG-only)</summary>\n\n```\n"
                                        + ke_prompt
                                        + "\n```\n</details>\n\n"
                                    )

        # Per-gene consolidated output (always on) with optional BH adjustment and scope control
        # This section ALWAYS runs to ensure summary_per_gene.tsv is created
        per_out = os.path.join(args.outdir, "summary_per_gene.tsv")
        print(f"[{_now()}] Generating per-gene summary: {per_out}")
        with open(per_out, "w", encoding="utf-8") as pg:
            pg.write(
                "gene_name\tsimilarity_gene_name\tENTREZ_ID\tpathway\tcondition\tadditional_condition\torgan\tmodel\tcategory\tcomparison_control\tcomparison_condition\tcell_type\tday\tfactor\tsource\tstatistic\tA_size\tB_size\tU_size\tS_obs\tnull_mean\tnull_sd\tz_score\tR\tp_right\tp_left\tp_two_tailed\tq_value\tA_GO_size\tB_GO_size\tS_obs_GO\tp_right_GO\teffect_size_GO\tverdict_GO\tA_KEGG_size\tB_KEGG_size\tS_obs_KEGG\tp_right_KEGG\teffect_size_KEGG\tverdict_KEGG\tstratified\tbins\talpha\teffect_size\tverdict\n"
            )

            # Common settings
            if args.stat == "overlap":
                stat_fn = overlap
            elif args.stat == "jaccard":
                stat_fn = jaccard
            elif args.stat == "hypergeometric":
                stat_fn = None  # hypergeometric handled explicitly
            else:
                stat_fn = None  # semantic handled explicitly
            rng_for_group = make_group_rng(
                args.seed, getattr(args, "rng_scope", "global")
            )
            use_strata = bool(size_map)

            all_rows = []
            group_rows_map: dict[tuple[str, str, str, str], list[dict]] = {}

            for (cond_val, add_val, organ_val, model_val), B_raw in groups.items():
                B = set(B_raw) & U
                B_GO = B & U_GO
                B_KEGG = B & U_KEGG

                # Reuse cached random B-like sets for this group
                rng_group = rng_for_group((cond_val, add_val, organ_val, model_val))
                
                # Use GO structured stratification if available
                if (isinstance(U_buckets_GO, dict) and args.stat in ["semantic", "overlap", "jaccard"] and 
                    getattr(args, 'go_structured_stratification', False)):
                    # Use GO structured buckets for GO terms, regular buckets for others
                    B_randoms = make_B_randoms(
                        B,
                        U_list,
                        U_buckets_GO,  # Use GO structured buckets
                        size_map if use_strata else None,
                        bins,
                        rng_group,
                        args.R,
                        desc=f"Generating per-gene permutations ({cond_val}/{add_val}/{organ_val}/{model_val})",
                        go_ns_map=go_ns_map if 'go_ns_map' in locals() else None,
                        go_depth_map=go_depth_map if 'go_depth_map' in locals() else None,
                        go_depth_bins=depth_bins if 'depth_bins' in locals() else None,
                    )
                else:
                    # Use standard stratification
                    B_randoms = make_B_randoms(
                        B,
                        U_list,
                        U_buckets,
                        size_map if use_strata else None,
                        bins,
                        rng_group,
                        args.R,
                        desc=f"Generating per-gene permutations ({cond_val}/{add_val}/{organ_val}/{model_val})",
                    )
                B_randoms_GO = [(br & U_GO) if br else set() for br in B_randoms]
                B_randoms_KEGG = [(br & U_KEGG) if br else set() for br in B_randoms]
                if "bitset_mode" in locals() and bitset_mode:
                    B_bits = _encode_bits(B, idx_map)
                    B_randoms_bits = [_encode_bits(br, idx_map) for br in B_randoms]

                rows = []
                # Prepare per-gene inputs
                gene_inputs = []
                for rec in per_gene_aligned:
                    A_g = set(rec.get("pathway", []))
                    if not A_g:
                        continue
                    A_g_GO = A_g & U_GO
                    A_g_KEGG = A_g & U_KEGG
                    if (
                        "bitset_mode" in locals()
                        and bitset_mode
                        and args.stat in ("overlap", "jaccard")
                    ):
                        A_g_bits = _encode_bits(A_g, idx_map)
                    else:
                        A_g_bits = None
                    gene_inputs.append((rec, A_g, A_g_GO, A_g_KEGG, A_g_bits))

                def _compute_gene_row_seq(rec, A_g, A_g_GO, A_g_KEGG, A_g_bits):
                    # Observed statistic for this gene
                    if args.stat == "semantic":
                        if args.semantic_method == "closure_jaccard":
                            s_go_g = _semantic_go_component(A_g_GO, B_GO, go_anc, ic_map)
                        elif args.semantic_method == "resnik_bma":
                            ns_map = _load_go_namespace(args.go_namespace)
                            s_go_g = semantic_go_similarity(A_g_GO, B_GO, go_anc, ic_map, ns_map, method="resnik_bma")
                        elif args.semantic_method == "lin_bma":
                            ns_map = _load_go_namespace(args.go_namespace)
                            s_go_g = semantic_go_similarity(A_g_GO, B_GO, go_anc, ic_map, ns_map, method="lin_bma")
                        
                        s_ke_g = _semantic_kegg_component_enhanced(
                            A_g_KEGG, B_KEGG, 
                            base=args.semantic_kegg_base,
                            topology_analyzer=topology_analyzer,
                            topology_method=args.kegg_topology_method
                        )
                        S_obs_g = _combine_go_kegg(
                            s_go_g,
                            s_ke_g,
                            A_g_GO,
                            B_GO,
                            A_g_KEGG,
                            B_KEGG,
                            args.semantic_kegg_base,
                        )
                    elif args.stat == "hypergeometric":
                        # Perform hypergeometric enrichment test for this gene
                        hypergeometric_result_g = hypergeometric_enrichment(A_g, B, U)
                        S_obs_g = hypergeometric_result_g['enrichment_score']
                        p_value_g = hypergeometric_result_g['p_value']
                        odds_ratio_g = hypergeometric_result_g['odds_ratio']
                        overlap_count_g = hypergeometric_result_g['overlap_count']
                    else:
                        if bitset_mode and A_g_bits is not None:
                            S_obs_g = (
                                _overlap_bits(A_g_bits, B_bits)
                                if args.stat == "overlap"
                                else _jaccard_bits(A_g_bits, B_bits)
                            )
                        else:
                            S_obs_g = stat_fn(A_g, B)

                    # Null distribution using cached B_randoms
                    null_stats_g = []
                    if args.stat in ["hypergeometric"]:
                        # For hypergeometric test, we don't need permutations
                        # We'll handle this directly in the main logic
                        pass
                    else:
                        for i, B_rand in enumerate(B_randoms):
                            if args.stat == "semantic":
                                br_go = B_randoms_GO[i]
                                br_ke = B_randoms_KEGG[i]
                                if args.semantic_method == "closure_jaccard":
                                    s_go = _semantic_go_component(A_g_GO, br_go, go_anc, ic_map)
                                elif args.semantic_method == "resnik_bma":
                                    ns_map = _load_go_namespace(args.go_namespace)
                                    s_go = semantic_go_similarity(A_g_GO, br_go, go_anc, ic_map, ns_map, method="resnik_bma")
                                elif args.semantic_method == "lin_bma":
                                    ns_map = _load_go_namespace(args.go_namespace)
                                    s_go = semantic_go_similarity(A_g_GO, br_go, go_anc, ic_map, ns_map, method="lin_bma")
                                
                                s_ke = _semantic_kegg_component_enhanced(
                                    A_g_KEGG, br_ke, 
                                    base=args.semantic_kegg_base,
                                    topology_analyzer=topology_analyzer,
                                    topology_method=args.kegg_topology_method
                                )
                                null_stats_g.append(
                                    _combine_go_kegg(
                                        s_go,
                                        s_ke,
                                        A_g_GO,
                                        br_go,
                                        A_g_KEGG,
                                        br_ke,
                                        args.semantic_kegg_base,
                                    )
                                )
                            else:
                                if bitset_mode and A_g_bits is not None:
                                    br_bits = B_randoms_bits[i]
                                    null_stats_g.append(
                                        _overlap_bits(A_g_bits, br_bits)
                                        if args.stat == "overlap"
                                        else _jaccard_bits(A_g_bits, br_bits)
                                    )
                                else:
                                    null_stats_g.append(stat_fn(A_g, B_rand))

                    if args.stat == "hypergeometric":
                        # For hypergeometric test, use the calculated p-value
                        mu_g = float("nan")
                        sd_g = float("nan")
                        z_g = float("nan")
                        p_right_g = p_value_g
                        p_left_g = 1.0 - p_value_g
                        p_two_g = 2 * min(p_value_g, 1.0 - p_value_g)
                        effect_g = odds_ratio_g
                        verdict_g = "enriched" if (p_value_g < args.alpha and odds_ratio_g > 1) else "not_significant"
                    else:
                        mu_g, sd_g, p_right_g, p_left_g, p_two_g, effect_g = (
                            _summarize_null(null_stats_g, S_obs_g, args.R)
                        )
                        z_g = (effect_g / sd_g) if (sd_g and sd_g > 0) else float("nan")
                        verdict_g = (
                            "enriched"
                            if (p_right_g < args.alpha and effect_g > 0)
                            else (
                                "depleted"
                                if (p_left_g < args.alpha and effect_g < 0)
                                else "not_significant"
                            )
                        )

                    # GO-only per-gene
                    if args.stat == "hypergeometric":
                        # Perform hypergeometric enrichment test for GO terms
                        if A_g_GO and B_GO:
                            hypergeometric_result_GO_g = hypergeometric_enrichment(A_g_GO, B_GO, U_GO)
                            S_obs_GO_g = hypergeometric_result_GO_g['enrichment_score']
                            p_right_GO_g = hypergeometric_result_GO_g['p_value']
                            effect_GO_g = hypergeometric_result_GO_g['odds_ratio']
                            verdict_GO_g = "enriched" if (p_right_GO_g < args.alpha and effect_GO_g > 1) else "not_significant"
                        else:
                            S_obs_GO_g = 0.0
                            p_right_GO_g = 1.0
                            effect_GO_g = 0.0
                            verdict_GO_g = "not_applicable"
                        mu_GO_g = float("nan")
                    elif A_g_GO:
                        null_stats_GO_g = []
                        for ix, br_go in enumerate(B_randoms_GO):
                            if args.stat == "semantic":
                                if args.semantic_method == "closure_jaccard":
                                    null_stats_GO_g.append(
                                        _semantic_go_component(
                                            A_g_GO, br_go, go_anc, ic_map
                                        )
                                    )
                                elif args.semantic_method == "resnik_bma":
                                    ns_map = _load_go_namespace(args.go_namespace)
                                    null_stats_GO_g.append(
                                        semantic_go_similarity(A_g_GO, br_go, go_anc, ic_map, ns_map, method="resnik_bma")
                                    )
                                elif args.semantic_method == "lin_bma":
                                    ns_map = _load_go_namespace(args.go_namespace)
                                    null_stats_GO_g.append(
                                        semantic_go_similarity(A_g_GO, br_go, go_anc, ic_map, ns_map, method="lin_bma")
                                    )
                            else:
                                if bitset_mode and A_g_bits is not None:
                                    null_stats_GO_g.append(
                                        _overlap_bits(
                                            A_g_bits & GO_mask,
                                            B_randoms_bits[ix] & GO_mask,
                                        )
                                        if args.stat == "overlap"
                                        else _jaccard_bits(
                                            A_g_bits & GO_mask,
                                            B_randoms_bits[ix] & GO_mask,
                                        )
                                    )
                                else:
                                    null_stats_GO_g.append(stat_fn(A_g_GO, br_go))
                        if args.stat == "semantic":
                            if B_GO:
                                if args.semantic_method == "closure_jaccard":
                                    S_obs_GO_g = _semantic_go_component(A_g_GO, B_GO, go_anc, ic_map)
                                elif args.semantic_method == "resnik_bma":
                                    ns_map = _load_go_namespace(args.go_namespace)
                                    S_obs_GO_g = semantic_go_similarity(A_g_GO, B_GO, go_anc, ic_map, ns_map, method="resnik_bma")
                                elif args.semantic_method == "lin_bma":
                                    ns_map = _load_go_namespace(args.go_namespace)
                                    S_obs_GO_g = semantic_go_similarity(A_g_GO, B_GO, go_anc, ic_map, ns_map, method="lin_bma")
                            else:
                                S_obs_GO_g = 0.0
                        else:
                            if bitset_mode and A_g_bits is not None:
                                S_obs_GO_g = (
                                    (
                                        _overlap_bits(
                                            A_g_bits & GO_mask, B_bits & GO_mask
                                        )
                                        if args.stat == "overlap"
                                        else _jaccard_bits(
                                            A_g_bits & GO_mask, B_bits & GO_mask
                                        )
                                    )
                                    if B_GO
                                    else 0.0
                                )
                            else:
                                S_obs_GO_g = stat_fn(A_g_GO, B_GO) if B_GO and stat_fn else 0.0
                        if _NP_AVAILABLE and null_stats_GO_g:
                            arr_go_g = _np.asarray(null_stats_GO_g, dtype=float)
                            mu_GO_g = float(arr_go_g.mean())
                            right_GO_g = int((arr_go_g >= S_obs_GO_g).sum())
                        else:
                            mu_GO_g = mean(null_stats_GO_g) if null_stats_GO_g else 0.0
                            right_GO_g = sum(
                                1 for s in null_stats_GO_g if s >= S_obs_GO_g
                            )
                        p_right_GO_g = (
                            (right_GO_g + 1) / (args.R + 1) if args.R > 0 else 1.0
                        )
                        effect_GO_g = S_obs_GO_g - mu_GO_g
                        verdict_GO_g = (
                            "enriched"
                            if (p_right_GO_g < args.alpha and effect_GO_g > 0)
                            else (
                                "depleted"
                                if (
                                    S_obs_GO_g < mu_GO_g
                                    and (1 - p_right_GO_g) < args.alpha
                                )
                                else "not_significant"
                            )
                        )
                    else:
                        S_obs_GO_g = 0.0
                        p_right_GO_g = 1.0
                        effect_GO_g = 0.0
                        verdict_GO_g = "not_applicable"

                    # KEGG-only per-gene
                    if args.stat == "hypergeometric":
                        # Perform hypergeometric enrichment test for KEGG terms
                        if A_g_KEGG and B_KEGG:
                            hypergeometric_result_KEGG_g = hypergeometric_enrichment(A_g_KEGG, B_KEGG, U_KEGG)
                            S_obs_KEGG_g = hypergeometric_result_KEGG_g['enrichment_score']
                            p_right_KEGG_g = hypergeometric_result_KEGG_g['p_value']
                            effect_KEGG_g = hypergeometric_result_KEGG_g['odds_ratio']
                            verdict_KEGG_g = "enriched" if (p_right_KEGG_g < args.alpha and effect_KEGG_g > 1) else "not_significant"
                        else:
                            S_obs_KEGG_g = 0.0
                            p_right_KEGG_g = 1.0
                            effect_KEGG_g = 0.0
                            verdict_KEGG_g = "not_applicable"
                        mu_KEGG_g = float("nan")
                    elif A_g_KEGG:
                        null_stats_KEGG_g = []
                        for ix, br_ke in enumerate(B_randoms_KEGG):
                            if args.stat == "semantic":
                                null_stats_KEGG_g.append(
                                    _semantic_kegg_component_enhanced(
                                        A_g_KEGG, br_ke, 
                                        base=args.semantic_kegg_base,
                                        topology_analyzer=topology_analyzer,
                                        topology_method=args.kegg_topology_method
                                    )
                                )
                            else:
                                if bitset_mode and A_g_bits is not None:
                                    null_stats_KEGG_g.append(
                                        _overlap_bits(
                                            A_g_bits & KEGG_mask,
                                            B_randoms_bits[ix] & KEGG_mask,
                                        )
                                        if args.stat == "overlap"
                                        else _jaccard_bits(
                                            A_g_bits & KEGG_mask,
                                            B_randoms_bits[ix] & KEGG_mask,
                                        )
                                    )
                                else:
                                    null_stats_KEGG_g.append(stat_fn(A_g_KEGG, br_ke))
                        if args.stat == "semantic":
                            S_obs_KEGG_g = (
                                _semantic_kegg_component_enhanced(
                                    A_g_KEGG, B_KEGG, 
                                    base=args.semantic_kegg_base,
                                    topology_analyzer=topology_analyzer,
                                    topology_method=args.kegg_topology_method
                                )
                                if B_KEGG
                                else 0.0
                            )
                        else:
                            if bitset_mode and A_g_bits is not None:
                                S_obs_KEGG_g = (
                                    (
                                        _overlap_bits(
                                            A_g_bits & KEGG_mask, B_bits & KEGG_mask
                                        )
                                        if args.stat == "overlap"
                                        else _jaccard_bits(
                                            A_g_bits & KEGG_mask, B_bits & KEGG_mask
                                        )
                                    )
                                    if B_KEGG
                                    else 0.0
                                )
                            else:
                                S_obs_KEGG_g = (
                                    stat_fn(A_g_KEGG, B_KEGG) if B_KEGG and stat_fn else 0.0
                                )
                        if _NP_AVAILABLE and null_stats_KEGG_g:
                            arr_ke_g = _np.asarray(null_stats_KEGG_g, dtype=float)
                            mu_KEGG_g = float(arr_ke_g.mean())
                            right_KEGG_g = int((arr_ke_g >= S_obs_KEGG_g).sum())
                        else:
                            mu_KEGG_g = (
                                mean(null_stats_KEGG_g) if null_stats_KEGG_g else 0.0
                            )
                            right_KEGG_g = sum(
                                1 for s in null_stats_KEGG_g if s >= S_obs_KEGG_g
                            )
                        p_right_KEGG_g = (
                            (right_KEGG_g + 1) / (args.R + 1) if args.R > 0 else 1.0
                        )
                        effect_KEGG_g = S_obs_KEGG_g - mu_KEGG_g
                        verdict_KEGG_g = (
                            "enriched"
                            if (p_right_KEGG_g < args.alpha and effect_KEGG_g > 0)
                            else (
                                "depleted"
                                if (
                                    S_obs_KEGG_g < mu_KEGG_g
                                    and (1 - p_right_KEGG_g) < args.alpha
                                )
                                else "not_significant"
                            )
                        )
                    else:
                        S_obs_KEGG_g = 0.0
                        p_right_KEGG_g = 1.0
                        effect_KEGG_g = 0.0
                        verdict_KEGG_g = "not_applicable"

                    row = {
                        "gene_name": rec.get("gene_name", ""),
                        "similarity_gene_name": rec.get("similarity_gene_name", ""),
                        "ENTREZ_ID": rec.get("ENTREZ_ID", ""),
                        "pathway_str": ",".join(sorted(A_g)),
                        "condition": cond_val,
                        "additional_condition": add_val,
                        "organ": organ_val,
                        "model": model_val,
                        "factor": res.get("factor", ""),
                        "day": res.get("day", ""),
                        "source": res.get("source", ""),
                        "category": res.get("category", ""),
                        "comparison_condition": res.get("comparison_condition", ""),
                        "cell_type": res.get("cell_type", ""),
                        "A_size": len(A_g),
                        "B_size": len(B),
                        "U_size": len(U),
                        "S_obs": S_obs_g,
                        "mu": mu_g,
                        "sd": sd_g,
                        "z": z_g,
                        "p_right": p_right_g,
                        "p_left": p_left_g,
                        "p_two": p_two_g,
                        "effect": effect_g,
                        "verdict": verdict_g,
                        "A_GO_size": len(A_g_GO),
                        "B_GO_size": len(B_GO),
                        "S_obs_GO": S_obs_GO_g,
                        "mu_GO": mu_GO_g if A_g_GO else float("nan"),
                        "p_right_GO": p_right_GO_g,
                        "effect_GO": effect_GO_g,
                        "verdict_GO": verdict_GO_g,
                        "A_KEGG_size": len(A_g_KEGG),
                        "B_KEGG_size": len(B_KEGG),
                        "S_obs_KEGG": S_obs_KEGG_g,
                        "mu_KEGG": mu_KEGG_g if A_g_KEGG else float("nan"),
                        "p_right_KEGG": p_right_KEGG_g,
                        "effect_KEGG": effect_KEGG_g,
                        "verdict_KEGG": verdict_KEGG_g,
                    }
                    return row

                use_pool = (
                    getattr(args, "jobs", 1)
                    and args.jobs > 1
                    and (args.stat in ("overlap", "jaccard"))
                    and ("bitset_mode" in locals() and bitset_mode)
                )
                if use_pool and gene_inputs:
                    print(f"  Processing {len(gene_inputs)} genes with {args.jobs} workers")
                    try:
                        with _fut.ProcessPoolExecutor(max_workers=args.jobs) as ex:
                            # Use submit for better error handling
                            future_to_gene = {
                                ex.submit(_compute_gene_row_seq, *tpl): tpl for tpl in gene_inputs
                            }
                            rows = []
                            for future in _fut.as_completed(future_to_gene):
                                try:
                                    result = future.result()
                                    rows.append(result)
                                except Exception as e:
                                    gene_info = future_to_gene[future]
                                    print(f"  [WARN] Gene {gene_info[0]} failed: {e}", file=sys.stderr)
                                    # Create empty result for failed gene
                                    rows.append({
                                        "gene": gene_info[0],
                                        "S_obs": 0.0,
                                        "mu": float("nan"),
                                        "sd": float("nan"),
                                        "p_right": 1.0,
                                        "p_left": 1.0,
                                        "p_two": 1.0,
                                        "effect": 0.0,
                                        "z": float("nan"),
                                        "S_obs_GO": 0.0,
                                        "mu_GO": float("nan"),
                                        "sd_GO": float("nan"),
                                        "p_right_GO": 1.0,
                                        "p_left_GO": 1.0,
                                        "p_two_GO": 1.0,
                                        "effect_GO": 0.0,
                                        "z_GO": float("nan"),
                                        "S_obs_KEGG": 0.0,
                                        "mu_KEGG": float("nan"),
                                        "sd_KEGG": float("nan"),
                                        "p_right_KEGG": 1.0,
                                        "p_left_KEGG": 1.0,
                                        "p_two_KEGG": 1.0,
                                        "effect_KEGG": 0.0,
                                        "z_KEGG": float("nan"),
                                    })
                    except Exception:
                        # Fallback gracefully when process-based parallelism is not permitted
                        try:
                            with _fut.ThreadPoolExecutor(max_workers=args.jobs) as ex:
                                future_to_gene = {
                                    ex.submit(_compute_gene_row_seq, *tpl): tpl for tpl in gene_inputs
                                }
                                rows = []
                                for future in _fut.as_completed(future_to_gene):
                                    try:
                                        result = future.result()
                                        rows.append(result)
                                    except Exception as e:
                                        gene_info = future_to_gene[future]
                                        print(f"  [WARN] Gene {gene_info[0]} failed: {e}", file=sys.stderr)
                                        rows.append({
                                            "gene": gene_info[0],
                                            "S_obs": 0.0,
                                            "mu": float("nan"),
                                            "sd": float("nan"),
                                            "p_right": 1.0,
                                            "p_left": 1.0,
                                            "p_two": 1.0,
                                            "effect": 0.0,
                                            "z": float("nan"),
                                        })
                        except Exception:
                            rows = [_compute_gene_row_seq(*tpl) for tpl in gene_inputs]
                else:
                    rows = [_compute_gene_row_seq(*tpl) for tpl in gene_inputs]

                # append rows
                for r in rows:
                    all_rows.append(r)

                group_rows_map[(cond_val, add_val, organ_val, model_val)] = rows

            # === Compute q-values and write per-gene table ===
            # Always compute BH-FDR corrected q-values
            if args.adjust_scope == "global":
                p_all = [r.get("p_right", 1.0) for r in all_rows]
                q_all = _bh_fdr(p_all)
                for r, qv in zip(all_rows, q_all):
                    r["q_value"] = float(f"{qv:.5f}")
            else:
                for key, rows in group_rows_map.items():
                    pvals = [r.get("p_right", 1.0) for r in rows]
                    qvals = _bh_fdr(pvals)
                    for r, qv in zip(rows, qvals):
                        r["q_value"] = float(f"{qv:.5f}")

            # Write per-gene table rows
            for key, rows in group_rows_map.items():
                cond_val, add_val, organ_val, model_val = key
                res = group_metadata.get(key, {})
                for r in rows:
                    pg.write(
                        f"{r['gene_name']}\t{r['similarity_gene_name']}\t{r['ENTREZ_ID']}\t{r['pathway_str']}\t"
                        f"{cond_val}\t{add_val}\t{organ_val}\t{model_val}\t{res.get('category', '')}\t{res.get('comparison_control', '')}\t{res.get('comparison_condition', '')}\t{res.get('cell_type', '')}\t{res.get('day', '')}\t{res.get('factor', '')}\t{res.get('source', '')}\t"
                        f"{args.stat}\t{r['A_size']}\t{r['B_size']}\t{r['U_size']}\t"
                        f"{_fmt5(r['S_obs'])}\t{_fmt5(r['mu'])}\t{_fmt5(r['sd'])}\t{_fmt5(r['z'])}\t{args.R}\t"
                        f"{_fmt5(r['p_right'])}\t{_fmt5(r['p_left'])}\t{_fmt5(r['p_two'])}\t{_fmt5(r['q_value'])}\t"
                        f"{r['A_GO_size']}\t{r['B_GO_size']}\t{_fmt5(r['S_obs_GO'])}\t{_fmt5(r['p_right_GO'])}\t{_fmt5(r['effect_GO'])}\t{r['verdict_GO']}\t"
                        f"{r['A_KEGG_size']}\t{r['B_KEGG_size']}\t{_fmt5(r['S_obs_KEGG'])}\t{_fmt5(r['p_right_KEGG'])}\t{_fmt5(r['effect_KEGG'])}\t{r['verdict_KEGG']}\t"
                        f"{use_strata}\t\"{args.bins}\"\t{args.alpha:.5f}\t{_fmt5(r['effect'])}\t{r['verdict']}\n"
                    )

        # === Aggregate over per-gene and patch summaries ===
        agg_q_map: dict[tuple[str, str, str, str], float] = {}
        agg_p_map: dict[tuple[str, str, str, str], float] = {}
        if args.aggregate_q != "none":

            def _collect(vals: list[float], method: str) -> float:
                vals = [v for v in vals if v is not None and not math.isnan(float(v))]
                if not vals:
                    return float("nan")
                if method == "min":
                    return float(f"{_combine_min(vals):.5f}")
                if method == "simes":
                    return float(f"{_combine_simes(vals):.5f}")
                if method == "stouffer":
                    return float(f"{_combine_stouffer(vals):.5f}")
                return float("nan")

            for key, rows in group_rows_map.items():
                if not rows:
                    continue
                q_vals = [r.get("q_value", float("nan")) for r in rows]
                p_vals = [r.get("p_right", float("nan")) for r in rows]
                agg_q_map[key] = _collect(q_vals, args.aggregate_q)
                agg_p_map[key] = _collect(p_vals, args.aggregate_q)

            def _patch_summary_file(
                path: str,
                cond_key: str | None = None,
                add_key: str | None = None,
                organ_key: str | None = None,
                model_key: str | None = None,
            ):
                if not os.path.exists(path):
                    return
                with open(path, "r", encoding="utf-8") as f:
                    lines = [ln.rstrip("\n") for ln in f]
                if not lines:
                    return
                hdr = lines[0].split("\t")
                try:
                    strat_idx = hdr.index("stratified")
                except ValueError:
                    strat_idx = len(hdr)
                if args.aggregate_q_report == "both":
                    new_cols_hdr = [
                        "aggregate_method",
                        "aggregate_over_q",
                        "aggregate_over_p",
                    ]
                else:
                    new_cols_hdr = ["aggregate_method", "aggregate_q"]
                new_hdr = hdr[:strat_idx] + new_cols_hdr + hdr[strat_idx:]
                out_lines = ["\t".join(new_hdr)]
                try:
                    cond_idx = hdr.index("condition")
                    add_idx = hdr.index("additional_condition")
                    organ_idx = hdr.index("organ")
                    model_idx = hdr.index("model")
                except ValueError:
                    cond_idx = add_idx = organ_idx = model_idx = None
                for ln in lines[1:]:
                    if not ln.strip():
                        out_lines.append(ln)
                        continue
                    cols = ln.split("\t")
                    if None not in (cond_idx, add_idx, organ_idx, model_idx) and len(
                        cols
                    ) > max(cond_idx, add_idx, organ_idx, model_idx):
                        cval = cols[cond_idx]
                        aval = cols[add_idx]
                        oval = cols[organ_idx]
                        mval = cols[model_idx]
                    else:
                        cval = cond_key or ""
                        aval = add_key or ""
                        oval = organ_key or ""
                        mval = model_key or ""
                    aq = agg_q_map.get((cval, aval, oval, mval), float("nan"))
                    ap = agg_p_map.get((cval, aval, oval, mval), float("nan"))
                    if args.aggregate_q_report == "both":
                        ins = [
                            args.aggregate_q,
                            (
                                _fmt5(aq)
                                if isinstance(aq, float) and not math.isnan(aq)
                                else ""
                            ),
                            (
                                _fmt5(ap)
                                if isinstance(ap, float) and not math.isnan(ap)
                                else ""
                            ),
                        ]
                    else:
                        use = aq  # Always use q-value since we always compute BH-FDR
                        ins = [
                            args.aggregate_q,
                            (
                                _fmt5(use)
                                if isinstance(use, float) and not math.isnan(use)
                                else ""
                            ),
                        ]
                    new_cols = cols[:strat_idx] + ins + cols[strat_idx:]
                    out_lines.append("\t".join(new_cols))
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(out_lines) + "\n")

            # Patch consolidated summary and per-group summaries
            _patch_summary_file(summary_path)
            for cond_val, add_val, organ_val, model_val in group_rows_map.keys():
                factor_val = group_metadata.get((cond_val, add_val, organ_val, model_val), {}).get('factor', '')
                group_dirname = f"condition={_sanitize_name(cond_val)}__additional={_sanitize_name(add_val)}__organ={_sanitize_name(organ_val)}__model={_sanitize_name(model_val)}__factor={_sanitize_name(factor_val)}"
                group_summary = os.path.join(args.outdir, group_dirname, "summary.tsv")
                _patch_summary_file(
                    group_summary, cond_val, add_val, organ_val, model_val
                )

        # === Optional: per-gene REPORT.md files under each group ===
        if args.per_gene_report:
            for (
                cond_val,
                add_val,
                organ_val,
                model_val,
            ), rows in group_rows_map.items():
                factor_val = group_metadata.get((cond_val, add_val, organ_val, model_val), {}).get('factor', '')
                group_dirname = f"condition={_sanitize_name(cond_val)}__additional={_sanitize_name(add_val)}__organ={_sanitize_name(organ_val)}__model={_sanitize_name(model_val)}__factor={_sanitize_name(factor_val)}"
                group_dir = os.path.join(args.outdir, group_dirname)
                gene_dir = os.path.join(group_dir, "gene_reports")
                os.makedirs(gene_dir, exist_ok=True)
                # recover B set for overlap selection
                B_set = set(
                    groups.get((cond_val, add_val, organ_val, model_val), set())
                )
                for r in rows:
                    gname = str(r.get("gene_name", "") or "UNKNOWN")
                    pathways = [
                        t for t in str(r.get("pathway_str", "")).split(",") if t
                    ]
                    A_g_set = set(pathways)
                    # Overlap-based top IDs for LLM
                    overlap_ids = sorted(A_g_set & B_set)
                    top_ids = overlap_ids[: max(0, args.llm_max_terms)]
                    go_ids = [t for t in top_ids if t.startswith("GO:")]
                    kegg_ids = [t for t in top_ids if not t.startswith("GO:")]

                    report_path = os.path.join(gene_dir, f"{_sanitize_name(gname)}.md")
                    # Build minimal group_core-style dict for header
                    core = {
                        "stat": args.stat,
                        "S_obs": r.get("S_obs"),
                        "mu": r.get("mu"),
                        "sd": r.get("sd"),
                        "p_right": r.get("p_right"),
                        "effect_size": r.get("effect"),
                        "verdict": r.get("verdict"),
                        "gene_name": gname,
                        "similarity_gene_name": r.get("similarity_gene_name"),
                        "ENTREZ_ID": r.get("ENTREZ_ID"),
                        # GO-only
                        "S_obs_GO": r.get("S_obs_GO"),
                        "mu_GO": r.get("mu_GO"),
                        "p_right_GO": r.get("p_right_GO"),
                        "effect_GO": r.get("effect_GO"),
                        "verdict_GO": r.get("verdict_GO"),
                        "A_GO_size": r.get("A_GO_size"),
                        "B_GO_size": r.get("B_GO_size"),
                        # KEGG-only
                        "S_obs_KEGG": r.get("S_obs_KEGG"),
                        "mu_KEGG": r.get("mu_KEGG"),
                        "p_right_KEGG": r.get("p_right_KEGG"),
                        "effect_KEGG": r.get("effect_KEGG"),
                        "verdict_KEGG": r.get("verdict_KEGG"),
                        "A_KEGG_size": r.get("A_KEGG_size"),
                        "B_KEGG_size": r.get("B_KEGG_size"),
                    }
                    # Build prompt if LLM per-gene enabled (enable when --llm-explain)
                    llm_text = ""
                    if args.llm_explain:
                        # Build protein evidence text first so it's included in dumped prompt
                        ev_text = ""
                        if args.evidence_dir:
                            ev = _load_gene_evidence(args.evidence_dir, gname)
                            analyses = (
                                tuple(
                                    x.strip()
                                    for x in str(
                                        getattr(args, "evidence_analyses", "")
                                    ).split(",")
                                    if x.strip()
                                )
                                or None
                            )
                            ev_text = _summarize_evidence(
                                ev,
                                max_interpro=args.evidence_max_interpro,
                                max_hits_per_db=args.evidence_max_hits_per_db,
                                max_pathways=args.evidence_max_pathways,
                                analyses=analyses,
                                summarize_by_desc=True,
                                max_desc_per_db=int(
                                    getattr(args, "evidence_max_desc_per_db", 5)
                                ),
                            )
                        prompt = _make_llm_prompt(
                            disease=args.condition or "(unspecified)",
                            group_keys=(cond_val, add_val, organ_val, model_val),
                            go_ids=go_ids,
                            kegg_ids=kegg_ids,
                            go_meta=go_meta,
                            kegg_meta=kegg_meta,
                            statistic=args.stat,
                            S_obs=r.get("S_obs"),
                            null_mean=r.get("mu"),
                            null_sd=r.get("sd"),
                            p_right=r.get("p_right"),
                            verdict=r.get("verdict"),
                            effect_size=r.get("effect"),
                            A_size=r.get("A_size"),
                            B_size=r.get("B_size"),
                            U_size=r.get("U_size"),
                            top_overlap_ids=top_ids,
                            S_obs_GO=r.get("S_obs_GO"),
                            null_mean_GO=r.get("mu_GO"),
                            p_right_GO=r.get("p_right_GO"),
                            verdict_GO=r.get("verdict_GO"),
                            effect_size_GO=r.get("effect_GO"),
                            A_GO_size=r.get("A_GO_size"),
                            B_GO_size=r.get("B_GO_size"),
                            U_GO_size=None,
                            S_obs_KEGG=r.get("S_obs_KEGG"),
                            null_mean_KEGG=r.get("mu_KEGG"),
                            p_right_KEGG=r.get("p_right_KEGG"),
                            verdict_KEGG=r.get("verdict_KEGG"),
                            effect_size_KEGG=r.get("effect_KEGG"),
                            A_KEGG_size=r.get("A_KEGG_size"),
                            B_KEGG_size=r.get("B_KEGG_size"),
                            U_KEGG_size=None,
                            evidence_text=ev_text,
                        )
                        safe_to_call = True
                        if args.llm_guard and not (
                            str(r.get("verdict", "")) == "enriched"
                            and float(r.get("p_right") or 1.0) < args.alpha
                            and float(r.get("effect") or 0.0) > 0
                        ):
                            safe_to_call = False
                        if args.llm_explain and safe_to_call and args.llm_views in ("all", "combined"):
                            llm_text = _llm_call(
                                prompt=_make_llm_prompt(
                                    disease=args.condition or "(unspecified)",
                                    group_keys=(
                                        cond_val,
                                        add_val,
                                        organ_val,
                                        model_val,
                                    ),
                                    go_ids=go_ids,
                                    kegg_ids=kegg_ids,
                                    go_meta=go_meta,
                                    kegg_meta=kegg_meta,
                                    statistic=args.stat,
                                    S_obs=r.get("S_obs"),
                                    null_mean=r.get("mu"),
                                    null_sd=r.get("sd"),
                                    p_right=r.get("p_right"),
                                    verdict=r.get("verdict"),
                                    effect_size=r.get("effect"),
                                    A_size=r.get("A_size"),
                                    B_size=r.get("B_size"),
                                    U_size=r.get("U_size"),
                                    top_overlap_ids=top_ids,
                                    S_obs_GO=r.get("S_obs_GO"),
                                    null_mean_GO=r.get("mu_GO"),
                                    p_right_GO=r.get("p_right_GO"),
                                    verdict_GO=r.get("verdict_GO"),
                                    effect_size_GO=r.get("effect_GO"),
                                    A_GO_size=r.get("A_GO_size"),
                                    B_GO_size=r.get("B_GO_size"),
                                    U_GO_size=len(U_GO),
                                    S_obs_KEGG=r.get("S_obs_KEGG"),
                                    null_mean_KEGG=r.get("mu_KEGG"),
                                    p_right_KEGG=r.get("p_right_KEGG"),
                                    verdict_KEGG=r.get("verdict_KEGG"),
                                    effect_size_KEGG=r.get("effect_KEGG"),
                                    A_KEGG_size=r.get("A_KEGG_size"),
                                    B_KEGG_size=r.get("B_KEGG_size"),
                                    U_KEGG_size=len(U_KEGG),
                                    evidence_text=ev_text,
                                ),
                                model=args.llm_model,
                                api_key=args.llm_api_key,
                                base_url=args.llm_base_url,
                                timeout=args.llm_timeout,
                            )
                        # Write a lightweight report using the same writer
                        _write_report_md(
                            path=report_path,
                            title=f"Gene report — {gname} | condition={cond_val} | additional={add_val} | organ={organ_val} | model={model_val} | day={res.get('day', '')} | factor={res.get('factor', '')}",
                            prompt=(
                                prompt
                                if (
                                    safe_to_call
                                    and args.llm_views in ("all", "combined")
                                )
                                else ""
                            ),
                            llm_text=(
                                llm_text
                                if (
                                    safe_to_call
                                    and args.llm_views in ("all", "combined")
                                )
                                else ""
                            ),
                            dump_prompt=bool(args.llm_dump_prompt),
                            group_core=core,
                            go_ids=go_ids,
                            kegg_ids=kegg_ids,
                        )
                        # Append GO-only and KEGG-only LLM sections for this gene based on --llm-views
                        go_only_ids = go_ids
                        kegg_only_ids = kegg_ids
                        with open(report_path, "a", encoding="utf-8") as rf:
                            # GO-only
                            if args.llm_views in ("all", "go"):
                                rf.write(
                                    "\n## GO-only LLM interpretation (per gene)\n\n"
                                )
                            go_safe = True
                            if args.llm_guard and not (
                                str(r.get("verdict_GO", "")) == "enriched"
                                and float(r.get("p_right_GO") or 1.0) < args.alpha
                                and float(r.get("effect_GO") or 0.0) > 0
                            ):
                                go_safe = False
                            go_text = ""
                            if (
                                args.llm_views in ("all", "go")
                                and go_safe
                                and go_only_ids
                            ):
                                ev_text_go = ""
                                try:
                                    if args.evidence_dir:
                                        ev = _load_gene_evidence(
                                            args.evidence_dir, gname
                                        )
                                        if (
                                            ev
                                            and str(ev.get("gene_name", "") or "")
                                            != gname
                                        ):
                                            ev = None
                                        ev_text_go = _summarize_evidence(
                                            ev,
                                            max_interpro=args.evidence_max_interpro,
                                            max_hits_per_db=args.evidence_max_hits_per_db,
                                            max_pathways=args.evidence_max_pathways,
                                        )
                                except Exception:
                                    ev_text_go = ""

                                go_prompt = _make_llm_prompt(
                                    disease=args.condition or "(unspecified)",
                                    group_keys=(
                                        cond_val,
                                        add_val,
                                        organ_val,
                                        model_val,
                                    ),
                                    go_ids=go_ids,
                                    kegg_ids=[],
                                    go_meta=go_meta,
                                    kegg_meta=kegg_meta,
                                    statistic=args.stat,
                                    S_obs=r.get("S_obs_GO"),
                                    null_mean=r.get("mu_GO"),
                                    null_sd=float("nan"),
                                    p_right=r.get("p_right_GO"),
                                    verdict=r.get("verdict_GO"),
                                    effect_size=r.get("effect_GO"),
                                    A_size=r.get("A_GO_size"),
                                    B_size=r.get("B_GO_size"),
                                    U_size=len(U_GO),
                                    top_overlap_ids=go_ids,
                                    S_obs_GO=r.get("S_obs_GO"),
                                    null_mean_GO=r.get("mu_GO"),
                                    p_right_GO=r.get("p_right_GO"),
                                    verdict_GO=r.get("verdict_GO"),
                                    effect_size_GO=r.get("effect_GO"),
                                    A_GO_size=r.get("A_GO_size"),
                                    B_GO_size=r.get("B_GO_size"),
                                    U_GO_size=len(U_GO),
                                    S_obs_KEGG=None,
                                    null_mean_KEGG=None,
                                    p_right_KEGG=None,
                                    verdict_KEGG=None,
                                    effect_size_KEGG=None,
                                    A_KEGG_size=None,
                                    B_KEGG_size=None,
                                    U_KEGG_size=None,
                                    evidence_text=ev_text_go,
                                )
                                go_text = _llm_call(
                                    prompt=go_prompt,
                                    model=args.llm_model,
                                    api_key=args.llm_api_key,
                                    base_url=args.llm_base_url,
                                    timeout=args.llm_timeout,
                                )
                                if args.llm_views in ("all", "go") and go_text.strip():
                                    rf.write(_normalize_llm_text(go_text))
                                else:
                                    if args.llm_views in ("all", "go"):
                                        rf.write(
                                            "*GO-only interpretation unavailable (guarded or empty response).*\n\n"
                                        )
                                if args.llm_dump_prompt and args.llm_views in (
                                    "all",
                                    "go",
                                ):
                                    rf.write(
                                        "<details><summary>Prompt (GO-only per gene)</summary>\n\n```\n"
                                        + go_prompt
                                        + "\n```\n</details>\n\n"
                                    )
                            elif args.llm_views in ("all", "go"):
                                rf.write(
                                    "*GO-only interpretation unavailable (guarded or no GO overlap terms).*\n\n"
                                )

                            # KEGG-only
                            if args.llm_views in ("all", "kegg"):
                                rf.write(
                                    "## KEGG-only LLM interpretation (per gene)\n\n"
                                )
                            ke_safe = True
                            if args.llm_guard and not (
                                str(r.get("verdict_KEGG", "")) == "enriched"
                                and float(r.get("p_right_KEGG") or 1.0) < args.alpha
                                and float(r.get("effect_KEGG") or 0.0) > 0
                            ):
                                ke_safe = False
                            ke_text = ""
                            if (
                                args.llm_views in ("all", "kegg")
                                and ke_safe
                                and kegg_only_ids
                            ):
                                ev_text_kegg = ""
                                try:
                                    if args.evidence_dir:
                                        # Use only current gene evidence
                                        ev = _load_gene_evidence(
                                            args.evidence_dir, gname
                                        )
                                        if (
                                            ev
                                            and str(ev.get("gene_name", "") or "")
                                            != gname
                                        ):
                                            ev = None
                                        ev_text_kegg = _summarize_evidence(
                                            ev,
                                            max_interpro=args.evidence_max_interpro,
                                            max_hits_per_db=args.evidence_max_hits_per_db,
                                            max_pathways=args.evidence_max_pathways,
                                        )
                                except Exception:
                                    ev_text_kegg = ""

                                ke_prompt = _make_llm_prompt(
                                    disease=args.condition or "(unspecified)",
                                    group_keys=(
                                        cond_val,
                                        add_val,
                                        organ_val,
                                        model_val,
                                    ),
                                    go_ids=[],
                                    kegg_ids=kegg_only_ids,
                                    go_meta=go_meta,
                                    kegg_meta=kegg_meta,
                                    statistic=args.stat,
                                    S_obs=r.get("S_obs_KEGG"),
                                    null_mean=r.get("mu_KEGG"),
                                    null_sd=float("nan"),
                                    p_right=r.get("p_right_KEGG"),
                                    verdict=r.get("verdict_KEGG"),
                                    effect_size=r.get("effect_KEGG"),
                                    A_size=r.get("A_KEGG_size"),
                                    B_size=r.get("B_KEGG_size"),
                                    U_size=len(U_KEGG),
                                    top_overlap_ids=kegg_only_ids,
                                    S_obs_GO=None,
                                    null_mean_GO=None,
                                    p_right_GO=None,
                                    verdict_GO=None,
                                    effect_size_GO=None,
                                    A_GO_size=None,
                                    B_GO_size=None,
                                    U_GO_size=None,
                                    S_obs_KEGG=r.get("S_obs_KEGG"),
                                    null_mean_KEGG=r.get("mu_KEGG"),
                                    p_right_KEGG=r.get("p_right_KEGG"),
                                    verdict_KEGG=r.get("verdict_KEGG"),
                                    effect_size_KEGG=r.get("effect_KEGG"),
                                    A_KEGG_size=r.get("A_KEGG_size"),
                                    B_KEGG_size=r.get("B_KEGG_size"),
                                    U_KEGG_size=len(U_KEGG),
                                    evidence_text=ev_text_kegg,
                                )
                                ke_text = _llm_call(
                                    prompt=ke_prompt,
                                    model=args.llm_model,
                                    api_key=args.llm_api_key,
                                    base_url=args.llm_base_url,
                                    timeout=args.llm_timeout,
                                )
                                if (
                                    args.llm_views in ("all", "kegg")
                                    and ke_text.strip()
                                ):
                                    rf.write(_normalize_llm_text(ke_text))
                                else:
                                    if args.llm_views in ("all", "kegg"):
                                        rf.write(
                                            "*KEGG-only interpretation unavailable (guarded or empty response).*\n\n"
                                        )
                                if args.llm_dump_prompt and args.llm_views in (
                                    "all",
                                    "kegg",
                                ):
                                    rf.write(
                                        "<details><summary>Prompt (KEGG-only per gene)</summary>\n\n```\n"
                                        + ke_prompt
                                        + "\n```\n</details>\n\n"
                                    )
                            elif args.llm_views in ("all", "kegg"):
                                rf.write(
                                    "*KEGG-only interpretation unavailable (guarded or no KEGG overlap terms).*\n\n"
                                )
                    else:
                        # Stats-only report without LLM
                        _write_report_md(
                            path=report_path,
                            title=f"Gene report — {gname} | condition={cond_val} | additional={add_val} | organ={organ_val} | model={model_val}",
                            prompt="",
                            llm_text="",
                            dump_prompt=False,
                            group_core=core,
                            go_ids=[t for t in pathways if t.startswith("GO:")],
                            kegg_ids=[t for t in pathways if not t.startswith("GO:")],
                        )

        # === Top-level per-gene reports (aggregate across groups) ===
        # Always generate global gene reports (in addition to group-level ones)
        gene_all_dir = os.path.join(args.outdir, "gene_reports")
        os.makedirs(gene_all_dir, exist_ok=True)
        gene_map: dict[str, list[tuple[tuple[str, str, str, str], dict]]] = {}
        for key, rows in group_rows_map.items():
            for r in rows:
                gname = str(r.get("gene_name", "") or "UNKNOWN")
                gene_map.setdefault(gname, []).append((key, r))
        for gname, items in sorted(gene_map.items(), key=lambda x: x[0].lower()):
            out_path = os.path.join(gene_all_dir, f"{_sanitize_name(gname)}.md")
            # Aggregate union pathways and B overlap across groups for LLM
            pw_union = set()
            B_union = set()
            any_enriched = False
            best_p = 1.0
            best_effect = 0.0
            for key, r in items:
                pw_union.update(
                    [t for t in str(r.get("pathway_str", "")).split(",") if t]
                )
                if str(r.get("gene_name", "") or "") == gname:
                    B_union.update(groups.get(key, set()))

                if (
                    str(r.get("verdict", "")) == "enriched"
                    and float(r.get("p_right") or 1.0) < best_p
                    and float(r.get("effect") or 0.0) > 0
                ):
                    any_enriched = True
                    best_p = float(r.get("p_right") or 1.0)
                    best_effect = float(r.get("effect") or 0.0)
            go_list = sorted([t for t in pw_union if t.startswith("GO:")])
            kegg_list = sorted([t for t in pw_union if not t.startswith("GO:")])
            # Optional per-gene LLM at top-level (enable when --llm-explain)
            per_gene_llm_text = ""
            per_gene_prompt = ""
            if args.llm_explain:
                top_ids = sorted(pw_union & B_union)[: max(0, args.llm_max_terms)]
                go_ids_top = [t for t in top_ids if t.startswith("GO:")]
                kegg_ids_top = [t for t in top_ids if not t.startswith("GO:")]
                ev_text = ""
                if args.evidence_dir:
                    ev = _load_gene_evidence(args.evidence_dir, gname)
                    if ev and str(ev.get("gene_name", "") or "") != gname:
                        ev = None
                    ev_text = _summarize_evidence(
                        ev,
                        max_interpro=args.evidence_max_interpro,
                        max_hits_per_db=args.evidence_max_hits_per_db,
                        max_pathways=args.evidence_max_pathways,
                    )
                per_gene_prompt = _make_llm_prompt(
                    disease=args.condition or "(unspecified)",
                    group_keys=("(mixed)", "(mixed)", "(mixed)", "(mixed)"),
                    go_ids=go_ids_top,
                    kegg_ids=kegg_ids_top,
                    go_meta=go_meta,
                    kegg_meta=kegg_meta,
                    statistic=args.stat,
                    S_obs=None,
                    null_mean=None,
                    null_sd=None,
                    p_right=best_p,
                    verdict="enriched" if any_enriched else "not_significant",
                    effect_size=best_effect,
                    A_size=None,
                    B_size=None,
                    U_size=len(U),
                    top_overlap_ids=top_ids,
                    S_obs_GO=None,
                    null_mean_GO=None,
                    p_right_GO=None,
                    verdict_GO=None,
                    effect_size_GO=None,
                    A_GO_size=None,
                    B_GO_size=None,
                    U_GO_size=None,
                    S_obs_KEGG=None,
                    null_mean_KEGG=None,
                    p_right_KEGG=None,
                    verdict_KEGG=None,
                    effect_size_KEGG=None,
                    A_KEGG_size=None,
                    B_KEGG_size=None,
                    U_KEGG_size=None,
                    evidence_text=ev_text,
                )
                safe_to_call = True
                if args.llm_guard and not any_enriched:
                    safe_to_call = False
                if safe_to_call:
                    per_gene_llm_text = _llm_call(
                        prompt=per_gene_prompt,
                        model=args.llm_model,
                        api_key=args.llm_api_key,
                        base_url=args.llm_base_url,
                        timeout=args.llm_timeout,
                        llm_enabled=args.llm_explain,
                    )
            # Render a full REPORT.md for this gene mirroring the top-level structure
            with open(out_path, "w", encoding="utf-8") as rf:
                rf.write(
                    f"# Functional-term permutation test report — Gene: {gname}\n\n"
                )
                rf.write(f"**Generated:** {_now()}\n\n")
                rf.write("## Inputs\n\n")
                rf.write(f"- A file: `{args.A}`  (gene: `{gname}`)\n")
                rf.write(f"- B file: `{args.B}`\n")
                rf.write(f"- Species: `{species}`\n")
                rf.write(f"- Universe: `{U_path}` (|U| = {len(U)})\n\n")
                # Gene metadata (first occurrence)
                first_row = items[0][1] if items else {}
                simg = (
                    first_row.get("similarity_gene_name", "")
                    if isinstance(first_row, dict)
                    else ""
                )
                eid = (
                    first_row.get("ENTREZ_ID", "")
                    if isinstance(first_row, dict)
                    else ""
                )
                rf.write("## Gene\n\n")
                rf.write(f"- gene_name: `{gname}`\n")
                if simg:
                    rf.write(f"- similarity_gene_name: `{simg}`\n")
                if eid:
                    rf.write(f"- ENTREZ_ID: `{eid}`\n")
                rf.write("\n")

                rf.write("## Group Results\n\n")
                rf.write(
                    "| Condition | Additional | Organ | Model | A | B | S_obs | mu | sd | effect | p_right | p_two | verdict | confidence |\n"
                )
                rf.write(
                    "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|\n"
                )
                for (cond_val, add_val, organ_val, model_val), r in items:
                    conf_lbl = _confidence_label(r.get("p_right"), r.get("verdict"))
                    rf.write(
                        f"| {cond_val} | {add_val} | {organ_val} | {model_val} | {r.get('A_size')} | {r.get('B_size')} | "
                        f"{_fmt5(r.get('S_obs'))} | {_fmt5(r.get('mu'))} | {_fmt5(r.get('sd'))} | {_fmt5(r.get('effect'))} | {_fmt5(r.get('p_right'))} | {_fmt5(r.get('p_two'))} | {r.get('verdict')} | {conf_lbl} |\n"
                    )

                rf.write("\n## Ontology Breakdown (GO / KEGG)\n\n")
                rf.write(
                    "| Condition | Additional | Organ | Model | A_GO | B_GO | S_obs_GO | p_right_GO | verdict_GO | A_KEGG | B_KEGG | S_obs_KEGG | p_right_KEGG | verdict_KEGG |\n"
                )
                rf.write(
                    "|---|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---|\n"
                )
                for (cond_val, add_val, organ_val, model_val), r in items:
                    rf.write(
                        f"| {cond_val} | {add_val} | {organ_val} | {model_val} | {r.get('A_GO_size')} | {r.get('B_GO_size')} | "
                        f"{_fmt5(r.get('S_obs_GO'))} | {_fmt5(r.get('p_right_GO'))} | {r.get('verdict_GO')} | "
                        f"{r.get('A_KEGG_size')} | {r.get('B_KEGG_size')} | {_fmt5(r.get('S_obs_KEGG'))} | {_fmt5(r.get('p_right_KEGG'))} | {r.get('verdict_KEGG')} |\n"
                    )

                rf.write("\n## Terms (union across groups)\n\n")
                rf.write(f"- GO: {', '.join(go_list) if go_list else '(none)'}\n")
                rf.write(
                    f"- KEGG: {', '.join(kegg_list) if kegg_list else '(none)'}\n\n"
                )

                # Collect LLM outputs per group for JSON report
                if args.llm_explain:
                    rf.write("## LLM-based Interpretation\n\n")
                    for (cond_val, add_val, organ_val, model_val), r in items:
                        A_g = set(
                            [t for t in str(r.get("pathway_str", "")).split(",") if t]
                        )
                        B_set = groups.get(
                            (cond_val, add_val, organ_val, model_val), set()
                        )
                        overlap_ids = sorted(A_g & B_set)
                        top_ids = overlap_ids[: max(0, args.llm_max_terms)]
                        go_ids = [t for t in top_ids if t.startswith("GO:")]
                        kegg_ids = [t for t in top_ids if not t.startswith("GO:")]
                        rf.write(
                            f"### {cond_val} / {add_val} / {organ_val} / {model_val}\n\n"
                        )
                        rf.write(
                            f"**LLM Model:** {args.llm_model} (via {args.llm_base_url})\n\n"
                        )

                        # Combined view
                        if args.llm_views in ("all", "combined"):
                            # For gene reports, use only the current gene's evidence
                            ev_text_gene = ""
                            try:
                                if args.evidence_dir:
                                    ev = _load_gene_evidence(args.evidence_dir, gname)
                                    if (
                                        ev
                                        and str(ev.get("gene_name", "") or "") == gname
                                    ):
                                        ev_text_gene = _summarize_evidence(
                                            ev,
                                            max_interpro=args.evidence_max_interpro,
                                            max_hits_per_db=args.evidence_max_hits_per_db,
                                            max_pathways=args.evidence_max_pathways,
                                        )
                            except Exception:
                                ev_text_gene = ""

                            prompt_c = _make_llm_prompt(
                                disease=args.condition or "(unspecified)",
                                group_keys=(cond_val, add_val, organ_val, model_val),
                                go_ids=go_ids,
                                kegg_ids=kegg_ids,
                                go_meta=go_meta,
                                kegg_meta=kegg_meta,
                                statistic=args.stat,
                                S_obs=r.get("S_obs"),
                                null_mean=r.get("mu"),
                                null_sd=r.get("sd"),
                                p_right=r.get("p_right"),
                                verdict=r.get("verdict"),
                                effect_size=r.get("effect"),
                                A_size=r.get("A_size"),
                                B_size=r.get("B_size"),
                                U_size=r.get("U_size"),
                                top_overlap_ids=top_ids,
                                S_obs_GO=r.get("S_obs_GO"),
                                null_mean_GO=r.get("mu_GO"),
                                p_right_GO=r.get("p_right_GO"),
                                verdict_GO=r.get("verdict_GO"),
                                effect_size_GO=r.get("effect_GO"),
                                A_GO_size=r.get("A_GO_size"),
                                B_GO_size=r.get("B_GO_size"),
                                U_GO_size=None,
                                S_obs_KEGG=r.get("S_obs_KEGG"),
                                null_mean_KEGG=r.get("mu_KEGG"),
                                p_right_KEGG=r.get("p_right_KEGG"),
                                verdict_KEGG=r.get("verdict_KEGG"),
                                effect_size_KEGG=r.get("effect_KEGG"),
                                A_KEGG_size=r.get("A_KEGG_size"),
                                B_KEGG_size=r.get("B_KEGG_size"),
                                U_KEGG_size=None,
                                evidence_text=ev_text_gene,
                            )
                            safe_c = True
                            if args.llm_guard and not (
                                str(r.get("verdict", "")) == "enriched"
                                and float(r.get("p_right") or 1.0) < args.alpha
                                and float(r.get("effect") or 0.0) > 0
                            ):
                                safe_c = False
                            text_c = ""
                            if safe_c:
                                text_c = _llm_call(
                                    prompt=prompt_c,
                                    model=args.llm_model,
                                    api_key=args.llm_api_key,
                                    base_url=args.llm_base_url,
                                    timeout=args.llm_timeout,
                                )
                            rf.write("#### Combined\n\n")
                            rf.write(
                                _normalize_llm_text(text_c)
                                if text_c.strip()
                                else "*Combined interpretation unavailable (guarded or empty response).*\n\n"
                            )
                            if args.llm_dump_prompt and prompt_c.strip():
                                rf.write(
                                    "<details><summary>Prompt (Combined)</summary>\n\n```\n"
                                    + prompt_c
                                    + "\n```\n</details>\n\n"
                                )

                            # GO-only view
                            if args.llm_views in ("all", "go"):
                                prompt_g = _make_llm_prompt(
                                    disease=args.condition or "(unspecified)",
                                    group_keys=(
                                        cond_val,
                                        add_val,
                                        organ_val,
                                        model_val,
                                    ),
                                    go_ids=go_ids,
                                    kegg_ids=[],
                                    go_meta=go_meta,
                                    kegg_meta=kegg_meta,
                                    statistic=args.stat,
                                    S_obs=r.get("S_obs_GO"),
                                    null_mean=r.get("mu_GO"),
                                    null_sd=float("nan"),
                                    p_right=r.get("p_right_GO"),
                                    verdict=r.get("verdict_GO"),
                                    effect_size=r.get("effect_GO"),
                                    A_size=r.get("A_GO_size"),
                                    B_size=r.get("B_GO_size"),
                                    U_size=None,
                                    top_overlap_ids=go_ids,
                                    S_obs_GO=r.get("S_obs_GO"),
                                    null_mean_GO=r.get("mu_GO"),
                                    p_right_GO=r.get("p_right_GO"),
                                    verdict_GO=r.get("verdict_GO"),
                                    effect_size_GO=r.get("effect_GO"),
                                    A_GO_size=r.get("A_GO_size"),
                                    B_GO_size=r.get("B_GO_size"),
                                    U_GO_size=None,
                                    evidence_text=ev_text_gene,
                                )
                                safe_g = True
                                if args.llm_guard and not (
                                    str(r.get("verdict_GO", "")) == "enriched"
                                    and float(r.get("p_right_GO") or 1.0) < args.alpha
                                    and float(r.get("effect_GO") or 0.0) > 0
                                ):
                                    safe_g = False
                                text_g = ""
                                if safe_g and go_ids:
                                    text_g = _llm_call(
                                        prompt=prompt_g,
                                        model=args.llm_model,
                                        api_key=args.llm_api_key,
                                        base_url=args.llm_base_url,
                                        timeout=args.llm_timeout,
                                    )
                                rf.write("#### GO-only\n\n")
                                rf.write(
                                    _normalize_llm_text(text_g)
                                    if text_g.strip()
                                    else "*GO-only interpretation unavailable (guarded or empty response).*\n\n"
                                )
                                if args.llm_dump_prompt and safe_g and prompt_g.strip():
                                    rf.write(
                                        "<details><summary>Prompt (GO-only)</summary>\n\n```\n"
                                        + prompt_g
                                        + "\n```\n</details>\n\n"
                                    )

                            # KEGG-only view
                            if args.llm_views in ("all", "kegg"):
                                prompt_k = _make_llm_prompt(
                                    disease=args.condition or "(unspecified)",
                                    group_keys=(
                                        cond_val,
                                        add_val,
                                        organ_val,
                                        model_val,
                                    ),
                                    go_ids=[],
                                    kegg_ids=kegg_ids,
                                    go_meta=go_meta,
                                    kegg_meta=kegg_meta,
                                    statistic=args.stat,
                                    S_obs=r.get("S_obs_KEGG"),
                                    null_mean=r.get("mu_KEGG"),
                                    null_sd=float("nan"),
                                    p_right=r.get("p_right_KEGG"),
                                    verdict=r.get("verdict_KEGG"),
                                    effect_size=r.get("effect_KEGG"),
                                    A_size=r.get("A_KEGG_size"),
                                    B_size=r.get("B_KEGG_size"),
                                    U_size=None,
                                    top_overlap_ids=kegg_ids,
                                    S_obs_KEGG=r.get("S_obs_KEGG"),
                                    null_mean_KEGG=r.get("mu_KEGG"),
                                    p_right_KEGG=r.get("p_right_KEGG"),
                                    verdict_KEGG=r.get("verdict_KEGG"),
                                    effect_size_KEGG=r.get("effect_KEGG"),
                                    A_KEGG_size=r.get("A_KEGG_size"),
                                    B_KEGG_size=r.get("B_KEGG_size"),
                                    U_KEGG_size=None,
                                    evidence_text=ev_text_gene,
                                )
                                safe_k = True
                                if args.llm_guard and not (
                                    str(r.get("verdict_KEGG", "")) == "enriched"
                                    and float(r.get("p_right_KEGG") or 1.0) < args.alpha
                                    and float(r.get("effect_KEGG") or 0.0) > 0
                                ):
                                    safe_k = False
                                text_k = ""
                                if safe_k and kegg_ids:
                                    text_k = _llm_call(
                                        prompt=prompt_k,
                                        model=args.llm_model,
                                        api_key=args.llm_api_key,
                                        base_url=args.llm_base_url,
                                        timeout=args.llm_timeout,
                                    )
                                rf.write("#### KEGG-only\n\n")
                                rf.write(
                                    _normalize_llm_text(text_k)
                                    if text_k.strip()
                                    else "*KEGG-only interpretation unavailable (guarded or empty response).*\n\n"
                                )
                                if args.llm_dump_prompt and safe_k and prompt_k.strip():
                                    rf.write(
                                        "<details><summary>Prompt (KEGG-only)</summary>\n\n```\n"
                                        + prompt_k
                                        + "\n```\n</details>\n\n"
                                    )
                    # (no index file is written as per user's preference)

            # === Collect all gene evidence for main report ===
            all_gene_evidence = []
            if args.evidence_dir:
                # Extract gene names from A_per_gene_raw (contains gene info)
                A_gene_names = []
                for item in A_per_gene_raw:
                    if isinstance(item, dict) and "gene_name" in item:
                        A_gene_names.append(str(item["gene_name"]))

                for gname in A_gene_names:
                    try:
                        ev = _load_gene_evidence(args.evidence_dir, gname)
                        if ev and str(ev.get("gene_name", "") or "") == gname:
                            all_gene_evidence.append(ev)
                    except Exception:
                        continue

            # Create aggregated evidence text for main report
            ev_text_main = ""
            if all_gene_evidence:
                ev_text_main = _summarize_evidence_detailed_multi(
                    all_gene_evidence,
                    max_interpro=args.evidence_max_interpro,
                    analyses=tuple(
                        x.strip()
                        for x in str(getattr(args, "evidence_analyses", "")).split(",")
                        if x.strip()
                    )
                    or (
                        "Pfam",
                        "CDD",
                        "NCBIfam",
                        "PANTHER",
                        "Gene3D",
                        "ProSitePatterns",
                        "ProSiteProfiles",
                        "SUPERFAMILY",
                    ),
                    max_desc_per_db=args.evidence_max_desc_per_db,
                )

            # === Regenerate group reports with correct evidence ===
            # This is now handled in the LLM generation section below

            # === Human-readable report ===
            try:
                report_path = os.path.join(args.outdir, "REPORT.md")
                with open(report_path, "w", encoding="utf-8") as rf:
                    rf.write("# Functional-term permutation test report\n\n")
                    rf.write(f"**Generated:** {_now()}\n\n")
                    rf.write("## Inputs\n\n")
                    rf.write(f"- A file: `{args.A}`\n")
                    rf.write(f"- B file: `{args.B}`\n")
                    rf.write(f"- Species: `{species}`\n")
                    rf.write(f"- Universe: `{U_path}` (|U| = {len(U)})\n\n")

                    rf.write("## Filters\n\n")
                    rf.write(f"- condition: `{args.condition}`\n")
                    rf.write(f"- additional_condition: `{args.additional_condition}`\n")
                    rf.write(f"- organ: `{args.organ}`\n")
                    rf.write(f"- model: `{args.model}`\n")
                    rf.write(f"- category: `{args.category}`\n")
                    rf.write(f"- comparison_control: `{args.comparison_control}`\n")
                    rf.write(f"- comparison_condition: `{args.comparison_condition}`\n")
                    rf.write(f"- cell_type: `{args.cell_type}`\n")
                    # Get day from first group's metadata
                    first_group_meta = next(iter(group_metadata.values()), {})
                    rf.write(f"- day: `{first_group_meta.get('day', args.day)}`\n")
                    rf.write(f"- factor: `{first_group_meta.get('factor', args.factor)}`\n\n")

                    rf.write("## Settings\n\n")
                    rf.write(
                        f"- Statistic: `{args.stat}`  Alpha: `{_fmt5(args.alpha)}`\n"
                    )
                    rf.write(
                        f"- R (permutations): `{args.R}`  RNG scope: `{getattr(args,'rng_scope','global')}`  Seed: `{args.seed}`\n"
                    )
                    rf.write(
                        f"- Stratified: `{bool(size_map)}`  Bins: `{args.bins}`  Term-size file: `{args.term_size or '(none)'}`\n"
                    )
                    rf.write(
                        f"- Multiple testing adjust: `BH` (scope: `{args.adjust_scope}`)  Aggregate: `{args.aggregate_q}` (report: `{args.aggregate_q_report}`)\n"
                    )
                    # Acceleration summary
                    try:
                        acc_bitset = (
                            "on"
                            if (
                                args.stat in ("overlap", "jaccard")
                                and (args.bitset in ("on", "auto"))
                            )
                            else "off"
                        )
                    except Exception:
                        acc_bitset = "auto"
                    acc_numpy = "yes" if _NP_AVAILABLE else "no"
                    rf.write(
                        f"- Acceleration: bitset=`{acc_bitset}`  numpy=`{acc_numpy}`  jobs(per-gene)=`{getattr(args,'jobs',1)}`  group-jobs=`{getattr(args,'group_jobs',1)}`\n\n"
                    )

                    rf.write("## Group Results\n\n")
                    if args.aggregate_q != "none" and args.aggregate_q_report == "both":
                        rf.write(
                            "| Condition | Additional | Organ | Model | A | B | S_obs | mu | sd | effect | p_right | p_two | verdict | confidence | aggregate_over_q | aggregate_over_p |\n"
                        )
                        rf.write(
                            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|\n"
                        )
                    elif args.aggregate_q != "none":
                        rf.write(
                            "| Condition | Additional | Organ | Model | A | B | S_obs | mu | sd | effect | p_right | p_two | verdict | confidence | aggregate_q |\n"
                        )
                        rf.write(
                            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|\n"
                        )
                    else:
                        rf.write(
                            "| Condition | Additional | Organ | Model | A | B | S_obs | mu | sd | effect | p_right | p_two | verdict | confidence |\n"
                        )
                        rf.write(
                            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|\n"
                        )
                    for (
                        cond_val,
                        add_val,
                        organ_val,
                        model_val,
                    ), core in group_core.items():
                        A_sz = core.get("A_size", len(A))
                        B_sz = core.get("B_size", 0)
                        S_obs = core.get("S_obs", float("nan"))
                        mu = core.get("mu", float("nan"))
                        sd = core.get("sd", float("nan"))
                        p_right = core.get("p_right", float("nan"))
                        verdict = core.get("verdict", "")
                        if args.aggregate_q != "none":
                            aq = agg_q_map.get(
                                (cond_val, add_val, organ_val, model_val), float("nan")
                            )
                            ap = agg_p_map.get(
                                (cond_val, add_val, organ_val, model_val), float("nan")
                            )
                            conf_lbl = _confidence_label(
                                core.get("p_right"), core.get("verdict")
                            )
                            if args.aggregate_q_report == "both":
                                rf.write(
                                    f"| {cond_val} | {add_val} | {organ_val} | {model_val} | {A_sz} | {B_sz} | {_fmt5(S_obs)} | {_fmt5(mu)} | {_fmt5(sd)} | {_fmt5(core.get('effect_size'))} | {_fmt5(core.get('p_right'))} | {_fmt5(core.get('p_two'))} | {verdict} | {conf_lbl} | {_fmt5(aq)} | {_fmt5(ap)} |\n"
                                )
                            else:
                                use = aq  # Always use q-value since we always compute BH-FDR
                                rf.write(
                                    f"| {cond_val} | {add_val} | {organ_val} | {model_val} | {A_sz} | {B_sz} | {_fmt5(S_obs)} | {_fmt5(mu)} | {_fmt5(sd)} | {_fmt5(core.get('effect_size'))} | {_fmt5(core.get('p_right'))} | {_fmt5(core.get('p_two'))} | {verdict} | {conf_lbl} | {_fmt5(use)} |\n"
                                )
                        else:
                            conf_lbl = _confidence_label(
                                core.get("p_right"), core.get("verdict")
                            )
                            rf.write(
                                f"| {cond_val} | {add_val} | {organ_val} | {model_val} | {A_sz} | {B_sz} | {_fmt5(S_obs)} | {_fmt5(mu)} | {_fmt5(sd)} | {_fmt5(core.get('effect_size'))} | {_fmt5(core.get('p_right'))} | {_fmt5(core.get('p_two'))} | {verdict} | {conf_lbl} |\n"
                            )

                    rf.write("\n## Ontology Breakdown (GO / KEGG)\n\n")
                    rf.write(
                        "| Condition | Additional | Organ | Model | A_GO | B_GO | S_obs_GO | p_right_GO | verdict_GO | A_KEGG | B_KEGG | S_obs_KEGG | p_right_KEGG | verdict_KEGG |\n"
                    )
                    rf.write(
                        "|---|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---|\n"
                    )
                    for (
                        cond_val,
                        add_val,
                        organ_val,
                        model_val,
                    ), core in group_core.items():
                        A_GO_sz = core.get("A_GO_size", len(A & U_GO))
                        B_GO_sz = core.get("B_GO_size", 0)
                        A_KEGG_sz = core.get("A_KEGG_size", len(A & U_KEGG))
                        B_KEGG_sz = core.get("B_KEGG_size", 0)
                        rf.write(
                            f"| {cond_val} | {add_val} | {organ_val} | {model_val} | "
                            f"{A_GO_sz} | {B_GO_sz} | {_fmt5(core.get('S_obs_GO'))} | {_fmt5(core.get('p_right_GO'))} | {core.get('verdict_GO')} | "
                            f"{A_KEGG_sz} | {B_KEGG_sz} | {_fmt5(core.get('S_obs_KEGG'))} | {_fmt5(core.get('p_right_KEGG'))} | {core.get('verdict_KEGG')} |\n"
                        )

                    rf.write("\n## Biological Interpretation (summary)\n\n")
                    for (
                        cond_val,
                        add_val,
                        organ_val,
                        model_val,
                    ), core in group_core.items():
                        verdict = core.get("verdict", "not_significant")
                        A_sz = core.get("A_size", len(A))
                        B_sz = core.get("B_size", 0)
                        S_obs = core.get("S_obs", float("nan"))
                        mu = core.get("mu", float("nan"))
                        effect = core.get("effect_size", float("nan"))
                        rf.write(
                            f"### {cond_val} / {add_val} / {organ_val} / {model_val}\n\n"
                        )
                        if verdict == "enriched":
                            rf.write(
                                "- **Summary:** The gene set shares significantly more functions/pathways with the disease background than expected by chance (enrichment).\n"
                            )
                            rf.write(
                                "- **Implication:** Points to potential mechanistic overlap; genes may act via disease-relevant biological processes or pathways.\n"
                            )
                        elif verdict == "depleted":
                            rf.write(
                                "- **Summary:** The overlap/similarity is significantly lower than expected (depletion).\n"
                            )
                            rf.write(
                                "- **Implication:** Suggests functional divergence; genes may operate through distinct pathways from the current disease signatures.\n"
                            )
                        else:
                            rf.write(
                                "- **Summary:** No significant functional similarity detected.\n"
                            )
                            rf.write(
                                "- **Implication:** Either the gene set is unrelated to the disease pathways, or statistical power is limited (see notes below).\n"
                            )
                        overlap_terms = (
                            sorted(
                                (
                                    A
                                    & (
                                        groups.get(
                                            (cond_val, add_val, organ_val, model_val),
                                            set(),
                                        )
                                    )
                                )
                            )
                            if A
                            else []
                        )
                        rf.write(
                            f"- **Sizes:** |A|={A_sz}, |B|={B_sz}, |A∩B|={len(overlap_terms)}\n"
                        )
                        rf.write(
                            f"- **Effect:** S_obs={_fmt5(S_obs)} vs null_mean={_fmt5(mu)}, effect={_fmt5(effect)}\n"
                        )
                        if overlap_terms:
                            tops = ", ".join(overlap_terms)
                            rf.write(f"- **Top overlapping terms (IDs):** {tops}\n")

                    # === LLM-based biological interpretation (three views per group) ===
                    if args.llm_explain:
                        rf.write("\n## LLM-based Interpretation\n\n")
                    for (
                        cond_val,
                        add_val,
                        organ_val,
                        model_val,
                    ), core in group_core.items():
                        try:
                            B_set = groups.get(
                                (cond_val, add_val, organ_val, model_val), set()
                            )
                            overlap_terms = sorted((A & B_set)) if A else []
                            overlap_go = [
                                t for t in overlap_terms if t.startswith("GO:")
                            ]
                            overlap_kegg = [
                                t
                                for t in overlap_terms
                                if _is_kegg_allowed(t, allowed_kegg)
                            ]
                            go_for_llm = (
                                (overlap_go[: args.llm_max_terms])
                                if overlap_go
                                else sorted((A_GO & B_set))[: args.llm_max_terms]
                            )
                            kegg_for_llm = (
                                (overlap_kegg[: args.llm_max_terms])
                                if overlap_kegg
                                else sorted((A_KEGG & B_set))[: args.llm_max_terms]
                            )
                            top_overlap_ids = (overlap_go + overlap_kegg)[
                                : args.llm_max_terms
                            ]

                            # Generate evidence for this specific group
                            ev_text_group = ""
                            if args.evidence_dir:
                                try:
                                    # Find genes that have significant enrichment in this group
                                    group_genes = []
                                    group_rows = group_rows_map.get(
                                        (cond_val, add_val, organ_val, model_val), []
                                    )
                                    print(
                                    )
                                    for r in group_rows:
                                        verdict = str(r.get("verdict", ""))
                                        p_right = float(r.get("p_right", 1.0))
                                        effect = float(r.get("effect", 0.0))
                                        gene_name = str(r.get("gene_name", "") or "")
                                        print(
                                        )
                                        if (
                                            verdict == "enriched"
                                            and p_right < args.alpha
                                            and effect > 0
                                        ):
                                            if (
                                                gene_name
                                                and gene_name not in group_genes
                                            ):
                                                group_genes.append(gene_name)
                                    print(
                                    )

                                    # Load evidence for significant genes in this group
                                    group_evidence = []
                                    for gene_name in group_genes:
                                        print(
                                        )
                                        ev = _load_gene_evidence(
                                            args.evidence_dir, gene_name
                                        )
                                        print(
                                        )
                                        if ev:
                                            print(
                                            )
                                        if (
                                            ev
                                            and str(ev.get("gene_name", "") or "")
                                            == gene_name
                                        ):
                                            group_evidence.append(ev)
                                            print(
                                            )
                                    print(
                                    )

                                    if group_evidence:
                                        print(
                                        )
                                        ev_text_group = _summarize_evidence_detailed_multi(
                                            group_evidence,
                                            max_interpro=args.evidence_max_interpro,
                                            analyses=tuple(
                                                x.strip()
                                                for x in str(
                                                    getattr(
                                                        args, "evidence_analyses", ""
                                                    )
                                                ).split(",")
                                                if x.strip()
                                            )
                                            or (
                                                "Pfam",
                                                "CDD",
                                                "NCBIfam",
                                                "PANTHER",
                                                "Gene3D",
                                                "ProSitePatterns",
                                                "ProSiteProfiles",
                                                "SUPERFAMILY",
                                            ),
                                            max_desc_per_db=args.evidence_max_desc_per_db,
                                        )
                                        print(
                                        )
                                        if ev_text_group:
                                            print(
                                            )
                                except Exception:
                                    ev_text_group = ""

                            print(
                            )
                            if ev_text_group:
                                print(
                                )

                            rf.write(
                                f"### {cond_val} / {add_val} / {organ_val} / {model_val}\n\n"
                            )
                            rf.write(
                                f"**LLM Model:** {args.llm_model} (via {args.llm_base_url})\n\n"
                            )

                            # Combined view
                            if args.llm_views in ("all", "combined"):
                                safe_c = True
                                if args.llm_guard and not (
                                    (core.get("p_right", 1.0) < args.alpha)
                                    and (core.get("effect_size", 0.0) > 0)
                                ):
                                    safe_c = False
                                text_c = ""
                                prompt_c = ""
                                if safe_c:
                                    prompt_c = _make_llm_prompt(
                                        disease=args.condition or "(unspecified)",
                                        group_keys=(
                                            cond_val,
                                            add_val,
                                            organ_val,
                                            model_val,
                                        ),
                                        go_ids=go_ids,
                                        kegg_ids=kegg_ids,
                                        go_meta=go_meta,
                                        kegg_meta=kegg_meta,
                                        statistic=args.stat,
                                        S_obs=core.get("S_obs"),
                                        null_mean=core.get("mu"),
                                        null_sd=core.get("sd"),
                                        p_right=core.get("p_right"),
                                        verdict=core.get("verdict"),
                                        effect_size=core.get("effect"),
                                        A_size=core.get("A_size"),
                                        B_size=core.get("B_size"),
                                        U_size=len(U),
                                        top_overlap_ids=top_ids,
                                        S_obs_GO=core.get("S_obs_GO"),
                                        null_mean_GO=core.get("mu_GO"),
                                        p_right_GO=core.get("p_right_GO"),
                                        verdict_GO=core.get("verdict_GO"),
                                        effect_size_GO=core.get("effect_GO"),
                                        A_GO_size=core.get("A_GO_size"),
                                        B_GO_size=core.get("B_GO_size"),
                                        U_GO_size=len(U_GO),
                                        S_obs_KEGG=core.get("S_obs_KEGG"),
                                        null_mean_KEGG=core.get("mu_KEGG"),
                                        p_right_KEGG=core.get("p_right_KEGG"),
                                        verdict_KEGG=core.get("verdict_KEGG"),
                                        effect_size_KEGG=core.get("effect_KEGG"),
                                        A_KEGG_size=core.get("A_KEGG_size"),
                                        B_KEGG_size=core.get("B_KEGG_size"),
                                        U_KEGG_size=len(U_KEGG),
                                        evidence_text=ev_text_group,
                                    )
                                    if args.llm_dump_prompt and prompt_c.strip():
                                        rf.write(
                                            "<details><summary>Prompt (Combined)</summary>\n\n```\n"
                                            + prompt_c
                                            + "\n```\n</details>\n\n"
                                        )
                                if safe_c and prompt_c.strip():
                                    text_c = _llm_call(
                                        prompt=prompt_c,
                                        model=args.llm_model,
                                        api_key=args.llm_api_key,
                                        base_url=args.llm_base_url,
                                        timeout=args.llm_timeout,
                                    )
                                    # Store group report LLM info for JSON report
                                    llm_group_map.setdefault(
                                        (cond_val, add_val, organ_val, model_val), {}
                                    )["combined"] = {
                                        "text": (text_c or "").strip(),
                                        "prompt": (prompt_c or ""),
                                    }
                                rf.write("#### Combined\n\n")
                                rf.write(
                                    _normalize_llm_text(text_c)
                                    if text_c.strip()
                                    else "*Combined interpretation unavailable (guarded or empty response).*\n\n"
                                )

                            # GO-only view
                            if args.llm_views in ("all", "go"):
                                safe_g = True
                                if args.llm_guard and not (
                                    (core.get("p_right_GO", 1.0) < args.alpha)
                                    and (core.get("effect_GO", 0.0) > 0)
                                ):
                                    safe_g = False
                                text_g = ""
                                if safe_g and go_for_llm:
                                    prompt_g = _make_llm_prompt(
                                        disease=str(cond_val or "(unspecified)"),
                                        group_keys=(
                                            cond_val,
                                            add_val,
                                            organ_val,
                                            model_val,
                                        ),
                                        go_ids=go_for_llm,
                                        kegg_ids=[],
                                        go_meta=go_meta,
                                        kegg_meta=kegg_meta,
                                        statistic=args.stat,
                                        S_obs=core.get("S_obs_GO"),
                                        null_mean=core.get("mu_GO"),
                                        null_sd=float("nan"),
                                        p_right=core.get("p_right_GO"),
                                        verdict=core.get("verdict_GO"),
                                        effect_size=core.get("effect_GO"),
                                        A_size=core.get("A_GO_size"),
                                        B_size=core.get("B_GO_size"),
                                        U_size=core.get("U_GO_size"),
                                        top_overlap_ids=go_for_llm,
                                        S_obs_GO=core.get("S_obs_GO"),
                                        null_mean_GO=core.get("mu_GO"),
                                        p_right_GO=core.get("p_right_GO"),
                                        verdict_GO=core.get("verdict_GO"),
                                        effect_size_GO=core.get("effect_GO"),
                                        A_GO_size=core.get("A_GO_size"),
                                        B_GO_size=core.get("B_GO_size"),
                                        U_GO_size=core.get("U_GO_size"),
                                        evidence_text=ev_text_group,
                                    )
                                    text_g = _llm_call(
                                        prompt=prompt_g,
                                        model=args.llm_model,
                                        api_key=args.llm_api_key,
                                        base_url=args.llm_base_url,
                                        timeout=args.llm_timeout,
                                    )
                                    # Store group report GO-only LLM info for JSON report
                                    llm_group_map.setdefault(
                                        (cond_val, add_val, organ_val, model_val), {}
                                    )["go"] = {
                                        "text": (text_g or "").strip(),
                                        "prompt": (prompt_g or ""),
                                    }
                                rf.write("#### GO-only\n\n")
                                rf.write(
                                    _normalize_llm_text(text_g)
                                    if text_g.strip()
                                    else "*GO-only interpretation unavailable (guarded or empty response).*\n\n"
                                )
                                if (
                                    args.llm_dump_prompt
                                    and safe_g
                                    and go_for_llm
                                    and prompt_g.strip()
                                ):
                                    rf.write(
                                        "<details><summary>Prompt (GO-only)</summary>\n\n```\n"
                                        + prompt_g
                                        + "\n```\n</details>\n\n"
                                    )

                            # KEGG-only view
                            if args.llm_views in ("all", "kegg"):
                                safe_k = True
                                if args.llm_guard and not (
                                    (core.get("p_right_KEGG", 1.0) < args.alpha)
                                    and (core.get("effect_KEGG", 0.0) > 0)
                                ):
                                    safe_k = False
                                text_k = ""
                                if safe_k and kegg_for_llm:
                                    prompt_k = _make_llm_prompt(
                                        disease=str(cond_val or "(unspecified)"),
                                        group_keys=(
                                            cond_val,
                                            add_val,
                                            organ_val,
                                            model_val,
                                        ),
                                        go_ids=[],
                                        kegg_ids=kegg_for_llm,
                                        go_meta=go_meta,
                                        kegg_meta=kegg_meta,
                                        statistic=args.stat,
                                        S_obs=core.get("S_obs_KEGG"),
                                        null_mean=core.get("mu_KEGG"),
                                        null_sd=float("nan"),
                                        p_right=core.get("p_right_KEGG"),
                                        verdict=core.get("verdict_KEGG"),
                                        effect_size=core.get("effect_KEGG"),
                                        A_size=core.get("A_KEGG_size"),
                                        B_size=core.get("B_KEGG_size"),
                                        U_size=core.get("U_KEGG_size"),
                                        top_overlap_ids=kegg_for_llm,
                                        S_obs_KEGG=core.get("S_obs_KEGG"),
                                        null_mean_KEGG=core.get("mu_KEGG"),
                                        p_right_KEGG=core.get("p_right_KEGG"),
                                        verdict_KEGG=core.get("verdict_KEGG"),
                                        effect_size_KEGG=core.get("effect_KEGG"),
                                        A_KEGG_size=core.get("A_KEGG_size"),
                                        B_KEGG_size=core.get("B_KEGG_size"),
                                        U_KEGG_size=core.get("U_KEGG_size"),
                                        evidence_text=ev_text_group,
                                    )
                                    text_k = _llm_call(
                                        prompt=prompt_k,
                                        model=args.llm_model,
                                        api_key=args.llm_api_key,
                                        base_url=args.llm_base_url,
                                        timeout=args.llm_timeout,
                                    )
                                    # Store group report KEGG-only LLM info for JSON report
                                    llm_group_map.setdefault(
                                        (cond_val, add_val, organ_val, model_val), {}
                                    )["kegg"] = {
                                        "text": (text_k or "").strip(),
                                        "prompt": (prompt_k or ""),
                                    }
                                rf.write("#### KEGG-only\n\n")
                                rf.write(
                                    _normalize_llm_text(text_k)
                                    if text_k.strip()
                                    else "*KEGG-only interpretation unavailable (guarded or empty response).*\n\n"
                                )
                                if (
                                    args.llm_dump_prompt
                                    and safe_k
                                    and kegg_for_llm
                                    and prompt_k.strip()
                                ):
                                    rf.write(
                                        "<details><summary>Prompt (KEGG-only)</summary>\n\n```\n"
                                        + prompt_k
                                        + "\n```\n</details>\n\n"
                                    )

                        except Exception:
                            rf.write(
                                f"### {cond_val} / {add_val} / {organ_val} / {model_val}\n\n"
                            )
                            rf.write(
                                "*LLM interpretation unavailable due to an internal error.*\n\n"
                            )

                    # Update Protein evidence section in group reports after LLM generation
                    if args.evidence_dir and not (
                        args.skip_group_report or args.light_output
                    ):
                        for (
                            cond_val,
                            add_val,
                            organ_val,
                            model_val,
                        ), core in group_core.items():
                            factor_val = group_metadata.get((cond_val, add_val, organ_val, model_val), {}).get('factor', '')
                            group_dirname = f"condition={_sanitize_name(cond_val)}__additional={_sanitize_name(add_val)}__organ={_sanitize_name(organ_val)}__model={_sanitize_name(model_val)}__factor={_sanitize_name(factor_val)}"
                            group_dir = os.path.join(args.outdir, group_dirname)
                            report_path = os.path.join(group_dir, "REPORT.md")

                            if os.path.exists(report_path):
                                # Find significant genes for this group
                                group_genes = []
                                group_rows = group_rows_map.get(
                                    (cond_val, add_val, organ_val, model_val), []
                                )
                                for r in group_rows:
                                    verdict = str(r.get("verdict", ""))
                                    p_right = float(r.get("p_right", 1.0))
                                    effect = float(r.get("effect", 0.0))
                                    gene_name = str(r.get("gene_name", "") or "")
                                    if (
                                        verdict == "enriched"
                                        and p_right < args.alpha
                                        and effect > 0
                                    ):
                                        if gene_name and gene_name not in group_genes:
                                            group_genes.append(gene_name)

                                # Generate evidence for significant genes
                                group_evidence = []
                                for gene_name in group_genes:
                                    ev = _load_gene_evidence(
                                        args.evidence_dir, gene_name
                                    )
                                    if (
                                        ev
                                        and str(ev.get("gene_name", "") or "")
                                        == gene_name
                                    ):
                                        group_evidence.append(ev)

                                if group_evidence:
                                    ev_text_group = _summarize_evidence_detailed_multi(
                                        group_evidence,
                                        max_interpro=args.evidence_max_interpro,
                                        analyses=tuple(
                                            x.strip()
                                            for x in str(
                                                getattr(args, "evidence_analyses", "")
                                            ).split(",")
                                            if x.strip()
                                        )
                                        or (
                                            "Pfam",
                                            "CDD",
                                            "NCBIfam",
                                            "PANTHER",
                                            "Gene3D",
                                            "ProSitePatterns",
                                            "ProSiteProfiles",
                                            "SUPERFAMILY",
                                        ),
                                        max_desc_per_db=args.evidence_max_desc_per_db,
                                    )

                                    # Update the report file with correct evidence
                                    try:
                                        with open(
                                            report_path, "r", encoding="utf-8"
                                        ) as f:
                                            content = f.read()

                                        # Replace the Protein evidence section
                                        updated_content = re.sub(
                                            r"\*\*Protein evidence \(summary\):\*\*\n[^*]*?(?=\n\*\*|\n## |\n# |$)",
                                            f"**Protein evidence (summary):**\n{ev_text_group}\n",
                                            content,
                                            flags=re.DOTALL,
                                        )

                                        with open(
                                            report_path, "w", encoding="utf-8"
                                        ) as f:
                                            f.write(updated_content)
                                    except Exception as e:
                                        print(
                                            f"[WARN] Failed to update protein evidence in {report_path}: {e}",
                                            file=sys.stderr,
                                        )

                    min_p = _fmt5(1.0 / (args.R + 1) if args.R > 0 else 1.0)
                    rf.write("\n## Power & sensitivity\n\n")
                    rf.write(
                        f"- With R={args.R} permutations, the minimal empirical p-value resolution is ~{min_p}.\n"
                    )
                    rf.write(
                        "- Very small |A| or |B| reduces power; consider increasing R or augmenting B terms.\n"
                    )
                    rf.write(
                        "- Under semantic mode, GO ancestor-closure can inflate unions; check diagnostic overlaps above.\n"
                    )
            except Exception:
                pass

            json_path = out_path.replace(".md", ".json")
            json_data = _convert_md_to_json(out_path)
            try:
                with open(json_path, "w", encoding="utf-8") as jf:
                    json.dump(json_data, jf, indent=2, ensure_ascii=False)
            except Exception as e:
                print(
                    f"[WARN] Failed to write JSON report for {gname}: {e}",
                    file=sys.stderr,
                )

        # Final JSON report including LLM outputs
        if args.json_report:
            try:
                json_report_path = os.path.join(args.outdir, "report.json")

                def _as_float(x):
                    try:
                        return float(x)
                    except Exception:
                        return None

                cfg = {
                    "species": species,
                    "stat": args.stat,
                    "R": int(args.R),
                    "seed": int(args.seed),
                    "alpha": float(args.alpha),
                    "verdict_rule": args.verdict_rule,
                    "adjust": "BH",  # Always use BH-FDR
                    "adjust_scope": args.adjust_scope,
                    "aggregate_q": args.aggregate_q,
                    "aggregate_q_report": args.aggregate_q_report,
                    "bins": str(args.bins),
                    "term_size": args.term_size or None,
                    "semantic_kegg_base": args.semantic_kegg_base,
                    "go_ancestors": args.go_ancestors or None,
                    "bitset": args.bitset,
                    "jobs": int(getattr(args, "jobs", 1)),
                    "group_jobs": int(getattr(args, "group_jobs", 1)),
                }
                groups_json = []
                for (
                    cond_val,
                    add_val,
                    organ_val,
                    model_val,
                ), core in group_core.items():
                    # Get metadata for this group
                    group_metadata = group_metadata.get((cond_val, add_val, organ_val, model_val), {})
                    
                    item = {
                        "condition": cond_val,
                        "additional_condition": add_val,
                        "organ": organ_val,
                        "model": model_val,
                        "factor": group_metadata.get("factor", ""),
                        "day": group_metadata.get("day", ""),
                        "source": group_metadata.get("source", ""),
                        "category": group_metadata.get("category", ""),
                        "comparison_condition": group_metadata.get("comparison_condition", ""),
                        "cell_type": group_metadata.get("cell_type", ""),
                    }
                    item.update(
                        {
                            k: core.get(k)
                            for k in [
                                "A_size",
                                "B_size",
                                "U_size",
                                "S_obs",
                                "mu",
                                "sd",
                                "p_right",
                                "p_left",
                                "p_two",
                                "effect_size",
                                "verdict",
                                "A_GO_size",
                                "B_GO_size",
                                "U_GO_size",
                                "S_obs_GO",
                                "mu_GO",
                                "p_right_GO",
                                "effect_GO",
                                "verdict_GO",
                                "A_KEGG_size",
                                "B_KEGG_size",
                                "U_KEGG_size",
                                "S_obs_KEGG",
                                "mu_KEGG",
                                "p_right_KEGG",
                                "effect_KEGG",
                                "verdict_KEGG",
                            ]
                        }
                    )
                    if (cond_val, add_val, organ_val, model_val) in llm_group_map:
                        sub = llm_group_map[(cond_val, add_val, organ_val, model_val)]
                        item["llm"] = {}
                        for view in ("combined", "go", "kegg"):
                            if view in sub:
                                v = sub[view]
                                item["llm"][view] = {
                                    "parsed_output": _parse_llm_output(
                                        v.get("text") or ""
                                    ),
                                    "parsed_prompt": _parse_llm_prompt(
                                        v.get("prompt") or ""
                                    ),
                                    "raw_text": v.get("text") or "",
                                    "raw_prompt": v.get("prompt") or "",
                                }
                    if args.aggregate_q != "none":
                        item["aggregate_method"] = args.aggregate_q
                        if (cond_val, add_val, organ_val, model_val) in agg_q_map:
                            aq = agg_q_map[(cond_val, add_val, organ_val, model_val)]
                            ap = agg_p_map[(cond_val, add_val, organ_val, model_val)]
                            if args.aggregate_q_report == "both":
                                item["aggregate_over_q"] = _as_float(aq)
                                item["aggregate_over_p"] = _as_float(ap)
                            else:
                                item["aggregate_value"] = _as_float(
                                    aq  # Always use q-value since we always compute BH-FDR
                                )
                    groups_json.append(item)
                # Add main report LLM info and protein evidence
                main_llm_info = {}
                if ("main", "main", "main", "main") in llm_group_map:
                    main_llm = llm_group_map[("main", "main", "main", "main")]
                    for view in ("combined", "go", "kegg"):
                        if view in main_llm:
                            v = main_llm[view]
                            main_llm_info[view] = {
                                "parsed_output": _parse_llm_output(v.get("text") or ""),
                                "parsed_prompt": _parse_llm_prompt(
                                    v.get("prompt") or ""
                                ),
                                "raw_text": v.get("text") or "",
                                "raw_prompt": v.get("prompt") or "",
                            }

                # Add protein evidence info
                protein_evidence_info = {}
                if all_gene_evidence:
                    # Create structured protein evidence with individual gene details
                    protein_evidence_info = {"genes": []}
                    for ev in all_gene_evidence:
                        if ev and isinstance(ev, dict):
                            gene_info = {
                                "Gene": str(ev.get("gene_name", "") or "UNKNOWN"),
                                "Accessions": ev.get("protein_accessions", []),
                                "Length": ev.get("sequence_length"),
                                "Coverage": ev.get("coverage", {}),
                                "InterPro": ev.get("interpro", []),
                                "Hits": ev.get("hits", []),
                            }
                            protein_evidence_info["genes"].append(gene_info)

                data = {
                    "metadata": {
                        "title": "Functional-term permutation test report",
                        "generated": _now(),
                        "type": "main_report"
                    },
                    "config": cfg,
                    "statistics": {
                        "groups": groups_json,
                        "per_gene": all_rows
                    },
                    "ontology": {
                        "breakdown": [],  # Main reports do not contain group-level ontology breakdown
                        "terms": {}  # Main reports do not contain term summary
                    },
                    "llm": {
                        "main": main_llm_info,
                        "groups": {}  # Main reports LLM results are in main
                    },
                    "evidence": {
                        "protein": protein_evidence_info,
                        "conclusions": {}  # Main reports do not contain conclusions
                    }
                }
                with open(json_report_path, "w", encoding="utf-8") as jf:
                    json.dump(data, jf, indent=2, ensure_ascii=False)
            except Exception as e:
                print(
                    f"[WARN] Failed to write JSON report (final): {e}", file=sys.stderr
                )

        # Calculate and display timing
        end_time = time.time()
        duration = end_time - start_time
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            time_str = f"{int(hours)}h {int(minutes)}m {seconds:.1f}s"
        elif minutes > 0:
            time_str = f"{int(minutes)}m {seconds:.1f}s"
        else:
            time_str = f"{seconds:.1f}s"
            
        print(f"[{_now()}] Analysis completed! Found {len(groups)} groups in {time_str}. Results saved to: {args.outdir}")

    except KeyboardInterrupt:
        print(f"\n[{_now()}] Analysis interrupted by user", file=sys.stderr, flush=True)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"[{_now()}] File not found: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
    except MemoryError as e:
        print(f"[{_now()}] Insufficient memory: {e}", file=sys.stderr, flush=True)
        print("Try reducing --R or using --light-output", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[{_now()}] ERROR: {e}", file=sys.stderr, flush=True)
        print(f"Error type: {type(e).__name__}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
