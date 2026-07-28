# Omics Analysis Pipeline Operating Instructions

Batch analysis pipelines for public GEO omics datasets (human / mouse), covering:

- **Bulk RNA-seq** - upstream (download -> align -> count) and downstream (DEG -> enrichment -> GSEA -> GSVA)
- **Microarray** - GEO prepare + limma DEG + enrichment / GSEA / GSVA
- **scRNA-seq** - Seurat QC / clustering / annotation, optional multi-group DE and pseudobulk enrichment

Species codes: `hsa` (human), `mmu` (mouse).

## Repository layout

```text
omics-pipeline/
  README.md
  OPERATING_INSTRUCTIONS.md
  Script/
    install_deps.R          # install R / Bioconductor dependencies
    run_rna_upstream.sh     # bulk RNA-seq upstream
    run_RNA_seq.R           # bulk RNA-seq downstream
    run_MicroArray.R        # microarray downstream
    run_scRNA_seq.R         # scRNA-seq downstream
    lib/                    # shared helpers
  GeneralFile/              # gene sets, annotations, references
  Example/                  # minimal example inputs
```

## Requirements

| Component | Requirement |
|-----------|-------------|
| R | >= 4.3 recommended (tested on 4.5.x) |
| Bioconductor | matching your R version (e.g. 3.21 for R 4.5) |
| Upstream tools | `iseq`, `fastp`, `hisat2`, `samtools`, `featureCounts` |
| Disk | reference genomes under `GeneralFile/ref_genome/` (see below) |

## Install R packages

From the repository root:

```bash
# All downstream pipelines
Rscript Script/install_deps.R --type all

# Or by pipeline
Rscript Script/install_deps.R --type rna
Rscript Script/install_deps.R --type microarray
Rscript Script/install_deps.R --type scrna

# Verify only
Rscript Script/install_deps.R --type all --check_only TRUE
```

Useful options:

- `--bioc_version 3.21` - set Bioconductor version explicitly
- `--use_default_repos TRUE` - use official CRAN / Bioconductor mirrors
- `--force TRUE` - reinstall packages

Upstream binaries are **not** installed by this script:

```bash
Rscript Script/install_deps.R --type upstream
```

## Reference data (`GeneralFile`)

Place shared resources under `GeneralFile/` (paths are resolved relative to `Script/`):

| Path | Purpose |
|------|---------|
| `CellMarker/` | CellMarker gene sets |
| `scType/` | ScType DB + helper R scripts |
| `SingleR/` | Bundled SingleR references: `HumanPrimaryCellAtlasData.rds` (human), `MouseRNAseqData.rds` (mouse) |
| `ssGSEA/` | Immune signature list (human), e.g. `ssGSEA_Hs.rds` (optional; place locally if used) |
| `gene_length_Hs.txt` / `gene_length_Mm.txt` | Gene lengths for TPM |
| `GEOMods.R` | Microarray GPL helpers |
| `ref_genome/` | FASTA + GTF; HISAT2 indexes built on demand |

Large genome FASTA files and HISAT2 indexes are not shipped in git (see `.gitignore`). Download them locally, then build indexes:

```bash
bash Script/run_rna_upstream.sh --species hsa --stage build-index
bash Script/run_rna_upstream.sh --species mmu --stage build-index
```

Default files expected in `ref_genome/`:

- Human: `GRCh38.p14.genome.fa.gz`, `gencode.v46.annotation.gtf.gz`, index prefix `GRCh38.p14`
- Mouse: `GRCm39.genome.fa.gz`, `gencode.vM35.annotation.gtf.gz`, index prefix `GRCm39`

## Quick start (examples)

