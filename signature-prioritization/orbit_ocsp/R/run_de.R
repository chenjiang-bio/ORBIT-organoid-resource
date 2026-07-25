#!/usr/bin/env Rscript
# Differential expression for orbit-ocsp expression→biomarker pipeline.
#
# Engine selection by biological replicate counts:
#   n_case == 1 AND n_control == 1  → edgeR (fixed BCV; only engine for 1vs1)
#   n_case > 8 AND n_control > 8    → Wilcoxon rank-sum (Mann–Whitney)
#   otherwise:
#       rnaseq_count                → DESeq2
#       microarray / normalized     → limma
#
# Optional groups column: subject (enables paired DESeq2 / paired Wilcoxon)

suppressPackageStartupMessages({
  # Intentionally empty: packages loaded per engine.
})

parse_args <- function(args) {
  out <- list(
    matrix = NULL,
    groups = NULL,
    data_type = NULL,
    output = NULL,
    engine = "auto",
    bcv = 0.2
  )
  i <- 1
  while (i <= length(args)) {
    key <- args[[i]]
    if (i == length(args)) stop(paste("Missing value for", key))
    val <- args[[i + 1]]
    if (key == "--matrix") out$matrix <- val
    else if (key == "--groups") out$groups <- val
    else if (key == "--data-type") out$data_type <- val
    else if (key == "--output") out$output <- val
    else if (key == "--engine") out$engine <- val
    else if (key == "--bcv") out$bcv <- as.numeric(val)
    else stop(paste("Unknown argument:", key))
    i <- i + 2
  }
  required <- c("matrix", "groups", "data_type", "output")
  missing <- required[vapply(required, function(k) is.null(out[[k]]), logical(1))]
  if (length(missing)) {
    stop(paste("Missing required arguments:", paste(missing, collapse = ", ")))
  }
  out
}

read_table_auto <- function(path) {
  if (grepl("\\.csv$", path, ignore.case = TRUE)) {
    utils::read.csv(path, check.names = FALSE, stringsAsFactors = FALSE)
  } else {
    utils::read.delim(path, check.names = FALSE, stringsAsFactors = FALSE)
  }
}

choose_engine <- function(n_case, n_control, data_type) {
  if (n_case < 1 || n_control < 1) {
    stop("Both case and control groups must contain at least one sample")
  }
  if (n_case == 1 && n_control == 1) {
    return("edger")
  }
  if (n_case > 8 && n_control > 8) {
    return("wilcox")
  }
  if (identical(data_type, "rnaseq_count")) {
    return("deseq2")
  }
  return("limma")
}

bh_adjust <- function(p) {
  p <- as.numeric(p)
  out <- rep(NA_real_, length(p))
  ok <- is.finite(p)
  if (any(ok)) {
    out[ok] <- stats::p.adjust(p[ok], method = "BH")
  }
  out
}

run_deseq2 <- function(mat, groups, paired) {
  if (!requireNamespace("DESeq2", quietly = TRUE)) {
    stop("Package DESeq2 is required for rnaseq_count analysis")
  }
  count_mat <- round(as.matrix(mat))
  storage.mode(count_mat) <- "integer"
  coldata <- groups
  rownames(coldata) <- coldata$sample_id
  if (paired) {
    coldata$subject <- factor(coldata$subject)
    design_formula <- ~ subject + group
    design_label <- "~ subject + group"
  } else {
    design_formula <- ~ group
    design_label <- "~ group"
  }
  dds <- DESeq2::DESeqDataSetFromMatrix(
    countData = count_mat,
    colData = coldata,
    design = design_formula
  )
  keep <- rowSums(DESeq2::counts(dds)) >= 10
  if (!any(keep)) {
    stop("No genes retained after DESeq2 count filter (rowSums >= 10)")
  }
  dds <- DESeq2::DESeq(dds[keep, ], quiet = TRUE)
  res <- as.data.frame(DESeq2::results(dds, contrast = c("group", "case", "control")))
  list(
    out = data.frame(
      gene = rownames(res),
      log2FoldChange = res$log2FoldChange,
      statistic = res$stat,
      pvalue = res$pvalue,
      padj = res$padj,
      engine = "deseq2",
      stringsAsFactors = FALSE
    ),
    design = design_label
  )
}

