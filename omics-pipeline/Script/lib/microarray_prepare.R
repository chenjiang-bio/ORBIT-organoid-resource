# Microarray GEO prepare helpers.
# Download ExpressionSet, auto-build samples_info/comparisons, write gene-level expr.

#' Clean a free-text phenotype string into a group label.
clean_group_label <- function(x) {
  x %>%
    as.character() %>%
    stringr::str_replace_all("[-,:/.; ]+", "_") %>%
    stringr::str_remove("_Technical_replicate_of_[A-Za-z0-9]+$") %>%
    stringr::str_remove("^H\\d+") %>%
    stringr::str_remove("^RNA\\d+") %>%
    stringr::str_remove("^C4\\d+") %>%
    stringr::str_remove("P\\d+$") %>%
    stringr::str_remove("[-_]rep\\d+$") %>%
    stringr::str_remove("[-_]replicate\\d+$") %>%
    stringr::str_remove("[-_]\\d+$") %>%
    stringr::str_remove("ext\\d+$") %>%
    stringr::str_remove("MP\\d+$") %>%
    stringr::str_remove("#\\d+$") %>%
    stringr::str_replace_all("[-,:/.; ]+", "_") %>%
    stringr::str_replace_all("_{2,}", "_") %>%
    stringr::str_replace_all("organoid[_][A-Za-z0-9]+", "organoid") %>%
    stringr::str_replace_all("oranoid[_][A-Za-z0-9]+", "organoid") %>%
    stringr::str_replace_all("organod[_][A-Za-z0-9]+", "organoid") %>%
    stringr::str_replace_all("(?i)ko[_][A-Za-z0-9]+", "ko") %>%
    stringr::str_replace_all("(?i)wt[_][A-Za-z0-9]+", "wt") %>%
    stringr::str_replace_all("[Pp]atient[_][A-Za-z0-9]+", "") %>%
    stringr::str_replace_all("subline+", "subclone") %>%
    stringr::str_replace_all("cms_[A-Za-z0-9]+", "cms") %>%
    stringr::str_replace_all("batch_[A-Za-z0-9]+", "") %>%
    make.names(unique = FALSE) %>%
    stringr::str_replace_all("[-,:/.; ]+", "_") %>%
    stringr::str_replace_all("_{2,}", "_") %>%
    stringr::str_replace_all("(^_+)|(_+$)", "")
}

#' Pick a phenotype column for auto-grouping.
pick_group_column <- function(geo.meta) {
  prefer <- c(
    "source_name_ch1", "title", "characteristics_ch1",
    "characteristics_ch1.1", "genotype", "treatment_protocol_ch1"
  )
  present <- prefer[prefer %in% colnames(geo.meta)]
  if (length(present) == 0) {
    # Fallback: first character column with >1 unique non-NA values
    for (cn in colnames(geo.meta)) {
      if (cn %in% c("sample", "geo_accession")) next
      vals <- unique(na.omit(as.character(geo.meta[[cn]])))
      if (length(vals) >= 2 && length(vals) < nrow(geo.meta)) return(cn)
    }
    stop("Could not find a suitable phenotype column for auto-grouping.")
  }
  # Prefer column with most unique groups among preferred (but not all-unique)
  best <- present[[1]]
  best_n <- -1
  for (cn in present) {
    n <- length(unique(na.omit(as.character(geo.meta[[cn]]))))
    if (n >= 2 && n > best_n && n < nrow(geo.meta)) {
      best <- cn
      best_n <- n
    }
  }
  best
}

