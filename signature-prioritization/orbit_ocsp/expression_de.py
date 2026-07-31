"""Differential expression helpers for the expression→biomarker pipeline.

Default backend is R (``R/run_de.R``), with sample-size–aware engine selection:

- ``n_case == 1`` and ``n_control == 1`` → edgeR (only viable 1-vs-1 path)
- ``n_case > 8`` and ``n_control > 8`` → Wilcoxon rank-sum
- otherwise:
  - ``rnaseq_count`` → DESeq2
  - ``microarray`` / ``normalized`` → limma

``data_type`` is declared by the caller, so
:func:`check_data_type_against_matrix` compares it against the matrix values
before dispatch. A mismatch is not cosmetic: ``data_type`` also decides whether
counts are TMM/logCPM-normalized ahead of the Wilcoxon path, and on the
un-normalized branch ``log2FoldChange`` holds a difference of raw per-group
means rather than a log2 ratio.

``backend="mock"`` remains available for deterministic unit tests.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional, Tuple, Union

import numpy as np
import pandas as pd

DataType = Literal["rnaseq_count", "microarray", "normalized"]
VALID_DATA_TYPES = {"rnaseq_count", "microarray", "normalized"}
# Docs / older scripts sometimes say ``rnaseq``; treat it as counts.
DATA_TYPE_ALIASES = {"rnaseq": "rnaseq_count", "rna-seq": "rnaseq_count"}
VALID_GROUPS = {"case", "control"}
LARGE_N_THRESHOLD = 8  # use Wilcoxon when both groups have n > 8

# --- thresholds for describing a matrix's numeric scale ---------------------
# Counts are integers. A handful of non-integer entries can survive rounding or
# manual edits, so require "almost all" rather than "all".
INTEGER_FRACTION_MIN = 0.999
# Raw counts reach into the thousands; small synthetic fixtures do not. This
# keeps toy matrices in the test suite from being mistaken for real count data.
COUNT_LIKE_MAX_VALUE_MIN = 1000.0
# Per-sample totals: raw libraries differ in depth, whereas CPM/TPM columns sum
# to a constant. This is what separates raw counts from integer-rounded
# normalized values, which would otherwise look identical.
COUNT_LIKE_LIBRARY_CV_MIN = 0.01


def normalize_data_type(data_type: str) -> str:
    """Map aliases onto a canonical ``VALID_DATA_TYPES`` value."""
    dtype = (data_type or "").strip().lower()
    dtype = DATA_TYPE_ALIASES.get(dtype, dtype)
    if dtype not in VALID_DATA_TYPES:
        raise ValueError(
            f"Unsupported data_type {data_type!r}; expected one of "
            f"{sorted(VALID_DATA_TYPES)} (alias: rnaseq → rnaseq_count)"
        )
    return dtype

@dataclass(frozen=True)
class MatrixScale:
    """What the matrix values actually look like, independent of any label."""

    n_values: int
    min_value: float
    max_value: float
    frac_integer: float
    has_negative: bool
    library_size_cv: float
    looks_like_counts: bool

    def describe(self) -> str:
        return (
            f"min={self.min_value:.4g}, max={self.max_value:.4g}, "
            f"integer fraction={self.frac_integer:.4f}, "
            f"negative values={'yes' if self.has_negative else 'no'}, "
            f"per-sample total CV={self.library_size_cv:.4g}"
        )


def describe_matrix_scale(matrix: pd.DataFrame) -> MatrixScale:
    """Summarize the numeric scale of an expression matrix.

    ``data_type`` is a declaration by the caller and is never checked against
    the data anywhere else in the pipeline. This function supplies the evidence
    needed to notice a mismatch.
    """
    values = matrix.to_numpy(dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("Expression matrix contains no finite values")

    frac_integer = float(np.mean(finite == np.round(finite)))
    library_sizes = np.nansum(values, axis=0)
    mean_library = float(np.mean(library_sizes))
    library_cv = (
        float(np.std(library_sizes) / mean_library) if mean_library else 0.0
    )
    has_negative = bool(finite.min() < 0)
    max_value = float(finite.max())

    looks_like_counts = (
        not has_negative
        and frac_integer >= INTEGER_FRACTION_MIN
        and max_value >= COUNT_LIKE_MAX_VALUE_MIN
        and library_cv >= COUNT_LIKE_LIBRARY_CV_MIN
    )
    return MatrixScale(
        n_values=int(finite.size),
        min_value=float(finite.min()),
        max_value=max_value,
        frac_integer=frac_integer,
        has_negative=has_negative,
        library_size_cv=library_cv,
        looks_like_counts=looks_like_counts,
    )


def check_data_type_against_matrix(
    matrix: pd.DataFrame,
    data_type: str,
    strict: bool = True,
) -> MatrixScale:
    """Verify that a declared ``data_type`` is consistent with the values.

    Two different failure modes, so two different responses:

    ``rnaseq_count`` declared for data that cannot be counts (negative or
    largely non-integer) raises. Every count path is invalid for such input:
    DESeq2 and edgeR require integers, and the TMM/logCPM step applied before
    Wilcoxon testing assumes library-size scaling.

    ``microarray``/``normalized`` declared for data that looks like raw counts
    warns rather than raises, because the declaration may be deliberate and the
    evidence is circumstantial. It matters because that branch skips
    normalization entirely and reports ``log2FoldChange`` as a difference of
    raw per-group means, which is not a log2 ratio, so a ``--abs-log2fc-min``
    cutoff silently stops meaning "at least this fold change".

    Set ``strict=False`` to downgrade the raising case to a warning.
    """
    dtype = normalize_data_type(data_type)
    scale = describe_matrix_scale(matrix)

    if dtype == "rnaseq_count":
        problems = []
        if scale.has_negative:
            problems.append("negative values")
        if scale.frac_integer < INTEGER_FRACTION_MIN:
            problems.append(
                f"non-integer values (only {scale.frac_integer:.1%} are integers)"
            )
        if problems:
            message = (
                f"data_type='rnaseq_count' declares raw counts, but the matrix has "
                f"{' and '.join(problems)} ({scale.describe()}). "
                "Counts are required here: DESeq2 and edgeR need integers, and "
                "counts are TMM/logCPM-normalized before Wilcoxon testing. "
                "For FPKM/TPM/RPKM or log-transformed data use "
                "data_type='normalized'; for array intensities use "
                "data_type='microarray'."
            )
            if strict:
                raise ValueError(message)
            warnings.warn(message, UserWarning, stacklevel=2)
        return scale

    if scale.looks_like_counts:
        warnings.warn(
            f"data_type={dtype!r} was declared, but the matrix looks like raw counts "
            f"({scale.describe()}). Two consequences: the values are used as given, "
            "with no library-size normalization, so per-sample sequencing depth "
            "contributes to the comparison; and log2FoldChange is reported as a "
            "difference of raw per-group means rather than a log2 ratio, so an "
            "absolute log2 fold-change cutoff no longer selects on fold change. "
            "Use data_type='rnaseq_count' for raw counts.",
            UserWarning,
            stacklevel=2,
        )
    return scale


_PKG_ROOT = Path(__file__).resolve().parents[1]


def _resolve_default_rscript() -> Path:
    """Locate ``run_de.R``, preferring the copy installed with the package.

    Only files inside the package directory survive ``pip install``; a sibling
    ``R/`` directory at the repository root does not. Checking the packaged copy
    first means expression mode works for installed users, while a source
    checkout still finds the repo-root copy.
    """
    packaged = Path(__file__).resolve().parent / "R" / "run_de.R"
    if packaged.exists():
        return packaged
    return _PKG_ROOT / "R" / "run_de.R"


_DEFAULT_RSCRIPT = _resolve_default_rscript()

DeBackend = Callable[..., pd.DataFrame]


def select_de_engine(data_type: str) -> str:
    """Return the baseline engine name for a data type (ignoring sample size)."""
    dtype = normalize_data_type(data_type)
    if dtype == "rnaseq_count":
        return "deseq2"
    return "limma"


def select_de_method(
    n_case: int,
    n_control: int,
    data_type: str,
) -> str:
    """Choose DE method from group sizes and data type.

    Rules
    -----
    - 1 vs 1 → ``edger``
    - both groups ``> 8`` → ``wilcox``
    - else ``deseq2`` (counts) or ``limma`` (microarray/normalized)
    """
    if n_case < 1 or n_control < 1:
        raise ValueError("Both case and control must have at least one sample")
    if n_case == 1 and n_control == 1:
        return "edger"
    if n_case > LARGE_N_THRESHOLD and n_control > LARGE_N_THRESHOLD:
        return "wilcox"
    return select_de_engine(data_type)


def _read_table(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() in {".tsv", ".txt"}:
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def read_expression_matrix(path: Union[str, Path]) -> pd.DataFrame:
    """Read an expression matrix (genes × samples)."""
    df = _read_table(Path(path))
    gene_cols = {"gene", "gene_symbol", "symbol", "genes"}
    first = df.columns[0]
    if first.lower() in gene_cols or "unnamed" in str(first).lower():
        df = df.rename(columns={first: "gene"})
    elif "gene" not in {c.lower() for c in df.columns}:
        df = df.rename(columns={first: "gene"})
    else:
        for col in df.columns:
            if col.lower() in gene_cols:
                df = df.rename(columns={col: "gene"})
                break
    df["gene"] = df["gene"].astype(str).str.strip()
    if df["gene"].duplicated().any():
        raise ValueError("Expression matrix contains duplicate gene symbols")
    return df.set_index("gene")


def read_group_table(path: Union[str, Path]) -> pd.DataFrame:
    """Read sample grouping table with columns ``sample_id`` and ``group``.

    Optional ``subject`` column is preserved for paired designs.
    """
    df = _read_table(Path(path))
    colmap = {c.lower(): c for c in df.columns}
    sample_col = colmap.get("sample_id") or colmap.get("sample") or df.columns[0]
    group_col = colmap.get("group") or colmap.get("condition") or df.columns[1]
    cols = [sample_col, group_col]
    out_names = ["sample_id", "group"]
    if "subject" in colmap:
        cols.append(colmap["subject"])
        out_names.append("subject")
    out = df[cols].copy()
    out.columns = out_names
    out["sample_id"] = out["sample_id"].astype(str).str.strip()
    out["group"] = out["group"].astype(str).str.strip().str.lower()
    invalid = sorted(set(out["group"]) - VALID_GROUPS)
    if invalid:
        raise ValueError(
            f"Invalid group labels {invalid}; expected only {sorted(VALID_GROUPS)}"
        )
    if out["sample_id"].duplicated().any():
        raise ValueError("Group table contains duplicate sample_id values")
    if set(out["group"]) != VALID_GROUPS:
        raise ValueError("Group table must include both 'case' and 'control' samples")
    return out


def validate_matrix_and_groups(
    matrix: pd.DataFrame,
    groups: pd.DataFrame,
) -> pd.DataFrame:
    """Align groups to matrix sample columns.

    ``groups`` may be a subset of matrix samples. Samples listed in groups but
    absent from the matrix are errors.
    """
    sample_cols = [str(c) for c in matrix.columns]
    group_ids = [str(s) for s in groups["sample_id"].tolist()]
    missing_in_matrix = sorted(set(group_ids) - set(sample_cols))
    if missing_in_matrix:
        raise ValueError(
            f"Samples present in groups but missing from matrix: {missing_in_matrix}"
        )
    ordered = groups.copy()
    ordered["sample_id"] = ordered["sample_id"].astype(str)
    return ordered.reset_index(drop=True)


def subset_matrix_to_groups(
    matrix: pd.DataFrame,
    groups: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return matrix columns restricted to samples in ``groups`` (groups order)."""
    aligned = validate_matrix_and_groups(matrix, groups)
    sample_ids = aligned["sample_id"].tolist()
    return matrix.loc[:, sample_ids].astype(float), aligned


