#!/usr/bin/env Rscript
# =============================================================================
# run_MicroArray.R
# Microarray downstream analysis (limma DEG, enrichment, GSEA, GSVA).
#
# Modes:
#   Prepared input (default) — use meta + expression already under the GSE folder
#   GEO prepare              — --download / --prepare builds inputs from GEO
#
# Required input layout:
#   work_dir/<organism>/<GSE>/   OR   work_dir/<GSE>/
#     samples_info.txt              # Sample, Source, Group [, Group_1]
#     comparisons.txt               # Control, Treatment (or group1, group2)
#     {GSE}.{organism}.ExprMatrix.txt     # first column Symbol; sample columns = Sample IDs
#
# Usage:
#   Rscript Script/run_MicroArray.R --work_dir PATH --organism hsa|mmu \
#     (--gse GSE12345 | --gse_list file.txt) \
#     [--general_file PATH] [--skip_completed TRUE|FALSE] [--strict TRUE|FALSE] \
#     [--download FALSE] [--prepare FALSE] [--force_prepare FALSE]
#
# Examples (from repository root):
#   Rscript Script/run_MicroArray.R \
#     --work_dir Example/MicroArray --organism hsa --gse GSE30304
#
#   # Download from GEO, auto-build meta + expression, then analyze
#   Rscript Script/run_MicroArray.R \
#     --work_dir ./microarray_out --organism hsa --gse GSE30304 \
#     --download TRUE
#
#   # Rebuild expression/meta from an existing GEO cache (no re-download)
#   Rscript Script/run_MicroArray.R \
#     --work_dir ./microarray_out --organism hsa --gse GSE30304 \
#     --prepare TRUE --force_prepare TRUE
#
# Outputs: work_dir/.../<GSE>/{Treatment}_vs_{Control}/
# Batch log: work_dir/batch_MicroArray.log
#
# Dependencies:
#   Rscript Script/install_deps.R --type microarray
# =============================================================================

# Resolve script dir and source CLI helpers
cli_utils_path <- {
  args_all <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args_all, value = TRUE)
  if (length(file_arg) == 1) {
    file.path(dirname(normalizePath(sub("^--file=", "", file_arg), winslash = "/")), "lib", "cli_utils.R")
  } else {
    file.path(getwd(), "lib", "cli_utils.R")
  }
}
if (!file.exists(cli_utils_path)) {
  # Fallback relative to this file layout
  alt <- file.path(dirname(cli_utils_path), "cli_utils.R")
  if (file.exists(alt)) cli_utils_path <- alt
}
if (!file.exists(cli_utils_path)) {
  stop("Missing helper: ", cli_utils_path)
}
source(cli_utils_path, local = FALSE)

SCRIPT_DIR <- get_script_dir()
REPO_ROOT <- normalizePath(file.path(SCRIPT_DIR, ".."), winslash = "/")

cli_defaults <- list(
  work_dir = "",
  organism = "",
  gse = "",
  gse_list = "",
  general_file = "",
  skip_completed = FALSE,
  download = FALSE,
  prepare = FALSE,
  force_prepare = FALSE,
  strict = TRUE,
  fast = FALSE,
  max_gsea_plots = "",
  skip_gsea_plots = FALSE,
  skip_ssgsea = "",
  skip_save_image = "",
  n_workers = 1
)

opts <- parse_cli_args(
  commandArgs(trailingOnly = TRUE),
  defaults = cli_defaults,
  required = c("work_dir", "organism")
)

work_dir <- normalizePath(opts$work_dir, winslash = "/", mustWork = FALSE)
organism <- tolower(as.character(opts$organism))
skip_completed <- isTRUE(opts$skip_completed)
do_download <- isTRUE(opts$download)
do_prepare <- isTRUE(opts$prepare) || do_download
force_prepare <- isTRUE(opts$force_prepare)
strict_mode <- isTRUE(opts$strict)
perf <- resolve_perf_opts(opts)
batch_had_error <- FALSE

if (!organism %in% c("hsa", "mmu")) {
  stop("--organism must be 'hsa' or 'mmu'. Got: ", organism)
}

gse_ids <- read_gse_ids(gse = opts$gse, gse_list = opts$gse_list)

GeneralFile <- resolve_general_file(
  override = if (nzchar(as.character(opts$general_file))) as.character(opts$general_file) else NULL,
  script_dir = SCRIPT_DIR
)
if (!dir.exists(GeneralFile)) {
  stop("GeneralFile directory not found: ", GeneralFile)
}

if (!dir.exists(work_dir)) {
  dir.create(work_dir, recursive = TRUE, showWarnings = FALSE)
}
work_dir <- normalizePath(work_dir, winslash = "/", mustWork = TRUE)

batch_log <- file.path(work_dir, "batch_MicroArray.log")
log_message(batch_log, paste0(
  "Start microarray batch | organism=", organism,
  " | work_dir=", work_dir,
  " | skip_completed=", skip_completed,
  " | download=", do_download,
  " | prepare=", do_prepare,
  " | force_prepare=", force_prepare,
  " | strict=", strict_mode,
  " | fast=", perf$fast,
  " | n_workers=", perf$n_workers,
  " | max_gsea_plots=", perf$max_gsea_plots
))

GEOMods <- new.env()
geomods_path <- file.path(GeneralFile, "GEOMods.R")
if (!file.exists(geomods_path)) {
  stop("GEOMods.R not found: ", geomods_path)
}
source(geomods_path, local = GEOMods)
source(file.path(SCRIPT_DIR, "lib", "microarray_prepare.R"), local = FALSE)

