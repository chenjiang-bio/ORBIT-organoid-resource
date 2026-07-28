#!/usr/bin/env Rscript
# =============================================================================
# run_RNA_seq.R
# Bulk RNA-seq downstream analysis (DEG, enrichment, GSEA, GSVA / ssGSEA).
#
# Required input layout (per GSE):
#   work_dir/<organism>/<GSE>/
#     {GSE}.{organism}.ExprMatrix.txt|.tsv   # gene × samples (raw counts preferred)
#     samples_info.txt     # Sample, Source, Group
#     comparisons.txt      # Control, Treatment  (or group1, group2)
#
# Usage (named arguments):
#   Rscript Script/run_RNA_seq.R --work_dir PATH --organism hsa|mmu \
#       (--gse GSE123 | --gse_list file.txt) \
#       [--general_file PATH] [--skip_completed TRUE|FALSE] [--strict TRUE|FALSE]
#
# Usage (positional):
#   Rscript Script/run_RNA_seq.R <work_dir> <organism> <GSE_or_list_file>
#
# Examples (from repository root):
#   Rscript Script/run_RNA_seq.R \
#       --work_dir Example/RNA_seq --organism hsa --gse GSE111082
#
#   Rscript Script/run_RNA_seq.R \
#       --work_dir Example/RNA_seq --organism hsa \
#       --gse_list Example/RNA_seq/hsa/gse_list.txt
#
# Outputs: work_dir/<organism>/<GSE>/{Treatment}_vs_{Control}/
# Batch log: work_dir/batch_RNA_seq.log
#
# --strict TRUE (default): any GSE failure exits with status 1 (CI-friendly).
#
# Dependencies:
#   Rscript Script/install_deps.R --type rna
# =============================================================================

suppressPackageStartupMessages({
  # Resolve helpers relative to this script
  cmd_args_full <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", cmd_args_full, value = TRUE)
  if (length(file_arg) >= 1) {
    .script_dir <- dirname(normalizePath(sub("^--file=", "", file_arg[[1]]), winslash = "/"))
  } else {
    .script_dir <- getwd()
  }
  source(file.path(.script_dir, "lib", "cli_utils.R"), local = FALSE)
})

# -----------------------------------------------------------------------------
# 0. Parse CLI
# -----------------------------------------------------------------------------
.parse_cli <- function() {
  opts <- parse_named_args(
    commandArgs(trailingOnly = TRUE),
    defaults = list(
      work_dir = NULL,
      organism = NULL,
      gse = NULL,
      gse_list = NULL,
      general_file = NULL,
      skip_completed = FALSE,
      strict = TRUE,
      fast = FALSE,
      max_gsea_plots = "",
      skip_gsea_plots = FALSE,
      skip_ssgsea = "",
      skip_save_image = "",
      n_workers = 1
    )
  )
  pos <- opts[[".positionals"]]

  work_dir <- opts$work_dir
  organism <- opts$organism
  gse <- opts$gse
  gse_list <- opts$gse_list
  general_file <- opts$general_file
  skip_completed <- isTRUE(opts$skip_completed)
  strict_mode <- isTRUE(opts$strict)
  perf <- resolve_perf_opts(opts)

  # Positional: work_dir organism gse_or_list_file
  if (is.null(work_dir) && length(pos) >= 1) work_dir <- pos[[1]]
  if (is.null(organism) && length(pos) >= 2) organism <- pos[[2]]
  if (is.null(gse) && is.null(gse_list) && length(pos) >= 3) {
    third <- pos[[3]]
    if (file.exists(third) && !dir.exists(third)) {
      gse_list <- third
    } else {
      gse <- third
    }
  }

  if (is.null(work_dir) || is.null(organism)) {
    stop(
      "Usage: Rscript run_RNA_seq.R --work_dir PATH --organism hsa|mmu ",
      "(--gse GSE123 OR --gse_list file.txt) [--general_file PATH] [--skip_completed TRUE/FALSE] [--strict TRUE/FALSE]\n",
      "   or: Rscript run_RNA_seq.R <work_dir> <organism> <GSE_or_list_file>"
    )
  }

  organism <- tolower(as.character(organism))
  if (!organism %in% c("hsa", "mmu")) {
    stop("Unsupported organism. Use 'hsa' or 'mmu'.")
  }

  work_dir <- normalizePath(work_dir, winslash = "/", mustWork = FALSE)
  if (!dir.exists(work_dir)) {
    stop("work_dir does not exist: ", work_dir)
  }

  GeneralFile <- resolve_general_file(general_file)
  gse_ids <- read_gse_ids(gse = gse, gse_list = gse_list)

  list(
    work_dir = work_dir,
    organism = organism,
    GeneralFile = GeneralFile,
    gse_ids = gse_ids,
    skip_completed = skip_completed,
    strict = strict_mode,
    perf = perf
  )
}

# -----------------------------------------------------------------------------
# 1. Load packages (once)
# -----------------------------------------------------------------------------
load_packages <- function() {
  suppressPackageStartupMessages({
    library(DESeq2)
    library(edgeR)
    library(limma)
    library(clusterProfiler)
    library(data.table)
    library(org.Hs.eg.db)
    library(org.Mm.eg.db)
    library(GSVA)
    library(ggstatsplot)
    library(GSEABase)
    library(ggplot2)
    library(pheatmap)
    library(enrichplot)
    library(DOSE)
    library(pathview)
    library(BiocParallel)
    library(igraph)
    library(msigdbr)
    library(reshape2)
    library(dplyr)
    library(tidyr)
    library(tibble)
    library(ggprism)
    library(ggthemes)
    library(stringr)
  })
  suppress_namespace_conflicts()
  options(timeout = 3000)
  if (!requireNamespace("fs", quietly = TRUE)) {
    warning("Package 'fs' is not installed; some enrichment writers may fail.")
  }
  invisible(TRUE)
}

