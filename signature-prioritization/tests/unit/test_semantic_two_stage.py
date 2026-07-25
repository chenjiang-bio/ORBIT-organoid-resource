"""Tests for the label-blind two-stage semantic runner."""

import inspect

from orbit_ocsp.semantic_two_stage import (
    formal_selection_decision,
    select_formal_candidates,
)


def _result(method, p_value, effect_size):
    return {
        "method": method,
        "p_value": p_value,
        "effect_size": effect_size,
    }


def test_formal_selection_uses_either_semantic_method_at_fixed_rule():
    selected, reasons = formal_selection_decision(
        [
            _result("resnik_bma", 0.20, 1.0),
            _result("lin_bma", 0.08, 0.2),
        ],
        p_threshold=0.10,
    )
    rejected, rejected_reasons = formal_selection_decision(
        [
            _result("resnik_bma", 0.08, -0.1),
            _result("lin_bma", 0.20, 1.0),
        ],
        p_threshold=0.10,
    )

    assert selected is True
    assert reasons == ["lin_bma"]
    assert rejected is False
    assert rejected_reasons == []


def test_selector_reruns_both_methods_and_contains_no_truth_labels():
    screening = {
        "G1__A": [
            _result("resnik_bma", 0.08, 0.5),
            _result("lin_bma", 0.30, 0.2),
        ],
        "G2__A": [
            _result("resnik_bma", 0.40, 0.5),
            _result("lin_bma", 0.50, 0.2),
        ],
    }

    manifest = select_formal_candidates(screening, p_threshold=0.10)

    assert manifest["selected_sample_ids"] == ["G1__A"]
    assert manifest["formal_methods"] == ["resnik_bma", "lin_bma"]
    assert manifest["selection_is_label_blind"] is True
    assert "ground_truth" not in inspect.getsource(select_formal_candidates)
    assert "Diagnostic" not in inspect.getsource(select_formal_candidates)
    assert "Risk" not in inspect.getsource(select_formal_candidates)