```bash
# Bulk RNA-seq downstream
Rscript Script/run_RNA_seq.R \
  --work_dir Example/RNA_seq --organism hsa --gse GSE111082

# Microarray (prepared inputs)
Rscript Script/run_MicroArray.R \
  --work_dir Example/MicroArray --organism hsa --gse GSE30304

# Microarray from GEO (download + auto meta + analysis)
Rscript Script/run_MicroArray.R \
  --work_dir ./microarray_out --organism hsa --gse GSE30304 \
  --download TRUE

# scRNA-seq
Rscript Script/run_scRNA_seq.R \
  --work_dir Example/scRNA_seq --organism mmu --gse GSE223368 \
  --mode auto --tissue Intestine
```

Batch mode: pass `--gse_list ids.txt` (one GSE ID per line). Use `--skip_completed TRUE` to resume. Use `--strict TRUE` (default) so any GSE/comparison failure exits with status 1.

## Downstream inputs: file types and notes

All three downstream runners share the same meta-table conventions where applicable.

### Shared meta files

#### `samples_info.txt` (tab-separated)

| Column | Required | Meaning |
|--------|----------|---------|
| `Sample` | yes | GEO sample ID (usually GSM...); bulk/microarray matrix columns; scRNA join key for h5/csv/multi-10x |
| `Source` | yes | Label used inside the analysis object; bulk RNA-seq remaps matrix columns Sample -> Source |
| `Group` | yes | Condition label used in comparisons |
| `ID` | scRNA often yes | Library index for merged 10x barcodes ending in `-N` (see Examples) |
| `Group_1` | microarray optional | Alternate grouping column if needed |
| `tissue` | scRNA optional | ScType panel; must be a `tissueType` in `GeneralFile/scType/ScTypeDB_full.xlsx` |

Notes:

- Header aliases are accepted case-insensitively (`sample` / `Sample`, etc.).
- `Group` values must match the names used in `comparisons.txt` (after cleaning).
- Prefer short, file-safe labels (letters, digits, `_`); avoid spaces and `/`.

#### `comparisons.txt` (tab-separated)

| Column | Required | Meaning |
|--------|----------|---------|
| `Control` or `group1` | yes* | Reference / baseline group |
| `Treatment` or `group2` | yes* | Contrast group |
| `tissue_type` | scRNA yes (preferred) | Per-comparison ScType `tissueType`; primary way to set tissue |
| `source` | microarray optional | Extra phenotype column name to subset on |

\* scRNA `mode=single` does not need comparisons; `mode=multi` / `auto` with rows does.

Each row becomes an output folder `{Treatment}_vs_{Control}/`.

---

### Bulk RNA-seq - `run_RNA_seq.R`

```text
work_dir/<organism>/<GSE>/
  {GSE}.{organism}.ExprMatrix.txt|.tsv
  samples_info.txt
  comparisons.txt
```

| File | Type | Content |
|------|------|---------|
| `{GSE}.{organism}.ExprMatrix.txt` | TSV | Gene x sample matrix. **Raw integer counts** (featureCounts / HTSeq style). First column = gene ID (Ensembl preferred; Symbol/Entrez are mapped). Remaining columns = `Sample` IDs from `samples_info.txt` |
| `samples_info.txt` | TSV | `Sample`, `Source`, `Group` |
| `comparisons.txt` | TSV | `Control`/`Treatment` or `group1`/`group2` |

Accepted aliases for the matrix (first match wins):

`{GSE}.{organism}.ExprMatrix.txt|.tsv` -> `.expr.*` -> `.counts.*` -> bare `ExprMatrix.txt` / `expr.txt` / `counts.txt`

Notes:

- Prefer **raw counts**. DESeq2 / edgeR assume count data; do not feed TPM/FPKM/log2 as primary input.
- Ensembl version suffixes (e.g. `ENSG000001.12`) are stripped; duplicate genes are summed.
- Biological replicates are strongly recommended. The pipeline selects DESeq2, edgeR, or Wilcoxon according to group sizes and also filters low-count genes.
- Upstream `run_rna_upstream.sh` writes `{GSE}.{species}.ExprMatrix.txt` ready for this step.

---

### Microarray - `run_MicroArray.R`

```text
work_dir/<organism>/<GSE>/   # or work_dir/<GSE>/
  {GSE}.{organism}.ExprMatrix.txt
  samples_info.txt
  comparisons.txt
```

