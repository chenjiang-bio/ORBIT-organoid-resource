"""Unit tests for DE filtering / top-k, method selection, and mock backend."""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from orbit_ocsp.expression_de import (
    COUNT_LIKE_LIBRARY_CV_MIN,
    check_data_type_against_matrix,
    describe_matrix_scale,
    filter_and_topk,
    filter_de_results,
    mock_de_from_matrix,
    normalize_data_type,
    read_expression_matrix,
    read_group_table,
    run_differential_expression,
    select_de_engine,
    select_de_method,
    select_topk,
    validate_matrix_and_groups,
)


def test_normalize_data_type_aliases():
    assert normalize_data_type("rnaseq") == "rnaseq_count"
    assert normalize_data_type("RNA-SEQ") == "rnaseq_count"
    assert normalize_data_type("rnaseq_count") == "rnaseq_count"
    assert normalize_data_type("microarray") == "microarray"
    with pytest.raises(ValueError, match="Unsupported data_type"):
        normalize_data_type("fpkm")


def test_select_de_engine_accepts_rnaseq_alias():
    assert select_de_engine("rnaseq") == "deseq2"


def _write_matrix_and_groups(tmp_path: Path):
    matrix = tmp_path / "matrix.tsv"
    groups = tmp_path / "groups.tsv"
    matrix.write_text(
        "gene\tS1\tS2\tS3\tS4\n"
        "G1\t100\t120\t10\t12\n"
        "G2\t11\t9\t90\t95\n"
        "G3\t50\t55\t48\t52\n"
        "G4\t200\t180\t20\t25\n"
        "G5\t30\t28\t35\t33\n",
        encoding="utf-8",
    )
    groups.write_text(
        "sample_id\tgroup\n"
        "S1\tcase\n"
        "S2\tcase\n"
        "S3\tcontrol\n"
        "S4\tcontrol\n",
        encoding="utf-8",
    )
    return matrix, groups


def test_select_de_engine():
    assert select_de_engine("rnaseq_count") == "deseq2"
    assert select_de_engine("microarray") == "limma"
    assert select_de_engine("normalized") == "limma"
    with pytest.raises(ValueError):
        select_de_engine("unknown")


def test_select_de_method_by_sample_size():
    assert select_de_method(1, 1, "rnaseq_count") == "edger"
    assert select_de_method(9, 9, "rnaseq_count") == "wilcox"
    assert select_de_method(9, 9, "microarray") == "wilcox"
    assert select_de_method(8, 8, "rnaseq_count") == "deseq2"
    assert select_de_method(3, 3, "rnaseq_count") == "deseq2"
    assert select_de_method(3, 3, "microarray") == "limma"
    assert select_de_method(2, 10, "rnaseq_count") == "deseq2"
    with pytest.raises(ValueError):
        select_de_method(0, 3, "rnaseq_count")


def test_read_and_validate(tmp_path):
    matrix_path, groups_path = _write_matrix_and_groups(tmp_path)
    matrix = read_expression_matrix(matrix_path)
    groups = read_group_table(groups_path)
    aligned = validate_matrix_and_groups(matrix, groups)
    assert list(aligned["sample_id"]) == ["S1", "S2", "S3", "S4"]
    assert set(aligned["group"]) == {"case", "control"}


def test_groups_may_be_subset_of_matrix(tmp_path):
    from orbit_ocsp.expression_de import subset_matrix_to_groups

    matrix_path, _groups_path = _write_matrix_and_groups(tmp_path)
    matrix = read_expression_matrix(matrix_path)
    groups = pd.DataFrame(
        {"sample_id": ["S1", "S3"], "group": ["case", "control"]}
    )
    sub, aligned = subset_matrix_to_groups(matrix, groups)
    assert list(sub.columns) == ["S1", "S3"]
    assert list(aligned["group"]) == ["case", "control"]


def test_filter_and_topk_ordering():
    de = pd.DataFrame(
        {
            "gene": ["A", "B", "C", "D"],
            "log2FoldChange": [2.0, -1.5, 0.2, 3.0],
            "padj": [0.01, 0.04, 0.001, 0.2],
        }
    )
    filtered = filter_de_results(de, padj_max=0.05, abs_log2fc_min=1.0)
    assert set(filtered["gene"]) == {"A", "B"}
    top = select_topk(filtered, k=1)
    assert top.iloc[0]["gene"] == "A"
    top2 = filter_and_topk(de, k=2)
    assert list(top2["gene"]) == ["A", "B"]