def filter_de_results(
    de_table: pd.DataFrame,
    padj_max: float = 0.05,
    abs_log2fc_min: float = 1.0,
) -> pd.DataFrame:
    """Filter DE results by adjusted p-value and absolute log2 fold-change."""
    required = {"gene", "log2FoldChange", "padj"}
    missing = required - set(de_table.columns)
    if missing:
        raise ValueError(f"DE table missing columns: {sorted(missing)}")
    df = de_table.copy()
    df["padj"] = pd.to_numeric(df["padj"], errors="coerce")
    df["log2FoldChange"] = pd.to_numeric(df["log2FoldChange"], errors="coerce")
    keep = (
        df["padj"].notna()
        & df["log2FoldChange"].notna()
        & (df["padj"] < padj_max)
        & (df["log2FoldChange"].abs() >= abs_log2fc_min)
    )
    return df.loc[keep].copy()


def add_full_table_de_rank(de_table: pd.DataFrame) -> pd.DataFrame:
    """Add ``de_rank_full``: the gene's rank across the *whole* DE table.

    This is the baseline the reranking comparison uses. ``de_rank`` is a
    position within the filtered shortlist (1..k), so it cannot express "this
    gene sat at position 364 of the full differential-expression ranking" —
    which is the number the reranking analysis reports.
    """
    df = de_table.copy()
    df["abs_log2FoldChange"] = df["log2FoldChange"].abs()
    ordered = df.sort_values(
        by=["padj", "abs_log2FoldChange"],
        ascending=[True, False],
        na_position="last",
        kind="mergesort",
    )
    ordered["de_rank_full"] = range(1, len(ordered) + 1)
    return ordered.drop(columns=["abs_log2FoldChange"])