#' Build samples_info from GEO pData (non-interactive).
build_samples_info_from_geo <- function(geo.meta, replace_chars_fun) {
  if (!"sample" %in% colnames(geo.meta)) {
    if ("geo_accession" %in% colnames(geo.meta)) {
      geo.meta$sample <- geo.meta$geo_accession
    } else {
      geo.meta$sample <- rownames(as.data.frame(geo.meta))
    }
  }

  group_col <- pick_group_column(geo.meta)
  raw_group <- as.character(geo.meta[[group_col]])
  group_clean <- vapply(raw_group, clean_group_label, character(1), USE.NAMES = FALSE)
  group_clean <- vapply(group_clean, replace_chars_fun, character(1), USE.NAMES = FALSE)

  samples_info <- data.frame(
    Sample = as.character(geo.meta$sample),
    Group = group_clean,
    stringsAsFactors = FALSE
  )
  # Source = Group_repN within each group
  samples_info <- samples_info %>%
    dplyr::group_by(Group) %>%
    dplyr::mutate(Source = paste0(Group, "_rep", dplyr::row_number())) %>%
    dplyr::ungroup() %>%
    dplyr::relocate(Sample, Source, Group) %>%
    as.data.frame()

  # Also keep Group_1 (= Group) for comparison source column compatibility
  samples_info$Group_1 <- samples_info$Group
  attr(samples_info, "group_column") <- group_col
  samples_info
}

#' Prefer control-like labels as Control when building pairwise comparisons.
is_control_like <- function(x) {
  grepl("(?i)(?:^|_)(wt|wild_type|control|con|ctrl|healthy|normal|vehicle|untreated|mock)(?:$|_)", x)
}

#' Build Control-vs-Treatment comparisons from samples_info Group.
#' Template: each non-control group is compared against the preferred control
#' (not all pairwise combn). If no control-like label exists, the shortest
#' group name is used as Control and remaining groups as Treatment.
build_comparisons_from_samples <- function(samples_info, replace_chars_fun) {
  groups <- unique(as.character(samples_info$Group))
  groups <- groups[nzchar(groups) & !is.na(groups)]
  if (length(groups) < 2) {
    stop("Auto-grouping produced fewer than 2 groups; cannot build comparisons.")
  }

  control_hits <- groups[is_control_like(groups)]
  if (length(control_hits) >= 1) {
    # Prefer shortest control-like label when several match
    control_hits <- control_hits[order(nchar(control_hits), control_hits)]
    control <- control_hits[[1]]
  } else {
    groups_ord <- groups[order(nchar(groups), groups)]
    control <- groups_ord[[1]]
    message(
      "No control-like group label found; using '", control,
      "' as Control template. Review comparisons.txt before analysis."
    )
  }

  treatments <- setdiff(groups, control)
  if (length(treatments) == 0) {
    stop("Auto comparison template found only the control group: ", control)
  }

  comp <- data.frame(
    Control = control,
    Treatment = treatments,
    source = "Group_1",
    stringsAsFactors = FALSE
  )

  comp$Control <- vapply(comp$Control, replace_chars_fun, character(1), USE.NAMES = FALSE)
  comp$Treatment <- vapply(comp$Treatment, replace_chars_fun, character(1), USE.NAMES = FALSE)
  message(
    "Auto comparisons (Control vs each Treatment): Control=", control,
    " | n_treatment=", nrow(comp)
  )
  comp
}

#' Aggregate probe-level matrix to Symbol by mean.
aggregate_by_symbol <- function(df) {
  # df: Probe_ID + Symbol + sample columns OR Symbol + sample columns
  num_cols <- setdiff(colnames(df), c("Probe_ID", "Symbol"))
  df %>%
    dplyr::select(Symbol, dplyr::all_of(num_cols)) %>%
    dplyr::group_by(Symbol) %>%
    dplyr::summarise(
      dplyr::across(dplyr::everything(), ~ mean(as.numeric(.), na.rm = TRUE)),
      .groups = "drop"
    ) %>%
    dplyr::filter(!is.na(Symbol), nzchar(as.character(Symbol))) %>%
    as.data.frame()
}

#' Detect whether probe IDs already look like gene symbols.
looks_like_symbols <- function(ids, species_db, min_frac = 0.3) {
  ids <- unique(as.character(ids))
  ids <- ids[!is.na(ids) & nzchar(ids)]
  if (length(ids) == 0) return(FALSE)
  probe <- head(ids, min(2000L, length(ids)))
  mapped <- tryCatch({
    AnnotationDbi::select(
      species_db, keys = probe, keytype = "SYMBOL", columns = "SYMBOL"
    )
  }, error = function(e) NULL)
  if (is.null(mapped)) return(FALSE)
  frac <- mean(probe %in% unique(mapped$SYMBOL[!is.na(mapped$SYMBOL)]))
  frac >= min_frac
}

