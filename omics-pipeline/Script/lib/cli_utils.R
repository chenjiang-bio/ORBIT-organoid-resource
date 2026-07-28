# Shared CLI helpers for omics-pipeline batch runners.

#' Directory containing the calling script (Rscript) or getwd() fallback.
get_script_dir <- function() {
  cmd_args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", cmd_args, value = TRUE)
  if (length(file_arg) > 0) {
    script_path <- normalizePath(sub("^--file=", "", file_arg[[1]]), winslash = "/", mustWork = FALSE)
    return(dirname(script_path))
  }
  ofile <- sys.frames()[[1]]$ofile
  if (!is.null(ofile)) {
    return(dirname(normalizePath(ofile, winslash = "/", mustWork = FALSE)))
  }
  normalizePath(getwd(), winslash = "/", mustWork = FALSE)
}

#' Resolve GeneralFile directory (default: Script/../GeneralFile).
resolve_general_file <- function(override = NULL, script_dir = NULL) {
  if (!is.null(override) && nzchar(override)) {
    return(normalizePath(override, winslash = "/", mustWork = FALSE))
  }
  if (is.null(script_dir)) script_dir <- get_script_dir()
  cand <- normalizePath(file.path(script_dir, "..", "GeneralFile"), winslash = "/", mustWork = FALSE)
  cand
}

#' Parse "--key value" and "--flag" style arguments (alias of parse_named_args).
parse_cli_args <- function(args, defaults = list(), required = character()) {
  parse_named_args(args, defaults = defaults, required = required)
}

#' Parse named CLI args; also accepts trailing positionals into .positionals.
parse_named_args <- function(args, defaults = list(), required = character()) {
  opts <- defaults
  positionals <- character()
  i <- 1L
  while (i <= length(args)) {
    token <- args[[i]]
    if (!startsWith(token, "--")) {
      positionals <- c(positionals, token)
      i <- i + 1L
      next
    }
    key <- sub("^--", "", token)
    next_is_value <- (i < length(args)) && !startsWith(args[[i + 1L]], "--")
    if (next_is_value) {
      val <- args[[i + 1L]]
      i <- i + 2L
    } else {
      val <- TRUE
      i <- i + 1L
    }
    if (is.character(val)) {
      low <- tolower(val)
      if (low %in% c("true", "t", "1", "yes", "y")) {
        val <- TRUE
      } else if (low %in% c("false", "f", "0", "no", "n")) {
        val <- FALSE
      } else if (!is.null(defaults[[key]]) && is.numeric(defaults[[key]])) {
        suppressWarnings(num <- as.numeric(val))
        if (!is.na(num)) val <- num
      }
    }
    opts[[key]] <- val
  }
  opts[[".positionals"]] <- positionals

  missing <- setdiff(required, names(opts))
  missing <- missing[vapply(missing, function(k) {
    is.null(opts[[k]]) || (is.character(opts[[k]]) && !nzchar(as.character(opts[[k]])))
  }, logical(1))]
  if (length(missing) > 0) {
    stop("Missing required options: ", paste0("--", missing, collapse = ", "),
         call. = FALSE)
  }
  opts
}

#' Append a timestamped line to a log file and message to console.
log_message <- function(log_file, msg) {
  line <- paste0("[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "] ", msg)
  message(line)
  if (!is.null(log_file) && nzchar(log_file)) {
    cat(line, "\n", file = log_file, append = TRUE, sep = "")
  }
  invisible(line)
}

#' Alias used by batch runners.
batch_log <- function(logfile, msg) {
  log_message(logfile, msg)
}

# Completion markers are written only after every requested analysis step succeeds.
analysis_success_marker <- function(out_dir) {
  file.path(out_dir, "_SUCCESS")
}

analysis_is_complete <- function(out_dir) {
  file.exists(analysis_success_marker(out_dir))
}

clear_analysis_success <- function(out_dir) {
  marker <- analysis_success_marker(out_dir)
  if (file.exists(marker)) unlink(marker)
  invisible(TRUE)
}