def select_topk(
    de_table: pd.DataFrame,
    k: int = 20,
) -> pd.DataFrame:
    """Rank by padj ascending, then |log2FC| descending, and keep top-k."""
    if k < 1:
        raise ValueError("k must be >= 1")
    df = de_table.copy()
    df["abs_log2FoldChange"] = df["log2FoldChange"].abs()
    ranked = df.sort_values(
        by=["padj", "abs_log2FoldChange"],
        ascending=[True, False],
        kind="mergesort",
    ).head(k)
    ranked = ranked.reset_index(drop=True)
    ranked.insert(0, "de_rank", range(1, len(ranked) + 1))
    return ranked


def mock_de_from_matrix(
    matrix: pd.DataFrame,
    groups: pd.DataFrame,
    seed: int = 42,
) -> pd.DataFrame:
    """Deterministic mock DE for tests (no R dependency)."""
    rng = np.random.default_rng(seed)
    matrix, aligned = subset_matrix_to_groups(matrix, groups)
    case_samples = aligned.loc[aligned["group"] == "case", "sample_id"].tolist()
    control_samples = aligned.loc[aligned["group"] == "control", "sample_id"].tolist()
    values = np.log1p(matrix.astype(float))
    case_mean = values[case_samples].mean(axis=1)
    control_mean = values[control_samples].mean(axis=1)
    log2fc = (case_mean - control_mean).astype(float)
    noise = rng.uniform(0.0, 0.05, size=len(log2fc))
    score = log2fc.abs().to_numpy()
    rank = score.argsort().argsort().astype(float)
    padj = (1.0 - (rank + 1.0) / (len(score) + 1.0)) * 0.2 + noise
    padj = np.clip(padj, 1e-12, 1.0)
    n_case = int((aligned["group"] == "case").sum())
    n_control = int((aligned["group"] == "control").sum())
    return pd.DataFrame(
        {
            "gene": values.index.astype(str),
            "log2FoldChange": log2fc.to_numpy(),
            "pvalue": padj,
            "padj": padj,
            "engine": "mock",
            "n_case": n_case,
            "n_control": n_control,
        }
    )