suppressPackageStartupMessages({
  # Prefer explicit packages over tidyverse meta-package to reduce masking.
  library(BiocGenerics)
  library(org.Hs.eg.db)
  library(org.Mm.eg.db)
  library(GEOquery)
  library(limma)
  library(AnnotationDbi)
  library(clusterProfiler)
  library(GSVA)
  library(GSEABase)
  library(ggplot2)
  library(enrichplot)
  library(DOSE)
  library(BiocParallel)
  library(msigdbr)
  library(reshape2)
  library(dplyr)
  library(tidyr)
  library(readr)
  library(tibble)
  library(purrr)
  library(data.table)
  library(fs)
  library(glue)
  library(stringr)
  library(Biobase)
})
suppress_namespace_conflicts()
options(timeout = max(600, getOption("timeout")))
# Prefer dplyr verbs if masked
select <- dplyr::select
filter <- dplyr::filter
mutate <- dplyr::mutate
rename <- dplyr::rename
summarise <- dplyr::summarise
arrange <- dplyr::arrange
group_by <- dplyr::group_by
ungroup <- dplyr::ungroup
left_join <- dplyr::left_join
pull <- dplyr::pull
slice <- dplyr::slice
across <- dplyr::across

if (organism == "hsa") {
  OrgDb <- "org.Hs.eg.db"
  species <- "Homo sapiens"
  species_db <- org.Hs.eg.db
  cellmarker_path <- file.path(GeneralFile, "CellMarker", "cellMarker_Hs.txt")
} else {
  OrgDb <- "org.Mm.eg.db"
  species <- "Mus musculus"
  species_db <- org.Mm.eg.db
  cellmarker_path <- file.path(GeneralFile, "CellMarker", "cellMarker_Mm.txt")
}

if (!file.exists(cellmarker_path)) {
  stop("CellMarker file not found: ", cellmarker_path)
}
cellmarker <- data.table::fread(cellmarker_path)

KEGG_df_all <- msigdbr(species = species, category = "C2", subcategory = "CP:KEGG")
KEGG_df <- dplyr::select(KEGG_df_all, gs_name, gs_exact_source, gene_symbol)
kegg_list <- split(KEGG_df$gene_symbol, KEGG_df$gs_name)

GO_df_all <- msigdbr(species = species, category = "C5")
GO_df <- dplyr::select(GO_df_all, gs_name, gene_symbol, gs_exact_source, gs_subcat)
GO_df <- GO_df[GO_df$gs_subcat != "HPO", ]
go_list <- split(GO_df$gene_symbol, GO_df$gs_name)
gsva_term_id_map <- build_gsva_term_id_map(GO_df, KEGG_df)
kegg_index <- resolve_kegg_pathway_index(organism, GeneralFile = GeneralFile)
kegg_id2name <- load_kegg_id2name(kegg_index)
if (!length(kegg_id2name)) {
  log_message(
    batch_log,
    paste0(
      "KEGG pathway name index missing for organism=", organism,
      "; GSVA term_name for KEGG will use stripped MSigDB names"
    )
  )
}
gsva_term_name_map <- build_gsva_term_name_map(gsva_term_id_map, kegg_id2name)

ssGSEA_list <- NULL
ssgsea_rds <- file.path(GeneralFile, "ssGSEA", "ssGSEA_Hs.rds")
if (organism == "hsa" && file.exists(ssgsea_rds)) {
  ssGSEA_list <- readRDS(ssgsea_rds)
  log_message(batch_log, paste0("Loaded ssGSEA gene sets: ", ssgsea_rds))
} else if (organism == "hsa") {
  log_message(batch_log, paste0("ssGSEA skipped (RDS missing): ", ssgsea_rds))
} else {
  log_message(batch_log, "ssGSEA skipped (organism != hsa)")
}

# ---- helpers -----------------------------------------------------------------

normalize_group_name <- function(x) {
  vapply(as.character(x), function(v) {
    if (is.na(v) || !nzchar(v)) return(NA_character_)
    GEOMods$replace_chars(v)
  }, character(1), USE.NAMES = FALSE)
}

normalize_comparisons_ma <- function(comp_df) {
  # Case-insensitive header remap, then Control/Treatment + group1/group2 aliases
  cn <- colnames(comp_df)
  cn_low <- tolower(cn)
  for (i in seq_along(cn)) {
    if (cn_low[i] %in% c("group1", "control")) colnames(comp_df)[i] <- "Control"
    if (cn_low[i] %in% c("group2", "treatment")) colnames(comp_df)[i] <- "Treatment"
    if (cn_low[i] == "source") colnames(comp_df)[i] <- "source"
  }
  comp_df <- comp_df[, !duplicated(colnames(comp_df)), drop = FALSE]
  comp_df <- normalize_comparisons(comp_df)  # from cli_utils.R

  # Clean labels via GEOMods$replace_chars for matching samples_info
  comp_df$Control <- normalize_group_name(comp_df$Control)
  comp_df$Treatment <- normalize_group_name(comp_df$Treatment)
  comp_df$group1 <- comp_df$Control
  comp_df$group2 <- comp_df$Treatment
  comp_df
}

expr_file_path <- function(gse_dir, gse, organism) {
  file.path(gse_dir, paste(gse, organism, "ExprMatrix.txt", sep = "."))
}

