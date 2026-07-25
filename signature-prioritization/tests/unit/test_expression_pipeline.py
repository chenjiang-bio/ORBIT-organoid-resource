"""End-to-end pipeline tests using mocked DE and scoring."""

import json
from pathlib import Path

import pandas as pd

from orbit_ocsp.expression_pipeline import (
    annotation_links,
    run_expression_biomarker_pipeline,
)


def _write_mock_protein_root(tmp_path: Path) -> Path:
    root = tmp_path / "data" / "protein"
    root.mkdir(parents=True)
    (root / "Gene_Annotation_Human.txt").write_text(
        "entrez_id\tensembl\tsymbol\n"
        "10\tENSG00000156006\tNAT2\n"
        "6934\tENSG00000148737\tTCF7L2\n"
        "1019\tENSG00000135446\tCDK4\n",
        encoding="utf-8",
    )
    human = root / "human"
    human.mkdir()
    (human / "10.fasta").write_text(">NP_A\nMALL\n>NP_B\nMAKK\n", encoding="utf-8")
    (human / "6934.fasta").write_text(">NP_T\nMPQL\n", encoding="utf-8")
    (human / "1019.fasta").write_text(">NP_C\nMATS\n", encoding="utf-8")
    return root


def _write_expression_inputs(tmp_path: Path):
    matrix = tmp_path / "matrix.tsv"
    groups = tmp_path / "groups.tsv"
    # Strong case/control separation for NAT2/TCF7L2/CDK4-like mock genes.
    matrix.write_text(
        "gene\tS1\tS2\tS3\tS4\n"
        "NAT2\t200\t220\t20\t18\n"
        "TCF7L2\t180\t190\t15\t12\n"
        "CDK4\t150\t160\t25\t22\n"
        "WEAK\t40\t42\t38\t39\n",
        encoding="utf-8",
    )
    groups.write_text(
        "sample_id\tgroup\nS1\tcase\nS2\tcase\nS3\tcontrol\nS4\tcontrol\n",
        encoding="utf-8",
    )
    return matrix, groups


def test_annotation_links():
    links = annotation_links(["GO:0008150", "hsa04110", "GO:0003674"])
    assert links["go_links"][0]["url"].startswith("https://amigo.geneontology.org/")
    assert links["kegg_links"][0]["url"] == "https://www.kegg.jp/pathway/hsa04110"