# -----------------------------------------------------------------------------
# 2. Load common species resources (once per organism)
# -----------------------------------------------------------------------------
#' Convert gene IDs to Ensembl IDs (from MultiGroup 2.1)
convert_to_ensembl <- function(gene_ids, OrgDb, ensembl_prefix, map_columns) {
  is_ensembl <- grepl(ensembl_prefix, gene_ids)
  new_ids <- gene_ids

  if (any(is_ensembl)) {
    new_ids[is_ensembl] <- sub("\\.[0-9]+$", "", gene_ids[is_ensembl])
  }

  to_convert <- gene_ids[!is_ensembl]
  if (length(to_convert) > 0) {
    is_numeric <- grepl("^[0-9]+$", to_convert)

    if (any(is_numeric)) {
      entrez_ids <- to_convert[is_numeric]
      tryCatch({
        mapping <- AnnotationDbi::select(
          get(OrgDb),
          keys = entrez_ids,
          keytype = "ENTREZID",
          columns = map_columns
        )
        mapping <- mapping[!is.na(mapping$ENSEMBL), ]
        new_ids[match(mapping$ENTREZID, gene_ids)] <- mapping$ENSEMBL
      }, error = function(e) {
        warning("ENTREZID conversion failed: ", e$message)
      })
    }

    if (any(!is_numeric)) {
      symbol_ids <- to_convert[!is_numeric]
      valid_symbols <- symbol_ids[symbol_ids != "" & !is.na(symbol_ids)]
      if (length(valid_symbols) > 0) {
        tryCatch({
          mapping <- AnnotationDbi::select(
            get(OrgDb),
            keys = valid_symbols,
            keytype = "SYMBOL",
            columns = map_columns
          )
          mapping <- mapping[!is.na(mapping$ENSEMBL), ]
          new_ids[match(mapping$SYMBOL, gene_ids)] <- mapping$ENSEMBL
        }, error = function(e) {
          warning("SYMBOL conversion failed: ", e$message)
        })
      }
    }
  }
  new_ids
}

load_common_resources <- function(organism, GeneralFile) {
  if (organism == "hsa") {
    OrgDb <- "org.Hs.eg.db"
    species <- "Homo sapiens"
    bcv_value <- 0.4
    map_keytype <- "ENTREZID"
    map_columns <- c("ENSEMBL", "SYMBOL")
    ensembl_prefix <- "^ENSG"
    cellmarker <- read.csv(
      file.path(GeneralFile, "CellMarker/cellMarker_Hs.txt"),
      header = TRUE, sep = "\t", stringsAsFactors = FALSE
    )
    gene_lengths <- read.csv(
      file.path(GeneralFile, "gene_length_Hs.txt"),
      header = TRUE, sep = "\t", stringsAsFactors = FALSE
    )
  } else if (organism == "mmu") {
    OrgDb <- "org.Mm.eg.db"
    species <- "Mus musculus"
    bcv_value <- 0.1
    map_keytype <- "ENTREZID"
    map_columns <- c("ENSEMBL", "SYMBOL")
    ensembl_prefix <- "^ENSMUSG"
    cellmarker <- read.csv(
      file.path(GeneralFile, "CellMarker/cellMarker_Mm.txt"),
      header = TRUE, sep = "\t", stringsAsFactors = FALSE
    )
    gene_lengths <- read.csv(
      file.path(GeneralFile, "gene_length_Mm.txt"),
      header = TRUE, sep = "\t", stringsAsFactors = FALSE
    )
  } else {
    stop("Unsupported organism. Only 'hsa' and 'mmu' are supported.")
  }

  # msigdbr gene sets for GSVA
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
    warning(
      "KEGG pathway name index not found for organism=", organism,
      " (expected GeneralFile/KEGG/kegg_pathway_", organism, ".tsv); ",
      "GSVA term_name for KEGG will fall back to stripped MSigDB names."
    )
  }
  gsva_term_name_map <- build_gsva_term_name_map(gsva_term_id_map, kegg_id2name)

  # ssGSEA (human only); warn and skip if missing
  ssGSEA_list <- NULL
  ssgsea_rds <- file.path(GeneralFile, "ssGSEA", "ssGSEA_Hs.rds")
  if (organism == "hsa") {
    if (file.exists(ssgsea_rds)) {
      ssGSEA_list <- readRDS(ssgsea_rds)
    } else {
      warning(
        "ssGSEA_Hs.rds not found at ", ssgsea_rds,
        " — ssGSEA will be skipped."
      )
    }
  }

  list(
    OrgDb = OrgDb,
    species = species,
    bcv_value = bcv_value,
    map_keytype = map_keytype,
    map_columns = map_columns,
    ensembl_prefix = ensembl_prefix,
    cellmarker = cellmarker,
    gene_lengths = gene_lengths,
    kegg_list = kegg_list,
    go_list = go_list,
    gsva_term_id_map = gsva_term_id_map,
    gsva_term_name_map = gsva_term_name_map,
    ssGSEA_list = ssGSEA_list
  )
}

# -----------------------------------------------------------------------------
# skip_completed helpers
# -----------------------------------------------------------------------------
comparison_is_complete <- function(out_dir, compare_name) {
  analysis_is_complete(out_dir)
}

is_gse_completed <- function(gse_dir, comparisons) {
  if (nrow(comparisons) == 0) return(FALSE)
  for (i in seq_len(nrow(comparisons))) {
    compareName <- paste0(comparisons$Treatment[i], "_vs_", comparisons$Control[i])
    out_dir <- file.path(gse_dir, compareName)
    if (!comparison_is_complete(out_dir, compareName)) return(FALSE)
  }
  TRUE
}