find_expr_file <- function(gse_dir, gse, organism) {
  # Canonical: {GSE}.{organism}.ExprMatrix.txt; then older aliases
  candidates <- c(
    expr_file_path(gse_dir, gse, organism),
    file.path(gse_dir, paste(gse, organism, "expr.txt", sep = ".")),
    file.path(gse_dir, paste(gse, organism, "counts.txt", sep = ".")),
    file.path(gse_dir, "ExprMatrix.txt"),
    file.path(gse_dir, "expr.txt"),
    file.path(gse_dir, "counts.txt"),
    file.path(gse_dir, paste0(gse, ".ExprMatrix.txt")),
    file.path(gse_dir, paste0(gse, ".expr.txt")),
    file.path(gse_dir, paste0(gse, ".counts.txt"))
  )
  hit <- candidates[file.exists(candidates)]
  if (length(hit) == 0) {
    extra <- list.files(
      gse_dir,
      pattern = "\\.(ExprMatrix|expr|counts)\\.txt$",
      full.names = TRUE, ignore.case = TRUE
    )
    hit <- extra
  }
  if (length(hit) == 0) {
    stop(
      "No expression matrix found in ", gse_dir,
      " (expected {GSE}.{organism}.ExprMatrix.txt). ",
      "Use --download TRUE or --prepare TRUE to build it from GEO."
    )
  }
  hit[[1]]
}

load_prepared_expr <- function(expr_path) {
  exprs <- data.table::fread(expr_path, data.table = FALSE)
  first <- colnames(exprs)[1]
  if (!tolower(first) %in% c("symbol", "gene", "genesymbol", "gene_symbol", "id")) {
    message("First column '", first, "' treated as Symbol/Gene.")
  }
  colnames(exprs)[1] <- "Symbol"
  exprs <- exprs[!is.na(exprs$Symbol) & nzchar(as.character(exprs$Symbol)), , drop = FALSE]
  if (any(duplicated(exprs$Symbol))) {
    message("Aggregating duplicated symbols in expression matrix by mean.")
    num_cols <- setdiff(colnames(exprs), "Symbol")
    exprs <- exprs %>%
      dplyr::group_by(Symbol) %>%
      dplyr::summarise(
        dplyr::across(dplyr::all_of(num_cols), ~ mean(as.numeric(.), na.rm = TRUE)),
        .groups = "drop"
      ) %>%
      as.data.frame()
  }
  exprs
}

load_samples_info <- function(path) {
  si <- data.table::fread(path, data.table = FALSE)
  si <- normalize_samples_info(si)  # from cli_utils.R
  si$Sample <- as.character(si$Sample)
  si$Group <- as.character(si$Group)
  si$Group_norm <- normalize_group_name(si$Group)
  si
}

need_prepare_files <- function(gse_dir, gse, organism) {
  !file.exists(expr_file_path(gse_dir, gse, organism)) ||
    !file.exists(file.path(gse_dir, "samples_info.txt")) ||
    !file.exists(file.path(gse_dir, "comparisons.txt"))
}

comparison_is_complete <- function(out_dir, compare_name) {
  analysis_is_complete(out_dir)
}