#' Map probes to gene symbols using GPL annotation (auto strategy).
map_probes_to_symbols <- function(exprs_dt, platform_dt, species_db, log_fun = message) {
  # exprs_dt: first col currently named Symbol but may be probe IDs
  exprs_dt <- as.data.frame(exprs_dt, check.names = FALSE)
  colnames(exprs_dt)[1] <- "Probe_ID"
  exprs_dt$Probe_ID <- as.character(exprs_dt$Probe_ID)

  if (looks_like_symbols(exprs_dt$Probe_ID, species_db)) {
    log_fun("Expression IDs already look like gene symbols; skip GPL remap.")
    out <- exprs_dt
    colnames(out)[1] <- "Symbol"
    return(aggregate_by_symbol(out))
  }

  platform_dt <- as.data.frame(platform_dt, check.names = FALSE)
  colnames(platform_dt)[1] <- "Probe_ID"
  platform_dt$Probe_ID <- as.character(platform_dt$Probe_ID)
  cn <- colnames(platform_dt)

  # Strategy 1: GENE SYMBOL column
  sym_col <- grep("(?i)(gene[ _]?symbol|^symbol$|orf)", cn, value = TRUE)[1]
  if (!is.na(sym_col) && nzchar(sym_col)) {
    log_fun(paste0("Probe map strategy: SYMBOL column = ", sym_col))
    anno <- platform_dt %>%
      dplyr::select(Probe_ID, Symbol = dplyr::all_of(sym_col)) %>%
      tidyr::separate_longer_delim(Symbol, delim = " /// ") %>%
      dplyr::mutate(Symbol = stringr::str_trim(as.character(Symbol))) %>%
      dplyr::filter(!is.na(Symbol), Symbol != "", Symbol != "---") %>%
      dplyr::distinct(Probe_ID, Symbol)
    if (nrow(anno) > 0) {
      merged <- dplyr::inner_join(exprs_dt, anno, by = "Probe_ID")
      if (nrow(merged) > 0) return(aggregate_by_symbol(merged))
    }
  }

  # Strategy 2: ENTREZID
  entrez_col <- grep("(?i)(entrez|gene_id|geneid)", cn, value = TRUE)[1]
  if (is.na(entrez_col)) {
    # content-based: majority digits
    ratios <- vapply(cn, function(col) {
      v <- as.character(platform_dt[[col]])
      mean(grepl("^\\d+$", v[!is.na(v) & nzchar(v)]), na.rm = TRUE)
    }, numeric(1))
    if (any(ratios >= 0.2, na.rm = TRUE)) {
      entrez_col <- names(ratios)[which.max(ratios)]
    }
  }
  if (!is.na(entrez_col) && nzchar(entrez_col)) {
    log_fun(paste0("Probe map strategy: ENTREZ column = ", entrez_col))
    plat <- platform_dt %>%
      dplyr::mutate(
        ENTREZID = vapply(as.character(.data[[entrez_col]]), function(x) {
          entries <- unlist(stringr::str_split(x, "///|,|;"))
          entries <- stringr::str_trim(entries)
          hit <- entries[grepl("^\\d+$", entries)][1]
          if (is.na(hit)) NA_character_ else hit
        }, character(1))
      ) %>%
      dplyr::filter(!is.na(ENTREZID), ENTREZID != "") %>%
      dplyr::distinct(Probe_ID, ENTREZID)
    symbol_map <- tryCatch({
      AnnotationDbi::select(
        species_db, keys = unique(plat$ENTREZID),
        columns = "SYMBOL", keytype = "ENTREZID"
      ) %>%
        dplyr::distinct(ENTREZID, SYMBOL) %>%
        dplyr::filter(!is.na(SYMBOL)) %>%
        dplyr::rename(Symbol = SYMBOL)
    }, error = function(e) NULL)
    if (!is.null(symbol_map) && nrow(symbol_map) > 0) {
      anno <- dplyr::inner_join(plat, symbol_map, by = "ENTREZID") %>%
        dplyr::distinct(Probe_ID, Symbol)
      merged <- dplyr::inner_join(exprs_dt, anno, by = "Probe_ID")
      if (nrow(merged) > 0) return(aggregate_by_symbol(merged))
    }
  }

  # Strategy 3: ACCNUM / RefSeq
  gb_col <- grep("(?i)(gb_acc|accnum|refseq|genbank)", cn, value = TRUE)[1]
  if (!is.na(gb_col) && nzchar(gb_col)) {
    log_fun(paste0("Probe map strategy: ACCNUM column = ", gb_col))
    refseq_pattern <- "^[NX][MR]_\\d+"
    plat <- platform_dt %>%
      dplyr::mutate(
        ACCNUM = vapply(as.character(.data[[gb_col]]), function(x) {
          entries <- unlist(stringr::str_split(x, "///"))
          entries <- stringr::str_trim(entries)
          for (entry in entries) {
            id <- stringr::str_trim(unlist(stringr::str_split(entry, "//"))[1])
            id <- sub("\\.\\d+$", "", id)
            if (grepl(refseq_pattern, id)) return(id)
          }
          id <- stringr::str_trim(unlist(stringr::str_split(entries[1], "//"))[1])
          id <- sub("\\.\\d+$", "", id)
          if (is.na(id) || !nzchar(id)) NA_character_ else id
        }, character(1))
      ) %>%
      dplyr::filter(!is.na(ACCNUM), ACCNUM != "") %>%
      dplyr::distinct(Probe_ID, ACCNUM)
    symbol_map <- tryCatch({
      AnnotationDbi::select(
        species_db, keys = unique(plat$ACCNUM),
        columns = "SYMBOL", keytype = "ACCNUM"
      ) %>%
        dplyr::distinct(ACCNUM, SYMBOL) %>%
        dplyr::filter(!is.na(SYMBOL)) %>%
        dplyr::rename(Symbol = SYMBOL)
    }, error = function(e) NULL)
    if (!is.null(symbol_map) && nrow(symbol_map) > 0) {
      anno <- dplyr::inner_join(plat, symbol_map, by = "ACCNUM") %>%
        dplyr::distinct(Probe_ID, Symbol)
      merged <- dplyr::inner_join(exprs_dt, anno, by = "Probe_ID")
      if (nrow(merged) > 0) return(aggregate_by_symbol(merged))
    }
  }

  # Strategy 4: gene_assignment (Affymetrix-style)
  if ("gene_assignment" %in% cn) {
    log_fun("Probe map strategy: gene_assignment")
    anno <- platform_dt %>%
      dplyr::mutate(
        Symbol = stringr::str_trim(
          stringr::str_split(as.character(gene_assignment), "//", simplify = TRUE)[, 2]
        )
      ) %>%
      dplyr::select(Probe_ID, Symbol) %>%
      dplyr::filter(!is.na(Symbol), Symbol != "", Symbol != "---") %>%
      dplyr::distinct(Probe_ID, Symbol)
    if (nrow(anno) > 0) {
      merged <- dplyr::inner_join(exprs_dt, anno, by = "Probe_ID")
      if (nrow(merged) > 0) return(aggregate_by_symbol(merged))
    }
  }

  stop("Failed to map probes to gene symbols with available GPL annotation.")
}