# -----------------------------------------------------------------------------
# 3. Per-GSE analysis (MultiGroup sections 2.2-4)
# -----------------------------------------------------------------------------
run_one_gse <- function(gse.number, work_dir, organism, resources, perf = NULL,
                        skip_completed = FALSE) {
  if (is.null(perf)) perf <- resolve_perf_opts(list())
  OrgDb <- resources$OrgDb
  bcv_value <- resources$bcv_value
  map_columns <- resources$map_columns
  ensembl_prefix <- resources$ensembl_prefix
  cellmarker <- resources$cellmarker
  gene_lengths <- resources$gene_lengths
  kegg_list <- resources$kegg_list
  go_list <- resources$go_list
  gsva_term_id_map <- resources$gsva_term_id_map
  gsva_term_name_map <- resources$gsva_term_name_map
  ssGSEA_list <- resources$ssGSEA_list

  gse_dir <- resolve_gse_dir(
    work_dir, organism, gse.number, create = FALSE, allow_legacy = FALSE
  )
  if (!dir.exists(gse_dir)) {
    stop(
      "GSE directory not found: ", gse_dir,
      "\nExpected layout: work_dir/", organism, "/", gse.number, "/"
    )
  }

  # ----- 2.2 Read sample-specific input files -----
  # Canonical: {GSE}.{organism}.ExprMatrix.txt|.tsv; also accept older .expr/.counts names
  expr_candidates <- c(
    paste0(gse.number, ".", organism, ".ExprMatrix.txt"),
    paste0(gse.number, ".", organism, ".ExprMatrix.tsv"),
    paste0(gse.number, ".", organism, ".expr.txt"),
    paste0(gse.number, ".", organism, ".expr.tsv"),
    paste0(gse.number, ".", organism, ".counts.txt"),
    paste0(gse.number, ".", organism, ".counts.tsv"),
    "ExprMatrix.txt",
    "ExprMatrix.tsv",
    "expr.txt",
    "expr.tsv",
    "counts.txt",
    "counts.tsv"
  )
  expr_paths <- file.path(gse_dir, expr_candidates)
  counts_file <- expr_paths[file.exists(expr_paths)]
  if (length(counts_file) == 0) {
    stop(
      "Expression matrix not found in ", gse_dir,
      " (expected {GSE}.{organism}.ExprMatrix.txt). Candidates tried: ",
      paste(expr_candidates, collapse = ", ")
    )
  }
  counts_file <- counts_file[[1]]
  message("Using expression matrix: ", counts_file)

  sig <- readBin(counts_file, what = "raw", n = 2)
  if (identical(sig, as.raw(c(0xFF, 0xFE)))) {
    counts <- read.delim(
      counts_file, sep = "\t", fileEncoding = "UTF-16LE",
      stringsAsFactors = FALSE, check.names = FALSE
    )
  } else {
    counts <- read.delim(
      counts_file, sep = "\t",
      stringsAsFactors = FALSE, check.names = FALSE
    )
  }

  colnames(counts)[1] <- "GeneID"
  counts[[1]] <- str_split_fixed(counts[[1]], "\\.", 2)[, 1]

  samples_info <- normalize_samples_info(
    read.csv(file.path(gse_dir, "samples_info.txt"), sep = "\t", stringsAsFactors = FALSE)
  )
  comparisons <- normalize_comparisons(
    read.csv(file.path(gse_dir, "comparisons.txt"), sep = "\t", stringsAsFactors = FALSE)
  )

  # ----- 3. Update column names in counts file -----
  mat_samples <- as.character(colnames(counts)[2:(ncol(counts))])
  missing_samples <- setdiff(mat_samples, samples_info$Sample)
  if (length(missing_samples) > 0) {
    stop(
      "Expression matrix columns not found in samples_info$Sample: ",
      paste(missing_samples, collapse = ", ")
    )
  }
  unused_samples <- setdiff(samples_info$Sample, mat_samples)
  if (length(unused_samples) > 0) {
    message(
      "Note: samples_info Sample IDs absent from matrix (ignored): ",
      paste(unused_samples, collapse = ", ")
    )
  }
  sample_map <- setNames(samples_info$Source, samples_info$Sample)
  mapped <- unname(sample_map[mat_samples])
  if (any(is.na(mapped)) || any(!nzchar(mapped))) {
    stop("Failed to map matrix columns to samples_info$Source for: ",
         paste(mat_samples[is.na(mapped) | !nzchar(mapped)], collapse = ", "))
  }
  colnames(counts)[2:(ncol(counts))] <- mapped

  gene_id_col <- counts[, 1]
  ok <- !is.na(gene_id_col) & gene_id_col != ""
  gene_id_col <- as.character(gene_id_col[ok])
  counts <- counts[ok, -1, drop = FALSE]
  # make.names on matrix colnames; keep samples_info$Source in sync via Sample
  raw_source_cols <- as.character(colnames(counts))
  safe_source_cols <- make.names(raw_source_cols, unique = TRUE)
  colnames(counts) <- safe_source_cols
  sample_to_safe_source <- setNames(safe_source_cols, mat_samples)
  samples_info$Source <- ifelse(
    samples_info$Sample %in% names(sample_to_safe_source),
    unname(sample_to_safe_source[as.character(samples_info$Sample)]),
    make.names(as.character(samples_info$Source), unique = FALSE)
  )

  {
    is_ensembl <- grepl(ensembl_prefix, gene_id_col)

    if (all(is_ensembl)) {
      counts$ENSEMBL <- sub("\\.[0-9]+$", "", gene_id_col)
    } else {
      gene_ids_new <- convert_to_ensembl(gene_id_col, OrgDb, ensembl_prefix, map_columns)
      counts$ENSEMBL <- gene_ids_new
    }
    counts_agg <- counts %>%
      as_tibble() %>%
      group_by(ENSEMBL) %>%
      summarise(across(everything(), sum), .groups = "drop")

    counts <- as.data.frame(counts_agg)
    rownames(counts) <- counts$ENSEMBL
    counts$ENSEMBL <- NULL
    counts <- counts[grepl(ensembl_prefix, rownames(counts)), ]
  }

  counts <- as.data.frame(counts)
  counts[] <- lapply(counts, function(x) as.integer(round(x)))
  counts[is.na(counts)] <- 0
  counts <- counts[rowSums(counts) != 0, ]

  # Note: analysis uses raw counts. Convert TPM/other inputs beforehand.
  # Loop format: rownames = Ensembl IDs; values = raw counts.

  # ----- 4. Loop differential analysis per comparison -----
  message("Starting analysis for ", gse.number, "...")

  for (i in seq_len(nrow(comparisons))) {

    Control <- as.character(comparisons$Control[i])
    Treatment <- as.character(comparisons$Treatment[i])
    compareName <- paste0(Treatment, "_vs_", Control)
    out_dir <- file.path(gse_dir, compareName)
    dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

    if (isTRUE(skip_completed) && comparison_is_complete(out_dir, compareName)) {
      message("SKIP completed comparison: ", compareName)
      next
    }
    clear_analysis_success(out_dir)

    ## 4.1 Obtain comparison data ####
    group_data <- subset(samples_info, Group %in% c(Control, Treatment))
    group_data$Group <- factor(group_data$Group, levels = c(Control, Treatment))

    group_data <- subset(group_data, select = -Sample)
    info_Control <- subset(group_data, Group == Control)
    info_Treatment <- subset(group_data, Group == Treatment)

    missing_src <- setdiff(as.character(group_data$Source), colnames(counts))
    if (length(missing_src) > 0) {
      stop(
        "Source columns missing from count matrix after make.names for ",
        compareName, ": ", paste(missing_src, collapse = ", ")
      )
    }
    current_counts <- counts[, as.character(group_data$Source), drop = FALSE]
    current_counts <- current_counts[rowSums(current_counts > 1) >= (ncol(current_counts) / 2), ]

    # Calculate TPM ####
    {
      gene_lengths_sub <- gene_lengths[match(rownames(current_counts), gene_lengths$GeneID), "length"]
      current_counts_sub <- current_counts[!is.na(gene_lengths_sub), ]
      gene_lengths_sub <- gene_lengths_sub[!is.na(gene_lengths_sub)]

      tpm <- function(current_counts, gene_length) {
        kb <- gene_length / 1000
        rpk <- current_counts / kb
        tpm <- t(t(rpk) / colSums(rpk) * 1000000)
        tpm <- as.matrix(tpm)
        return(tpm)
      }
      tpm <- tpm(current_counts_sub, gene_lengths_sub)
      z_score_matrix <- t(scale(t(tpm)))
    }

    # 4.2 Differential analysis ####
    {
      nC <- nrow(info_Control)
      nT <- nrow(info_Treatment)
      deg_method <- choose_bulk_deg_method(nC, nT)
      message("DEG method for ", compareName, ": ", deg_method,
              " (n_control=", nC, ", n_treatment=", nT, ")")

      if (deg_method == "DESeq2") {
        dds <- DESeqDataSetFromMatrix(
          countData = current_counts,
          colData = group_data,
          design = ~ Group
        )
        dds <- DESeq(dds)
        res <- results(dds, contrast = c("Group", Treatment, Control))
        res <- res[order(res$padj), ]
        tempDEG <- as.data.frame(res)
        DEG <- na.omit(tempDEG)
      } else if (deg_method == "edgeR") {
        DEG <- run_edger_low_replicate(
          current_counts, group_data$Group, bcv_value, Control, Treatment
        )
      } else if (deg_method == "wilcoxon") {
        conditions <- factor(group_data$Group, levels = c(Control, Treatment))
        y <- DGEList(counts = current_counts, group = conditions)
        keep <- filterByExpr(y)
        y <- y[keep, keep.lib.sizes = FALSE]
        y <- calcNormFactors(y, method = "TMM")
        count_norm <- edgeR::cpm(y)
        count_norm <- as.data.frame(count_norm)

        pvalues <- sapply(1:nrow(count_norm), function(i) {
          data <- cbind.data.frame(gene = as.numeric(t(count_norm[i, ])), conditions)
          p <- wilcox.test(gene ~ conditions, data)$p.value
          return(p)
        })
        fdr <- p.adjust(pvalues, method = "fdr")

        conditionsLevel <- levels(conditions)
        dataCon1 <- count_norm[, c(which(conditions == conditionsLevel[1]))]
        dataCon2 <- count_norm[, c(which(conditions == conditionsLevel[2]))]
        exp_control <- rowMeans(dataCon1)
        exp_case <- rowMeans(dataCon2)
        foldChanges <- log2(rowMeans(dataCon2) / rowMeans(dataCon1))

        outRst <- data.frame(
          log2FoldChange = foldChanges,
          exp_control = exp_control,
          exp_case = exp_case,
          pvalue = pvalues,
          padj = fdr
        )
        rownames(outRst) <- rownames(count_norm)
        outRst <- na.omit(outRst)
        DEG <- cbind(name = rownames(outRst), outRst)
      } else {
        stop("Unknown DEG method: ", deg_method)
      }

      ## Add regulation column ####
      DEG$regulation <- ifelse(
        DEG$log2FoldChange > 1 & DEG$padj < 0.05, "up",
        ifelse(DEG$log2FoldChange < -1 & DEG$padj < 0.05, "down", "stable")
      )

      ## Add Gene symbol, handling 1:many mappings ####
      {
        current_counts_with_symbol <- merge(
          current_counts, gene_lengths[, c("GeneID", "SYMBOL")],
          by.x = "row.names", by.y = "GeneID", all.x = TRUE
        )
        row.names(current_counts_with_symbol) <- current_counts_with_symbol$Row.names
        current_counts_with_symbol$Row.names <- NULL
      }

      # Add basic information column
      DEG$data <- gse.number
      DEG$group <- compareName
      DEG$SYMBOL <- current_counts_with_symbol$SYMBOL[
        match(rownames(DEG), rownames(current_counts_with_symbol))
      ]
      DEG <- DEG[, c(8, 9, 10, 1, 2, 3, 4, 5, 6, 7)]

      ## Add expression level columns ####
      {
        group_list <- factor(group_data$Group, levels = c(Control, Treatment))
        common_genes <- intersect(rownames(DEG), rownames(z_score_matrix))
        DEG <- DEG[common_genes, , drop = FALSE]
        z_scores_aligned <- z_score_matrix[common_genes, , drop = FALSE]
        DEG <- cbind(DEG, z_scores_aligned)
        DEG_tpm <- tpm[rownames(DEG), ]

        # Control group
        if (nrow(info_Control) >= 2) {
          tpm_Control <- DEG_tpm[, info_Control$Source]
          AveExpr_Control <- rowMeans(tpm_Control)
        } else {
          AveExpr_Control <- DEG_tpm[, info_Control$Source]
        }
        DEG <- cbind(DEG[, 1:4], AveExpr_Control, DEG[, 5:ncol(DEG)])

        # Treatment group
        if (nrow(info_Treatment) >= 2) {
          tpm_Treatment <- DEG_tpm[, info_Treatment$Source]
          AveExpr_Case <- rowMeans(tpm_Treatment)
        } else {
          AveExpr_Case <- DEG_tpm[, info_Treatment$Source]
        }
        DEG <- cbind(DEG[, 1:5], AveExpr_Case, DEG[, 6:ncol(DEG)])
      }

      ## Save final results ####
      write_csv_if_nonempty(DEG, file.path(out_dir, "DEG_all.csv"))
      DEG_significant <- subset(DEG, regulation != "stable")
      write_csv_if_nonempty(DEG_significant, file.path(out_dir, "DEG_significant.csv"))
    }

    # 4.3. CellMarker/GO/KEGG Enrichment ####
    {
      ## 4.3.1 Helper functions ####
      deg_rich_save <- function(df, gse.number, compareName, filename) {
        if (!is_nonempty_df(df)) {
          message(filename, " No significant terms found. Skipping.")
          return(invisible(FALSE))
        }
        df$data <- gse.number
        df$group <- compareName
        write_csv_if_nonempty(df, file.path(out_dir, filename), row.names = FALSE)
      }

      network_save <- function(p, filename) {
        if (!is.null(p) && inherits(p, "ggplot") && nrow(p$data) > 3) {
          ggsave(filename = file.path(out_dir, filename), plot = p, width = 10, height = 10, units = "in")
        } else if (inherits(p, "ggplot")) {
          message("Plot object empty or no data, not saving.")
        } else {
          message("Invalid plot object, not saving.")
        }
      }

      KEGG_enrich_Func <- function(gene, filename) {
        kegg_enrich_results <- enrichKEGG(
          gene = gene,
          organism = organism,
          pvalueCutoff = 0.05,
          qvalueCutoff = 0.2
        )
        if (is.null(kegg_enrich_results)) {
          message("No significant KEGG pathways found.")
        } else {
          kegg_enrich_results <- DOSE::setReadable(
            kegg_enrich_results, OrgDb = OrgDb, keyType = "ENTREZID"
          )
          kegg_enrich <- kegg_enrich_results@result %>%
            filter(p.adjust < 0.05)
          deg_rich_save(kegg_enrich, gse.number, compareName, filename)
          return(kegg_enrich_results)
        }
      }

      GO_enrich_Func <- function(gene, filename) {
        ontologies <- c("BP", "MF", "CC")
        results_list <- list()
        go_enrich_results_list <- list()

        for (ont in ontologies) {
          temp_results <- enrichGO(
            gene = gene,
            OrgDb = OrgDb,
            ont = ont,
            pvalueCutoff = 0.05,
            qvalueCutoff = 0.2
          )

          if (is.null(temp_results)) {
            message(paste("No significant GO terms for ontology:", ont))
            next
          } else {
            go_enrich_results <- DOSE::setReadable(
              temp_results, OrgDb = OrgDb, keyType = "ENTREZID"
            )
            go_enrich <- go_enrich_results@result %>% filter(p.adjust < 0.05)

            if (nrow(go_enrich) == 0) {
              message(paste("No significant GO terms after filtering for:", ont))
            } else {
              go_enrich$ONTOLOGY <- ont
              results_list[[ont]] <- go_enrich
              go_enrich_results_list[[ont]] <- go_enrich_results
            }
          }
        }

        if (length(results_list) == 0) {
          message("No significant results for any GO ontology.")
          return(NULL)
        } else {
          combined_results <- bind_rows(results_list) %>%
            select(ONTOLOGY, everything()) %>%
            as.data.frame()
          rownames(combined_results) <- combined_results$ID

          if (length(go_enrich_results_list) > 0) {
            combined_go_enrich_results <- go_enrich_results_list[[1]]
            combined_go_enrich_results@result <- combined_results
          } else {
            combined_go_enrich_results <- NULL
          }

          deg_rich_save(combined_results, gse.number, compareName, filename)
          return(combined_go_enrich_results)
        }
      }

      cellmarker_rich_Func <- function(gene_select, gse.number, compareName, regulation, filename) {
        cellmarker_rich <- enricher(
          gene = gene_select,
          TERM2GENE = cellmarker[c("CellType", "geneSymbol")],
          TERM2NAME = cellmarker[c("CellType", "Source")],
          pvalueCutoff = 0.05,
          pAdjustMethod = "BH",
          qvalueCutoff = 0.2,
          maxGSSize = 500
        )

        if (!is.null(cellmarker_rich)) {
          result <- cellmarker_rich@result
          result$data <- gse.number
          result$group <- compareName
          result$Regulation <- regulation
          result <- result[, c(13, 14, 1, 2, 15, 3, 4, 8, 9, 10, 11, 12)]
          colnames(result) <- c(
            "data", "group",
            "CellType", "Source", "Regulation",
            "GeneRatio", "BgRatio", "P-value", "Adjusted P-value",
            "qvalue", "MarkerGene", "count"
          )
          fwrite_if_nonempty(result, file.path(out_dir, filename), sep = ",")
          return(result)
        }
      }

      networkDiagram_Func <- function(diff_enrich_results, pathway2gene_filename, pathway2pathway_filename) {
        if (!is.null(diff_enrich_results) && nrow(diff_enrich_results) > 1) {
          gene_pathway <- diff_enrich_results@result[, c("Description", "geneID")]
          gene_pathway_long <- do.call(rbind, lapply(1:nrow(gene_pathway), function(i) {
            data.frame(
              Pathway = gene_pathway$Description[i],
              Gene = unlist(strsplit(gene_pathway$geneID[i], "/"))
            )
          }))
          fwrite_if_nonempty(gene_pathway_long, file.path(out_dir, paste0(pathway2gene_filename, ".csv")), sep = ",")

          pathway2 <- pairwise_termsim(diff_enrich_results)
          similarity_matrix <- as.data.frame(pathway2@termsim)
          similarity_matrix$Term1 <- rownames(similarity_matrix)
          long_sim <- melt(similarity_matrix, id.vars = "Term1", variable.name = "Term2", value.name = "similarity")
          long_sim <- long_sim[long_sim$similarity > 0, ]
          long_sim <- merge(
            long_sim,
            diff_enrich_results@result[, c("Description", "p.adjust", "Count")],
            by.x = "Term1", by.y = "Description", all.x = TRUE
          )
          fwrite_if_nonempty(long_sim, file.path(out_dir, paste0(pathway2pathway_filename, ".csv")), sep = ",")
        }
      }

      enrich_ana_Func <- function(DEG_significant) {
        {
          gene_select <- DEG_significant$SYMBOL
          DEG_significant_up <- DEG_significant[DEG_significant$regulation == "up", ]
          gene_select_up <- DEG_significant_up$SYMBOL
          DEG_significant_down <- DEG_significant[DEG_significant$regulation == "down", ]
          gene_select_down <- DEG_significant_down$SYMBOL

          {
            gene_up_entrez <- tryCatch({
              result <- bitr(gene_select_up, fromType = "SYMBOL", toType = "ENTREZID", OrgDb = OrgDb)
              entrez_ids <- as.character(na.omit(result[, 2]))
              if (length(entrez_ids) == 0) warning("No valid ENTREZID found.")
              entrez_ids
            }, error = function(e) {
              message("[!] ID conversion failed: ", e$message)
              return(NULL)
            })

            gene_down_entrez <- tryCatch({
              result <- bitr(gene_select_down, fromType = "SYMBOL", toType = "ENTREZID", OrgDb = OrgDb)
              entrez_ids <- as.character(na.omit(result[, 2]))
              if (length(entrez_ids) == 0) warning("No valid ENTREZID found.")
              entrez_ids
            }, error = function(e) {
              message("[!] ID conversion failed: ", e$message)
              return(NULL)
            })

            gene_diff_entrez <- unique(c(gene_up_entrez, gene_down_entrez))
          }
        }

        ## CellMarker enrichment
        {
          if (length(gene_select_up) > 0) {
            cellmarker_rich_up <- cellmarker_rich_Func(
              gene_select_up, gse.number, compareName, "up", "CellMarker_rich_up.csv"
            )
          }
          if (length(gene_select_down) > 0) {
            cellmarker_rich_down <- cellmarker_rich_Func(
              gene_select_down, gse.number, compareName, "down", "CellMarker_rich_down.csv"
            )
          }

          if (exists("cellmarker_rich_up") && exists("cellmarker_rich_down")) {
            cellmarker_rich <- rbind(cellmarker_rich_up, cellmarker_rich_down)
          } else if (!exists("cellmarker_rich_up") && exists("cellmarker_rich_down")) {
            cellmarker_rich <- cellmarker_rich_down
          } else if (exists("cellmarker_rich_up") && !exists("cellmarker_rich_down")) {
            cellmarker_rich <- cellmarker_rich_up
          }
          if (exists("cellmarker_rich") && !is.null(cellmarker_rich)) {
            fwrite_if_nonempty(cellmarker_rich, file.path(out_dir, "CellMarker_rich.csv"), sep = ",")
          }
        }

        ## GO/KEGG Up-regulated
        if (!is.null(gene_up_entrez)) {
          go_up_enrich_results <- GO_enrich_Func(gene_up_entrez, "GO_enrich_up.csv")
          kegg_up_enrich_results <- KEGG_enrich_Func(gene_up_entrez, "KEGG_enrich_up.csv")
        }

        ## GO/KEGG Down-regulated
        if (!is.null(gene_down_entrez)) {
          go_down_enrich_results <- GO_enrich_Func(gene_down_entrez, "GO_enrich_down.csv")
          kegg_down_enrich_results <- KEGG_enrich_Func(gene_down_entrez, "KEGG_enrich_down.csv")
        }

        ## GO/KEGG Significant
        if (!is.null(gene_diff_entrez)) {
          go_diff_enrich_results <- GO_enrich_Func(gene_diff_entrez, "GO_enrich_AllDiff.csv")
          networkDiagram_Func(go_diff_enrich_results, "GO_Gene_NetworkDiagram", "GO_GO_NetworkDiagram")
          kegg_diff_enrich_results <- KEGG_enrich_Func(gene_diff_entrez, "KEGG_enrich_AllDiff.csv")
          networkDiagram_Func(kegg_diff_enrich_results, "KEGG_Gene_NetworkDiagram", "KEGG_KEGG_NetworkDiagram")
        }
      }

      if (nrow(DEG_significant) > 0) {
        enrich_ana_Func(DEG_significant)
      }
    }

    # 4.4. GSEA ####
    {
      GSEA_plot <- function(kk_gse, kk_gse_cut) {
        kk_gse_cut <- cap_gsea_terms(kk_gse_cut, perf$max_gsea_plots)
        if (is.null(kk_gse_cut) || nrow(kk_gse_cut) == 0) return(invisible(NULL))
        message("GSEA plots: ", nrow(kk_gse_cut))
        for (i in seq_along(kk_gse_cut$ID)) {
          gseap1 <- gseaplot2(
            kk_gse, kk_gse_cut$ID[i],
            title = kk_gse_cut$Description[i],
            color = "red", base_size = 20,
            rel_heights = c(1.5, 0.5, 1),
            subplots = 1:3, ES_geom = "line", pvalue_table = TRUE
          )
          filename <- paste0(gsub("[:\\/]", "_", kk_gse_cut$ID[i]), ".jpg")
          ggsave(gseap1, filename = file.path(out_dir, filename), width = 10, height = 8)
        }
      }

      gsea_go_func <- function(geneList, ont) {
        GO_kk_entrez <- gseGO(
          geneList = geneList, ont = ont, OrgDb = OrgDb,
          keyType = "ENTREZID", pvalueCutoff = 0.05, pAdjustMethod = "BH"
        )
        if (nrow(GO_kk_entrez@result) == 0) {
          message("No GO enrichment found.")
        } else {
          GO_kk <- DOSE::setReadable(GO_kk_entrez, OrgDb = OrgDb, keyType = "ENTREZID")
          GO_kk_cut <- GO_kk[GO_kk$pvalue < 0.05 & GO_kk$p.adjust < 0.25 & abs(GO_kk$NES) > 1]
          gsea_go <- as.data.frame(GO_kk_cut)
          gsea_go$data <- gse.number
          gsea_go$group <- compareName
          if (!"ONTOLOGY" %in% names(gsea_go)) gsea_go$ONTOLOGY <- ont
          GSEA_plot(GO_kk, GO_kk_cut)
          return(gsea_go)
        }
      }

      GSEA_analysis <- function(need_DEG) {
        colnames(need_DEG) <- c("log2FoldChange", "SYMBOL")
        need_DEG$ENSEMBL <- rownames(need_DEG)

        df <- bitr(rownames(need_DEG), fromType = "ENSEMBL", toType = "ENTREZID", OrgDb = OrgDb)
        need_DEG <- merge(need_DEG, df, by = "ENSEMBL")
        need_DEG_avg <- need_DEG %>%
          group_by(ENTREZID) %>%
          summarise(log2FoldChange = median(log2FoldChange, na.rm = TRUE))

        geneList <- need_DEG_avg$log2FoldChange
        names(geneList) <- need_DEG_avg$ENTREZID
        geneList <- geneList[!duplicated(names(geneList))]
        geneList <- sort(geneList, decreasing = TRUE)
        geneList <- geneList[!is.na(geneList) & !is.nan(geneList) & !is.infinite(geneList)]

        # KEGG GSEA
        KEGG_kk_entrez <- gseKEGG(
          geneList = geneList, organism = organism,
          pvalueCutoff = 0.05, pAdjustMethod = "BH"
        )
        if (nrow(KEGG_kk_entrez@result) == 0) {
          message("No KEGG GSEA found.")
        } else {
          KEGG_kk <- DOSE::setReadable(KEGG_kk_entrez, OrgDb = OrgDb, keyType = "ENTREZID")
          KEGG_kk_cut <- KEGG_kk[KEGG_kk$pvalue < 0.05 & KEGG_kk$p.adjust < 0.25 & abs(KEGG_kk$NES) > 1]
          gsea_kegg <- KEGG_kk_cut
          gsea_kegg$data <- gse.number
          gsea_kegg$group <- compareName
          write_csv_if_nonempty(gsea_kegg, file.path(out_dir, "GSEA_KEGG.csv"), row.names = FALSE)
          GSEA_plot(KEGG_kk, KEGG_kk_cut)
        }

        # GO GSEA (ont=ALL once; faster than BP+MF+CC)
        gsea_go <- gsea_go_func(geneList, "ALL")
        if (!is.null(gsea_go) && nrow(gsea_go) > 0) {
          fwrite_if_nonempty(gsea_go, file.path(out_dir, "GSEA_GO.csv"), sep = ",")
        }
      }

      need_DEG <- DEG[, c(7, 3)]
      GSEA_analysis(need_DEG)
    }

    # 4.5 GSVA Analysis ####
    {
      GSVA_ana <- function(dat, geneset) {
        gsvaPar <- gsvaParam(dat, geneset, kcdf = "Poisson", minSize = 5, maxSize = 500)
        es.max <- gsva(gsvaPar, verbose = FALSE)
        return(es.max)
      }

      deg_limma <- function(es_max, design, contrast_matrix, group_list) {
        fit <- lmFit(es_max, design)
        fit2 <- contrasts.fit(fit, contrast_matrix)
        fit2 <- eBayes(fit2)
        res <- decideTests(fit2, p.value = 0.05)
        tempOutput <- topTable(fit2, coef = 1, n = Inf)
        nrDEG <- na.omit(tempOutput)

        if (nrow(info_Control) >= 2) {
          control_mean <- rowMeans(es_max[, group_list == Control])
          nrDEG$AveExpr_Control <- control_mean[rownames(nrDEG)]
        } else {
          nrDEG$AveExpr_Control <- es_max[, group_list == Control]
        }
        if (nrow(info_Treatment) >= 2) {
          treatment_mean <- rowMeans(es_max[, group_list == Treatment])
          nrDEG$AveExpr_Case <- treatment_mean[rownames(nrDEG)]
        } else {
          nrDEG$AveExpr_Case <- es_max[, group_list == Treatment]
        }
        return(nrDEG)
      }

      safe_analysis <- function(expr, analysis_name) {
        tryCatch({
          eval(expr)
        }, error = function(e) {
          message("\n[!] ", analysis_name, " analysis failed: ", e$message)
          return(NULL)
        })
      }

      GSVA_func <- function(data_GSVA) {
        dat <- as.matrix(data_GSVA)
        group_list <- factor(group_data$Group, levels = c(Control, Treatment))
        design <- model.matrix(~ 0 + group_list)
        rownames(design) <- colnames(data_GSVA)
        colnames(design) <- levels(group_list)

        contrast_formula <- paste0(Treatment, "-", Control)
        contrast_matrix <- makeContrasts(contrasts = contrast_formula, levels = design)

        go_kegg_result <- safe_analysis(
          expr = {
            es_max_GO <- GSVA_ana(dat, go_list)
            es_max_KEGG <- GSVA_ana(dat, kegg_list)
            es_max <- rbind(es_max_GO, es_max_KEGG)

            nrDEG_GO <- safe_analysis(
              deg_limma(es_max_GO, design, contrast_matrix, group_list),
              "GO differential analysis"
            )
            nrDEG_KEGG <- safe_analysis(
              deg_limma(es_max_KEGG, design, contrast_matrix, group_list),
              "KEGG differential analysis"
            )

            if (is.null(nrDEG_GO)) nrDEG_GO <- data.frame()
            if (is.null(nrDEG_KEGG)) nrDEG_KEGG <- data.frame()

            nrDEG <- rbind(nrDEG_GO, nrDEG_KEGG)
            if (nrow(nrDEG) > 0) {
              nrDEG$data <- gse.number
              nrDEG$group <- compareName
              nrDEG <- nrDEG[, c(9, 10, 7, 8, 1, 2, 3, 4, 5, 6)]
              nrDEG$Regulation <- base::as.factor(ifelse(
                nrDEG$P.Value < 0.05,
                ifelse(nrDEG$logFC > 0, "UP", "DOWN"),
                "Stable"
              ))

              nrDEG_with_rownames <- nrDEG %>% rownames_to_column(var = "term")
              z_score_es_max <- t(scale(t(es_max)))
              es_max_hebin <- as.data.frame(z_score_es_max)
              es_max_with_rownames <- es_max_hebin %>% rownames_to_column(var = "term")
              nrDEG_all <- merge(nrDEG_with_rownames, es_max_with_rownames, by = "term")
              nrDEG_all <- annotate_gsva_term_meta(nrDEG_all, gsva_term_id_map, gsva_term_name_map)
              rownames(nrDEG_all) <- nrDEG_all$term
              nrDEG_significant <- nrDEG_all[nrDEG_all$P.Value < 0.05, ]

              nrDEG_go_all <- nrDEG_all %>% filter(grepl("^GO", term))
              nrDEG_kegg_all <- nrDEG_all %>% filter(grepl("^KEGG", term))
              list(all = nrDEG_all, go = nrDEG_go_all, kegg = nrDEG_kegg_all, sig = nrDEG_significant)
            }
          },
          analysis_name = "GO/KEGG GSVA"
        )

        try({
          if (!is.null(go_kegg_result)) {
            fwrite_if_nonempty(go_kegg_result$all, file.path(out_dir, "GSVA_DEG_all.csv"), sep = ",")
            fwrite_if_nonempty(go_kegg_result$go, file.path(out_dir, "GSVA_DEG_GO.csv"), sep = ",")
            fwrite_if_nonempty(go_kegg_result$kegg, file.path(out_dir, "GSVA_DEG_KEGG.csv"), sep = ",")
            fwrite_if_nonempty(go_kegg_result$sig, file.path(out_dir, "GSVA_DEG_significant.csv"), sep = ",")
          }
        })

        # ssGSEA: human only; skip gracefully if gene set was not loaded
        if (organism == "hsa" && !is.null(ssGSEA_list) && !isTRUE(perf$skip_ssgsea)) {
          ssgsea_result <- safe_analysis(
            expr = {
              gsvaPar <- ssgseaParam(exprData = dat, geneSets = ssGSEA_list)
              ssGSEA_matrix <- gsva(gsvaPar, verbose = FALSE)
              nrDEG_ssGSEA <- safe_analysis(
                deg_limma(ssGSEA_matrix, design, contrast_matrix, group_list),
                "ssGSEA analysis"
              )
              if (is.null(nrDEG_ssGSEA)) nrDEG_ssGSEA <- data.frame()
              if (nrow(nrDEG_ssGSEA) > 0) {
                nrDEG_ssGSEA$data <- gse.number
                nrDEG_ssGSEA$group <- compareName
                nrDEG_ssGSEA <- nrDEG_ssGSEA[, c(9, 10, 7, 8, 1, 2, 3, 4, 5, 6)]
                nrDEG_ssGSEA$Regulation <- base::as.factor(ifelse(
                  nrDEG_ssGSEA$P.Value < 0.05,
                  ifelse(nrDEG_ssGSEA$logFC > 0, "UP", "DOWN"),
                  "Stable"
                ))

                nrDEG_ssGSEA_with_rownames <- nrDEG_ssGSEA %>% rownames_to_column(var = "term")
                z_score_es_max_ssGSEA <- t(scale(t(ssGSEA_matrix)))
                es_max_hebin_ssGSEA <- as.data.frame(z_score_es_max_ssGSEA)
                es_max_with_rownames_ssGSEA <- es_max_hebin_ssGSEA %>% rownames_to_column(var = "term")
                nrDEG_ssGSEA_all <- merge(
                  nrDEG_ssGSEA_with_rownames, es_max_with_rownames_ssGSEA,
                  by = "term"
                )
                rownames(nrDEG_ssGSEA_all) <- nrDEG_ssGSEA_all$term
                list(all = nrDEG_ssGSEA_all)
              }
            },
            analysis_name = "ssGSEA"
          )
          try({
            if (!is.null(ssgsea_result)) {
              fwrite_if_nonempty(ssgsea_result$all, file.path(out_dir, "ssGSEA_DEG_all.csv"), sep = ",")
            }
          })
        } else if (organism == "hsa" && is.null(ssGSEA_list)) {
          message("ssGSEA skipped (ssGSEA_Hs.rds not available).")
        }
      }

      {
        duplicated_genes <- current_counts_with_symbol %>%
          group_by(SYMBOL) %>%
          filter(n() > 1)
        current_counts_merged <- current_counts_with_symbol %>%
          group_by(SYMBOL) %>%
          summarize(across(everything(), ~ median(.x, na.rm = TRUE)))
        data_GSVA <- data.frame(current_counts_merged)
        data_GSVA <- data_GSVA[!is.na(data_GSVA$SYMBOL), ]
        rownames(data_GSVA) <- data_GSVA$SYMBOL
        data_GSVA <- data_GSVA[, -1]
      }
      GSVA_func(data_GSVA)
    }

    if (!isTRUE(perf$skip_save_image)) {
      save(
        list = c("DEG", "DEG_significant", "compareName", "Control", "Treatment",
                 "current_counts", "group_data", "gse.number", "organism"),
        file = file.path(out_dir, paste0(compareName, ".RData"))
      )
    } else {
      save(list = c("compareName", "gse.number", "organism"),
           file = file.path(out_dir, paste0(compareName, ".RData")))
      message("skip_save_image=TRUE; wrote lightweight .RData image")
    }
    write_analysis_success(out_dir, "bulk_rna_seq", compareName)
  }

  message("Analysis completed for ", gse.number, ".")
  invisible(TRUE)
}