def _run_r_de(
    matrix: pd.DataFrame,
    groups: pd.DataFrame,
    data_type: str,
    output_tsv: Path,
    rscript_path: Optional[Path] = None,
    r_binary: str = "Rscript",
    engine: str = "auto",
) -> pd.DataFrame:
    script = Path(rscript_path) if rscript_path else _DEFAULT_RSCRIPT
    if not script.exists():
        raise FileNotFoundError(
            f"R DE script not found: {script}. "
            "Install R packages DESeq2/limma/edgeR, or use backend='mock' / --de-results."
        )

    # Fail with instructions rather than a bare FileNotFoundError from
    # subprocess. pip cannot install R, so a pip-only user reaches this point
    # with no idea what is missing.
    if shutil.which(r_binary) is None:
        raise RuntimeError(
            f"Expression mode needs R, but {r_binary!r} was not found on PATH.\n"
            "\n"
            "Differential expression runs in R; pip cannot install it. Options:\n"
            "\n"
            "  1. conda (installs R and the Bioconductor packages together):\n"
            "       conda env create -f environment.yml\n"
            "       conda activate orbit-ocsp\n"
            "\n"
            "  2. Install R yourself, then:\n"
            '       R -e \'install.packages("BiocManager"); '
            "BiocManager::install(c(\"DESeq2\",\"limma\",\"edgeR\"))'\n"
            "\n"
            "  3. Skip R entirely: run differential expression elsewhere and\n"
            "     pass the table with --de-results results.tsv, which needs\n"
            "     columns gene, log2FoldChange, padj.\n"
            "\n"
            "Gene-list and sequence modes do not require R."
        )

    output_tsv = Path(output_tsv)
    output_tsv.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="orbit-ocsp_de_") as tmp:
        tmp_dir = Path(tmp)
        matrix_path = tmp_dir / "matrix.tsv"
        groups_path = tmp_dir / "groups.tsv"
        mat_out = matrix.copy()
        mat_out.index.name = "gene"
        mat_out.to_csv(matrix_path, sep="\t")
        groups.to_csv(groups_path, sep="\t", index=False)

        chosen = engine
        if chosen == "auto":
            n_case = int((groups["group"] == "case").sum())
            n_control = int((groups["group"] == "control").sum())
            chosen = select_de_method(n_case, n_control, data_type)

        cmd = [
            r_binary,
            str(script),
            "--matrix",
            str(matrix_path),
            "--groups",
            str(groups_path),
            "--data-type",
            data_type,
            "--output",
            str(output_tsv),
            "--engine",
            chosen,
        ]
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "R differential expression failed.\n"
                f"Command: {' '.join(cmd)}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
    return pd.read_csv(output_tsv, sep="\t")


