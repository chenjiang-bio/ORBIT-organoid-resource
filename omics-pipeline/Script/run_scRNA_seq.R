#!/usr/bin/env Rscript
# =============================================================================
# run_scRNA_seq.R
# scRNA-seq downstream analysis (QC, clustering, annotation; optional multi-group DE).
#
# Modes (--mode):
#   auto   — multi if comparisons.txt has rows, otherwise single
#   single — clustering, annotation, markers, trajectory
#   multi  — group DE plus pseudobulk enrichment / GSEA / GSVA
#
# Required input layout:
#   work_dir/<organism>/<GSE>/   OR   work_dir/<GSE>/
#     samples_info.txt
#     comparisons.txt    # optional for mode=single; required for mode=multi
#     ExprMatrix/        # expression matrices (counts/ still accepted as fallback)
#
# samples_info.txt (tab-separated; Example columns):
#   ID       — library / batch index (required for merged 10x barcodes ending in -N)
#   Sample   — GSM ID (join key for h5 / multi-csv / per-sample 10x folders)
#   Source   — descriptive sample label written into cell metadata after join
#   Group    — condition label used in comparisons
#   tissue   — optional default ScType tissueType
# Legacy aliases accepted: orig.ident→ID, new.ident→Sample, group→Group.
#
# comparisons.txt (tab-separated):
#   Control/Treatment or group1/group2; optional tissue_type (ScType tissueType)
#
# ExprMatrix/ formats and how cells join to samples_info:
#   1) Single 10x folder (matrix.mtx + features/genes + barcodes)
#        barcode suffix -1,-2,...  →  samples_info$ID
#        GEO-prefixed triplet names are normalized automatically
#   2) Multiple 10x sample folders (one folder per sample; name usually GSM)
#        folder name               →  samples_info$Sample
#   3) One or more .h5 files
#        GSM prefix before '_'     →  samples_info$Sample
#   4) Multiple csv/txt/tsv (one file per sample; first column = gene ID)
#        GSM prefix in filename    →  samples_info$Sample
#   5) Single merged csv/txt/tsv (genes × cells)
#        barcode prefix (e.g. CTRL_) → Sample / Source / ID, or CTRL↔control
#        / treatment aliases when prefixes are not GSM
#
# Usage:
#   Rscript Script/run_scRNA_seq.R --work_dir PATH --organism hsa|mmu \
#       (--gse GSE123 | --gse_list file.txt) \
#       [--mode auto|single|multi] [--general_file PATH] [--tissue TISSUE] \
#       [--skip_completed TRUE|FALSE] [--strict TRUE|FALSE]
#
# --tissue / comparisons$tissue_type / samples_info$tissue must match a tissueType
# value in GeneralFile/scType/ScTypeDB_full.xlsx (see README for the current list).
# Primary source: comparisons.txt column tissue_type (per comparison).
# Fallbacks: --tissue, then samples_info$tissue; if still empty, ScType is skipped.
#
# Examples (from repository root):
#   Rscript Script/run_scRNA_seq.R \
#     --work_dir Example/scRNA_seq --organism hsa --gse GSE276177 --mode auto
#
#   Rscript Script/run_scRNA_seq.R \
#     --work_dir Example/scRNA_seq --organism mmu --gse GSE118055 --mode single
#
#   Rscript Script/run_scRNA_seq.R \
#     --work_dir Example/scRNA_seq --organism hsa --gse_list my_gse.txt \
#     --mode auto --skip_completed TRUE
#
# Outputs: under each GSE folder (cohort / comparison subdirectories)
# Batch log: work_dir/batch_scRNA_seq.log
#
# Dependencies:
#   Rscript Script/install_deps.R --type scrna
# =============================================================================

suppressPackageStartupMessages({
  options(stringsAsFactors = FALSE)
  Sys.setenv(R_MAX_NUM_DLLS = 999)
  options(timeout = 600)
})

# ---- Locate helpers ----
args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args_all, value = TRUE)
if (length(file_arg) > 0) {
  SCRIPT_PATH <- normalizePath(sub("^--file=", "", file_arg[[1]]), winslash = "/", mustWork = FALSE)
  SCRIPT_DIR <- dirname(SCRIPT_PATH)
} else {
  SCRIPT_DIR <- normalizePath(getwd(), winslash = "/", mustWork = FALSE)
}

source(file.path(SCRIPT_DIR, "lib", "cli_utils.R"))
source(file.path(SCRIPT_DIR, "lib", "scRNA_core.R"))

