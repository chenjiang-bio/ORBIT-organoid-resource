"""Unit tests for sequence-mode annotation merging."""

from __future__ import annotations

import json

import pytest

from orbit_ocsp.sequence_annotation import (
    CONTRACT_FIELDS,
    DEFAULT_DEEPGO_MIN_SCORE,
    SOURCE_DEEPGO,
    SOURCE_INTERPRO,
    SOURCE_KOFAM,
    IdResolver,
    SequenceInputError,
    discover_annotation_dir,
    load_id_map,
    load_ko_pathway_map,
    merge_annotations,
    parse_deepgoplus,
    parse_interproscan,
    parse_kofam,
    read_merged_json,
    records_to_gene_pathways,
    species_prefix_mismatches,
    validate_merged_records,
    write_merged_json,
)

KOFAM_SAMPLE = """\
# gene name           KO     thrshld  score   E-value KO definition
#-------------------- ------ ------- ------ --------- --------------------
  NP_1.1              K00001  316.13  176.3   2.9e-56 alcohol dehydrogenase
* NP_1.1              K00002  381.60  124.4   2.4e-40 second hit with spaces
  NP_1.1              K99999       -      -   1.0e-01 dash threshold and score
  NP_2.2              K00001  200.00   12.5   1.0e-05 low scoring hit
garbage line that should be skipped
"""

IPR_SAMPLE = (
    "NP_1.1\thash\t495\tGene3D\tG3DSA:2.60\tImmunoglobulins\t26\t111\t"
    "9.8E-11\tT\t19-07-2026\tIPR013783\tIg-like fold\tGO:0005515|GO:0005886\t"
    "MetaCyc:PWY-1901|Reactome:R-HSA-114608\n"
    "NP_1.1\thash\t495\tPfam\tPF00047\tIg\t30\t100\t1.0E-5\tT\t19-07-2026\t"
    "IPR013783\tIg-like fold\t-\t-\n"
    "NP_1.1\thash\t495\tSMART\tSM00409\tIG\t30\t100\t1.0E-5\tT\t19-07-2026\t"
    "IPR013783\tIg-like fold\tGO:0005515\t-\n"
    "NP_1.1\ttoo\tfew\tcolumns\n"
)

DEEPGO_SAMPLE = """\
NP_1.1\tGO:0001775\t0.129
NP_1.1\tGO:0003674\t0.521
NP_1.1\tGO:0005515\t0.900
NP_1.1\tGO:0005515\t0.400
NP_1.1\tGO:0009999\tnot_a_number
NP_1.1\tnotago\t0.5
"""


