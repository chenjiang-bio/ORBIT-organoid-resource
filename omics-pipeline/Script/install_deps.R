#!/usr/bin/env Rscript
# =============================================================================
# install_deps.R
# Install R / Bioconductor packages required by the omics-pipeline.
#
# Usage:
#   Rscript Script/install_deps.R --type all
#   Rscript Script/install_deps.R --type rna|microarray|scrna
#   Rscript Script/install_deps.R --type all --check_only TRUE
#   Rscript Script/install_deps.R --type all --bioc_version 3.21
#   Rscript Script/install_deps.R --type upstream   # prints system-tool notes only
#
# Options:
#   --type                 rna | microarray | scrna | all | upstream
#   --bioc_version         Bioconductor version (default: auto from R version)
#   --check_only TRUE      report missing packages without installing
#   --use_default_repos TRUE   use official CRAN / Bioconductor mirrors
#   --force TRUE           reinstall packages even if already present
#
# Notes:
#   - Default mirrors are TUNA (CRAN) and USTC (Bioconductor); override with
#     --use_default_repos TRUE if you prefer official hosts.
#   - msigdbr is pinned to 7.5.1; Seurat is pinned to 5.2.1 for scRNA.
#   - Upstream tools (iseq, fastp, hisat2, samtools, featureCounts) are not
#     installed by this script; use conda or your OS package manager.
# =============================================================================

options(timeout = max(600, getOption("timeout")))
options(stringsAsFactors = FALSE)

# Infer a sensible Bioconductor version from the running R major.minor.
default_bioc_version <- function() {
  rv <- getRversion()
  if (rv >= "4.5.0") return("3.21")
  if (rv >= "4.4.0") return("3.20")
  if (rv >= "4.3.0") return("3.19")
  "3.18"
}

# ---- CLI (self-contained; does not require cli_utils) ----
parse_args <- function(args) {
  opts <- list(
    type = "all",
    bioc_version = default_bioc_version(),
    check_only = FALSE,
    use_default_repos = FALSE,
    force = FALSE
  )
  i <- 1L
  while (i <= length(args)) {
    tok <- args[[i]]
    if (!startsWith(tok, "--")) {
      i <- i + 1L
      next
    }
    key <- sub("^--", "", tok)
    has_val <- (i < length(args)) && !startsWith(args[[i + 1L]], "--")
    val <- if (has_val) args[[i + 1L]] else TRUE
    if (has_val) i <- i + 2L else i <- i + 1L
    if (is.character(val)) {
      low <- tolower(val)
      if (low %in% c("true", "t", "1", "yes", "y")) val <- TRUE
      else if (low %in% c("false", "f", "0", "no", "n")) val <- FALSE
    }
    opts[[key]] <- val
  }
  opts
}

opts <- parse_args(commandArgs(trailingOnly = TRUE))
type <- tolower(as.character(opts$type))
valid_types <- c("rna", "microarray", "scrna", "all", "upstream")
if (!type %in% valid_types) {
  stop("--type must be one of: ", paste(valid_types, collapse = ", "))
}

message("========== omics-pipeline dependency installer ==========")
message("R version      : ", as.character(getRversion()))
message("type           : ", type)
message("bioc_version   : ", opts$bioc_version)
message("check_only     : ", opts$check_only)
message("force          : ", opts$force)
message("============================================================")

if (type == "upstream") {
  message(
    "Upstream (run_rna_upstream.sh) needs system binaries, not R packages:\n",
    "  iseq, fastp, hisat2, samtools, featureCounts (Subread)\n",
    "Install them via conda/mamba or your OS package manager, then verify with:\n",
    "  command -v iseq fastp hisat2 samtools featureCounts"
  )
  quit(save = "no", status = 0)
}

# ---- Repos / mirrors ----
if (!isTRUE(opts$use_default_repos)) {
  options(repos = c(CRAN = "https://mirrors.tuna.tsinghua.edu.cn/CRAN/"))
  options(BioC_mirror = "https://mirrors.ustc.edu.cn/bioc/")
  message("Using TUNA CRAN + USTC Bioconductor mirrors.")
} else {
  message("Using default CRAN/Bioconductor repos.")
}