# ---- CLI ----
usage_text <- function() {
  paste(
    "Usage:",
    "  Rscript run_scRNA_seq.R --work_dir PATH --organism hsa|mmu",
    "      (--gse GSE OR --gse_list FILE) [--mode auto|single|multi]",
    "      [--general_file PATH] [--tissue TISSUE] [--skip_completed TRUE]",
    sep = "\n"
  )
}

raw_args <- commandArgs(trailingOnly = TRUE)
if (length(raw_args) == 0) {
  cat(usage_text(), "\n")
  quit(status = 1)
}

opts <- parse_named_args(
  raw_args,
  defaults = list(
    work_dir = "",
    organism = "",
    gse = "",
    gse_list = "",
    mode = "auto",
    general_file = "",
    tissue = "",
    skip_completed = FALSE,
    strict = TRUE,
    fast = FALSE,
    max_gsea_plots = "",
    skip_gsea_plots = FALSE,
    skip_ssgsea = "",
    skip_save_image = "",
    skip_gene_cell_exp = "",
    skip_network_plots = "",
    resolutions = "",
    n_workers = 1
  ),
  required = character()
)
perf <- resolve_perf_opts(opts)

# Positional fallback: work_dir organism gse_or_list
pos <- opts[[".positionals"]]
if ((!nzchar(opts$work_dir) || !nzchar(opts$organism)) && length(pos) >= 2) {
  if (!nzchar(opts$work_dir)) opts$work_dir <- pos[[1]]
  if (!nzchar(opts$organism)) opts$organism <- pos[[2]]
  if (length(pos) >= 3 && !nzchar(opts$gse) && !nzchar(opts$gse_list)) {
    maybe <- pos[[3]]
    if (file.exists(maybe)) opts$gse_list <- maybe else opts$gse <- maybe
  }
}

if (!nzchar(opts$work_dir) || !nzchar(opts$organism)) {
  stop(usage_text(), call. = FALSE)
}
if (!opts$organism %in% c("hsa", "mmu")) {
  stop("--organism must be hsa or mmu", call. = FALSE)
}

work_dir <- normalizePath(opts$work_dir, winslash = "/", mustWork = FALSE)
if (!dir.exists(work_dir)) stop("work_dir does not exist: ", work_dir, call. = FALSE)

GeneralFile <- resolve_general_file(
  if (nzchar(opts$general_file)) opts$general_file else NULL,
  script_dir = SCRIPT_DIR
)
if (!dir.exists(GeneralFile)) {
  stop("GeneralFile not found: ", GeneralFile, call. = FALSE)
}

gse_ids <- read_gse_ids(
  gse = if (nzchar(opts$gse)) opts$gse else NULL,
  gse_list = if (nzchar(opts$gse_list)) opts$gse_list else NULL
)

batch_log_file <- file.path(work_dir, "batch_scRNA_seq.log")
batch_log(batch_log_file, paste(
  "START scRNA-seq batch | organism=", opts$organism,
  "| mode=", opts$mode, "| nGSE=", length(gse_ids),
  "| fast=", perf$fast,
  "| n_workers=", perf$n_workers,
  "| resolutions=", paste(perf$resolutions, collapse = ",")
))

# ---- Optional GPTCelltype setup (disabled; no secrets) ----
if (FALSE) {
  # Enable only when OPENAI_API_KEY is already set in the environment.
  # library(httr); library(openai); library(GPTCelltype)
  message("GPTCelltype block is disabled.")
}

# ---- Packages once ----
suppressPackageStartupMessages({
  library(AnnotationDbi)
  library(DESeq2)
  library(edgeR)
  library(limma)
  library(clusterProfiler)
  library(org.Hs.eg.db)
  library(org.Mm.eg.db)
  library(GSVA)
  library(GSEABase)
  library(ggplot2)
  library(pheatmap)
  library(enrichplot)
  library(DOSE)
  library(BiocParallel)
  library(msigdbr)
  library(dplyr)
  library(tidyr)
  library(tibble)
  library(purrr)
  library(future)
  library(SingleR)
  library(muscat)
  library(sctransform)
  library(slingshot)
  library(tradeSeq)
  library(glmGamPoi)
  library(SeuratWrappers)
  library(harmony)
  library(Seurat)
  library(HGNChelper)
  library(openxlsx)
  library(hdf5r)
  library(stringr)
  library(data.table)
  library(patchwork)
  library(scales)
  library(cowplot)
  library(plyr)
  library(ggrepel)
  library(ggpubr)
  library(ggsci)
  library(clustree)
  library(RColorBrewer)
  library(Matrix)
  library(SingleCellExperiment)
  library(S4Vectors)
  library(fs)
})
suppress_namespace_conflicts()

# ---- Resources once per organism ----
resources <- load_scRNA_resources(GeneralFile, opts$organism)
batch_log(batch_log_file, paste("Loaded GeneralFile resources from", GeneralFile))