write_analysis_success <- function(out_dir, pipeline, analysis_id) {
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  marker <- analysis_success_marker(out_dir)
  tmp <- paste0(marker, ".tmp-", Sys.getpid())
  lines <- c(
    paste0("pipeline=", pipeline),
    paste0("analysis_id=", analysis_id),
    paste0("completed_at=", format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z"))
  )
  writeLines(lines, tmp, useBytes = TRUE)
  if (!file.rename(tmp, marker)) {
    unlink(tmp)
    stop("Failed to write completion marker: ", marker, call. = FALSE)
  }
  invisible(marker)
}

format_error_calls <- function(max_calls = 12L) {
  calls <- sys.calls()
  if (!length(calls)) return("<no call stack available>")
  calls <- utils::tail(calls, max_calls)
  paste(vapply(calls, function(x) paste(deparse(x), collapse = " "), character(1)),
        collapse = " <- ")
}

#' Read a GSE list file (one ID per line; blank/# lines ignored).
read_gse_list_file <- function(path) {
  if (!file.exists(path)) {
    stop("GSE list file not found: ", path, call. = FALSE)
  }
  lines <- readLines(path, warn = FALSE)
  lines <- trimws(lines)
  lines <- lines[nzchar(lines) & !startsWith(lines, "#")]
  unique(lines)
}

#' Resolve GSE IDs from --gse and/or --gse_list.
read_gse_ids <- function(gse = NULL, gse_list = NULL) {
  ids <- character()
  if (!is.null(gse) && nzchar(as.character(gse))) {
    ids <- c(ids, unlist(strsplit(as.character(gse), "[,;\\s]+")))
  }
  if (!is.null(gse_list) && nzchar(as.character(gse_list))) {
    ids <- c(ids, read_gse_list_file(as.character(gse_list)))
  }
  ids <- unique(trimws(ids))
  ids <- ids[nzchar(ids)]
  if (length(ids) == 0) {
    stop("Provide --gse and/or --gse_list with at least one GSE ID.", call. = FALSE)
  }
  ids
}

#' Resolve GSE directory as work_dir/organism/GSE (canonical layout).
#'
#' @param allow_legacy If TRUE, also accept legacy work_dir/GSE and warn.
resolve_gse_dir <- function(work_dir, organism, gse, create = FALSE, allow_legacy = TRUE) {
  cand1 <- file.path(work_dir, organism, gse)
  cand2 <- file.path(work_dir, gse)
  if (dir.exists(cand1)) {
    return(normalizePath(cand1, winslash = "/", mustWork = FALSE))
  }
  if (isTRUE(allow_legacy) && dir.exists(cand2)) {
    message(
      "Using legacy path work_dir/GSE: ", cand2,
      " Prefer work_dir/", organism, "/", gse
    )
    return(normalizePath(cand2, winslash = "/", mustWork = FALSE))
  }
  if (create) {
    dir.create(cand1, recursive = TRUE, showWarnings = FALSE)
    return(normalizePath(cand1, winslash = "/", mustWork = FALSE))
  }
  normalizePath(cand1, winslash = "/", mustWork = FALSE)
}

#' Normalize comparisons.txt aliases: Control/Treatment <-> group1/group2.
#' Output always has Control, Treatment (+ tissue_type/source if present).
normalize_comparisons <- function(df) {
  if (is.null(df) || nrow(df) == 0) return(df)
  cn <- colnames(df)
  # Map aliases
  if (!("Control" %in% cn) && ("group1" %in% cn)) {
    df$Control <- df$group1
  }
  if (!("Treatment" %in% cn) && ("group2" %in% cn)) {
    df$Treatment <- df$group2
  }
  # Also keep group1/group2 aliases for callers that still use those names
  if (!("group1" %in% colnames(df)) && ("Control" %in% colnames(df))) {
    df$group1 <- df$Control
  }
  if (!("group2" %in% colnames(df)) && ("Treatment" %in% colnames(df))) {
    df$group2 <- df$Treatment
  }
  if (!("Control" %in% colnames(df)) || !("Treatment" %in% colnames(df))) {
    stop("comparisons.txt must have Control/Treatment or group1/group2 columns.", call. = FALSE)
  }
  # Drop empty rows
  df <- df[nzchar(as.character(df$Control)) & nzchar(as.character(df$Treatment)), , drop = FALSE]
  df
}

#' Suppress conflicted / tidyverse masking of base & Bioconductor generics.
#' Call once after attaching dplyr/tidyverse-related packages.
suppress_namespace_conflicts <- function() {
  if ("package:conflicted" %in% search()) {
    try(detach("package:conflicted", unload = TRUE, character.only = FALSE), silent = TRUE)
  }
  if (requireNamespace("conflicted", quietly = TRUE)) {
    try(
      conflicted::conflicts_prefer(
        base::as.factor,
        base::as.character,
        base::unname,
        base::`%in%`,
        base::intersect,
        base::setdiff,
        base::union,
        dplyr::filter,
        dplyr::select,
        dplyr::mutate,
        dplyr::summarise,
        dplyr::rename,
        dplyr::slice,
        dplyr::lag,
        dplyr::lead,
        .quiet = TRUE
      ),
      silent = TRUE
    )
  }
  invisible(TRUE)
}

#' edgeR DE for comparisons with <2 replicates on at least one side.
#' Uses estimateDisp when either side has replicates; otherwise fixed BCV^2.
run_edger_low_replicate <- function(counts_mat, group_factor, bcv_value,
                                    control_level, treatment_level) {
  group_factor <- factor(group_factor, levels = c(control_level, treatment_level))
  n_control <- sum(group_factor == control_level, na.rm = TRUE)
  n_treatment <- sum(group_factor == treatment_level, na.rm = TRUE)
  y <- edgeR::DGEList(counts = counts_mat, group = group_factor)
  min_lib <- min(2L, ncol(y))
  keep <- rowSums(edgeR::cpm(y) > 1) >= min_lib
  y <- y[keep, , keep.lib.sizes = FALSE]
  y <- edgeR::calcNormFactors(y, method = "TMM")
  design <- stats::model.matrix(~ 0 + group_factor)
  colnames(design) <- levels(group_factor)

  if (n_control >= 2L || n_treatment >= 2L) {
    message(
      "edgeR: estimating dispersion from available replicates ",
      "(n_control=", n_control, ", n_treatment=", n_treatment, ")"
    )
    y <- edgeR::estimateDisp(y, design, robust = TRUE)
  } else {
    # edgeR stores dispersion as BCV^2 (see edgeR User's Guide, no-replicate section)
    disp <- as.numeric(bcv_value)^2
    message(
      "WARNING: no biological replicates on either side; using fixed BCV=",
      bcv_value, " (dispersion=", disp, "). Results are exploratory only."
    )
    y$common.dispersion <- disp
    y$tagwise.dispersion <- rep(disp, nrow(y))
  }

  fit <- edgeR::glmFit(y, design)
  lt <- edgeR::glmLRT(fit, contrast = c(-1, 1))
  tempDEG <- as.data.frame(edgeR::topTags(lt, n = Inf))
  tempDEG <- stats::na.omit(tempDEG)
  DEG <- cbind(name = rownames(tempDEG), tempDEG)
  colnames(DEG) <- c("name", "log2FoldChange", "logCPM", "F", "pvalue", "padj")
  attr(DEG, "deg_method") <- if (n_control >= 2L || n_treatment >= 2L) {
    "edgeR_estimateDisp"
  } else {
    "edgeR_fixedBCV"
  }
  DEG
}

#' Choose bulk DE method from per-group sample counts.
#' Returns one of: "DESeq2", "wilcoxon", "edgeR".
choose_bulk_deg_method <- function(n_control, n_treatment) {
  n_control <- as.integer(n_control)
  n_treatment <- as.integer(n_treatment)
  if (is.na(n_control) || is.na(n_treatment) || n_control < 1L || n_treatment < 1L) {
    stop("Each comparison group needs >=1 sample.", call. = FALSE)
  }
  if (n_control >= 2L && n_treatment >= 2L) {
    if (n_control >= 8L && n_treatment >= 8L) {
      return("wilcoxon")
    }
    return("DESeq2")
  }
  "edgeR"
}

#' TRUE if x is a table-like object with >= 1 row.
is_nonempty_df <- function(x) {
  if (is.null(x)) return(FALSE)
  n <- tryCatch(nrow(x), error = function(e) NA_integer_)
  is.finite(n) && as.integer(n) >= 1L
}

#' Strip MSigDB prefixes and turn underscores into spaces (fallback only).
#' Mirrors map_kegg_go_terms.msigdb_to_text (case preserved from gs_name).
msigdb_term_name <- function(term) {
  term <- as.character(term)
  prefixes <- c("GOBP_", "GOCC_", "GOMF_", "KEGG_", "GO_")
  vapply(term, function(t) {
    if (is.na(t) || !nzchar(t)) return(NA_character_)
    tu <- toupper(t)
    for (p in prefixes) {
      if (startsWith(tu, p)) {
        t <- substring(t, nchar(p) + 1L)
        break
      }
    }
    t <- gsub("_", " ", t, fixed = TRUE)
    gsub("\\s+", " ", t)
  }, character(1), USE.NAMES = FALSE)
}

#' Load KEGG id -> official name from pathway list TSV (id\\tname), same as
#' gsva_map_pathway_id_package/database/kegg_pathway_*.tsv.
load_kegg_id2name <- function(path) {
  if (is.null(path) || !nzchar(as.character(path)[1]) || !file.exists(path)) {
    return(character(0))
  }
  df <- utils::read.delim(
    path, header = FALSE, stringsAsFactors = FALSE, quote = "",
    comment.char = "", check.names = FALSE
  )
  if (ncol(df) < 2L) return(character(0))
  pid <- as.character(df[[1]])
  pname <- as.character(df[[2]])
  keep <- nzchar(pid) & nzchar(pname)
  stats::setNames(pname[keep], pid[keep])
}

#' Resolve GeneralFile/KEGG/kegg_pathway_<organism>.tsv (optional fallback path).
resolve_kegg_pathway_index <- function(organism, GeneralFile = NULL, fallback = NULL) {
  org <- as.character(organism)[1]
  cands <- c(
    if (!is.null(GeneralFile) && nzchar(GeneralFile)) {
      file.path(GeneralFile, "KEGG", paste0("kegg_pathway_", org, ".tsv"))
    },
    fallback
  )
  cands <- cands[!is.na(cands) & nzchar(as.character(cands))]
  for (p in cands) {
    if (file.exists(p)) return(normalizePath(p, winslash = "/", mustWork = FALSE))
  }
  NA_character_
}

#' Named character vector: MSigDB gs_name -> official ID (gs_exact_source).
build_gsva_term_id_map <- function(...) {
  dfs <- list(...)
  dfs <- dfs[!vapply(dfs, is.null, logical(1))]
  if (!length(dfs)) return(character(0))
  parts <- lapply(dfs, function(d) {
    if (!all(c("gs_name", "gs_exact_source") %in% names(d))) return(NULL)
    unique(as.data.frame(d[, c("gs_name", "gs_exact_source")], stringsAsFactors = FALSE))
  })
  parts <- parts[!vapply(parts, is.null, logical(1))]
  if (!length(parts)) return(character(0))
  df <- do.call(rbind, parts)
  df <- df[!duplicated(df$gs_name), , drop = FALSE]
  stats::setNames(as.character(df$gs_exact_source), as.character(df$gs_name))
}

#' Official display names aligned with map_kegg_go_terms matched_name:
#' GO via GO.db Term(); KEGG via kegg_pathway_*.tsv (includes species suffix).
build_gsva_term_name_map <- function(id_map, kegg_id2name = NULL) {
  if (is.null(id_map) || !length(id_map)) return(character(0))
  ids <- as.character(id_map)
  names_out <- rep(NA_character_, length(ids))

  go_idx <- grepl("^GO:", ids)
  if (any(go_idx) && requireNamespace("GO.db", quietly = TRUE) &&
      requireNamespace("AnnotationDbi", quietly = TRUE)) {
    go_ids <- unique(ids[go_idx])
    go_terms <- tryCatch(
      AnnotationDbi::Term(go_ids),
      error = function(e) character(0)
    )
    if (length(go_terms)) {
      go_lookup <- as.character(go_terms)
      names(go_lookup) <- names(go_terms)
      names_out[go_idx] <- unname(go_lookup[ids[go_idx]])
    }
  }

  if (!is.null(kegg_id2name) && length(kegg_id2name)) {
    kegg_idx <- !go_idx & nzchar(ids)
    names_out[kegg_idx] <- unname(as.character(kegg_id2name[ids[kegg_idx]]))
  }

  miss <- is.na(names_out) | !nzchar(names_out)
  if (any(miss)) {
    names_out[miss] <- msigdb_term_name(names(id_map)[miss])
  }
  stats::setNames(as.character(names_out), names(id_map))
}

#' Add ID + term_name columns to a GSVA result table (expects a `term` column).
#' term_name prefers official ontology / KEGG list names (matched_name style).
annotate_gsva_term_meta <- function(df, id_map = NULL, name_map = NULL) {
  if (is.null(df) || !is.data.frame(df) || !nrow(df) || !"term" %in% names(df)) {
    return(df)
  }
  terms <- as.character(df$term)
  ids <- if (!is.null(id_map) && length(id_map)) {
    as.character(unname(id_map[terms]))
  } else {
    rep(NA_character_, length(terms))
  }
  ids[is.na(ids)] <- ""
  df$ID <- ids

  nm <- if (!is.null(name_map) && length(name_map)) {
    as.character(unname(name_map[terms]))
  } else {
    rep(NA_character_, length(terms))
  }
  miss <- is.na(nm) | !nzchar(nm)
  if (any(miss)) nm[miss] <- msigdb_term_name(terms[miss])
  df$term_name <- nm

  front <- c("term", "ID", "term_name")
  df[, c(front, setdiff(names(df), front)), drop = FALSE]
}

#' data.table::fwrite only when x has rows; otherwise skip and message.
fwrite_if_nonempty <- function(x, file, ..., sep = ",") {
  if (!is_nonempty_df(x)) {
    message("Skip empty output: ", basename(as.character(file)))
    return(invisible(FALSE))
  }
  data.table::fwrite(x, file = file, sep = sep, ...)
  invisible(TRUE)
}

#' utils::write.csv only when x has rows; otherwise skip and message.
write_csv_if_nonempty <- function(x, file, row.names = TRUE, ...) {
  if (!is_nonempty_df(x)) {
    message("Skip empty output: ", basename(as.character(file)))
    return(invisible(FALSE))
  }
  utils::write.csv(x, file = file, row.names = row.names, ...)
  invisible(TRUE)
}

#' utils::write.table only when x has rows; otherwise skip and message.
write_table_if_nonempty <- function(x, file, ...) {
  if (!is_nonempty_df(x)) {
    message("Skip empty output: ", basename(as.character(file)))
    return(invisible(FALSE))
  }
  utils::write.table(x, file = file, ...)
  invisible(TRUE)
}

#' Cap GSEA result object/data.frame to top N terms by |NES| then padj.
cap_gsea_terms <- function(kk_gse_cut, max_plots = Inf) {
  if (is.null(kk_gse_cut)) return(kk_gse_cut)
  n <- tryCatch(nrow(kk_gse_cut), error = function(e) 0L)
  if (is.null(n) || is.na(n) || n < 1L) return(kk_gse_cut)
  if (!is.finite(max_plots) || max_plots < 0) return(kk_gse_cut)
  max_plots <- as.integer(max_plots)
  if (max_plots == 0L) {
    return(kk_gse_cut[FALSE, ])
  }
  if (n <= max_plots) return(kk_gse_cut)
  df <- as.data.frame(kk_gse_cut)
  if (!"NES" %in% names(df)) {
    return(kk_gse_cut[seq_len(max_plots), ])
  }
  padj <- if ("p.adjust" %in% names(df)) df$p.adjust else rep(1, nrow(df))
  ord <- order(-abs(df$NES), padj, na.last = TRUE)
  kk_gse_cut[ord[seq_len(max_plots)], ]
}

#' Resolve performance-related CLI options (shared by RNA / MicroArray / scRNA).
#'
#' Supported keys in opts: fast, max_gsea_plots, skip_gsea_plots, skip_ssgsea,
#' skip_save_image, skip_gene_cell_exp, skip_network_plots, resolutions, n_workers.
resolve_perf_opts <- function(opts) {
  if (is.null(opts)) opts <- list()
  fast <- isTRUE(opts$fast)

  as_bool <- function(x, default) {
    if (is.null(x) || (is.character(x) && !nzchar(as.character(x)))) return(default)
    if (is.logical(x)) return(isTRUE(x))
    low <- tolower(as.character(x))
    if (low %in% c("true", "t", "1", "yes", "y")) return(TRUE)
    if (low %in% c("false", "f", "0", "no", "n")) return(FALSE)
    default
  }

  max_gsea_plots <- opts$max_gsea_plots
  if (is.null(max_gsea_plots) || (is.character(max_gsea_plots) && !nzchar(as.character(max_gsea_plots)))) {
    # Unlimited by default (and under --fast); only cap when user sets --max_gsea_plots
    max_gsea_plots <- Inf
  } else {
    max_gsea_plots <- suppressWarnings(as.numeric(max_gsea_plots))
    if (is.na(max_gsea_plots)) max_gsea_plots <- Inf
  }
  if (isTRUE(opts$skip_gsea_plots)) max_gsea_plots <- 0

  # ssGSEA always runs when available unless user explicitly sets --skip_ssgsea TRUE
  skip_ssgsea <- as_bool(opts$skip_ssgsea, default = FALSE)
  skip_save_image <- as_bool(opts$skip_save_image, default = fast)
  # gene_cell_exp.csv is always written unless user explicitly sets --skip_gene_cell_exp TRUE
  skip_gene_cell_exp <- as_bool(opts$skip_gene_cell_exp, default = FALSE)
  skip_network_plots <- as_bool(opts$skip_network_plots, default = fast)

  resolutions <- opts$resolutions
  if (is.null(resolutions) || (is.character(resolutions) && !nzchar(as.character(resolutions)))) {
    # Always run the full resolution set unless user overrides --resolutions
    resolutions <- c(0.2, 0.4, 0.6, 0.8, 1.0)
  } else if (is.character(resolutions) || is.numeric(resolutions)) {
    if (length(resolutions) == 1L && grepl("[,;[:space:]]", as.character(resolutions))) {
      resolutions <- as.numeric(unlist(strsplit(as.character(resolutions), "[,;[:space:]]+")))
    } else {
      resolutions <- as.numeric(resolutions)
    }
    resolutions <- resolutions[is.finite(resolutions) & resolutions > 0]
    if (length(resolutions) == 0) {
      resolutions <- c(0.2, 0.4, 0.6, 0.8, 1.0)
    }
  }

  n_workers <- opts$n_workers
  if (is.null(n_workers) || (is.character(n_workers) && !nzchar(as.character(n_workers)))) {
    n_workers <- 1L
  } else {
    n_workers <- suppressWarnings(as.integer(n_workers))
    if (is.na(n_workers) || n_workers < 1L) n_workers <- 1L
  }

  list(
    fast = fast,
    max_gsea_plots = max_gsea_plots,
    skip_ssgsea = skip_ssgsea,
    skip_save_image = skip_save_image,
    skip_gene_cell_exp = skip_gene_cell_exp,
    skip_network_plots = skip_network_plots,
    resolutions = resolutions,
    n_workers = n_workers
  )
}

#' Path to the current Rscript executable.
find_rscript <- function() {
  exe <- file.path(R.home("bin"), if (.Platform$OS.type == "windows") "Rscript.exe" else "Rscript")
  if (file.exists(exe)) return(normalizePath(exe, winslash = "/", mustWork = FALSE))
  Sys.which("Rscript")
}

#' Path of the calling Rscript (--file=...), or NA.
get_script_path <- function() {
  cmd_args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", cmd_args, value = TRUE)
  if (length(file_arg) < 1) return(NA_character_)
  normalizePath(sub("^--file=", "", file_arg[[1]]), winslash = "/", mustWork = FALSE)
}

#' Run many GSE jobs in parallel by spawning child Rscript processes.
#'
#' Each child receives the same CLI args except --gse_list is dropped and
#' --gse / --n_workers 1 are set. Safe on Windows (socket cluster).
#'
#' @param gse_ids character vector of GSE IDs
#' @param shared_args character vector of CLI args for children (must include
#'   --work_dir, --organism, etc.; must NOT include --gse / --gse_list)
#' @param n_workers integer concurrency
#' @param logfile optional batch log path
#' @param script_path path to the runner R script (default: current --file=)
#' @return list of list(gse, status, ok)
parallel_rscript_gse <- function(gse_ids, shared_args, n_workers = 2L,
                                 logfile = NULL, script_path = NULL) {
  gse_ids <- unique(trimws(as.character(gse_ids)))
  gse_ids <- gse_ids[nzchar(gse_ids)]
  if (length(gse_ids) == 0) return(list())

  n_workers <- max(1L, as.integer(n_workers))
  n_workers <- min(n_workers, length(gse_ids))

  if (is.null(script_path) || !nzchar(script_path) || is.na(script_path)) {
    script_path <- get_script_path()
  }
  if (is.na(script_path) || !file.exists(script_path)) {
    stop("Cannot locate runner script for parallel dispatch (--file= missing).", call. = FALSE)
  }
  rscript <- find_rscript()
  if (!nzchar(rscript) || !file.exists(rscript)) {
    stop("Cannot find Rscript executable.", call. = FALSE)
  }

  # Strip any existing --gse / --gse_list / --n_workers from shared_args
  drop_keys <- c("gse", "gse_list", "n_workers")
  keep <- rep(TRUE, length(shared_args))
  i <- 1L
  while (i <= length(shared_args)) {
    tok <- shared_args[[i]]
    if (startsWith(tok, "--")) {
      key <- sub("^--", "", tok)
      key <- sub("=.*$", "", key)
      if (key %in% drop_keys) {
        keep[[i]] <- FALSE
        if (!grepl("=", tok) && i < length(shared_args) &&
            !startsWith(shared_args[[i + 1L]], "--")) {
          keep[[i + 1L]] <- FALSE
          i <- i + 2L
          next
        }
      }
    }
    i <- i + 1L
  }
  shared_args <- shared_args[keep]
  # Force children to be serial to avoid recursive worker spawn
  shared_args <- c(shared_args, "--n_workers", "1")

  if (!is.null(logfile) && nzchar(logfile)) {
    log_message(logfile, paste0(
      "Parallel GSE dispatch: n_workers=", n_workers,
      " | n_gse=", length(gse_ids),
      " | script=", script_path
    ))
  }

  if (n_workers <= 1L || length(gse_ids) == 1L) {
    # Caller should use serial path; still support single-job dispatch
    n_workers <- 1L
  }

  run_one <- function(gse) {
    args <- c(script_path, shared_args, "--gse", gse)
    out <- system2(rscript, args = args, stdout = TRUE, stderr = TRUE)
    status <- attr(out, "status")
    if (is.null(status)) status <- 0L
    list(
      gse = gse,
      status = as.integer(status),
      ok = identical(as.integer(status), 0L),
      output = paste(out, collapse = "\n")
    )
  }

  if (n_workers == 1L) {
    results <- lapply(gse_ids, run_one)
  } else {
    cl <- parallel::makeCluster(n_workers)
    on.exit(try(parallel::stopCluster(cl), silent = TRUE), add = TRUE)
    parallel::clusterExport(
      cl,
      varlist = c("rscript", "script_path", "shared_args"),
      envir = environment()
    )
    results <- parallel::parLapply(cl, gse_ids, run_one)
  }

  if (!is.null(logfile) && nzchar(logfile)) {
    for (r in results) {
      if (isTRUE(r$ok)) {
        log_message(logfile, paste0("PARALLEL OK: ", r$gse))
      } else {
        log_message(logfile, paste0(
          "PARALLEL FAIL: ", r$gse, " | status=", r$status,
          " | ", substr(r$output, 1, 500)
        ))
      }
    }
  }
  results
}

#' Ensure samples_info has Source, Sample, Group (keeps ID if present).
#' Also accepts legacy aliases: orig.ident / new.ident / group.
normalize_samples_info <- function(df) {
  if (is.null(df) || nrow(df) == 0) {
    stop("samples_info.txt is empty.", call. = FALSE)
  }
  cn <- tolower(colnames(df))
  map <- c(
    source = "Source", sample = "Sample", group = "Group", tissue = "tissue",
    id = "ID", `orig.ident` = "ID", `new.ident` = "Sample"
  )
  for (i in seq_along(cn)) {
    key <- cn[[i]]
    if (key %in% names(map)) {
      colnames(df)[i] <- map[[key]]
    }
  }
  # Fill missing Sample/Source from each other when possible
  if (!"Sample" %in% colnames(df) && "Source" %in% colnames(df)) {
    df$Sample <- df$Source
  }
  if (!"Source" %in% colnames(df) && "Sample" %in% colnames(df)) {
    df$Source <- df$Sample
  }
  need <- c("Source", "Sample", "Group")
  miss <- setdiff(need, colnames(df))
  if (length(miss) > 0) {
    stop("samples_info.txt missing columns: ", paste(miss, collapse = ", "), call. = FALSE)
  }
  df$Sample <- as.character(df$Sample)
  df$Source <- as.character(df$Source)
  df$Group <- as.character(df$Group)
  if ("ID" %in% colnames(df)) {
    df$ID <- as.character(df$ID)
  }
  df
}