#' Download one GSE with GEOquery into work_dir/Data/<organism>/<GSE>.
download_geo_gse <- function(gse, organism, work_dir, log_fun = message) {
  dest <- file.path(work_dir, "Data", organism, gse)
  dir.create(dest, recursive = TRUE, showWarnings = FALSE)
  log_fun(paste0("GEOquery download: ", gse, " -> ", dest))
  GEOquery::getGEO(gse, destdir = dest, getGPL = TRUE)
  dest
}

#' Full prepare: download (optional) + samples_info + comparisons + ExprMatrix.txt
#'
#' @return list(gse_dir, expr_path, samples_path, comps_path)
prepare_microarray_gse <- function(
    gse, organism, work_dir, GeneralFile, GEOMods, species_db,
    download = TRUE, force = FALSE, log_fun = message
) {
  gse_dir <- file.path(work_dir, organism, gse)
  dir.create(gse_dir, recursive = TRUE, showWarnings = FALSE)
  gse_dir <- normalizePath(gse_dir, winslash = "/", mustWork = FALSE)

  expr_path <- file.path(gse_dir, paste(gse, organism, "ExprMatrix.txt", sep = "."))
  samples_path <- file.path(gse_dir, "samples_info.txt")
  comps_path <- file.path(gse_dir, "comparisons.txt")

  already <- file.exists(expr_path) && file.exists(samples_path) && file.exists(comps_path)
  if (already && !isTRUE(force)) {
    log_fun(paste0("Prepared files already exist for ", gse, "; skip prepare (use --force_prepare TRUE to overwrite)."))
    return(list(
      gse_dir = gse_dir, expr_path = expr_path,
      samples_path = samples_path, comps_path = comps_path
    ))
  }

  data_dir <- file.path(work_dir, "Data", organism, gse)
  if (isTRUE(download) || !dir.exists(data_dir) || length(list.files(data_dir)) == 0) {
    download_geo_gse(gse, organism, work_dir, log_fun = log_fun)
  } else {
    log_fun(paste0("Using existing GEO cache: ", data_dir))
  }

  log_fun(paste0("Loading ExpressionSet for ", gse))
  gse_list <- GEOquery::getGEO(GEO = gse, getGPL = FALSE, destdir = data_dir)
  geo.data <- gse_list[[1]]
  geo.meta <- Biobase::pData(geo.data) %>%
    data.table::as.data.table(keep.rownames = "sample")

  # Raw expression (probe-level)
  exprs_raw <- Biobase::exprs(geo.data) %>%
    data.table::as.data.table(keep.rownames = "Symbol")
  # Keep GSM-like sample IDs
  sample_cols <- colnames(exprs_raw)[-1]
  colnames(exprs_raw) <- c(
    "Symbol",
    stringr::str_extract(sample_cols, "^[^_]+")
  )

  # samples_info + comparisons
  replace_fun <- GEOMods$replace_chars
  samples_info <- build_samples_info_from_geo(geo.meta, replace_fun)
  log_fun(paste0(
    "Auto-grouping column: ", attr(samples_info, "group_column"),
    " | n_groups=", length(unique(samples_info$Group))
  ))
  comparisons <- build_comparisons_from_samples(samples_info, replace_fun)
  log_fun(paste0("Auto comparisons: ", nrow(comparisons), " pairs"))

  data.table::fwrite(samples_info, samples_path, sep = "\t")
  data.table::fwrite(comparisons, comps_path, sep = "\t")

  # GPL annotation -> gene symbols
  soft_files <- list.files(data_dir, pattern = "\\.soft\\.gz$", full.names = FALSE)
  if (length(soft_files) == 0) {
    # Retry getGPL
    GEOquery::getGEO(gse, destdir = data_dir, getGPL = TRUE)
    soft_files <- list.files(data_dir, pattern = "\\.soft\\.gz$", full.names = FALSE)
  }
  if (length(soft_files) == 0) {
    stop("No GPL .soft.gz found under ", data_dir)
  }
  gpl_name <- sub("\\.soft\\.gz$", "", soft_files[[1]])
  log_fun(paste0("Loading GPL: ", gpl_name))
  geo.platform <- GEOquery::getGEO(gpl_name, destdir = data_dir, getGPL = FALSE)
  platform_dt <- GEOMods$getGPLTable(geo.platform)

  expr_mat <- map_probes_to_symbols(
    exprs_dt = exprs_raw,
    platform_dt = platform_dt,
    species_db = species_db,
    log_fun = log_fun
  )

  # Align sample columns to samples_info$Sample when possible
  keep_cols <- c("Symbol", intersect(samples_info$Sample, colnames(expr_mat)))
  if (length(keep_cols) < 3) {
    # fall back to all numeric columns
    keep_cols <- colnames(expr_mat)
  }
  expr_mat <- expr_mat[, keep_cols, drop = FALSE]

  data.table::fwrite(expr_mat, expr_path, sep = "\t")
  log_fun(paste0("Wrote expression matrix: ", expr_path,
                 " | genes=", nrow(expr_mat),
                 " | samples=", ncol(expr_mat) - 1))

  list(
    gse_dir = gse_dir, expr_path = expr_path,
    samples_path = samples_path, comps_path = comps_path
  )
}