def test_mock_de_backend_writes_outputs(tmp_path):
    matrix_path, groups_path = _write_matrix_and_groups(tmp_path)
    outdir = tmp_path / "out"
    de = run_differential_expression(
        matrix_path=matrix_path,
        groups_path=groups_path,
        data_type="rnaseq_count",
        outdir=outdir,
        backend="mock",
        seed=0,
    )
    assert (outdir / "de_results.tsv").exists()
    assert {"gene", "log2FoldChange", "padj", "engine"} <= set(de.columns)
    assert set(de["engine"]) == {"mock"}
    top = filter_and_topk(de, k=2)
    assert len(top) <= 2
    assert "de_rank" in top.columns


def test_mock_de_from_matrix_deterministic(tmp_path):
    matrix_path, groups_path = _write_matrix_and_groups(tmp_path)
    matrix = read_expression_matrix(matrix_path)
    groups = read_group_table(groups_path)
    a = mock_de_from_matrix(matrix, groups, seed=1)
    b = mock_de_from_matrix(matrix, groups, seed=1)
    pd.testing.assert_frame_equal(a, b)


def test_one_vs_one_microarray_rejected(tmp_path):
    matrix = tmp_path / "matrix.tsv"
    groups = tmp_path / "groups.tsv"
    matrix.write_text(
        "gene\tS1\tS2\nG1\t1.0\t2.0\nG2\t3.0\t4.0\n",
        encoding="utf-8",
    )
    groups.write_text(
        "sample_id\tgroup\nS1\tcase\nS2\tcontrol\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="edgeR"):
        run_differential_expression(
            matrix_path=matrix,
            groups_path=groups,
            data_type="microarray",
            outdir=tmp_path / "out",
            backend="r",
        )


def test_missing_r_raises_an_actionable_error(tmp_path, monkeypatch):
    """A pip-only install has no R, and pip cannot provide it.

    Without this check the user gets a bare
    ``FileNotFoundError: [Errno 2] ... 'Rscript'`` from subprocess, which does
    not say what is missing or how to proceed.
    """
    import pandas as pd
    import pytest

    from orbit_ocsp import expression_de as ed

    monkeypatch.setattr(ed.shutil, "which", lambda name: None)

    matrix = pd.DataFrame({"s1": [1, 2], "s2": [3, 4]}, index=["g1", "g2"])
    groups = pd.DataFrame(
        {"sample_id": ["s1", "s2"], "group": ["case", "control"]}
    )

    with pytest.raises(RuntimeError) as excinfo:
        ed._run_r_de(matrix, groups, "rnaseq_count", tmp_path / "out.tsv")

    message = str(excinfo.value)
    # Names the missing dependency, and every documented way forward.
    assert "needs R" in message
    assert "conda" in message
    assert "BiocManager" in message
    assert "--de-results" in message
    # Says which modes are unaffected, so the user is not blocked entirely.
    assert "Gene-list and sequence modes do not require R" in message


def test_missing_r_error_is_not_a_bare_filenotfound(tmp_path, monkeypatch):
    import pandas as pd
    import pytest

    from orbit_ocsp import expression_de as ed

    monkeypatch.setattr(ed.shutil, "which", lambda name: None)
    matrix = pd.DataFrame({"s1": [1], "s2": [2]}, index=["g1"])
    groups = pd.DataFrame(
        {"sample_id": ["s1", "s2"], "group": ["case", "control"]}
    )

    # A FileNotFoundError here would mean the preflight check was bypassed and
    # subprocess raised instead.
    with pytest.raises(RuntimeError):
        ed._run_r_de(matrix, groups, "rnaseq_count", tmp_path / "out.tsv")


# --- data_type vs matrix values --------------------------------------------
# data_type is a caller declaration. Nothing else in the pipeline compares it
# against the data, yet it decides whether counts are TMM/logCPM-normalized
# before Wilcoxon testing, and therefore whether log2FoldChange is a log2 ratio
# or a difference of raw per-group means.


def _counts_frame(n_genes: int = 40, seed: int = 0) -> pd.DataFrame:
    """Count-like matrix: integers, large maximum, uneven library sizes."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 4000, size=(n_genes, 4))
    # Unequal sequencing depth is what distinguishes raw counts from CPM/TPM.
    depth = np.array([1.0, 1.6, 0.7, 1.3])
    return pd.DataFrame(
        (base * depth).astype(int),
        index=[f"G{i}" for i in range(n_genes)],
        columns=["S1", "S2", "S3", "S4"],
    )


def _cpm_frame(n_genes: int = 40, seed: int = 0) -> pd.DataFrame:
    """Integer-rounded CPM: also integers, but every column sums to ~1e6."""
    counts = _counts_frame(n_genes, seed=seed)
    cpm = counts.divide(counts.sum(axis=0), axis=1) * 1e6
    return cpm.round().astype(int)


def test_describe_matrix_scale_flags_counts():
    scale = describe_matrix_scale(_counts_frame())
    assert scale.frac_integer == 1.0
    assert not scale.has_negative
    assert scale.library_size_cv > COUNT_LIKE_LIBRARY_CV_MIN
    assert scale.looks_like_counts


def test_describe_matrix_scale_does_not_flag_normalized_values():
    """Integer-rounded CPM must not be mistaken for raw counts.

    Both are non-negative integers, so the only usable discriminator is that
    normalized columns share a common total.
    """
    scale = describe_matrix_scale(_cpm_frame())
    assert scale.frac_integer == 1.0
    assert scale.library_size_cv < COUNT_LIKE_LIBRARY_CV_MIN
    assert not scale.looks_like_counts


def test_describe_matrix_scale_rejects_all_nan():
    frame = pd.DataFrame(
        {"S1": [np.nan, np.nan], "S2": [np.nan, np.nan]}, index=["G1", "G2"]
    )
    with pytest.raises(ValueError, match="no finite values"):
        describe_matrix_scale(frame)


def test_counts_declared_but_values_are_not_integers_raises():
    fpkm = _counts_frame().astype(float) / 7.0  # FPKM-like, non-integer
    with pytest.raises(ValueError, match="declares raw counts"):
        check_data_type_against_matrix(fpkm, "rnaseq_count")


def test_counts_declared_but_values_are_negative_raises():
    logratio = _counts_frame().astype(float)
    logratio.iloc[0, 0] = -3.0
    with pytest.raises(ValueError, match="negative values"):
        check_data_type_against_matrix(logratio, "rnaseq_count")


def test_counts_declared_error_names_the_alternatives():
    """The message has to say what to declare instead, not just that it failed."""
    fpkm = _counts_frame().astype(float) / 7.0
    with pytest.raises(ValueError) as excinfo:
        check_data_type_against_matrix(fpkm, "rnaseq_count")
    message = str(excinfo.value)
    assert "normalized" in message
    assert "microarray" in message
    assert "DESeq2" in message


def test_counts_mismatch_downgrades_to_warning_when_not_strict():
    fpkm = _counts_frame().astype(float) / 7.0
    with pytest.warns(UserWarning, match="declares raw counts"):
        check_data_type_against_matrix(fpkm, "rnaseq_count", strict=False)


def test_normalized_declared_for_count_matrix_warns():
    with pytest.warns(UserWarning, match="looks like raw counts"):
        check_data_type_against_matrix(_counts_frame(), "normalized")


def test_normalized_warning_explains_both_consequences():
    with pytest.warns(UserWarning) as record:
        check_data_type_against_matrix(_counts_frame(), "microarray")
    message = str(record[0].message)
    assert "no library-size normalization" in message
    assert "log2 ratio" in message
    assert "rnaseq_count" in message


def test_normalized_declared_for_cpm_matrix_is_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning fails the test
        check_data_type_against_matrix(_cpm_frame(), "normalized")


def test_valid_count_matrix_passes_silently():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        scale = check_data_type_against_matrix(_counts_frame(), "rnaseq_count")
    assert scale.looks_like_counts


def test_run_differential_expression_validates_data_type(tmp_path):
    """The check must fire through the public entry point, not only directly."""
    matrix_path = tmp_path / "matrix.tsv"
    groups_path = tmp_path / "groups.tsv"
    (_counts_frame().astype(float) / 7.0).rename_axis("gene").to_csv(
        matrix_path, sep="\t"
    )
    groups_path.write_text(
        "sample_id\tgroup\nS1\tcase\nS2\tcase\nS3\tcontrol\nS4\tcontrol\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="declares raw counts"):
        run_differential_expression(
            matrix_path=matrix_path,
            groups_path=groups_path,
            data_type="rnaseq_count",
            outdir=tmp_path / "out",
            backend="mock",
        )


def test_check_data_type_false_skips_validation(tmp_path):
    matrix_path = tmp_path / "matrix.tsv"
    groups_path = tmp_path / "groups.tsv"
    (_counts_frame().astype(float) / 7.0).rename_axis("gene").to_csv(
        matrix_path, sep="\t"
    )
    groups_path.write_text(
        "sample_id\tgroup\nS1\tcase\nS2\tcase\nS3\tcontrol\nS4\tcontrol\n",
        encoding="utf-8",
    )
    de = run_differential_expression(
        matrix_path=matrix_path,
        groups_path=groups_path,
        data_type="rnaseq_count",
        outdir=tmp_path / "out",
        backend="mock",
        check_data_type=False,
    )
    assert not de.empty
