"""Unit tests for current B_terms schema accessors."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from orbit_ocsp.b_terms_schema import (
    b_categories,
    b_category_match,
    b_get,
    b_pathway_terms,
    b_record_matches,
    load_condition_pathways,
)
from orbit_ocsp.expression_pipeline import load_condition_terms
from orbit_ocsp.permutation_test_terms import build_B_groups_from_json, read_B_from_json


SAMPLE = {
    "GSE_ID": "GSE1",
    "condition": "Normal",
    "additional_condition": "note",
    "factor": "drugX",
    "organ_control": "Brain",
    "organ_condition": "Brain",
    "organ_system_control": ["Nervous System"],
    "organ_system_condition": ["Nervous System"],
    "organ_candidates_control": ["Brain", "Skull"],
    "organ_candidates_condition": ["Brain", "Skull"],
    "comparison_control": "ctrl",
    "comparison_condition": "treat",
    "model_control": "Organoid",
    "model_condition": "Organoid",
    "cell_type": "Bulk",
    "time_control": "48 h",
    "time_condition": "48 h",
    "source_control": "iPSCs",
    "source_condition": "iPSCs",
    "category": ["Cell Biology"],
    "pathway": {
        "enrich": ["GO:0000070", "GO:0000075"],
        "gsea": ["GO:0000086"],
        "gsva": ["GO:0000012"],
    },
}


def test_b_get_prefers_condition_fields_not_candidates():
    assert b_get(SAMPLE, "organ_condition") == "Brain"
    assert b_get(SAMPLE, "organ_control") == "Brain"
    assert b_get(SAMPLE, "source_condition") == "iPSCs"
    assert b_get(SAMPLE, "source_control") == "iPSCs"
    assert b_get(SAMPLE, "time_condition") == "48 h"
    assert b_get(SAMPLE, "time_control") == "48 h"
    assert "Skull" not in b_get(SAMPLE, "organ_condition")


def test_organ_system_list_filters():
    assert b_record_matches(
        SAMPLE,
        organ_condition="Brain",
        organ_system_condition="Nervous System",
    )
    assert not b_record_matches(SAMPLE, organ_system_condition="Digestive System")
    assert b_record_matches(
        SAMPLE,
        organ_system_control="Nervous System",
        organ_control="Brain",
    )


def test_paired_control_filters_are_independent():
    rec = {
        **SAMPLE,
        "organ_condition": "Brain",
        "organ_control": "Liver",
        "source_condition": "iPSCs",
        "source_control": "ESCs",
    }
    assert b_record_matches(rec, organ_condition="Brain", organ_control="Liver")
    assert not b_record_matches(rec, organ_condition="Brain", organ_control="Brain")
    assert b_record_matches(rec, source_condition="iPSCs", source_control="ESCs")
    assert not b_record_matches(rec, source_control="iPSCs")


def test_category_list_and_pathway_enrich():
    assert b_categories(SAMPLE) == ["Cell Biology"]
    assert b_category_match(SAMPLE, "Cell Biology")
    assert not b_category_match(SAMPLE, "Disease")
    assert b_pathway_terms(SAMPLE) == ["GO:0000070", "GO:0000075"]
    assert "GO:0000012" not in b_pathway_terms(SAMPLE)  # gsva excluded by default


def test_record_match_uses_real_fields():
    assert b_record_matches(
        SAMPLE,
        organ="Brain",
        model="Organoid",
        category="Cell Biology",
        day="48 h",
        source="iPSCs",
    )
    assert not b_record_matches(SAMPLE, organ="Colon")
    assert not b_record_matches(SAMPLE, model="Cell")


def test_build_groups_and_read_b_with_current_schema():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([SAMPLE], f)
        path = f.name
    try:
        groups, meta = build_B_groups_from_json(
            path,
            organ_filter="Brain",
            model_filter="Organoid",
            category_filter="Cell Biology",
            day_filter="48 h",
            source_filter="iPSCs",
            allowed_kegg=("hsa",),
        )
        key = ("Normal", "note", "Brain", "Organoid")
        assert key in groups
        assert groups[key] == {"GO:0000070", "GO:0000075"}
        assert meta[key]["organ_condition"] == "Brain"
        assert meta[key]["organ_control"] == "Brain"
        assert meta[key]["source_control"] == "iPSCs"
        assert meta[key]["time_condition"] == "48 h"
        assert meta[key]["time_control"] == "48 h"

        kept, dropped, _dupes = read_B_from_json(
            path,
            cond_filter="Normal",
            add_cond_filter="",
            organ_filter="",
            model_filter="",
            allowed_kegg=("hsa",),
            category_filter="Cell Biology",
            organ_condition_filter="Brain",
            organ_control_filter="Brain",
            source_condition_filter="iPSCs",
            source_control_filter="iPSCs",
            time_condition_filter="48 h",
            time_control_filter="48 h",
        )
        assert kept == {"GO:0000070", "GO:0000075"}
        assert dropped == []
    finally:
        Path(path).unlink(missing_ok=True)


def test_load_condition_terms_majority_and_filters():
    recs = [
        {
            **SAMPLE,
            "GSE_ID": "GSE1",
            "pathway": {"enrich": ["GO:0000001", "GO:0000002"]},
        },
        {
            **SAMPLE,
            "GSE_ID": "GSE2",
            "pathway": {"enrich": ["GO:0000001", "GO:0000003"]},
        },
        {
            **SAMPLE,
            "GSE_ID": "GSE3",
            "model_condition": "Cell",  # filtered out when model=Organoid
            "pathway": {"enrich": ["GO:0000001"]},
        },
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(recs, f)
        path = f.name
    try:
        # union + min_dataset_freq=2 → only GO:0000001
        terms = load_condition_terms(
            path,
            "Normal",
            category="Cell Biology",
            model="Organoid",
            pathway_mode="union",
            min_dataset_freq=2,
        )
        assert terms == ["GO:0000001"]

        # majority over 2 Organoid datasets → cut=1, but min_dataset_freq=2 → still only shared
        terms_m = load_condition_pathways(
            [r for r in recs if r["model_condition"] == "Organoid"],
            "Normal",
            category="Cell Biology",
            model="Organoid",
            pathway_mode="majority",
            min_dataset_freq=2,
        )
        assert terms_m == ["GO:0000001"]
    finally:
        Path(path).unlink(missing_ok=True)


def test_legacy_flat_fields_still_work():
    legacy = {
        "condition": "cancer",
        "additional_condition": "wnt",
        "organ": "colon",
        "model": "organoid",
        "category": "Disease",
        "day": "D7",
        "source": "iPSC",
        "pathway": ["GO:0008150", "GO:0008152"],
    }
    assert b_get(legacy, "organ") == "colon"
    assert b_get(legacy, "time") == "D7"
    assert b_pathway_terms(legacy) == ["GO:0008150", "GO:0008152"]
    assert b_record_matches(legacy, organ="colon", model="organoid", day="D7")