#' Run limma DEG + enrichment + GSEA + GSVA (+ optional ssGSEA) for one comparison.
run_one_comparison <- function(i, comparisons, samples_info, exprs_mat, gse, gse_dir) {
  group1 <- comparisons$group1[[i]]   # Control
  group2 <- comparisons$group2[[i]]   # Treatment
  compareName <- paste0(group2, "_vs_", group1)
  out_dir <- file.path(gse_dir, compareName)
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

  if (skip_completed && comparison_is_complete(out_dir, compareName)) {
    log_message(batch_log, paste0("[SKIP] ", gse, " / ", compareName, " (already complete)"))
    return(invisible(TRUE))
  }
  clear_analysis_success(out_dir)

  log_message(batch_log, paste0("[RUN] ", gse, " / ", compareName))

  group_col_norm <- "Group_norm"
  if ("source" %in% colnames(comparisons)) {
    src <- comparisons$source[[i]]
    if (!is.na(src) && nzchar(as.character(src)) && src %in% colnames(samples_info)) {
      samples_info[[paste0(src, "_norm")]] <- normalize_group_name(samples_info[[src]])
      group_col_norm <- paste0(src, "_norm")
    }
  }

  meta_cur <- samples_info[samples_info[[group_col_norm]] %in% c(group1, group2), , drop = FALSE]
  if (nrow(meta_cur) < 2) {
    stop("Fewer than 2 samples for comparison ", compareName,
         " (Control=", group1, ", Treatment=", group2, ")")
  }
  meta_cur$Group <- factor(meta_cur[[group_col_norm]], levels = c(group1, group2))

  sample_ids <- meta_cur$Sample
  missing_cols <- setdiff(sample_ids, colnames(exprs_mat))
  if (length(missing_cols) > 0) {
    stop("Sample columns missing from expression matrix: ", paste(missing_cols, collapse = ", "))
  }

  geo.data.current.symbol <- exprs_mat %>%
    dplyr::select(Symbol, dplyr::all_of(sample_ids)) %>%
    dplyr::filter(rowSums(dplyr::select(., -Symbol), na.rm = TRUE) != 0)
  geo.data.current <- as.data.frame(geo.data.current.symbol[, -1, drop = FALSE])
  rownames(geo.data.current) <- geo.data.current.symbol$Symbol

  qx <- as.numeric(quantile(as.matrix(geo.data.current),
                            c(0., 0.25, 0.5, 0.75, 0.99, 1.0), na.rm = TRUE))
  LogC <- (qx[5] > 100) || (qx[6] - qx[1] > 50 && qx[2] > 0)
  if (LogC) {
    geo.data.current[geo.data.current <= 0] <- NaN
    geo.data.current <- log2(geo.data.current)
  }
  fwrite_if_nonempty(geo.data.current, file.path(out_dir, "counts.csv"), sep = ",")

  z_scores <- t(scale(t(as.matrix(geo.data.current))))

  group.list <- factor(meta_cur$Group, levels = c(group1, group2))
  design <- model.matrix(~ 0 + group.list)
  rownames(design) <- colnames(geo.data.current)
  colnames(design) <- levels(group.list)

  # limma DEG
  fit <- limma::lmFit(geo.data.current, design)
  contrast <- limma::makeContrasts(
    contrasts = paste0(group2, "-", group1),
    levels = design
  )
  fit2 <- limma::contrasts.fit(fit, contrast)
  fit2 <- tryCatch(limma::eBayes(fit2), error = function(e) {
    message("[INFO] eBayes failed: ", e$message)
    NULL
  })
  if (is.null(fit2)) {
    stop("eBayes failed for ", compareName)
  }

  tempDEG <- limma::topTable(fit2, coef = paste0(group2, "-", group1), number = Inf)
  DEG <- na.omit(tempDEG)
  DEG <- DEG[, c(6, 1, 2, 3, 4, 5)]
  colnames(DEG) <- c("B", "log2FoldChange", "AveExpr", "t", "pvalue", "padj")

  DEG$regulation <- ifelse(
    DEG$log2FoldChange > 1 & DEG$pvalue < 0.05, "up",
    ifelse(DEG$log2FoldChange < -1 & DEG$pvalue < 0.05, "down", "stable")
  )
  message(glue::glue("In {compareName}, DEG frequency:"))
  print(table(DEG$regulation))

  DEG$data <- gse
  DEG$group <- compareName
  DEG$SYMBOL <- rownames(DEG)
  DEG <- DEG[, c("data", "group", "SYMBOL", "B", "log2FoldChange",
                 "AveExpr", "t", "pvalue", "padj", "regulation")]

  DEG <- cbind(DEG, z_scores[rownames(DEG), , drop = FALSE])
  geo.data.current.ave <- geo.data.current[rownames(DEG), , drop = FALSE]

  info_Control <- subset(meta_cur, Group == group1)
  info_Treatment <- subset(meta_cur, Group == group2)

  if (nrow(info_Control) >= 2) {
    AveExpr_Control <- rowMeans(geo.data.current.ave[, info_Control$Sample, drop = FALSE])
  } else {
    AveExpr_Control <- geo.data.current.ave[, info_Control$Sample]
  }
  if (nrow(info_Treatment) >= 2) {
    AveExpr_Case <- rowMeans(geo.data.current.ave[, info_Treatment$Sample, drop = FALSE])
  } else {
    AveExpr_Case <- geo.data.current.ave[, info_Treatment$Sample]
  }

  DEG <- cbind(
    DEG[, 1:3, drop = FALSE],
    AveExpr_Control = AveExpr_Control,
    AveExpr_Case = AveExpr_Case,
    DEG[, 4:ncol(DEG), drop = FALSE]
  )

  fwrite_if_nonempty(DEG, file.path(out_dir, "DEG_all.csv"), sep = ",")
  DEG_significant <- subset(DEG, regulation != "stable")
  fwrite_if_nonempty(DEG_significant, file.path(out_dir, "DEG_significant.csv"), sep = ",")

  gene_select_up <- DEG_significant$SYMBOL[DEG_significant$regulation == "up"]
  gene_select_down <- DEG_significant$SYMBOL[DEG_significant$regulation == "down"]

  # CellMarker
  cellmarker_df <- as.data.frame(cellmarker)
  term2gene_cm <- unique(cellmarker_df[, c("CellType", "geneSymbol")])
  term2name_cm <- unique(cellmarker_df[, c("CellType", "Source")])
  cellmarker_rich_fn <- function(gene_select, regulation, fileName) {
    enrich_obj <- tryCatch({
      clusterProfiler::enricher(
        gene = gene_select,
        TERM2GENE = term2gene_cm,
        TERM2NAME = term2name_cm,
        pvalueCutoff = 0.05,
        pAdjustMethod = "BH",
        qvalueCutoff = 0.2,
        maxGSSize = 500
      )
    }, error = function(e) {
      message("CellMarker enrichment failed: ", e$message)
      NULL
    })
    if (is.null(enrich_obj)) return(data.frame())
    result <- enrich_obj@result
    if (nrow(result) == 0) return(data.frame())
    result$data <- gse
    result$group <- compareName
    result$Regulation <- regulation
    result <- result[, c("data", "group", "ID", "Description", "Regulation",
                         "GeneRatio", "BgRatio", "pvalue", "p.adjust",
                         "qvalue", "geneID", "Count")]
    colnames(result) <- c("data", "group", "CellType", "Source", "Regulation",
                          "GeneRatio", "BgRatio", "P-value", "Adjusted P-value",
                          "qvalue", "MarkerGene", "count")
    fwrite_if_nonempty(result, file.path(out_dir, fileName), sep = ",")
    result
  }

  cellmarker_rich_up <- data.frame()
  cellmarker_rich_down <- data.frame()
  if (length(gene_select_up) > 0) {
    cellmarker_rich_up <- cellmarker_rich_fn(gene_select_up, "up", "CellMarker_rich_up.csv")
  }
  if (length(gene_select_down) > 0) {
    cellmarker_rich_down <- cellmarker_rich_fn(gene_select_down, "down", "CellMarker_rich_down.csv")
  }
  cellmarker_rich <- rbind(cellmarker_rich_up, cellmarker_rich_down)
  if (nrow(cellmarker_rich) > 0) {
    cellmarker_rich <- cellmarker_rich[order(cellmarker_rich[["P-value"]]), ]
  }
  fwrite_if_nonempty(cellmarker_rich, file.path(out_dir, "CellMarker_rich.csv"), sep = ",")

  # GO / KEGG enrichment
  deg_rich_save <- function(df, filename) {
    if (!is_nonempty_df(df)) {
      message(filename, " No significant terms found. Skipping.")
      return(invisible(FALSE))
    }
    df$data <- gse
    df$group <- compareName
    fwrite_if_nonempty(df, file.path(out_dir, filename), sep = ",")
  }

  KEGG_enrich_Func <- function(gene, filename) {
    kegg_enrich_results <- enrichKEGG(
      gene = gene, organism = organism,
      pvalueCutoff = 0.05, qvalueCutoff = 0.2
    )
    if (is.null(kegg_enrich_results)) {
      message("No significant KEGG pathways found.")
      return(NULL)
    }
    kegg_enrich_results <- DOSE::setReadable(kegg_enrich_results, OrgDb = OrgDb, keyType = "ENTREZID")
    kegg_enrich <- kegg_enrich_results@result %>%
      dplyr::filter(qvalue < 0.2, p.adjust < 0.05)
    deg_rich_save(kegg_enrich, filename)
    kegg_enrich_results
  }

  GO_enrich_Func <- function(gene, filename) {
    go_enrich_results <- enrichGO(
      gene = gene, OrgDb = OrgDb, ont = "ALL",
      pvalueCutoff = 0.05, qvalueCutoff = 0.2, readable = TRUE
    )
    if (is.null(go_enrich_results)) {
      message("No significant GO terms found.")
      return(NULL)
    }
    go_enrich <- go_enrich_results@result %>%
      dplyr::filter(qvalue < 0.2, p.adjust < 0.05)
    deg_rich_save(go_enrich, filename)
    go_enrich_results
  }

  networkDiagram_Func <- function(diff_enrich_results, pathway2gene_filename, pathway2pathway_filename) {
    if (is.null(diff_enrich_results) || nrow(diff_enrich_results) <= 1) return(invisible(NULL))
    gene_pathway <- diff_enrich_results@result[, c("Description", "geneID")]
    gene_pathway_long <- do.call(rbind, lapply(seq_len(nrow(gene_pathway)), function(j) {
      data.frame(
        Pathway = gene_pathway$Description[j],
        Gene = unlist(strsplit(gene_pathway$geneID[j], "/")),
        stringsAsFactors = FALSE
      )
    }))
    fwrite_if_nonempty(gene_pathway_long,
                       file = file.path(out_dir, paste0(pathway2gene_filename, ".csv")), sep = ",")

    pathway2 <- enrichplot::pairwise_termsim(diff_enrich_results)
    similarity_matrix <- as.data.frame(pathway2@termsim)
    similarity_matrix$Term1 <- rownames(similarity_matrix)
    long_sim <- reshape2::melt(similarity_matrix, id.vars = "Term1",
                               variable.name = "Term2", value.name = "similarity")
    long_sim <- long_sim[long_sim$similarity > 0, ]
    long_sim <- merge(long_sim, diff_enrich_results@result[, c("Description", "p.adjust", "Count")],
                      by.x = "Term1", by.y = "Description", all.x = TRUE)
    fwrite_if_nonempty(long_sim,
                       file = file.path(out_dir, paste0(pathway2pathway_filename, ".csv")), sep = ",")
  }

  orgdb_obj <- get(OrgDb)
  valid_up <- gene_select_up[gene_select_up %in% AnnotationDbi::keys(orgdb_obj, keytype = "SYMBOL")]
  valid_down <- gene_select_down[gene_select_down %in% AnnotationDbi::keys(orgdb_obj, keytype = "SYMBOL")]

  gene_up_entrez <- character(0)
  gene_down_entrez <- character(0)
  if (length(valid_up) > 0) {
    gene_up_entrez <- as.character(na.omit(bitr(valid_up, fromType = "SYMBOL",
                                                toType = "ENTREZID", OrgDb = OrgDb)[, 2]))
  }
  if (length(valid_down) > 0) {
    gene_down_entrez <- as.character(na.omit(bitr(valid_down, fromType = "SYMBOL",
                                                  toType = "ENTREZID", OrgDb = OrgDb)[, 2]))
  }
  gene_diff_entrez <- unique(c(gene_up_entrez, gene_down_entrez))

  if (length(gene_up_entrez) > 0) {
    GO_enrich_Func(gene_up_entrez, "GO_enrich_up.csv")
    KEGG_enrich_Func(gene_up_entrez, "KEGG_enrich_up.csv")
  }
  if (length(gene_down_entrez) > 0) {
    KEGG_enrich_Func(gene_down_entrez, "KEGG_enrich_down.csv")
    GO_enrich_Func(gene_down_entrez, "GO_enrich_down.csv")
  }
  if (length(gene_diff_entrez) > 0) {
    go_diff_enrich_results <- GO_enrich_Func(gene_diff_entrez, "GO_enrich_AllDiff.csv")
    networkDiagram_Func(go_diff_enrich_results, "GO_Gene_NetworkDiagram", "GO_GO_NetworkDiagram")
    kegg_diff_enrich_results <- KEGG_enrich_Func(gene_diff_entrez, "KEGG_enrich_AllDiff.csv")
    networkDiagram_Func(kegg_diff_enrich_results, "KEGG_Gene_NetworkDiagram", "KEGG_KEGG_NetworkDiagram")
  }

  # GSEA
  GSEA_plot <- function(kk_gse, kk_gse_cut) {
    kk_gse_cut <- cap_gsea_terms(kk_gse_cut, perf$max_gsea_plots)
    if (is.null(kk_gse_cut) || nrow(kk_gse_cut) == 0) return(invisible(NULL))
    message("GSEA plots: ", nrow(kk_gse_cut))
    for (ii in seq_along(kk_gse_cut$ID)) {
      gseap1 <- enrichplot::gseaplot2(
        kk_gse, kk_gse_cut$ID[ii],
        title = kk_gse_cut$Description[ii],
        color = "red", base_size = 20,
        rel_heights = c(1.5, 0.5, 1),
        subplots = 1:3, ES_geom = "line", pvalue_table = TRUE
      )
      filename <- paste0(gsub("[:\\\\/]", "_", kk_gse_cut$ID[ii]), ".jpg")
      ggplot2::ggsave(filename = file.path(out_dir, filename), plot = gseap1,
                      width = 10, height = 8)
    }
  }

  GSEA_analysis <- function(need_DEG) {
    colnames(need_DEG) <- c("log2FoldChange", "SYMBOL")
    df <- tryCatch(
      bitr(need_DEG$SYMBOL, fromType = "SYMBOL", toType = "ENTREZID", OrgDb = OrgDb),
      error = function(e) {
        message("GSEA bitr failed: ", e$message)
        NULL
      }
    )
    if (is.null(df) || nrow(df) == 0) return(invisible(NULL))

    need_DEG <- merge(need_DEG, df, by = "SYMBOL")
    need_DEG_avg <- need_DEG %>%
      dplyr::group_by(ENTREZID) %>%
      dplyr::summarise(log2FoldChange = median(log2FoldChange, na.rm = TRUE), .groups = "drop")

    geneList <- need_DEG_avg$log2FoldChange
    names(geneList) <- need_DEG_avg$ENTREZID
    geneList <- sort(geneList, decreasing = TRUE)

    KEGG_kk_entrez <- tryCatch(
      gseKEGG(geneList = geneList, organism = organism,
              pvalueCutoff = 0.05, pAdjustMethod = "BH"),
      error = function(e) {
        message("gseKEGG failed: ", e$message)
        NULL
      }
    )
    if (!is.null(KEGG_kk_entrez) && nrow(KEGG_kk_entrez@result) > 0) {
      KEGG_kk <- DOSE::setReadable(KEGG_kk_entrez, OrgDb = OrgDb, keyType = "ENTREZID")
      KEGG_kk_cut <- KEGG_kk[KEGG_kk$pvalue < 0.05 & KEGG_kk$p.adjust < 0.25 & abs(KEGG_kk$NES) > 1]
      gsea_kegg <- as.data.frame(KEGG_kk_cut)
      gsea_kegg$data <- gse
      gsea_kegg$group <- compareName
      fwrite_if_nonempty(gsea_kegg, file.path(out_dir, "GSEA_KEGG.csv"), sep = ",")
      GSEA_plot(KEGG_kk, KEGG_kk_cut)
    } else {
      message("No enriched KEGG GSEA terms found.")
    }

    GO_kk_entrez <- tryCatch(
      gseGO(geneList = geneList, ont = "ALL", OrgDb = OrgDb, keyType = "ENTREZID",
            pvalueCutoff = 0.05, pAdjustMethod = "BH"),
      error = function(e) {
        message("gseGO failed: ", e$message)
        NULL
      }
    )
    if (!is.null(GO_kk_entrez) && nrow(GO_kk_entrez@result) > 0) {
      GO_kk <- DOSE::setReadable(GO_kk_entrez, OrgDb = OrgDb, keyType = "ENTREZID")
      GO_kk_cut <- GO_kk[GO_kk$pvalue < 0.05 & GO_kk$p.adjust < 0.25 & abs(GO_kk$NES) > 1]
      gsea_go <- as.data.frame(GO_kk_cut)
      gsea_go$data <- gse
      gsea_go$group <- compareName
      fwrite_if_nonempty(gsea_go, file.path(out_dir, "GSEA_GO.csv"), sep = ",")
      GSEA_plot(GO_kk, GO_kk_cut)
    } else {
      message("No enriched GO GSEA terms found.")
    }
  }

  need_DEG <- DEG[, c("log2FoldChange", "SYMBOL")]
  GSEA_analysis(need_DEG)

  # GSVA
  GSVA_ana <- function(dat, geneset) {
    gsvaPar <- GSVA::gsvaParam(dat, geneset, kcdf = "Gaussian", minSize = 5, maxSize = 500)
    GSVA::gsva(gsvaPar, verbose = FALSE)
  }

  deg_limma_gsva <- function(es_max, design_m, contrast_matrix, group_list_f) {
    fit_g <- limma::lmFit(es_max, design_m)
    fit2_g <- limma::contrasts.fit(fit_g, contrast_matrix)
    fit2_g <- limma::eBayes(fit2_g)
    tempOutput <- limma::topTable(fit2_g, coef = 1, n = Inf)
    nrDEG <- na.omit(tempOutput)

    if (nrow(info_Control) >= 2) {
      nrDEG$AveExpr_Control <- rowMeans(es_max[, group_list_f == group1, drop = FALSE])[rownames(nrDEG)]
    } else {
      nrDEG$AveExpr_Control <- es_max[, group_list_f == group1][rownames(nrDEG)]
    }
    if (nrow(info_Treatment) >= 2) {
      nrDEG$AveExpr_Case <- rowMeans(es_max[, group_list_f == group2, drop = FALSE])[rownames(nrDEG)]
    } else {
      nrDEG$AveExpr_Case <- es_max[, group_list_f == group2][rownames(nrDEG)]
    }
    nrDEG
  }

  data_GSVA <- data.frame(geo.data.current)
  group_list_gsva <- factor(meta_cur$Group, levels = c(group1, group2))
  design_gsva <- model.matrix(~ 0 + group_list_gsva)
  rownames(design_gsva) <- colnames(data_GSVA)
  colnames(design_gsva) <- levels(group_list_gsva)
  contrast_matrix <- limma::makeContrasts(
    contrasts = paste0(group2, "-", group1),
    levels = design_gsva
  )
  dat <- as.matrix(data_GSVA)

  es_max_GO <- GSVA_ana(dat, go_list)
  es_max_KEGG <- GSVA_ana(dat, kegg_list)
  es_max <- rbind(es_max_GO, es_max_KEGG)

  nrDEG_GO <- deg_limma_gsva(es_max_GO, design_gsva, contrast_matrix, group_list_gsva)
  nrDEG_KEGG <- deg_limma_gsva(es_max_KEGG, design_gsva, contrast_matrix, group_list_gsva)
  nrDEG <- rbind(nrDEG_GO, nrDEG_KEGG)
  nrDEG$data <- gse
  nrDEG$group <- compareName
  nrDEG <- nrDEG[, c("data", "group", "AveExpr_Control", "AveExpr_Case",
                     "logFC", "AveExpr", "t", "P.Value", "adj.P.Val", "B")]
  nrDEG$Regulation <- base::as.factor(ifelse(
    nrDEG$P.Value < 0.05,
    ifelse(nrDEG$logFC > 0, "UP", "DOWN"), "Stable"
  ))

  nrDEG_with_rownames <- nrDEG %>% tibble::rownames_to_column(var = "term")
  z_score_es_max <- t(scale(t(es_max)))
  es_max_with_rownames <- as.data.frame(z_score_es_max) %>%
    tibble::rownames_to_column(var = "term")
  nrDEG_all <- merge(nrDEG_with_rownames, es_max_with_rownames, by = "term")
  nrDEG_all <- annotate_gsva_term_meta(nrDEG_all, gsva_term_id_map, gsva_term_name_map)
  rownames(nrDEG_all) <- nrDEG_all$term

  nrDEG_significant <- nrDEG_all[nrDEG_all$P.Value < 0.05, , drop = FALSE]
  nrDEG_significant <- nrDEG_significant[order(nrDEG_significant$P.Value), ]
  nrDEG_go_all <- nrDEG_all %>% dplyr::filter(grepl("^GO", term))
  nrDEG_kegg_all <- nrDEG_all %>% dplyr::filter(grepl("^KEGG", term))

  fwrite_if_nonempty(nrDEG_all, file.path(out_dir, "GSVA_DEG_all.csv"), sep = ",")
  fwrite_if_nonempty(nrDEG_go_all, file.path(out_dir, "GSVA_DEG_GO.csv"), sep = ",")
  fwrite_if_nonempty(nrDEG_kegg_all, file.path(out_dir, "GSVA_DEG_KEGG.csv"), sep = ",")
  fwrite_if_nonempty(nrDEG_significant, file.path(out_dir, "GSVA_DEG_significant.csv"), sep = ",")

  # ssGSEA only if hsa AND rds loaded
  nrDEG_ssGSEA_all <- NULL
  if (organism == "hsa" && !is.null(ssGSEA_list) && !isTRUE(perf$skip_ssgsea)) {
    gsvaPar <- GSVA::ssgseaParam(exprData = dat, geneSets = ssGSEA_list)
    ssGSEA_matrix <- GSVA::gsva(gsvaPar, verbose = FALSE)

    nrDEG_ssGSEA <- deg_limma_gsva(ssGSEA_matrix, design_gsva, contrast_matrix, group_list_gsva)
    nrDEG_ssGSEA$data <- gse
    nrDEG_ssGSEA$group <- compareName
    nrDEG_ssGSEA <- nrDEG_ssGSEA[, c("data", "group", "AveExpr_Control", "AveExpr_Case",
                                     "logFC", "AveExpr", "t", "P.Value", "adj.P.Val", "B")]
    nrDEG_ssGSEA$Regulation <- base::as.factor(ifelse(
      nrDEG_ssGSEA$P.Value < 0.05,
      ifelse(nrDEG_ssGSEA$logFC > 0, "UP", "DOWN"), "Stable"
    ))

    nrDEG_ssGSEA_with_rownames <- nrDEG_ssGSEA %>% tibble::rownames_to_column(var = "term")
    z_score_ss <- t(scale(t(ssGSEA_matrix)))
    es_ss_with_rownames <- as.data.frame(z_score_ss) %>%
      tibble::rownames_to_column(var = "term")
    nrDEG_ssGSEA_all <- merge(nrDEG_ssGSEA_with_rownames, es_ss_with_rownames, by = "term")
    rownames(nrDEG_ssGSEA_all) <- nrDEG_ssGSEA_all$term
    fwrite_if_nonempty(nrDEG_ssGSEA_all, file.path(out_dir, "ssGSEA_DEG_all.csv"), sep = ",")
  }

  if (!isTRUE(perf$skip_save_image)) {
    save(
      list = c(
        "DEG", "DEG_significant", "compareName", "group1", "group2",
        "geo.data.current", "meta_cur", "design",
        "nrDEG_all", "nrDEG_significant", "nrDEG_go_all", "nrDEG_kegg_all",
        "nrDEG_ssGSEA_all", "gse", "organism"
      ),
      file = file.path(out_dir, paste0(compareName, ".RData"))
    )
  } else {
    # Lightweight marker so --skip_completed still works
    save(list = c("compareName", "gse", "organism"),
         file = file.path(out_dir, paste0(compareName, ".RData")))
    message("skip_save_image=TRUE; wrote lightweight .RData image")
  }

  write_analysis_success(out_dir, "microarray", compareName)
  log_message(batch_log, paste0("[DONE] ", gse, " / ", compareName))
  invisible(TRUE)
}

