"""Unit tests for gene-ID → Entrez → sequence mapping."""

from pathlib import Path

import pytest

from orbit_ocsp.protein_lookup import (
    detect_id_type,
    load_canonical_sequence,
    load_symbol_to_entrez,
    lookup_entrez,
    map_gene_ids_to_proteins,
    map_symbols_to_proteins,
    normalize_species,
    parse_fasta_records,
    resolve_protein_root,
    resolve_to_entrez,
)


def _write_mock_protein_root(tmp_path: Path) -> Path:
    root = tmp_path / "data" / "protein"
    root.mkdir(parents=True)
    (root / "Gene_Annotation_Human.txt").write_text(
        "entrez_id\tensembl\tsymbol\n"
        "10\tENSG00000156006\tNAT2\n"
        "6934\tENSG00000148737\tTCF7L2\n"
        "999\tENSG00000000001\tNOFASTA\n",
        encoding="utf-8",
    )
    human = root / "human"
    human.mkdir()
    (human / "10.fasta").write_text(
        ">NP_000015.1 isoform A\nMALL\n"
        ">NP_000016.1 isoform B\nMAKK\n",
        encoding="utf-8",
    )
    (human / "6934.fasta").write_text(
        ">NP_001139755.1 TCF7L2\nMPQLNG\n",
        encoding="utf-8",
    )
    return root


def test_normalize_species_aliases():
    assert normalize_species("hsa") == "human"
    assert normalize_species("mmu") == "mouse"
    with pytest.raises(ValueError):
        normalize_species("yeast")


def test_detect_id_type():
    assert detect_id_type("6934") == "entrez"
    assert detect_id_type("ENSG00000148737") == "ensembl"
    assert detect_id_type("ENSG00000148737.1") == "ensembl"
    assert detect_id_type("ENSMUSG00000020804") == "ensembl"
    assert detect_id_type("TCF7L2") == "symbol"
    assert detect_id_type("nat2") == "symbol"


def test_resolve_protein_root_relative(tmp_path, monkeypatch):
    root = _write_mock_protein_root(tmp_path)
    monkeypatch.chdir(tmp_path)
    resolved = resolve_protein_root("data/protein")
    assert resolved == root.resolve()


def test_resolve_symbol_ensembl_entrez(tmp_path):
    root = _write_mock_protein_root(tmp_path)
    e1, t1, s1, ens1 = resolve_to_entrez("TCF7L2", "hsa", root)
    e2, t2, s2, ens2 = resolve_to_entrez("ENSG00000148737", "hsa", root)
    e3, t3, s3, ens3 = resolve_to_entrez("6934", "hsa", root)
    assert (e1, t1, s1) == ("6934", "symbol", "TCF7L2")
    assert (e2, t2, s2) == ("6934", "ensembl", "TCF7L2")
    assert ens2 == "ENSG00000148737"
    assert (e3, t3, s3) == ("6934", "entrez", "TCF7L2")
    assert ens3 == "ENSG00000148737"


def test_lookup_and_first_isoform_default(tmp_path):
    root = _write_mock_protein_root(tmp_path)
    assert lookup_entrez("nat2", "hsa", protein_root=root) == "10"
    protein = load_canonical_sequence("10", "human", protein_root=root)
    assert protein is not None
    assert protein["sequence"] == "MALL"
    assert protein["n_isoforms"] == 2
    assert protein["selected_isoform_index"] == 0
    assert protein["fasta_relpath"] == "data/protein/human/10.fasta"


def test_map_mixed_gene_ids(tmp_path):
    root = _write_mock_protein_root(tmp_path)
    rows = map_gene_ids_to_proteins(
        ["NAT2", "ENSG00000148737.1", "10", "MISSING", "NOFASTA"],
        species="hsa",
        protein_root=root,
    )
    by_query = {r["query_id"]: r for r in rows}
    assert by_query["NAT2"]["entrez_id"] == "10"
    assert by_query["NAT2"]["id_type"] == "symbol"
    assert by_query["NAT2"]["sequence"] == "MALL"
    assert by_query["ENSG00000148737.1"]["entrez_id"] == "6934"
    assert by_query["ENSG00000148737.1"]["gene_symbol"] == "TCF7L2"
    assert by_query["10"]["gene_symbol"] == "NAT2"
    assert by_query["10"]["sequence"] == "MALL"
    assert by_query["MISSING"]["mapping_status"] == "entrez_not_found"
    assert by_query["NOFASTA"]["mapping_status"] == "fasta_not_found"


def test_map_symbols_statuses(tmp_path):
    root = _write_mock_protein_root(tmp_path)
    rows = map_symbols_to_proteins(
        ["NAT2", "MISSING", "NOFASTA"],
        species="hsa",
        protein_root=root,
    )
    by_gene = {r["query_id"]: r for r in rows}
    assert by_gene["NAT2"]["mapping_status"] == "ok"
    assert by_gene["NAT2"]["sequence"] == "MALL"
    assert by_gene["MISSING"]["mapping_status"] == "entrez_not_found"
    assert by_gene["NOFASTA"]["mapping_status"] == "fasta_not_found"


def test_parse_fasta_records():
    records = parse_fasta_records(">a\nAA\n>b\nBB\n")
    assert records == [("a", "AA"), ("b", "BB")]


def test_load_symbol_map_from_mock(tmp_path):
    root = _write_mock_protein_root(tmp_path)
    mapping = load_symbol_to_entrez("human", protein_root=root)
    assert mapping["TCF7L2"] == "6934"
