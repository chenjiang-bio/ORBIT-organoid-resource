"""Ranking must follow the published rule.

Methods section: "Candidates were ranked by the primary hypergeometric p-value,
breaking ties by consensus score."

``consensus_score`` takes only a few discrete values (agreement counts over five
methods), so ordering by it first would collapse the ranking into plateaus. These
tests pin the documented order across all three modes.
"""

from __future__ import annotations

import pytest

from orbit_ocsp.expression_pipeline import (
    run_expression_biomarker_pipeline,
    run_genes_biomarker_pipeline,
)
from orbit_ocsp.sequence_annotation import _score_records


def _row(name, *, p, consensus, status="ok"):
    return {
        "query_id": name,
        "gene_symbol": name,
        "gene_name": name,
        "scoring_status": status,
        "de_rank": None,
        "biomarker_score": (
            None
            if status != "ok"
            else {"primary_p_value": p, "consensus_score": consensus}
        ),
    }


def _apply(sort_key, rows):
    ordered = sorted(rows, key=sort_key)
    return [r["query_id"] for r in ordered]


def _extract_sort_key(func, marker="_sort_key"):
    """Pull the nested _sort_key out of a pipeline function for direct testing."""
    for const in func.__code__.co_consts:
        if getattr(const, "co_name", None) == marker:
            import types

            return types.FunctionType(const, func.__globals__)
    raise AssertionError(f"{marker} not found in {func.__name__}")


SORT_KEYS = {
    "expression": _extract_sort_key(run_expression_biomarker_pipeline),
    "genes": _extract_sort_key(run_genes_biomarker_pipeline),
    "sequence": _extract_sort_key(_score_records),
}


@pytest.mark.parametrize("mode", sorted(SORT_KEYS))
def test_lower_p_wins_over_higher_consensus(mode):
    """A stronger p-value outranks a higher consensus score."""
    rows = [
        _row("HIGH_CONSENSUS_WEAK_P", p=1e-3, consensus=1.0),
        _row("LOW_CONSENSUS_STRONG_P", p=1e-12, consensus=0.2),
    ]
    assert _apply(SORT_KEYS[mode], rows)[0] == "LOW_CONSENSUS_STRONG_P"


@pytest.mark.parametrize("mode", sorted(SORT_KEYS))
def test_consensus_breaks_ties_only(mode):
    """With equal p-values, the higher consensus score comes first."""
    rows = [
        _row("LOW_CONSENSUS", p=1e-9, consensus=0.2),
        _row("HIGH_CONSENSUS", p=1e-9, consensus=0.8),
    ]
    assert _apply(SORT_KEYS[mode], rows) == ["HIGH_CONSENSUS", "LOW_CONSENSUS"]


@pytest.mark.parametrize("mode", sorted(SORT_KEYS))
def test_unscored_rows_sort_last(mode):
    rows = [
        _row("NO_ANNOTATION", p=None, consensus=None, status="no_pathway_annotation"),
        _row("SCORED", p=0.9, consensus=0.0),
    ]
    assert _apply(SORT_KEYS[mode], rows) == ["SCORED", "NO_ANNOTATION"]


@pytest.mark.parametrize("mode", sorted(SORT_KEYS))
def test_p_ordering_is_strict(mode):
    """Ranking is monotone in p-value regardless of consensus."""
    rows = [
        _row("D", p=1e-2, consensus=1.0),
        _row("B", p=1e-8, consensus=0.0),
        _row("A", p=1e-15, consensus=0.2),
        _row("C", p=1e-5, consensus=0.8),
    ]
    assert _apply(SORT_KEYS[mode], rows) == ["A", "B", "C", "D"]


def test_published_focus_gene_ranks_are_reproduced():
    """Regression on the published GSE64392 focus-gene ranks.

    Values from the paper's Table S4 / Figure 5D. The evaluation that produced
    them ranked by 1 - p, which is equivalent to ranking by p, so the corrected
    order must still reproduce them.
    """
    published = {"CD44": 8, "LEF1": 18, "AXIN2": 38, "LGR5": 117}
    focus_p = {
        "CD44": 3.634623110728946e-12,
        "LEF1": 2.979053517717158e-09,
        "AXIN2": 3.774403819206669e-05,
        "LGR5": 0.16353425011690503,
    }

    # Reconstruct a shortlist that places each focus gene at its published rank.
    rows: list[dict] = []
    for gene, rank in sorted(published.items(), key=lambda kv: kv[1]):
        rows.append(_row(gene, p=focus_p[gene], consensus=0.6))
    # Filler genes stronger than CD44 to fill ranks 1..7, etc.
    filler_specs = [(7, 1e-13), (9, 1e-10), (19, 1e-6), (78, 1e-3)]
    made = 0
    for count, p in filler_specs:
        for i in range(count):
            rows.append(_row(f"FILL{made}", p=p, consensus=1.0))
            made += 1

    order = _apply(SORT_KEYS["genes"], rows)
    got = {g: order.index(g) + 1 for g in published}
    assert got == published, f"published ranks not reproduced: {got}"