process_one_gse <- function(gse) {
  gse <- trimws(gse)
  if (!nzchar(gse)) return(invisible(NULL))

  # Prefer organism/GSE; create when preparing from GEO
  gse_dir <- resolve_gse_dir(work_dir, organism, gse, create = do_prepare || force_prepare)
  log_message(batch_log, paste0("==== GSE ", gse, " | dir=", gse_dir, " ===="))

  if (do_prepare || force_prepare || need_prepare_files(gse_dir, gse, organism)) {
    if (!(do_prepare || force_prepare || do_download) && need_prepare_files(gse_dir, gse, organism)) {
      # Expression/meta missing and prepare not requested: try alternate file names first
      has_legacy_expr <- length(list.files(
        gse_dir, pattern = "\\.(ExprMatrix|expr|counts)\\.txt$", ignore.case = TRUE
      )) > 0
      has_meta <- file.exists(file.path(gse_dir, "samples_info.txt")) &&
        file.exists(file.path(gse_dir, "comparisons.txt"))
      if (!(has_legacy_expr && has_meta)) {
        stop(
          "Missing prepared inputs for ", gse,
          ". Provide {GSE}.{organism}.ExprMatrix.txt + samples_info.txt + comparisons.txt, ",
          "or run with --download TRUE / --prepare TRUE."
        )
      }
    } else {
      log_fun <- function(msg) log_message(batch_log, msg)
      prepare_microarray_gse(
        gse = gse,
        organism = organism,
        work_dir = work_dir,
        GeneralFile = GeneralFile,
        GEOMods = GEOMods,
        species_db = species_db,
        download = do_download || !dir.exists(file.path(work_dir, "Data", organism, gse)),
        force = force_prepare,
        log_fun = log_fun
      )
      gse_dir <- file.path(work_dir, organism, gse)
    }
  }

  samples_path <- file.path(gse_dir, "samples_info.txt")
  comps_path <- file.path(gse_dir, "comparisons.txt")
  if (!file.exists(samples_path)) {
    stop("Required samples_info.txt missing: ", samples_path)
  }
  if (!file.exists(comps_path)) {
    stop("Required comparisons.txt missing: ", comps_path)
  }

  samples_info <- load_samples_info(samples_path)
  if (!"Group_1" %in% colnames(samples_info)) {
    samples_info$Group_1 <- samples_info$Group
  }
  comparisons <- data.table::fread(comps_path, data.table = FALSE)
  comparisons <- normalize_comparisons_ma(comparisons)

  expr_path <- find_expr_file(gse_dir, gse, organism)
  # If an older expr/counts filename was used, normalize to ExprMatrix when missing
  canonical <- expr_file_path(gse_dir, gse, organism)
  if (!file.exists(canonical) && normalizePath(expr_path, winslash = "/") !=
      normalizePath(canonical, winslash = "/", mustWork = FALSE)) {
    file.copy(expr_path, canonical, overwrite = FALSE)
    log_message(batch_log, paste0("Normalized expression filename -> ", canonical))
    expr_path <- canonical
  }
  log_message(batch_log, paste0("Using expression matrix: ", expr_path))
  exprs_mat <- load_prepared_expr(expr_path)

  common <- intersect(samples_info$Sample, colnames(exprs_mat))
  if (length(common) < 2) {
    stop("Fewer than 2 overlapping Sample IDs between samples_info and expr for ", gse)
  }
  if (length(common) < nrow(samples_info)) {
    missing <- setdiff(samples_info$Sample, colnames(exprs_mat))
    log_message(batch_log, paste0(
      "Warning: ", length(missing), " samples in samples_info not in expr: ",
      paste(head(missing, 10), collapse = ", ")
    ))
  }

  for (i in seq_len(nrow(comparisons))) {
    tryCatch({
      run_one_comparison(i, comparisons, samples_info, exprs_mat, gse, gse_dir)
    }, error = function(e) {
      batch_had_error <<- TRUE
      log_message(batch_log, paste0(
        "[ERROR] ", gse, " comparison row ", i, " (",
        comparisons$Treatment[[i]], "_vs_", comparisons$Control[[i]], "): ",
        conditionMessage(e)
      ))
    })
  }

  invisible(TRUE)
}