def run_differential_expression(
    matrix_path: Union[str, Path],
    groups_path: Union[str, Path],
    data_type: str,
    outdir: Union[str, Path],
    backend: Union[str, DeBackend] = "r",
    de_results_path: Optional[Union[str, Path]] = None,
    rscript_path: Optional[Union[str, Path]] = None,
    seed: int = 42,
    check_data_type: bool = True,
) -> pd.DataFrame:
    """Run or load differential expression and write ``de_results.tsv``.

    Parameters
    ----------
    backend:
        ``"r"`` (default) calls ``R/run_de.R`` with sample-size dispatch;
        ``"mock"`` uses :func:`mock_de_from_matrix`;
        or pass a callable ``(matrix, groups, data_type) -> DataFrame``.
    de_results_path:
        If provided, skip DE and load this precomputed table instead.
    check_data_type:
        Verify the declared ``data_type`` against the matrix values via
        :func:`check_data_type_against_matrix`. Set ``False`` to skip the check
        entirely.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    output_tsv = outdir / "de_results.tsv"
    data_type = normalize_data_type(data_type)

    if de_results_path is not None:
        df = pd.read_csv(de_results_path, sep="\t")
        df.to_csv(output_tsv, sep="\t", index=False)
        return df

    matrix = read_expression_matrix(matrix_path)
    groups = read_group_table(groups_path)
    matrix, groups = subset_matrix_to_groups(matrix, groups)

    if check_data_type:
        check_data_type_against_matrix(matrix, data_type)

    if callable(backend):
        df = backend(matrix, groups, data_type)
    elif backend == "mock":
        df = mock_de_from_matrix(matrix, groups, seed=seed)
    elif backend in {"r", "R"}:
        n_case = int((groups["group"] == "case").sum())
        n_control = int((groups["group"] == "control").sum())
        method = select_de_method(n_case, n_control, data_type)
        if method == "edger" and data_type != "rnaseq_count":
            raise ValueError(
                "1-vs-1 comparisons are only supported for rnaseq_count via edgeR"
            )
        df = _run_r_de(
            matrix=matrix,
            groups=groups,
            data_type=data_type,
            output_tsv=output_tsv,
            rscript_path=Path(rscript_path) if rscript_path else None,
            engine=method,
        )
        return df
    else:
        raise ValueError(
            f"Unknown DE backend {backend!r}; expected 'r', 'mock', or a callable"
        )

    if "engine" not in df.columns:
        df["engine"] = "mock" if backend == "mock" else select_de_engine(data_type)
    df.to_csv(output_tsv, sep="\t", index=False)
    return df


def filter_and_topk(
    de_table: pd.DataFrame,
    padj_max: float = 0.05,
    abs_log2fc_min: float = 1.0,
    k: int = 20,
) -> pd.DataFrame:
    """Convenience wrapper: filter then select top-k genes."""
    filtered = filter_de_results(
        de_table,
        padj_max=padj_max,
        abs_log2fc_min=abs_log2fc_min,
    )
    return select_topk(filtered, k=k)