run_limma <- function(mat, groups, paired) {
  if (!requireNamespace("limma", quietly = TRUE)) {
    stop("Package limma is required for microarray/normalized analysis")
  }
  expr <- as.matrix(mat)
  if (paired) {
    groups$subject <- factor(groups$subject)
    design <- stats::model.matrix(~ subject + group, data = groups)
    coef_name <- "groupcase"
    design_label <- "~ subject + group"
  } else {
    design <- stats::model.matrix(~ 0 + group, data = groups)
    colnames(design) <- levels(groups$group)
    contrast <- limma::makeContrasts(case - control, levels = design)
    fit <- limma::lmFit(expr, design)
    fit2 <- limma::eBayes(limma::contrasts.fit(fit, contrast))
    tt <- limma::topTable(fit2, number = Inf, sort.by = "none")
    return(list(
      out = data.frame(
        gene = rownames(tt),
        log2FoldChange = tt$logFC,
        statistic = tt$t,
        pvalue = tt$P.Value,
        padj = tt$adj.P.Val,
        engine = "limma",
        stringsAsFactors = FALSE
      ),
      design = "~ 0 + group (case-control)"
    ))
  }
  fit <- limma::eBayes(limma::lmFit(expr, design))
  tt <- limma::topTable(fit, coef = coef_name, number = Inf, sort.by = "none")
  list(
    out = data.frame(
      gene = rownames(tt),
      log2FoldChange = tt$logFC,
      statistic = tt$t,
      pvalue = tt$P.Value,
      padj = tt$adj.P.Val,
      engine = "limma",
      stringsAsFactors = FALSE
    ),
    design = design_label
  )
}

run_edger_one_vs_one <- function(mat, groups, bcv) {
  if (!requireNamespace("edgeR", quietly = TRUE)) {
    stop("Package edgeR is required for 1-vs-1 RNA-seq / count comparisons")
  }
  count_mat <- round(as.matrix(mat))
  storage.mode(count_mat) <- "integer"
  # Column order: control then case for pair=c("control","case")
  sample_order <- c(
    groups$sample_id[groups$group == "control"],
    groups$sample_id[groups$group == "case"]
  )
  count_mat <- count_mat[, sample_order, drop = FALSE]
  group <- factor(c("control", "case"), levels = c("control", "case"))
  y <- edgeR::DGEList(counts = count_mat, group = group)
  y <- edgeR::calcNormFactors(y)
  # No replication: use a fixed biological coefficient of variation.
  et <- edgeR::exactTest(y, pair = c("control", "case"), dispersion = bcv^2)
  tab <- edgeR::topTags(et, n = Inf, sort.by = "none")$table
  list(
    out = data.frame(
      gene = rownames(tab),
      log2FoldChange = tab$logFC,
      statistic = tab$logCPM,
      pvalue = tab$PValue,
      padj = bh_adjust(tab$PValue),
      engine = "edger",
      stringsAsFactors = FALSE
    ),
    design = paste0("edgeR exactTest (1vs1, BCV=", bcv, ")")
  )
}

run_wilcox <- function(mat, groups, data_type, paired) {
  expr <- as.matrix(mat)
  storage.mode(expr) <- "numeric"
  case_ids <- groups$sample_id[groups$group == "case"]
  ctrl_ids <- groups$sample_id[groups$group == "control"]

  # For RNA-seq counts, rank on TMM logCPM; otherwise use values as-is.
  if (identical(data_type, "rnaseq_count")) {
    if (!requireNamespace("edgeR", quietly = TRUE)) {
      stop("Package edgeR is required to normalize counts before Wilcoxon testing")
    }
    y <- edgeR::DGEList(counts = round(expr))
    y <- edgeR::calcNormFactors(y)
    expr <- edgeR::cpm(y, log = TRUE, prior.count = 1)
  }

  n_genes <- nrow(expr)
  log2fc <- rep(NA_real_, n_genes)
  statistic <- rep(NA_real_, n_genes)
  pvalue <- rep(NA_real_, n_genes)

  if (paired) {
    # Align by subject: one case and one control per subject
    subjects <- sort(unique(as.character(groups$subject)))
    for (i in seq_len(n_genes)) {
      case_vals <- numeric(length(subjects))
      ctrl_vals <- numeric(length(subjects))
      ok <- TRUE
      for (j in seq_along(subjects)) {
        sid <- subjects[[j]]
        c_id <- groups$sample_id[groups$subject == sid & groups$group == "case"]
        n_id <- groups$sample_id[groups$subject == sid & groups$group == "control"]
        if (length(c_id) != 1 || length(n_id) != 1) {
          ok <- FALSE
          break
        }
        case_vals[[j]] <- expr[i, c_id]
        ctrl_vals[[j]] <- expr[i, n_id]
      }
      if (!ok) {
        pvalue[[i]] <- NA_real_
        next
      }
      log2fc[[i]] <- mean(case_vals - ctrl_vals)
      wt <- stats::wilcox.test(case_vals, ctrl_vals, paired = TRUE, exact = FALSE)
      statistic[[i]] <- unname(wt$statistic)
      pvalue[[i]] <- wt$p.value
    }
    design_label <- "paired Wilcoxon signed-rank"
    engine <- "wilcox_paired"
  } else {
    case_mat <- expr[, case_ids, drop = FALSE]
    ctrl_mat <- expr[, ctrl_ids, drop = FALSE]
    log2fc <- rowMeans(case_mat) - rowMeans(ctrl_mat)
    for (i in seq_len(n_genes)) {
      a <- as.numeric(case_mat[i, ])
      b <- as.numeric(ctrl_mat[i, ])
      if (all(!is.finite(a)) || all(!is.finite(b))) {
        pvalue[[i]] <- NA_real_
        next
      }
      # Constant across all samples → non-significant
      if (length(unique(c(a, b))) <= 1) {
        statistic[[i]] <- 0
        pvalue[[i]] <- 1
        next
      }
      wt <- stats::wilcox.test(a, b, paired = FALSE, exact = FALSE)
      statistic[[i]] <- unname(wt$statistic)
      pvalue[[i]] <- wt$p.value
    }
    design_label <- "Wilcoxon rank-sum (Mann-Whitney)"
    engine <- "wilcox"
  }

  list(
    out = data.frame(
      gene = rownames(expr),
      log2FoldChange = log2fc,
      statistic = statistic,
      pvalue = pvalue,
      padj = bh_adjust(pvalue),
      engine = engine,
      stringsAsFactors = FALSE
    ),
    design = design_label
  )
}

