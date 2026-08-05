"""Integration tests over ``examples/data/``, organized by input mode.

These keep the shipped sample files and the commands documented in
``examples/README.md`` / the tutorial notebook from drifting apart. Steps that
need the large scoring data are skipped when it is absent; parsing and merging
are always exercised because they only need in-repo files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "examples" / "data"

EXPRESSION = DATA / "expression"
GENES = DATA / "genes"
SEQ_NATIVE = DATA / "sequence" / "native"
SEQ_MERGED = DATA / "sequence" / "merged"

SPECIES = "hsa"
CONDITION = "Colorectal Cancer"


def _scoring_data_available() -> bool:
    from orbit_ocsp.data_manager import data_status

    return bool(data_status(SPECIES)["ready"])


needs_scoring_data = pytest.mark.skipif(
    not _scoring_data_available(),
    reason="scoring data missing; run orbit-ocsp-download-data or set ORBIT_OCSP_DATA",
)


def run_cli(*args: object) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "orbit_ocsp", *(str(a) for a in args)]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def assert_standard_outputs(outdir: Path) -> list[dict]:
    """Every mode must emit the same four files."""
    for name in (
        "biomarker_ranked.json",
        "biomarker_ranked.tsv",
        "method_scores.tsv",
        "pipeline_summary.json",
    ):
        assert (outdir / name).is_file(), f"missing {name} in {outdir}"
    return json.loads((outdir / "biomarker_ranked.json").read_text())


# ---------------------------------------------------------------------------
# Sample data layout
# ---------------------------------------------------------------------------

class TestSampleDataLayout:
    """The files the docs reference must exist and be well-formed."""

    @pytest.mark.parametrize(
        "relpath",
        [
            "expression/matrix.tsv",
            "expression/groups.tsv",
            "genes/genes.txt",
            "genes/genes_epms.txt",
            "genes/a_terms.json",
            "sequence/native/kofam/1.txt",
            "sequence/native/interproscan/1.tsv",
            "sequence/native/deepgoplus/1.tsv",
            "sequence/native/id_map.tsv",
            "sequence/merged/merged_result_1.json",
        ],
    )
    def test_sample_file_exists_and_is_not_empty(self, relpath):
        path = DATA / relpath
        assert path.is_file(), f"{path} is referenced by the docs but missing"
        assert path.stat().st_size > 0

    def test_example_configs_exist(self):
        for name in ("config.no_llm.yaml", "config.ensemble_test.yaml"):
            path = ROOT / "examples" / name
            assert path.is_file(), f"missing {path}"
            text = path.read_text()
            assert "sk-" not in text, f"{name} must not ship API keys"

    def test_expression_matrix_and_groups_agree(self):
        import pandas as pd

        matrix = pd.read_csv(EXPRESSION / "matrix.tsv", sep="\t")
        groups = pd.read_csv(EXPRESSION / "groups.tsv", sep="\t")
        assert matrix.columns[0] == "gene"
        assert {"sample_id", "group"} <= set(groups.columns)
        assert set(groups["group"]) <= {"case", "control"}
        assert set(groups["sample_id"]) <= set(matrix.columns[1:])
        # GSE50760 primary CRC vs normal: symbols only, balanced groups
        genes = matrix["gene"].astype(str)
        assert genes.str.fullmatch(r"\d+").sum() == 0
        assert len(matrix) >= 20
        assert (groups["group"] == "case").sum() == 18
        assert (groups["group"] == "control").sum() == 18
        assert groups["sample_id"].str.startswith("GSM1228").all()

    @pytest.mark.parametrize(
        "filename, n_genes",
        [
            ("genes.txt", 4),
            ("genes_epms.txt", 4),
        ],
    )
    def test_gene_list_is_one_symbol_per_line(self, filename, n_genes):
        genes = (GENES / filename).read_text().split()
        assert genes
        assert len(genes) == n_genes
        assert all(g == g.strip() and " " not in g for g in genes)

    def test_id_map_has_required_column(self):
        from orbit_ocsp.sequence_annotation import load_id_map

        mapping = load_id_map(SEQ_NATIVE / "id_map.tsv")
        assert "NP_570602.2" in mapping
        assert mapping["NP_570602.2"]["entrez_id"] == "1"

    def test_merged_sample_matches_the_contract(self):
        from orbit_ocsp.sequence_annotation import (
            read_merged_json,
            validate_merged_records,
        )

        records = read_merged_json(SEQ_MERGED / "merged_result_1.json")
        scorable, excluded = validate_merged_records(records)
        assert scorable, "the shipped merged sample must be scorable"
        assert excluded == []


# ---------------------------------------------------------------------------
# Mode 1 — expression
# ---------------------------------------------------------------------------

class TestExpressionMode:
    def test_missing_arguments_are_reported(self):
        proc = run_cli("--mode", "expression", "--condition", CONDITION)
        assert proc.returncode == 2
        assert "--matrix" in proc.stderr

    @needs_scoring_data
    def test_expression_pipeline_with_mock_de(self, tmp_path):
        outdir = tmp_path / "expression"
        proc = run_cli(
            "--mode", "expression",
            "--matrix", EXPRESSION / "matrix.tsv",
            "--groups", EXPRESSION / "groups.tsv",
            "--data-type", "rnaseq_count",
            "--species", SPECIES,
            "--condition", CONDITION,
            "--de-backend", "mock",
            "--padj-max", "1.0",
            "--abs-log2fc-min", "0.0",
            "--top-k", "3",
            "--outdir", outdir,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        ranked = assert_standard_outputs(outdir)
        assert (outdir / "de_results.tsv").is_file()
        summary = json.loads((outdir / "pipeline_summary.json").read_text())
        assert summary["mode"] == "expression"
        assert summary["data_type"] == "rnaseq_count"
        assert len(ranked) <= 3

    @needs_scoring_data
    def test_rnaseq_alias_is_accepted(self, tmp_path):
        outdir = tmp_path / "expression_alias"
        proc = run_cli(
            "--mode", "expression",
            "--matrix", EXPRESSION / "matrix.tsv",
            "--groups", EXPRESSION / "groups.tsv",
            "--data-type", "rnaseq",
            "--species", SPECIES,
            "--condition", CONDITION,
            "--de-backend", "mock",
            "--padj-max", "1.0",
            "--abs-log2fc-min", "0.0",
            "--top-k", "3",
            "--outdir", outdir,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        summary = json.loads((outdir / "pipeline_summary.json").read_text())
        assert summary["data_type"] == "rnaseq_count"


# ---------------------------------------------------------------------------
# Mode 2 — gene list
# ---------------------------------------------------------------------------

class TestGenesMode:
    def test_condition_or_factor_is_required(self):
        proc = run_cli("--mode", "genes", "--genes", "CD44")
        assert proc.returncode == 2
        assert "--condition" in proc.stderr or "--factor" in proc.stderr

    @needs_scoring_data
    @pytest.mark.parametrize(
        "genes_file",
        ["genes.txt", "genes_epms.txt"],
    )
    def test_gene_list_from_file(self, tmp_path, genes_file):
        outdir = tmp_path / genes_file.replace(".", "_")
        proc = run_cli(
            "--mode", "genes",
            "--genes-file", GENES / genes_file,
            "--species", SPECIES,
            "--condition", CONDITION,
            "--outdir", outdir,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        ranked = assert_standard_outputs(outdir)
        expected = (GENES / genes_file).read_text().split()
        assert len(ranked) == len(expected)
        assert all(row.get("biomarker_rank") for row in ranked)


# ---------------------------------------------------------------------------
# Mode 3, entry A — native annotation output
# ---------------------------------------------------------------------------

class TestSequenceModeNative:
    """Parsing and merging need no scoring data, so these always run."""

    def test_merge_only_produces_terms_from_all_three_tools(self, tmp_path):
        outdir = tmp_path / "merge"
        proc = run_cli(
            "--mode", "sequence",
            "--kofam", SEQ_NATIVE / "kofam/1.txt",
            "--interproscan", SEQ_NATIVE / "interproscan/1.tsv",
            "--deepgo", SEQ_NATIVE / "deepgoplus/1.tsv",
            "--id-map", SEQ_NATIVE / "id_map.tsv",
            "--species", SPECIES,
            "--merge-only",
            "--outdir", outdir,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]

        records = json.loads((outdir / "merged_a_terms.json").read_text())
        assert len(records) == 1
        record = records[0]
        assert record["gene_name"] == "NP_570602.2"
        assert record["ENTREZ_ID"] == "1"
        assert record["id_source"] == "id_map"

        sources = {
            source
            for entry in record["pathway_sources"].values()
            for source in entry
        }
        assert sources == {"kofam", "interproscan", "deepgoplus"}

    @needs_scoring_data
    def test_id_map_resolves_symbol_from_the_annotation_table(self, tmp_path):
        """Entrez 1 → A1BG requires data/protein/Gene_Annotation_Human.txt."""
        outdir = tmp_path / "symbol"
        run_cli(
            "--mode", "sequence",
            "--kofam", SEQ_NATIVE / "kofam/1.txt",
            "--id-map", SEQ_NATIVE / "id_map.tsv",
            "--species", SPECIES,
            "--merge-only",
            "--outdir", outdir,
        )
        record = json.loads((outdir / "merged_a_terms.json").read_text())[0]
        assert record["similarity_gene_name"] == "A1BG"

    def test_each_tool_can_be_supplied_alone(self, tmp_path):
        for flag, relpath in (
            ("--kofam", "kofam/1.txt"),
            ("--interproscan", "interproscan/1.tsv"),
            ("--deepgo", "deepgoplus/1.tsv"),
        ):
            outdir = tmp_path / flag.lstrip("-")
            proc = run_cli(
                "--mode", "sequence",
                flag, SEQ_NATIVE / relpath,
                "--species", SPECIES,
                "--merge-only",
                "--outdir", outdir,
            )
            assert proc.returncode == 0, f"{flag} alone failed: {proc.stderr[-800:]}"
            records = json.loads((outdir / "merged_a_terms.json").read_text())
            assert records[0]["pathway"], f"{flag} alone produced no terms"

    def test_annotation_dir_batch_discovers_the_sample(self, tmp_path):
        outdir = tmp_path / "batch"
        proc = run_cli(
            "--mode", "sequence",
            "--annotation-dir", SEQ_NATIVE,
            "--species", SPECIES,
            "--merge-only",
            "--outdir", outdir,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        report = json.loads((outdir / "sequence_merge_report.json").read_text())
        assert report["samples"] == {"1": {"status": "ok", "n_records": 1}}
        records = json.loads((outdir / "merged_a_terms.json").read_text())
        assert records[0]["sample_key"] == "1"

    def test_diagnostic_report_counts_every_input(self, tmp_path):
        outdir = tmp_path / "report"
        run_cli(
            "--mode", "sequence",
            "--kofam", SEQ_NATIVE / "kofam/1.txt",
            "--interproscan", SEQ_NATIVE / "interproscan/1.tsv",
            "--deepgo", SEQ_NATIVE / "deepgoplus/1.tsv",
            "--species", SPECIES,
            "--merge-only",
            "--outdir", outdir,
        )
        report = json.loads((outdir / "sequence_merge_report.json").read_text())
        assert {i["source"] for i in report["inputs"]} == {
            "kofam",
            "interproscan",
            "deepgoplus",
        }
        assert all(i["parsed_lines"] > 0 for i in report["inputs"])
        assert report["excluded"] == []

    def test_unmapped_query_falls_back_to_query_id(self, tmp_path):
        """Without --id-map a novel sequence must still be scorable."""
        outdir = tmp_path / "nomap"
        run_cli(
            "--mode", "sequence",
            "--kofam", SEQ_NATIVE / "kofam/1.txt",
            "--species", SPECIES,
            "--merge-only",
            "--outdir", outdir,
        )
        record = json.loads((outdir / "merged_a_terms.json").read_text())[0]
        assert record["ENTREZ_ID"] == ""
        assert record["similarity_gene_name"] == record["gene_name"]
        assert record["id_source"] == "fallback_query_id"

        # similarity_gene_name is what load_gene_pathways indexes on
        from orbit_ocsp.expression_pipeline import load_gene_pathways

        assert record["gene_name"] in load_gene_pathways(
            outdir / "merged_a_terms.json"
        )

    @needs_scoring_data
    def test_native_inputs_score_end_to_end(self, tmp_path):
        outdir = tmp_path / "native"
        proc = run_cli(
            "--mode", "sequence",
            "--kofam", SEQ_NATIVE / "kofam/1.txt",
            "--interproscan", SEQ_NATIVE / "interproscan/1.tsv",
            "--deepgo", SEQ_NATIVE / "deepgoplus/1.tsv",
            "--id-map", SEQ_NATIVE / "id_map.tsv",
            "--species", SPECIES,
            "--condition", CONDITION,
            "--outdir", outdir,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        ranked = assert_standard_outputs(outdir)
        assert (outdir / "merged_a_terms.json").is_file()
        assert ranked[0]["scoring_status"] == "ok"

        summary = json.loads((outdir / "pipeline_summary.json").read_text())
        assert summary["mode"] == "sequence"
        assert summary["entry"] == "A"
        assert summary["deepgo_min_score"] == 0.0


# ---------------------------------------------------------------------------
# Mode 3, entry B — pre-merged JSON
# ---------------------------------------------------------------------------

class TestSequenceModeMerged:
    def test_entries_are_mutually_exclusive(self):
        proc = run_cli(
            "--mode", "sequence",
            "--merged-json", SEQ_MERGED / "merged_result_1.json",
            "--kofam", SEQ_NATIVE / "kofam/1.txt",
            "--condition", CONDITION,
        )
        assert proc.returncode == 2
        assert "mutually exclusive" in proc.stderr

    def test_no_input_lists_both_entries(self):
        proc = run_cli("--mode", "sequence", "--condition", CONDITION)
        assert proc.returncode == 2
        assert "--merged-json" in proc.stderr
        assert "--kofam" in proc.stderr

    @needs_scoring_data
    def test_pre_merged_json_scores_end_to_end(self, tmp_path):
        outdir = tmp_path / "merged"
        proc = run_cli(
            "--mode", "sequence",
            "--merged-json", SEQ_MERGED / "merged_result_1.json",
            "--species", SPECIES,
            "--condition", CONDITION,
            "--outdir", outdir,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        ranked = assert_standard_outputs(outdir)
        assert ranked[0]["scoring_status"] == "ok"

        summary = json.loads((outdir / "pipeline_summary.json").read_text())
        assert summary["entry"] == "B"
        # entry B keeps the user's file rather than rewriting it
        assert Path(summary["merged_json"]).name == "merged_result_1.json"


# ---------------------------------------------------------------------------
# Cross-entry consistency
# ---------------------------------------------------------------------------

class TestSequenceEntriesAgreeOnGO:
    """Both sequence samples describe NP_570602.2 but differ on KEGG.

    The pre-merged file came from an older script that kept only one pathway
    per KO. Pinning the relationship here documents the gap and would catch a
    regression that silently reintroduced it.
    """

    @staticmethod
    def _split(terms):
        go = {t for t in terms if t.startswith("GO:")}
        return terms - go, go

    def test_go_identical_and_kegg_is_a_strict_superset(self, tmp_path):
        outdir = tmp_path / "cmp"
        run_cli(
            "--mode", "sequence",
            "--kofam", SEQ_NATIVE / "kofam/1.txt",
            "--interproscan", SEQ_NATIVE / "interproscan/1.tsv",
            "--deepgo", SEQ_NATIVE / "deepgoplus/1.tsv",
            "--species", SPECIES,
            "--merge-only",
            "--outdir", outdir,
        )
        native = set(
            json.loads((outdir / "merged_a_terms.json").read_text())[0]["pathway"]
        )
        merged = set(
            json.loads((SEQ_MERGED / "merged_result_1.json").read_text())[0]["pathway"]
        )

        native_kegg, native_go = self._split(native)
        merged_kegg, merged_go = self._split(merged)

        assert native_go == merged_go, "GO halves should match exactly"
        assert merged_kegg < native_kegg, (
            "the pre-merged file should hold strictly fewer KEGG pathways; "
            "the current KO expansion keeps every mapped pathway"
        )