run_scRNA_stage <- function(gse_id, outdir, stage, expr) {
  batch_log(batch_log_file, paste("STAGE START", gse_id, outdir, stage))
  tryCatch(
    {
      value <- eval.parent(substitute(expr))
      batch_log(batch_log_file, paste("STAGE DONE", gse_id, outdir, stage))
      value
    },
    error = function(e) {
      batch_log(batch_log_file, paste(
        "STAGE ERROR", gse_id, outdir, stage, ":", conditionMessage(e)
      ))
      batch_log(batch_log_file, paste("CALL STACK", format_error_calls()))
      stop(e)
    }
  )
}

# ---- Per-GSE runner ----
run_one_gse <- function(gse_id) {
  gse_dir <- resolve_gse_dir(work_dir, opts$organism, gse_id, create = FALSE)
  if (!dir.exists(gse_dir)) {
    stop("GSE directory not found (tried organism/GSE and GSE): ", gse_id)
  }

  samples_path <- file.path(gse_dir, "samples_info.txt")
  if (!file.exists(samples_path)) stop("Missing samples_info.txt in ", gse_dir)
  samples_info <- normalize_samples_info(
    read.csv(samples_path, sep = "\t", stringsAsFactors = FALSE)
  )

  comparisons_path <- file.path(gse_dir, "comparisons.txt")
  comparisons <- NULL
  if (file.exists(comparisons_path)) {
    comparisons <- read.csv(comparisons_path, sep = "\t", stringsAsFactors = FALSE)
    comparisons <- normalize_comparisons(comparisons)
  }

  mode <- resolve_scRNA_mode(opts$mode, comparisons)

  # Expected output dirs for skip_completed
  if (mode == "multi") {
    if (is.null(comparisons) || nrow(comparisons) < 1) {
      stop("mode=multi requires comparisons.txt with >=1 row")
    }
    outdirs <- paste0(comparisons$Treatment, "_vs_", comparisons$Control)
  } else {
    ug <- unique(as.character(samples_info$Group))
    outdirs <- if (length(ug) == 1) ug else "all"
  }

  if (isTRUE(opts$skip_completed) && scRNA_outputs_complete(gse_dir, outdirs)) {
    batch_log(batch_log_file, paste("SKIP completed:", gse_id, "| outdirs=", paste(outdirs, collapse = ",")))
    return(invisible("skipped"))
  }

  # Prefer ExprMatrix/; fall back to counts/ for older layouts
  expr_dir <- file.path(gse_dir, "ExprMatrix")
  if (!dir.exists(expr_dir)) {
    alt <- file.path(gse_dir, "counts")
    if (dir.exists(alt)) {
      message("Using legacy counts/ directory; prefer renaming to ExprMatrix/")
      expr_dir <- alt
    }
  }
  scRNA_all <- load_counts_to_seurat(expr_dir, opts$organism, convert_id_to_symbols_offline)
  scRNA_all <- add_group_metadata(scRNA_all, samples_info)

  # Tissue resolution (ScType):
  #   1) comparisons.txt tissue_type (primary, per comparison in multi mode)
  #   2) --tissue CLI override
  #   3) samples_info$tissue
  #   4) empty → skip ScType
  cli_tissue <- if (nzchar(opts$tissue)) opts$tissue else ""
  sample_tissue <- if ("tissue" %in% colnames(samples_info)) {
    as.character(na.omit(unique(samples_info$tissue))[1])
  } else {
    ""
  }
  if (is.na(sample_tissue)) sample_tissue <- ""

  fallback_tissue <- if (nzchar(cli_tissue)) {
    cli_tissue
  } else if (nzchar(sample_tissue)) {
    sample_tissue
  } else {
    ""
  }
  if (nzchar(fallback_tissue)) {
    fallback_tissue <- validate_sctype_tissue(
      fallback_tissue,
      allowed = resources$sctype_tissues,
      db_path = resources$db_
    )
  }

  if (mode == "multi") {
    for (i in seq_len(nrow(comparisons))) {
      group1 <- as.character(comparisons$Control[i])
      group2 <- as.character(comparisons$Treatment[i])
      outdir <- paste0(group2, "_vs_", group1)

      tissue_i <- ""
      if ("tissue_type" %in% colnames(comparisons)) {
        tissue_i <- as.character(comparisons$tissue_type[i])
        if (is.na(tissue_i)) tissue_i <- ""
      }
      if (!nzchar(tissue_i)) tissue_i <- fallback_tissue
      if (nzchar(tissue_i)) {
        tissue_i <- validate_sctype_tissue(
          tissue_i,
          allowed = resources$sctype_tissues,
          db_path = resources$db_
        )
      }

      if (isTRUE(opts$skip_completed) && scRNA_outputs_complete(gse_dir, outdir)) {
        batch_log(batch_log_file, paste("SKIP comparison:", gse_id, outdir))
        next
      }

      batch_log(batch_log_file, paste(
        "RUN multi:", gse_id, outdir,
        "tissue=", if (nzchar(tissue_i)) tissue_i else "<none>"
      ))
      run_scRNA_stage(gse_id, outdir, "cohort_analysis", {
        analyze_scRNA_cohort(
          scRNA_all = scRNA_all,
          samples_info = samples_info,
          gse.number = gse_id,
          organism = opts$organism,
          resources = resources,
          outdir = outdir,
          group1 = group1,
          group2 = group2,
          tissue = tissue_i,
          do_multi_de = TRUE,
          gse_dir = gse_dir,
          perf = perf
        )
      })
    }
  } else {
    ug <- unique(as.character(samples_info$Group))
    outdir <- if (length(ug) == 1) ug[[1]] else "all"
    # single mode: prefer tissue_type from comparisons if present, else fallback
    single_tissue <- fallback_tissue
    if (!is.null(comparisons) && nrow(comparisons) >= 1 &&
        "tissue_type" %in% colnames(comparisons)) {
      tt <- unique(na.omit(as.character(comparisons$tissue_type)))
      tt <- tt[nzchar(tt)]
      if (length(tt) >= 1) {
        single_tissue <- tt[[1]]
        if (length(tt) > 1) {
          message(
            "Multiple tissue_type values in comparisons.txt for single mode; ",
            "using first: ", single_tissue
          )
        }
      }
    }
    if (nzchar(single_tissue)) {
      single_tissue <- validate_sctype_tissue(
        single_tissue,
        allowed = resources$sctype_tissues,
        db_path = resources$db_
      )
    }
    batch_log(batch_log_file, paste(
      "RUN single:", gse_id, "outdir=", outdir,
      "tissue=", if (nzchar(single_tissue)) single_tissue else "<none>"
    ))
    run_scRNA_stage(gse_id, outdir, "cohort_analysis", {
      analyze_scRNA_cohort(
        scRNA_all = scRNA_all,
        samples_info = samples_info,
        gse.number = gse_id,
        organism = opts$organism,
        resources = resources,
        outdir = outdir,
        group1 = NULL,
        group2 = NULL,
        tissue = single_tissue,
        do_multi_de = FALSE,
        gse_dir = gse_dir,
        perf = perf
      )
    })
  }

  invisible("ok")
}