@pytest.fixture()
def ko_map_file(tmp_path):
    path = tmp_path / "ko2hsa.txt"
    path.write_text(
        "KO\tPathway\n"
        "K00001\thsa00010\n"
        "K00001\thsa01100\n"  # multi-pathway KO must not collapse
        "K00002\thsa04350\n",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# KO -> pathway mapping
# --------------------------------------------------------------------------

def test_ko_map_keeps_all_pathways_per_ko(ko_map_file):
    """Regression: the prototype's dict(zip(...)) dropped all but the last row."""
    mapping = load_ko_pathway_map(ko_map_file)
    assert mapping["K00001"] == ["hsa00010", "hsa01100"]
    assert mapping["K00002"] == ["hsa04350"]


def test_ko_map_generic_layout_strips_prefixes_and_drops_map(tmp_path):
    path = tmp_path / "ko2pathway.txt"
    path.write_text(
        "ko:K00001\tpath:map00010\nko:K00001\tpath:ko00010\n", encoding="utf-8"
    )
    mapping = load_ko_pathway_map(path)
    assert mapping == {"K00001": ["ko00010"]}


def test_ko_map_rejects_wrong_columns(tmp_path):
    path = tmp_path / "bad.txt"
    path.write_text("KO\tSomethingElse\nK1\tx\n", encoding="utf-8")
    with pytest.raises(SequenceInputError, match="'KO' and 'Pathway'"):
        load_ko_pathway_map(path)


def test_ko_map_missing_file(tmp_path):
    with pytest.raises(SequenceInputError, match="not found"):
        load_ko_pathway_map(tmp_path / "absent.txt")


# --------------------------------------------------------------------------
# KOfam parser
# --------------------------------------------------------------------------

def test_parse_kofam_expands_all_pathways(tmp_path, ko_map_file):
    path = tmp_path / "k.txt"
    path.write_text(KOFAM_SAMPLE, encoding="utf-8")
    terms, stats = parse_kofam(path, load_ko_pathway_map(ko_map_file))
    assert terms["NP_1.1"] == ["hsa00010", "hsa01100", "hsa04350"]
    assert terms["NP_2.2"] == ["hsa00010", "hsa01100"]
    assert stats.parsed_lines == 4
    assert stats.skipped_lines == 1


def test_parse_kofam_handles_star_and_dash(tmp_path, ko_map_file):
    path = tmp_path / "k.txt"
    path.write_text(KOFAM_SAMPLE, encoding="utf-8")
    terms, _ = parse_kofam(path, load_ko_pathway_map(ko_map_file))
    # the starred K00002 row parsed, and the dash-threshold row didn't crash
    assert "hsa04350" in terms["NP_1.1"]


def test_parse_kofam_unmapped_ko_yields_no_terms(tmp_path, ko_map_file):
    path = tmp_path / "k.txt"
    path.write_text(
        "  NP_9.9              K88888  10.0  5.0   1e-3 unmapped\n", encoding="utf-8"
    )
    terms, stats = parse_kofam(path, load_ko_pathway_map(ko_map_file))
    assert terms == {"NP_9.9": []}
    assert stats.parsed_lines == 1


def test_parse_kofam_min_score_filter(tmp_path, ko_map_file):
    path = tmp_path / "k.txt"
    path.write_text(KOFAM_SAMPLE, encoding="utf-8")
    _, stats = parse_kofam(path, load_ko_pathway_map(ko_map_file), min_score=100.0)
    assert stats.filtered_lines == 2  # score 12.5 and the dash-score row (0.0)


def test_parse_kofam_empty_file(tmp_path, ko_map_file):
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")
    terms, stats = parse_kofam(path, load_ko_pathway_map(ko_map_file))
    assert terms == {}
    assert stats.empty_file is True


# --------------------------------------------------------------------------
# InterProScan parser
# --------------------------------------------------------------------------

def test_parse_interproscan_extracts_go_dedups_and_skips_short_rows(tmp_path):
    path = tmp_path / "i.tsv"
    path.write_text(IPR_SAMPLE, encoding="utf-8")
    terms, stats = parse_interproscan(path)
    assert terms["NP_1.1"] == ["GO:0005515", "GO:0005886"]
    assert stats.skipped_lines == 1


def test_parse_interproscan_ignores_metacyc_and_reactome(tmp_path):
    path = tmp_path / "i.tsv"
    path.write_text(IPR_SAMPLE, encoding="utf-8")
    terms, _ = parse_interproscan(path)
    joined = " ".join(terms["NP_1.1"])
    assert "MetaCyc" not in joined and "Reactome" not in joined


def test_parse_interproscan_skips_header_row(tmp_path):
    path = tmp_path / "i.tsv"
    cols = ["Protein accession"] + [f"c{i}" for i in range(13)]
    path.write_text("\t".join(cols) + "\n" + IPR_SAMPLE, encoding="utf-8")
    terms, _ = parse_interproscan(path)
    assert "Protein accession" not in terms


# --------------------------------------------------------------------------
# DeepGOPlus parser
# --------------------------------------------------------------------------

def test_parse_deepgoplus_default_threshold_keeps_everything(tmp_path):
    path = tmp_path / "d.tsv"
    path.write_text(DEEPGO_SAMPLE, encoding="utf-8")
    terms, scores, stats = parse_deepgoplus(path)
    assert DEFAULT_DEEPGO_MIN_SCORE == 0.0
    assert stats.filtered_lines == 0
    assert terms["NP_1.1"] == [
        "GO:0001775",
        "GO:0003674",
        "GO:0005515",
        "GO:0009999",
    ]
    assert scores["NP_1.1"]["GO:0001775"] == pytest.approx(0.129)


def test_parse_deepgoplus_threshold_filters(tmp_path):
    path = tmp_path / "d.tsv"
    path.write_text(DEEPGO_SAMPLE, encoding="utf-8")
    terms, scores, stats = parse_deepgoplus(path, min_score=0.5)
    assert "GO:0001775" not in terms["NP_1.1"]
    # filtered: 0.129, plus the 0.400 duplicate of GO:0005515
    assert stats.filtered_lines == 2
    assert scores["NP_1.1"]["GO:0005515"] == pytest.approx(0.900)


def test_parse_deepgoplus_keeps_max_score_on_duplicates(tmp_path):
    path = tmp_path / "d.tsv"
    path.write_text(DEEPGO_SAMPLE, encoding="utf-8")
    _, scores, _ = parse_deepgoplus(path)
    assert scores["NP_1.1"]["GO:0005515"] == pytest.approx(0.900)


def test_parse_deepgoplus_null_score_bypasses_threshold(tmp_path):
    path = tmp_path / "d.tsv"
    path.write_text(DEEPGO_SAMPLE, encoding="utf-8")
    terms, scores, _ = parse_deepgoplus(path, min_score=0.99)
    assert "GO:0009999" in terms["NP_1.1"]
    assert scores["NP_1.1"]["GO:0009999"] is None


# --------------------------------------------------------------------------
# ID resolution
# --------------------------------------------------------------------------

def test_id_map_requires_query_id_column(tmp_path):
    path = tmp_path / "m.tsv"
    path.write_text("protein\tentrez_id\nX\t1\n", encoding="utf-8")
    with pytest.raises(SequenceInputError, match="query_id"):
        load_id_map(path)


def test_id_map_first_duplicate_wins(tmp_path):
    path = tmp_path / "m.tsv"
    path.write_text(
        "query_id\tgene_symbol\nQ1\tAAA\nQ1\tBBB\n", encoding="utf-8"
    )
    assert load_id_map(path)["Q1"]["gene_symbol"] == "AAA"


def test_id_map_captures_evidence_columns(tmp_path):
    path = tmp_path / "m.tsv"
    path.write_text(
        "query_id\tgene_symbol\tidentity\tevalue\nQ1\tAAA\t99.5\t1e-90\n",
        encoding="utf-8",
    )
    assert load_id_map(path)["Q1"]["id_evidence"] == {
        "identity": "99.5",
        "evalue": "1e-90",
    }


def test_resolver_uses_exact_match_not_prefix():
    """Regression: the prototype used startswith and could mis-assign IDs."""
    resolver = IdResolver({"NP_570602": {"gene_symbol": "WRONG", "entrez_id": "9"}})
    resolved = resolver.resolve("NP_570602.2")
    assert resolved["similarity_gene_name"] == "NP_570602.2"
    assert resolved["id_source"] == "fallback_query_id"


def test_resolver_fallback_keeps_record_scorable():
    resolver = IdResolver({})
    resolved = resolver.resolve("NP_1.1")
    # similarity_gene_name is the only key load_gene_pathways will index here
    assert resolved["similarity_gene_name"] == "NP_1.1"
    assert resolved["ENTREZ_ID"] == ""


def test_resolver_prefers_explicit_symbol():
    resolver = IdResolver(
        {"NP_1.1": {"gene_symbol": "CD44", "entrez_id": "960"}}
    )
    resolved = resolver.resolve("NP_1.1")
    assert resolved["similarity_gene_name"] == "CD44"
    assert resolved["ENTREZ_ID"] == "960"
    assert resolved["id_source"] == "id_map"


# --------------------------------------------------------------------------
# Merge engine
# --------------------------------------------------------------------------

def test_merge_orders_sources_and_dedups():
    records, excluded = merge_annotations(
        kofam_terms={"Q": ["hsa00010"]},
        interpro_terms={"Q": ["GO:0005515"]},
        deepgo_terms={"Q": ["GO:0005515", "GO:0003674"]},
        deepgo_scores={"Q": {"GO:0005515": 0.9, "GO:0003674": 0.5}},
    )
    assert excluded == []
    record = records[0]
    assert record["pathway"] == ["hsa00010", "GO:0005515", "GO:0003674"]
    assert record["pathway_sources"]["GO:0005515"] == [
        SOURCE_INTERPRO,
        SOURCE_DEEPGO,
    ]
    assert record["pathway_sources"]["hsa00010"] == [SOURCE_KOFAM]


def test_merge_records_deepgo_scores_in_evidence():
    records, _ = merge_annotations(
        deepgo_terms={"Q": ["GO:0003674"]},
        deepgo_scores={"Q": {"GO:0003674": 0.5}},
    )
    assert records[0]["term_evidence"]["GO:0003674"]["deepgoplus_score"] == 0.5


def test_merge_excludes_query_with_zero_terms():
    records, excluded = merge_annotations(kofam_terms={"Q": []})
    assert records == []
    assert excluded == [{"query_id": "Q", "reason": "no_terms"}]


def test_merge_pathway_and_sources_are_bijective():
    records, _ = merge_annotations(
        kofam_terms={"Q": ["hsa00010", "hsa00010"]},
        interpro_terms={"Q": ["GO:0005515"]},
        deepgo_terms={"Q": ["GO:0005515"]},
    )
    record = records[0]
    assert set(record["pathway"]) == set(record["pathway_sources"])
    assert len(record["pathway"]) == len(record["pathway_sources"])


def test_merge_query_id_filter():
    records, _ = merge_annotations(
        kofam_terms={"Q1": ["hsa00010"], "Q2": ["hsa00020"]},
        query_id="Q2",
    )
    assert [r["gene_name"] for r in records] == ["Q2"]


# --------------------------------------------------------------------------
# Merged JSON I/O
# --------------------------------------------------------------------------

def test_merged_json_roundtrip_preserves_records(tmp_path):
    records, _ = merge_annotations(
        kofam_terms={"Q": ["hsa00010"]},
        deepgo_terms={"Q": ["GO:0003674"]},
        deepgo_scores={"Q": {"GO:0003674": 0.5}},
    )
    path = write_merged_json(records, tmp_path / "m.json")
    assert read_merged_json(path) == read_merged_json(write_merged_json(
        read_merged_json(path), tmp_path / "m2.json"
    ))


def test_merged_json_roundtrip_text_stable(tmp_path):
    records, _ = merge_annotations(kofam_terms={"Q": ["hsa00010"]})
    first = write_merged_json(records, tmp_path / "a.json")
    second = write_merged_json(read_merged_json(first), tmp_path / "b.json")
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_merged_json_contract_field_types(tmp_path):
    records, _ = merge_annotations(kofam_terms={"Q": ["hsa00010"]})
    path = write_merged_json(records, tmp_path / "m.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    for field in CONTRACT_FIELDS:
        assert field in payload[0]
    assert isinstance(payload[0]["ENTREZ_ID"], str)
    assert isinstance(payload[0]["similarity_gene_name"], str)
    assert isinstance(payload[0]["pathway"], list)


def test_extension_fields_do_not_change_pathway_indexing(tmp_path):
    from orbit_ocsp.expression_pipeline import load_gene_pathways

    records, _ = merge_annotations(
        kofam_terms={"Q": ["hsa00010"]},
        deepgo_terms={"Q": ["GO:0003674"]},
        deepgo_scores={"Q": {"GO:0003674": 0.5}},
    )
    with_ext = write_merged_json(records, tmp_path / "ext.json")
    stripped = [
        {k: v for k, v in r.items() if k in CONTRACT_FIELDS} for r in records
    ]
    without_ext = write_merged_json(stripped, tmp_path / "plain.json")
    assert load_gene_pathways(with_ext) == load_gene_pathways(without_ext)


def test_read_merged_json_rejects_non_array(tmp_path):
    path = tmp_path / "obj.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(SequenceInputError, match="--merged-result"):
        read_merged_json(path)


def test_read_merged_json_reports_parse_position(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("[{]", encoding="utf-8")
    with pytest.raises(SequenceInputError, match="line 1"):
        read_merged_json(path)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def test_validate_flags_empty_pathway_and_missing_keys():
    scorable, excluded = validate_merged_records(
        [
            {"pathway": [], "similarity_gene_name": "A"},
            {"pathway": ["GO:0000001"]},
            {"pathway": ["GO:0000002"], "ENTREZ_ID": "7"},
        ]
    )
    assert len(scorable) == 1
    reasons = {item["reason"] for item in excluded}
    assert reasons == {"empty_pathway", "no_index_key"}


@pytest.mark.parametrize(
    "record,match",
    [
        ({"similarity_gene_name": "A"}, "missing required field 'pathway'"),
        ({"pathway": "GO:1"}, "must be an array"),
    ],
)
def test_validate_raises_on_contract_violations(record, match):
    with pytest.raises(SequenceInputError, match=match):
        validate_merged_records([record])


def test_records_to_gene_pathways_matches_loader_keys():
    records = [
        {
            "gene_name": "NP_1.1",
            "similarity_gene_name": "cd44",
            "ENTREZ_ID": "960",
            "pathway": ["hsa00010"],
        }
    ]
    keys = records_to_gene_pathways(records)
    assert set(keys) == {"cd44", "CD44", "960"}
    assert "NP_1.1" not in keys  # gene_name is intentionally not indexed


def test_species_prefix_mismatch_detected():
    records = [{"pathway": ["hsa00010", "mmu00010", "GO:0005515"]}]
    warning = species_prefix_mismatches(records, "hsa")
    assert warning["n_mismatched_terms"] == 1
    assert warning["found_prefixes"] == {"mmu": 1}
    assert species_prefix_mismatches([{"pathway": ["hsa00010"]}], "hsa") is None


# --------------------------------------------------------------------------
# Batch discovery
# --------------------------------------------------------------------------

def test_discover_groups_by_sample_key(tmp_path):
    (tmp_path / "kofam").mkdir()
    (tmp_path / "interproscan").mkdir()
    (tmp_path / "deepgoplus").mkdir()
    (tmp_path / "kofam" / "1.txt").write_text("x", encoding="utf-8")
    (tmp_path / "kofam" / "2.txt").write_text("x", encoding="utf-8")
    (tmp_path / "interproscan" / "1.tsv").write_text("x", encoding="utf-8")
    (tmp_path / "deepgoplus" / "1.tsv").write_text("x", encoding="utf-8")

    groups = discover_annotation_dir(tmp_path)
    assert set(groups) == {"1", "2"}
    assert set(groups["1"]) == {SOURCE_KOFAM, SOURCE_INTERPRO, SOURCE_DEEPGO}
    assert set(groups["2"]) == {SOURCE_KOFAM}


def test_discover_ignores_aggregate_kofam_files(tmp_path):
    (tmp_path / "kofam").mkdir()
    (tmp_path / "kofam" / "1.txt").write_text("x", encoding="utf-8")
    (tmp_path / "kofam" / "all_results.txt").write_text("x", encoding="utf-8")
    (tmp_path / "kofam" / "ko_result_x.txt").write_text("x", encoding="utf-8")
    assert set(discover_annotation_dir(tmp_path)) == {"1"}


def test_discover_empty_dir_errors(tmp_path):
    with pytest.raises(SequenceInputError, match="No annotation files"):
        discover_annotation_dir(tmp_path)