main <- function(args) {
  opt <- parse_args(args)
  expr <- read_table_auto(opt$matrix)
  groups <- read_table_auto(opt$groups)
  colnames(groups) <- tolower(colnames(groups))
  if (!("sample_id" %in% colnames(groups))) {
    colnames(groups)[1] <- "sample_id"
  }
  if (!("group" %in% colnames(groups))) {
    stop("groups table must contain a 'group' column")
  }
  groups$sample_id <- as.character(groups$sample_id)
  groups$group <- factor(tolower(as.character(groups$group)), levels = c("control", "case"))
  if (any(is.na(groups$group))) {
    stop("groups must be labeled case/control only")
  }

  gene <- as.character(expr[[1]])
  mat <- as.matrix(expr[, -1, drop = FALSE])
  storage.mode(mat) <- "numeric"
  rownames(mat) <- gene

  missing <- setdiff(groups$sample_id, colnames(mat))
  if (length(missing)) {
    stop(paste("Samples in groups missing from matrix:", paste(missing, collapse = ", ")))
  }
  mat <- mat[, groups$sample_id, drop = FALSE]

  n_case <- sum(groups$group == "case")
  n_control <- sum(groups$group == "control")
  paired <- "subject" %in% colnames(groups) && !anyNA(groups$subject)
  if (paired) {
    groups$subject <- as.character(groups$subject)
  }

  engine <- opt$engine
  if (is.null(engine) || identical(engine, "auto")) {
    engine <- choose_engine(n_case, n_control, opt$data_type)
  }

  # 1vs1 is only supported via edgeR; force that path for counts.
  if (n_case == 1 && n_control == 1 && !identical(engine, "edger")) {
    warning("1-vs-1 design detected; forcing engine=edger")
    engine <- "edger"
  }
  if (identical(engine, "edger") && !identical(opt$data_type, "rnaseq_count")) {
    # For microarray 1vs1, fall back to a simple logFC with NA p-values is unsafe;
    # still run edgeR only on counts. For non-count 1vs1, use limma with caution
    # is not possible without df — report clear error.
    if (!identical(opt$data_type, "rnaseq_count")) {
      stop(
        "1-vs-1 comparisons are only supported for rnaseq_count via edgeR. ",
        "Microarray/normalized 1-vs-1 is not statistically identifiable."
      )
    }
  }

  result <- switch(
    engine,
    "deseq2" = run_deseq2(mat, groups, paired),
    "limma" = run_limma(mat, groups, paired),
    "edger" = run_edger_one_vs_one(mat, groups, opt$bcv),
    "wilcox" = run_wilcox(mat, groups, opt$data_type, paired),
    stop(paste("Unsupported engine:", engine))
  )

  out <- result$out
  out$n_control <- n_control
  out$n_case <- n_case
  out$design <- result$design
  out$contrast <- "case-control"
  dir.create(dirname(opt$output), recursive = TRUE, showWarnings = FALSE)
  utils::write.table(out, file = opt$output, sep = "\t", quote = FALSE, row.names = FALSE)
  message(paste0(
    "Wrote ", opt$output,
    " (engine=", unique(out$engine),
    ", n_case=", n_case,
    ", n_control=", n_control, ")"
  ))
}

main(commandArgs(trailingOnly = TRUE))
