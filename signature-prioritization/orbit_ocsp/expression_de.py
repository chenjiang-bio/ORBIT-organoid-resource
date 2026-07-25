"""Differential expression helpers for the expression→biomarker pipeline.

Default backend is R (``R/run_de.R``), with sample-size–aware engine selection:

- ``n_case == 1`` and ``n_control == 1`` → edgeR (only viable 1-vs-1 path)
- ``n_case > 8`` and ``n_control > 8`` → Wilcoxon rank-sum
- otherwise:
  - ``rnaseq_count`` → DESeq2
  - ``microarray`` / ``normalized`` → limma

``backend="mock"`` remains available for deterministic unit tests.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Literal, Optional, Tuple, Union

import numpy as np
import pandas as pd

DataType = Literal["rnaseq_count", "microarray", "normalized"]
VALID_DATA_TYPES = {"rnaseq_count", "microarray", "normalized"}
VALID_GROUPS = {"case", "control"}
LARGE_N_THRESHOLD = 8  # use Wilcoxon when both groups have n > 8

_PKG_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_RSCRIPT = _PKG_ROOT / "R" / "run_de.R"

DeBackend = Callable[..., pd.DataFrame]


def select_de_engine(data_type: str) -> str:
    """Return the baseline engine name for a data type (ignoring sample size)."""
    dtype = (data_type or "").strip().lower()
    if dtype not in VALID_DATA_TYPES:
        raise ValueError(
            f"Unsupported data_type {data_type!r}; expected one of "
            f"{sorted(VALID_DATA_TYPES)}"
        )
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
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    output_tsv = outdir / "de_results.tsv"

    if de_results_path is not None:
        df = pd.read_csv(de_results_path, sep="\t")
        df.to_csv(output_tsv, sep="\t", index=False)
        return df

    matrix = read_expression_matrix(matrix_path)
    groups = read_group_table(groups_path)
    matrix, groups = subset_matrix_to_groups(matrix, groups)

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
