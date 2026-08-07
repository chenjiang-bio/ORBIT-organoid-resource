# Example datasets

Minimal prepared inputs for trying each pipeline. Paths are relative to the `omics-pipeline/` directory.

| Pipeline | Expression input | Example command |
|----------|------------------|-----------------|
| RNA-seq | `{GSE}.{org}.ExprMatrix.txt` (raw counts) | `Rscript Script/run_RNA_seq.R --work_dir Example/RNA_seq --organism hsa --gse GSE111082` |
| Microarray | `{GSE}.{org}.ExprMatrix.txt` (Symbol × samples) | `Rscript Script/run_MicroArray.R --work_dir Example/MicroArray --organism hsa --gse GSE9196` |
| scRNA-seq | `ExprMatrix/` (10x / h5 / txt) | `Rscript Script/run_scRNA_seq.R --work_dir Example/scRNA_seq --organism mmu --gse GSE223368 --mode auto --tissue Intestine` |

See [OPERATING_INSTRUCTIONS.md](../OPERATING_INSTRUCTIONS.md) for input column requirements and full options.

## What is included

Only prepared **inputs** are kept in git:

- `samples_info.txt`, `comparisons.txt`, `gse_list*.txt`
- expression matrices under each GSE folder / `ExprMatrix/`

Generated analysis outputs (DEG tables, enrichment results, plots, Seurat objects, batch logs, etc.) are not included. Very large matrix files may also be omitted; download or prepare them locally if a listed example is incomplete.