| File | Type | Content |
|------|------|---------|
| `{GSE}.{organism}.ExprMatrix.txt` | TSV | **Gene symbol** x samples. First column named `Symbol` (or similar). Values = platform intensity / processed expression used by limma |
| `samples_info.txt` | TSV | `Sample`, `Source`, `Group` [, `Group_1`] |
| `comparisons.txt` | TSV | pairwise groups as above |

Notes:

- Matrix columns must match `samples_info$Sample` (GSM IDs).
- Duplicate symbols are aggregated by mean.
- With `--download TRUE` / `--prepare TRUE`, GEO Series Matrix + GPL annotation are used to build `ExprMatrix.txt` and draft meta files. Auto `comparisons.txt` uses a **Control vs each Treatment** template (control-like labels preferred). **Always review auto-generated `comparisons.txt`** before large batches - phenotype text is noisy.
- `--force_prepare TRUE` rebuilds meta / ExprMatrix from an existing GEO cache under `work_dir/Data/`.

---

### scRNA-seq - `run_scRNA_seq.R`

```text
work_dir/<organism>/<GSE>/   # or work_dir/<GSE>/
  samples_info.txt
  comparisons.txt            # optional for mode=single
  ExprMatrix/                # one of the formats below
```

| Item | Type | Content |
|------|------|---------|
| `ExprMatrix/` | directory | Raw count matrices (see formats); `counts/` is still accepted as a fallback |
| `samples_info.txt` | TSV | `ID`, `Sample`, `Source`, `Group`; optional `tissue` |
| `comparisons.txt` | TSV | required for `mode=multi` |

Supported layouts under `ExprMatrix/` (detected automatically, first match):

1. **Single 10x folder** - `matrix.mtx(.gz)` + `features/genes` + `barcodes` (prefixed GEO names are normalized automatically). Cell barcodes ending in `-1`, `-2`, ... are mapped to `samples_info$ID`.
2. **Multiple 10x folders** - one subfolder per sample (folder name usually GSM). Mapped to `samples_info$Sample`.
3. **`.h5` files** - Cell Ranger HDF5; GSM taken from the filename prefix before `_`. Mapped to `samples_info$Sample`.
4. **Multiple csv/txt/tsv** - one matrix file per sample (first column = gene ID; GSM from filename prefix). Mapped to `samples_info$Sample`.
5. **Single merged csv/txt/tsv** - genes x cells; barcode prefixes (e.g. `CTRL_...`) are mapped via Sample/Source/ID, or control/treatment aliases when needed.

Join key depends on matrix type as above; after joining, cell `Source` / `Sample` / `Group` come from `samples_info`. Example `samples_info.txt` files should be left as-is.

Notes:

- Gene IDs may be Ensembl / Entrez / Symbol; Ensembl/Entrez are mapped offline to symbols when needed.
- `--mode auto`: multi if `comparisons.txt` has >=1 row, else single.
- ScType tissue resolution order:
  1. `comparisons.txt` -> `tissue_type` (primary; per comparison in multi mode)
  2. CLI `--tissue`
  3. `samples_info.txt` -> `tissue`
  4. If still empty, ScType is skipped (`celltype_scType=Unknown`)

  Values **must** be a `tissueType` from `GeneralFile/scType/ScTypeDB_full.xlsx` (exact spelling). Current values in the bundled DB:

  `Adrenal`, `Brain`, `Eye`, `Heart`, `Hippocampus`, `Immune system`, `Intestine`, `Kidney`, `Liver`, `Lung`, `Muscle`, `Pancreas`, `Placenta`, `Spleen`, `Stomach`, `Thymus`

  Invalid names abort the run and print the allowed list. If the Excel file is updated, use the new `tissueType` values from that file.
- Runs can be long (many resolutions, markers, GSEA plots). Use `--skip_completed TRUE` to resume.

---

### Quick comparison