# ---- Package sets ----
pkgs_common_cran <- c(
  "remotes", "devtools", "data.table", "tidyverse", "dplyr", "stringr",
  "reshape2", "ggplot2", "pheatmap", "igraph", "rlang", "ggprism",
  "ggthemes", "fs", "glue", "tidyr", "scales", "Matrix"
)

pkgs_rna <- c(
  "BiocManager", "DESeq2", "edgeR", "limma", "clusterProfiler",
  "org.Hs.eg.db", "org.Mm.eg.db", "GSVA", "GSEABase", "enrichplot",
  "DOSE", "pathview", "BiocParallel", "AnnotationDbi",
  "ggstatsplot", "msigdbr"
)

pkgs_microarray <- c(
  "BiocManager", "GEOquery", "limma", "Biobase", "BiocGenerics",
  "AnnotationDbi", "clusterProfiler", "org.Hs.eg.db", "org.Mm.eg.db",
  "GSVA", "GSEABase", "enrichplot", "DOSE", "BiocParallel",
  "msigdbr"
)

pkgs_scrna <- c(
  "BiocManager",
  "DESeq2", "edgeR", "limma", "clusterProfiler",
  "org.Hs.eg.db", "org.Mm.eg.db", "GSVA", "GSEABase", "enrichplot",
  "DOSE", "BiocParallel", "AnnotationDbi", "SingleR", "celldex",
  "muscat", "sctransform", "slingshot", "tradeSeq", "glmGamPoi",
  "SingleCellExperiment", "S4Vectors", "biomaRt",
  "Seurat", "harmony", "HGNChelper", "openxlsx", "hdf5r",
  "patchwork", "cowplot", "plyr", "ggrepel", "ggpubr", "ggsci",
  "clustree", "RColorBrewer", "future", "msigdbr",
  "ggstatsplot", "SeuratWrappers"
)

select_packages <- function(type) {
  base <- pkgs_common_cran
  if (type == "rna") return(unique(c(base, pkgs_rna)))
  if (type == "microarray") return(unique(c(base, pkgs_microarray)))
  if (type == "scrna") return(unique(c(base, pkgs_rna, pkgs_scrna)))
  if (type == "all") return(unique(c(base, pkgs_rna, pkgs_microarray, pkgs_scrna)))
  character()
}

pkg_installed <- function(pkg) {
  requireNamespace(pkg, quietly = TRUE)
}

ensure_biocmanager <- function(bioc_version) {
  if (!pkg_installed("BiocManager")) {
    message("Installing BiocManager ...")
    install.packages("BiocManager")
  }
  tryCatch({
    BiocManager::install(version = as.character(bioc_version), ask = FALSE, update = FALSE)
  }, error = function(e) {
    message("BiocManager version set skipped/failed: ", conditionMessage(e))
  })
}

install_one <- function(pkg, force = FALSE) {
  if (!force && pkg_installed(pkg)) {
    message("[OK] ", pkg)
    return(invisible(TRUE))
  }
  message("[INSTALL] ", pkg)
  ok <- FALSE
  tryCatch({
    BiocManager::install(pkg, ask = FALSE, update = FALSE, dependencies = TRUE)
    ok <- pkg_installed(pkg)
  }, error = function(e) {
    message("  BiocManager::install failed for ", pkg, ": ", conditionMessage(e))
  })
  if (!ok) {
    tryCatch({
      install.packages(pkg, dependencies = TRUE)
      ok <- pkg_installed(pkg)
    }, error = function(e) {
      message("  install.packages failed for ", pkg, ": ", conditionMessage(e))
    })
  }
  if (ok) message("[DONE] ", pkg) else message("[FAIL] ", pkg)
  invisible(ok)
}

pin_msigdbr <- function(force = FALSE) {
  need <- TRUE
  if (pkg_installed("msigdbr") && !force) {
    ver <- as.character(utils::packageVersion("msigdbr"))
    if (ver == "7.5.1") {
      message("[OK] msigdbr ", ver)
      need <- FALSE
    } else {
      message("[INFO] msigdbr ", ver, " found; pinning to 7.5.1")
    }
  }
  if (!need) return(invisible(TRUE))
  if (!pkg_installed("remotes")) install.packages("remotes")
  message("[INSTALL] msigdbr 7.5.1 (pinned)")
  tryCatch({
    remotes::install_version("msigdbr", version = "7.5.1", upgrade = "never")
    message("[DONE] msigdbr ", utils::packageVersion("msigdbr"))
  }, error = function(e) {
    message("[FAIL] msigdbr pin: ", conditionMessage(e))
    message("  Fallback: BiocManager/CRAN latest msigdbr")
    install_one("msigdbr", force = TRUE)
  })
}

