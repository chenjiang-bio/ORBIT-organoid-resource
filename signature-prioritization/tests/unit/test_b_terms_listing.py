"""Tests for B_terms field listing."""

from __future__ import annotations

import json
from pathlib import Path

from orbit_ocsp.b_terms_listing import (
    collect_condition_tree,
    collect_field_values,
    format_text_listing,
)


def test_collect_field_values_from_sample(tmp_path):
    b_path = tmp_path / "B_terms_hsa.json"
    b_path.write_text(
        json.dumps(
            [
                {
                    "condition": "Colorectal Cancer",
                    "additional_condition": "High Wnt",
                    "factor": "APC",
                    "organ_condition": "Colon",
                    "organ_control": "Colon",
                    "model_condition": "Organoid",
                    "model_control": "Organoid",
                    "category": ["Cell Biology"],
                },
                {
                    "condition": "Colorectal Cancer",
                    "additional_condition": None,
                    "factor": "KRAS",
                    "organ_condition": "Colon",
                    "organ_control": "Liver",
                    "model_condition": "Organoid",
                    "model_control": "Tissue",
                    "category": ["Genetic Studies"],
                },
            ]
        ),
        encoding="utf-8",
    )

    values = collect_field_values(b_path, ["condition", "factor", "organ_control"])
    assert values["condition"] == ["Colorectal Cancer"]
    assert values["factor"] == ["APC", "KRAS"]
    assert values["organ_control"] == ["Colon", "Liver"]

    tree = collect_condition_tree(b_path)
    assert set(tree["Colorectal Cancer"]) == {"", "High Wnt"}

    text = format_text_listing(values, condition_tree=tree)
    assert "Colorectal Cancer" in text
    assert "organ_control" in text


def _counted_b_terms(tmp_path) -> Path:
    """Three conditions with deliberately different support levels."""
    records = []
    for _ in range(5):
        records.append({"condition": "Common", "factor": "APC",
                        "category": ["Cell Biology", "Genetic Studies"]})
    for _ in range(2):
        records.append({"condition": "Middling", "factor": "KRAS",
                        "category": ["Cell Biology"]})
    records.append({"condition": "Rare", "factor": "TP53", "category": []})
    records.append({"condition": "", "factor": ""})

    path = tmp_path / "B_terms_hsa.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def test_field_counts_reflect_record_support(tmp_path):
    from orbit_ocsp.b_terms_listing import collect_field_counts

    counts = collect_field_counts(_counted_b_terms(tmp_path), ["condition"])

    assert counts["condition"]["Common"] == 5
    assert counts["condition"]["Middling"] == 2
    assert counts["condition"]["Rare"] == 1


def test_frequency_order_puts_best_supported_first(tmp_path):
    from orbit_ocsp.b_terms_listing import collect_field_values

    values = collect_field_values(
        _counted_b_terms(tmp_path), ["condition"], order="frequency"
    )

    assert values["condition"][:3] == ["Common", "Middling", "Rare"]


def test_alpha_order_is_still_available_and_is_the_library_default(tmp_path):
    from orbit_ocsp.b_terms_listing import collect_field_values

    path = _counted_b_terms(tmp_path)
    default = collect_field_values(path, ["factor"])
    explicit = collect_field_values(path, ["factor"], order="alpha")

    assert default == explicit
    # Alphabetical, so the least-supported TP53 is not pushed to the back.
    assert default["factor"] == ["APC", "KRAS", "TP53"]


def test_frequency_and_alpha_orders_differ_when_support_is_uneven(tmp_path):
    from orbit_ocsp.b_terms_listing import collect_field_values

    path = _counted_b_terms(tmp_path)
    path.write_text(
        json.dumps(
            [{"condition": "Zebra"}] * 4 + [{"condition": "Alpha"}]
        ),
        encoding="utf-8",
    )

    assert collect_field_values(path, ["condition"], order="alpha")["condition"] == [
        "Alpha",
        "Zebra",
    ]
    assert collect_field_values(
        path, ["condition"], order="frequency"
    )["condition"] == ["Zebra", "Alpha"]