# -----------------------------------------------------------------------------
# 4. main(): batch loop
# -----------------------------------------------------------------------------
main <- function() {
  cfg <- .parse_cli()
  work_dir <- cfg$work_dir
  organism <- cfg$organism
  GeneralFile <- cfg$GeneralFile
  gse_ids <- cfg$gse_ids
  skip_completed <- cfg$skip_completed
  strict_mode <- isTRUE(cfg$strict)
  perf <- cfg$perf
  if (is.null(perf)) perf <- resolve_perf_opts(list())
  batch_had_error <- FALSE

  logfile <- file.path(work_dir, "batch_RNA_seq.log")
  batch_log(logfile, paste0(
    "=== batch RNA-seq start | organism=", organism,
    " | n_gse=", length(gse_ids),
    " | work_dir=", work_dir,
    " | GeneralFile=", GeneralFile,
    " | skip_completed=", skip_completed,
    " | strict=", strict_mode,
    " | fast=", perf$fast,
    " | n_workers=", perf$n_workers,
    " | skip_ssgsea=", perf$skip_ssgsea, " ==="
  ))

  # Parallel: spawn one child Rscript per GSE (Windows-safe)
  if (perf$n_workers > 1L && length(gse_ids) > 1L) {
    shared_args <- c(
      "--work_dir", work_dir,
      "--organism", organism,
      "--general_file", GeneralFile,
      "--skip_completed", as.character(skip_completed),
      "--strict", as.character(strict_mode),
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
      logfile = logfile
    )
    batch_had_error <- any(!vapply(results, function(r) isTRUE(r$ok), logical(1)))
    batch_log(logfile, "=== batch RNA-seq finished (parallel) ===")
    if (isTRUE(strict_mode) && isTRUE(batch_had_error)) {
      quit(save = "no", status = 1)
    }
    return(invisible(TRUE))
  }

  load_packages()
  batch_log(logfile, "Packages loaded.")

  resources <- load_common_resources(organism, GeneralFile)
  batch_log(logfile, "Common species resources loaded.")

  for (gse.number in gse_ids) {
    gse.number <- trimws(gse.number)
    if (!nzchar(gse.number)) next

    gse_dir <- resolve_gse_dir(
      work_dir, organism, gse.number, create = FALSE, allow_legacy = FALSE
    )
    batch_log(logfile, paste("Processing", organism, gse.number))

    tryCatch({
      if (!dir.exists(gse_dir)) {
        stop(
          "GSE directory not found: ", gse_dir,
          " (expected work_dir/", organism, "/", gse.number, ")"
        )
      }

      # Pre-check skip_completed using comparisons.txt
      if (skip_completed) {
        cmp_file <- file.path(gse_dir, "comparisons.txt")
        if (file.exists(cmp_file)) {
          cmp <- normalize_comparisons(
            read.csv(cmp_file, sep = "\t", stringsAsFactors = FALSE)
          )
          if (is_gse_completed(gse_dir, cmp)) {
            batch_log(logfile, paste(
              "SKIP completed:", gse.number,
              "| all", nrow(cmp), "comparison .RData present"
            ))
            next
          }
        }
      }

      run_one_gse(
        gse.number = gse.number,
        work_dir = work_dir,
        organism = organism,
        resources = resources,
        perf = perf,
        skip_completed = skip_completed
      )
      batch_log(logfile, paste("SUCCESS:", gse.number))
    }, error = function(e) {
      batch_had_error <<- TRUE
      batch_log(logfile, paste("ERROR:", gse.number, "|", conditionMessage(e)))
    })
  }

  batch_log(logfile, "=== batch RNA-seq finished ===")
  if (isTRUE(strict_mode) && isTRUE(batch_had_error)) {
    quit(save = "no", status = 1)
  }
  invisible(TRUE)
}

# Entrypoint
main()