pin_seurat <- function(force = FALSE) {
  need <- TRUE
  if (pkg_installed("Seurat") && !force) {
    ver <- as.character(utils::packageVersion("Seurat"))
    if (startsWith(ver, "5.2.")) {
      message("[OK] Seurat ", ver)
      need <- FALSE
    } else {
      message("[INFO] Seurat ", ver, " found; recommending 5.2.1")
    }
  }
  if (!need) return(invisible(TRUE))
  if (!pkg_installed("devtools")) install.packages("devtools")
  message("[INSTALL] Seurat 5.2.1 (pinned)")
  tryCatch({
    remotes::install_version("Seurat", version = "5.2.1", upgrade = "never")
    message("[DONE] Seurat ", utils::packageVersion("Seurat"))
  }, error = function(e) {
    message("[FAIL] Seurat pin: ", conditionMessage(e))
    install_one("Seurat", force = TRUE)
  })
}

install_github_pkgs <- function(force = FALSE) {
  if (!pkg_installed("remotes")) install.packages("remotes")
  gh <- c(
    "immunogenomics/presto",
    "satijalab/seurat-wrappers"
  )
  for (repo in gh) {
    pkg <- sub(".*/", "", repo)
    if (repo == "satijalab/seurat-wrappers") pkg <- "SeuratWrappers"
    if (!force && pkg_installed(pkg)) {
      message("[OK] ", pkg, " (github ", repo, ")")
      next
    }
    message("[INSTALL] github::", repo)
    tryCatch({
      remotes::install_github(repo, upgrade = "never")
      message("[DONE] ", pkg)
    }, error = function(e) {
      message("[FAIL] ", repo, ": ", conditionMessage(e))
    })
  }
}

check_packages <- function(pkgs) {
  miss <- pkgs[!vapply(pkgs, pkg_installed, logical(1))]
  message("Installed: ", length(pkgs) - length(miss), " / ", length(pkgs))
  if (length(miss) > 0) {
    message("Missing:\n  - ", paste(miss, collapse = "\n  - "))
    return(FALSE)
  }
  message("All listed packages are available.")
  TRUE
}

# ---- Main ----
pkgs <- select_packages(type)
pkgs <- setdiff(pkgs, c("msigdbr", "Seurat", "SeuratWrappers"))

if (isTRUE(opts$check_only)) {
  check_set <- unique(c(pkgs, "msigdbr"))
  if (type %in% c("scrna", "all")) {
    check_set <- unique(c(check_set, "Seurat", "SeuratWrappers", "presto"))
  }
  ok <- check_packages(check_set)
  quit(save = "no", status = if (ok) 0 else 1)
}

ensure_biocmanager(opts$bioc_version)
if (!pkg_installed("remotes")) install.packages("remotes")

failed <- character()
for (pkg in pkgs) {
  ok <- install_one(pkg, force = isTRUE(opts$force))
  if (!ok) failed <- c(failed, pkg)
}

pin_msigdbr(force = isTRUE(opts$force))

if (type %in% c("scrna", "all")) {
  pin_seurat(force = isTRUE(opts$force))
  install_github_pkgs(force = isTRUE(opts$force))
}

message("========== Summary ==========")
final_check <- unique(c(pkgs, "msigdbr"))
if (type %in% c("scrna", "all")) {
  final_check <- unique(c(final_check, "Seurat", "SeuratWrappers"))
}
ok <- check_packages(final_check)
if (length(failed) > 0) {
  message("Direct install failures (may still be present via Bioc): ",
          paste(failed, collapse = ", "))
}
if (!ok) {
  message("Some packages are still missing. Re-run with --force TRUE or install manually.")
  quit(save = "no", status = 1)
}
message("Dependency setup finished. You can now run:")
message("  Rscript Script/run_RNA_seq.R ...")
message("  Rscript Script/run_MicroArray.R ...")
message("  Rscript Script/run_scRNA_seq.R ...")
message("================================")