def test_blank_values_are_not_listed_as_choices(tmp_path):
    """A blank field is absence of a value, not a selectable filter value."""
    from orbit_ocsp.b_terms_listing import collect_field_counts, collect_field_values

    path = _counted_b_terms(tmp_path)
    for order in ("alpha", "frequency"):
        values = collect_field_values(path, ["condition"], order=order)
        assert "" not in values["condition"], order
    assert "" not in collect_field_counts(path, ["condition"])["condition"]


def test_list_valued_field_counts_each_record_once(tmp_path):
    """A record listing two categories must not count twice for one category."""
    from orbit_ocsp.b_terms_listing import collect_field_counts

    counts = collect_field_counts(_counted_b_terms(tmp_path), ["category"])

    # 5 records carry "Cell Biology" twice-listed? No: 5 + 2 records list it once each.
    assert counts["category"]["Cell Biology"] == 7
    assert counts["category"]["Genetic Studies"] == 5


def test_counts_sum_is_consistent_with_record_count(tmp_path):
    from orbit_ocsp.b_terms_listing import collect_field_counts

    path = _counted_b_terms(tmp_path)
    counts = collect_field_counts(path, ["condition"])
    records = json.loads(path.read_text())
    with_a_condition = sum(1 for r in records if str(r.get("condition") or "").strip())

    # condition is single-valued, so counts partition the records that have one.
    assert sum(counts["condition"].values()) == with_a_condition


def test_invalid_order_is_rejected(tmp_path):
    import pytest

    from orbit_ocsp.b_terms_listing import collect_field_values

    with pytest.raises(ValueError, match="order must be"):
        collect_field_values(_counted_b_terms(tmp_path), ["condition"], order="nope")


def test_text_listing_shows_counts_when_provided(tmp_path):
    from orbit_ocsp.b_terms_listing import collect_field_counts, collect_field_values

    path = _counted_b_terms(tmp_path)
    counts = collect_field_counts(path, ["condition"])
    values = collect_field_values(path, ["condition"], order="frequency")

    text = format_text_listing(values, field_counts=counts)

    assert "most records first" in text
    assert "5  Common" in text
    # Without counts the old plain rendering is preserved.
    plain = format_text_listing(values)
    assert "most records first" not in plain
    assert "- Common" in plain


def test_counts_match_a_real_background_build(tmp_path):
    """The listed count is the number of records a background would draw from."""
    from orbit_ocsp.b_terms_listing import collect_field_counts

    records = [
        {"condition": "Colorectal Cancer", "pathway": {"enrich": ["GO:0001"]}},
        {"condition": "Colorectal Cancer", "pathway": {"enrich": ["GO:0002"]}},
        {"condition": "Breast Cancer", "pathway": {"enrich": ["GO:0003"]}},
    ]
    path = tmp_path / "B.json"
    path.write_text(json.dumps(records), encoding="utf-8")

    counts = collect_field_counts(path, ["condition"])

    assert counts["condition"]["Colorectal Cancer"] == 2
    assert counts["condition"]["Breast Cancer"] == 1
    # Frequency order surfaces the better-supported condition first.
    assert list(counts["condition"]) == ["Colorectal Cancer", "Breast Cancer"]


def test_condition_tree_frequency_order(tmp_path):
    from orbit_ocsp.b_terms_listing import collect_condition_tree

    tree = collect_condition_tree(_counted_b_terms(tmp_path), order="frequency")

    keys = [k for k in tree if k]
    assert keys[0] == "Common"


def test_cli_top_limits_output_to_best_supported(tmp_path, capsys, monkeypatch):
    from orbit_ocsp import list_b_fields

    path = _counted_b_terms(tmp_path)
    monkeypatch.setattr(list_b_fields, "ensure_data_available", lambda species: None)

    exit_code = list_b_fields.main(
        ["--species", "hsa", "--b-terms", str(path), "--field", "condition", "--top", "2"]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Common" in out
    assert "Middling" in out
    assert "Rare" not in out


def test_cli_rejects_nonpositive_top(tmp_path, capsys, monkeypatch):
    from orbit_ocsp import list_b_fields

    path = _counted_b_terms(tmp_path)
    monkeypatch.setattr(list_b_fields, "ensure_data_available", lambda species: None)

    exit_code = list_b_fields.main(
        ["--species", "hsa", "--b-terms", str(path), "--field", "condition", "--top", "0"]
    )

    assert exit_code == 2