# ---- batch loop --------------------------------------------------------------
log_message(batch_log, paste0("GSE count: ", length(gse_ids), " | ", paste(gse_ids, collapse = ", ")))

if (perf$n_workers > 1L && length(gse_ids) > 1L) {
  shared_args <- c(
    "--work_dir", work_dir,
    "--organism", organism,
    "--general_file", GeneralFile,
    "--skip_completed", as.character(skip_completed),
    "--strict", as.character(strict_mode),
    "--download", as.character(do_download),
    "--prepare", as.character(do_prepare),
    "--force_prepare", as.character(force_prepare),
    "--fast", as.character(perf$fast),
    "--skip_ssgsea", as.character(perf$skip_ssgsea),
    "--skip_save_image", as.character(perf$skip_save_image)
  )
  if (is.finite(perf$max_gsea_plots)) {
    shared_args <- c(shared_args, "--max_gsea_plots", as.character(perf$max_gsea_plots))
  }
  results <- parallel_rscript_gse(
    gse_ids = gse_ids,
    shared_args = shared_args,
    n_workers = perf$n_workers,
    logfile = batch_log
  )
  batch_had_error <- any(!vapply(results, function(r) isTRUE(r$ok), logical(1)))
} else {
  for (gse_id in gse_ids) {
    tryCatch({
      process_one_gse(gse_id)
      log_message(batch_log, paste0("[GSE DONE] ", gse_id))
    }, error = function(e) {
      batch_had_error <<- TRUE
      log_message(batch_log, paste0("[GSE ERROR] ", gse_id, ": ", conditionMessage(e)))
    })
  }
}

log_message(batch_log, "Batch microarray analysis finished.")
if (isTRUE(strict_mode) && isTRUE(batch_had_error)) {
  quit(save = "no", status = 1)
}