| Pipeline | Expression input | Gene ID | Values | Meta |
|----------|------------------|---------|--------|------|
| RNA-seq | `{GSE}.{org}.ExprMatrix.txt` | Ensembl preferred | raw counts | samples + comparisons |
| Microarray | `{GSE}.{org}.ExprMatrix.txt` | Symbol | intensity / expr | samples + comparisons |
| scRNA | `ExprMatrix/` (10x / h5 / txt) | Ensembl or Symbol | raw UMI/counts | samples; comparisons if multi |

## Upstream RNA-seq

```bash
bash Script/run_rna_upstream.sh \
  --gse-list list.txt \
  --species hsa \
  --mode srr \
  --outdir ./rna_out \
  --stage all \
  --jobs 4 \
  --download-jobs 2
```

| Flag | Meaning |
|------|---------|
| `--mode srr` | one GSM <-> one SRR |
| `--mode srx` | one GSM <-> multiple SRR (`iseq -e ex`) |
| `--stage` | `download` \| `meta` \| `analyze` \| `build-index` \| `all` |
| `--jobs N` | parallel samples per GSE for QC+align (default 1; threads auto-divided) |
| `--download-jobs N` | parallel GSE downloads (default 1) |
| `--keep-clean-fq` | keep `*.clean.fq.gz` after alignment (default: delete) |
| `--remove-bam` | delete BAM after successful count matrix (default: keep) |

Analyze pipeline: `fastp -> hisat2 | samtools sort -> batch featureCounts -> merge`.

Final matrix per GSE: `{GSE}.{species}.ExprMatrix.txt` (plus `samples_info.txt` when generated).

See `bash Script/run_rna_upstream.sh --help` for threads and custom reference paths.

## Outputs and resuming

Each comparison (or cohort) is written under the GSE folder, typically as `{Treatment}_vs_{Control}/`, including DEG tables, enrichment CSVs, GSEA/GSVA results, and an `.RData` snapshot. A final `_SUCCESS` file is written only after the requested analysis finishes successfully; `--skip_completed TRUE` uses this marker rather than the `.RData` file. Existing output directories created by older versions without `_SUCCESS` are rerun once.

Batch logs:

- `batch_RNA_seq.log`
- `batch_MicroArray.log`
- `batch_scRNA_seq.log`

The scRNA-seq log records `STAGE START`, `STAGE DONE`, `STAGE ERROR`, and a compact call stack for cohort-level failures.

## Notes for users

- Override shared resources with `--general_file /path/to/GeneralFile`.
- Comparison headers accept `Control`/`Treatment` or `group1`/`group2`.
- Bulk DE method (RNA-seq / scRNA pseudobulk): DESeq2 when both groups have 2–7 samples; Wilcoxon when both >=8; otherwise edgeR (estimateDisp if either side has replicates, else fixed BCV²).
- Microarray DEG significance uses the raw `pvalue < 0.05` together with the configured fold-change threshold.
- GSVA/ssGSEA `Regulation` is assigned by `P.Value < 0.05`; direction comes from the sign of `logFC`.
- `--strict TRUE` (default) makes batch runners exit with status 1 if any GSE/comparison failed.
- **Speed options** (all three pipelines):
  - `--fast TRUE` - recommended for large batches: skips network PDFs, uses a lightweight `.RData` snapshot, and applies pipeline-specific performance defaults.
  - `--n_workers N` - run up to N GSE IDs **in parallel** using separate Rscript child processes. Example: `--gse_list ids.txt --n_workers 4`.
  - `--max_gsea_plots N` - optional; omit to plot all significant GSEA terms (`0` or `--skip_gsea_plots TRUE` disables plots).
  - `--skip_save_image TRUE` / `--skip_network_plots TRUE`.
  - `--resolutions 0.6` or `0.4,0.8` - scRNA only; optional subset (default: `0.2,0.4,0.6,0.8,1.0`).
- scRNA runs with many resolutions and per-term GSEA plots can take a long time on large datasets; parallel scRNA requires enough RAM for approximately N datasets at once.