def test_pipeline_with_mock_de_and_mock_score(tmp_path):
    protein_root = _write_mock_protein_root(tmp_path)
    matrix, groups = _write_expression_inputs(tmp_path)
    outdir = tmp_path / "out"

    def fake_score(gene, condition, **kwargs):
        return {
            "verdict": "enriched" if gene == "NAT2" else "not_sig",
            "confidence": "high",
            "consensus_score": 0.9 if gene == "NAT2" else 0.2,
            "agreement": 4,
            "total_methods": 5,
            "primary_p_value": 0.01 if gene == "NAT2" else 0.4,
            "n_overlap_terms": 2 if gene == "NAT2" else 1,
            "report_dir": f"gene_reports/{gene}__{condition.replace(' ', '_')}",
            "go_links": [{"term": "GO:0008150", "url": "https://amigo.geneontology.org/amigo/term/GO:0008150"}],
            "kegg_links": [],
            "semantic_stage": "formal" if gene == "NAT2" else "screening",
            "semantic_permutations": 999 if gene == "NAT2" else 50,
            "individual_methods": [
                {
                    "method": method,
                    "observed_statistic": 0.8,
                    "p_value": 0.01,
                    "effect_size": 2.5,
                    "verdict": "enriched",
                    "inference_stage": "final",
                    "rank": index,
                }
                for index, method in enumerate(
                    ["hypergeometric", "jaccard", "overlap", "resnik_bma", "lin_bma"],
                    start=1,
                )
            ],
        }

    # Provide tiny merged/B_terms so pathway lookup succeeds for scored genes.
    merged = tmp_path / "merged.json"
    merged.write_text(
        json.dumps(
            [
                {
                    "similarity_gene_name": "NAT2",
                    "pathway": ["GO:0008150", "hsa04110"],
                },
                {
                    "similarity_gene_name": "TCF7L2",
                    "pathway": ["GO:0003674"],
                },
                {
                    "similarity_gene_name": "CDK4",
                    "pathway": ["hsa04110"],
                },
            ]
        ),
        encoding="utf-8",
    )
    b_terms = tmp_path / "B_terms.json"
    b_terms.write_text(
        json.dumps(
            [
                {
                    "condition": "Breast Cancer",
                    "pathway": ["GO:0008150", "hsa04110"],
                }
            ]
        ),
        encoding="utf-8",
    )

    ranked = run_expression_biomarker_pipeline(
        matrix_path=matrix,
        groups_path=groups,
        data_type="rnaseq_count",
        condition="Breast Cancer",
        species="hsa",
        top_k=3,
        padj_max=0.2,
        abs_log2fc_min=0.5,
        outdir=outdir,
        merged_result=merged,
        b_terms=b_terms,
        protein_root=protein_root,
        de_backend="mock",
        score_fn=fake_score,
        seed=0,
    )

    assert len(ranked) == 3
    assert ranked[0]["query_id"] == "NAT2"
    assert ranked[0]["id_type"] == "symbol"
    assert ranked[0]["gene_symbol"] == "NAT2"
    assert ranked[0]["biomarker_rank"] == 1
    assert ranked[0]["entrez_id"] == "10"
    assert ranked[0]["fasta_relpath"] == "data/protein/human/10.fasta"
    assert ranked[0]["sequence_preview"] == "MALL"
    assert ranked[0]["biomarker_score"]["consensus_score"] == 0.9
    assert (outdir / "biomarker_ranked.json").exists()
    assert (outdir / "biomarker_ranked.tsv").exists()
    assert (outdir / "pipeline_summary.json").exists()
    assert (outdir / "method_scores.tsv").exists()

    tsv = pd.read_csv(outdir / "biomarker_ranked.tsv", sep="\t")
    assert "consensus_score" in tsv.columns
    assert tsv.iloc[0]["gene_symbol"] == "NAT2"
    assert "query_id" in tsv.columns
    assert "id_type" in tsv.columns
    # The flat table carries only quantities the paper names.
    assert {
        "primary_p_value", "primary_q_value", "n_shared_pathways",
        "hypergeometric_p_value", "jaccard_p_value", "overlap_p_value",
        "resnik_bma_p_value", "lin_bma_p_value",
    } <= set(tsv.columns)
    # Two-stage bookkeeping stays in the JSON.
    assert "semantic_stage" not in tsv.columns
    assert ranked[0]["biomarker_score"]["semantic_stage"] == "formal"
    methods = pd.read_csv(outdir / "method_scores.tsv", sep="\t")
    assert set(methods["method"]) == {
        "hypergeometric", "jaccard", "overlap", "resnik_bma", "lin_bma"
    }


def test_pipeline_skip_scoring(tmp_path):
    protein_root = _write_mock_protein_root(tmp_path)
    matrix, groups = _write_expression_inputs(tmp_path)
    outdir = tmp_path / "out_skip"
    ranked = run_expression_biomarker_pipeline(
        matrix_path=matrix,
        groups_path=groups,
        data_type="normalized",
        condition="Breast Cancer",
        species="human",
        top_k=2,
        padj_max=0.5,
        abs_log2fc_min=0.1,
        outdir=outdir,
        protein_root=protein_root,
        de_backend="mock",
        skip_scoring=True,
        seed=1,
    )
    assert len(ranked) == 2
    assert all(row["scoring_status"] == "skipped" for row in ranked)
    assert all(row["entrez_id"] is not None for row in ranked)