# ---- Batch loop ----
batch_had_error <- FALSE
strict_mode <- isTRUE(opts$strict)

if (perf$n_workers > 1L && length(gse_ids) > 1L) {
  shared_args <- c(
    "--work_dir", work_dir,
    "--organism", opts$organism,
    "--general_file", GeneralFile,
    "--mode", opts$mode,
    "--skip_completed", as.character(opts$skip_completed),
    "--strict", as.character(strict_mode),
    "--fast", as.character(perf$fast),
    "--skip_ssgsea", as.character(perf$skip_ssgsea),
    "--skip_save_image", as.character(perf$skip_save_image),
    "--skip_gene_cell_exp", as.character(perf$skip_gene_cell_exp),
    "--skip_network_plots", as.character(perf$skip_network_plots),
    "--resolutions", paste(perf$resolutions, collapse = ",")
  )
  if (nzchar(opts$tissue)) {
    shared_args <- c(shared_args, "--tissue", opts$tissue)
  }
  if (is.finite(perf$max_gsea_plots)) {
    shared_args <- c(shared_args, "--max_gsea_plots", as.character(perf$max_gsea_plots))
  }
  results <- parallel_rscript_gse(
    gse_ids = gse_ids,
    shared_args = shared_args,
    n_workers = perf$n_workers,
    logfile = batch_log_file
  )
  batch_had_error <- any(!vapply(results, function(r) isTRUE(r$ok), logical(1)))
} else {
  for (gse_id in gse_ids) {
    batch_log(batch_log_file, paste("Processing", opts$organism, gse_id))
    tryCatch({
      run_one_gse(gse_id)
      batch_log(batch_log_file, paste("SUCCESS", gse_id))
    }, error = function(e) {
      batch_had_error <<- TRUE
      batch_log(batch_log_file, paste("ERROR", gse_id, ":", conditionMessage(e)))
    })
  }
}

batch_log(batch_log_file, "DONE scRNA-seq batch")
if (isTRUE(strict_mode) && isTRUE(batch_had_error)) {
  quit(save = "no", status = 1)
}
