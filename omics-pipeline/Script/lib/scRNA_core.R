# scRNA-seq analysis core functions. Sourced by run_scRNA_seq.R.


#' Put data/group/resolution/type[/celltype] at the front of a result table.
#' Used for Marker/DEGs (type after resolution) and pseudobulk CSVs (all three).
annotate_sc_csv_meta <- function(df, resolution = NULL, type = NULL, celltype = NULL,
                                 data = NULL, group = NULL) {
  if (is.null(df) || !is.data.frame(df)) return(df)
  if (!is.null(data)) df$data <- as.character(data)
  if (!is.null(group)) df$group <- as.character(group)
  if (!is.null(resolution)) df$resolution <- as.character(resolution)
  if (!is.null(type)) df$type <- as.character(type)
  if (!is.null(celltype)) df$celltype <- as.character(celltype)
  front <- c("data", "group", "resolution", "type", "celltype")
  front <- front[front %in% names(df)]
  rest <- setdiff(names(df), front)
  df[, c(front, rest), drop = FALSE]
}

#' Offline ENSEMBL/ENTREZID -> SYMBOL conversion (aggregate duplicates).
convert_id_to_symbols_offline <- function(count_matrix, organism = c("hsa", "mmu")) {
  organism <- match.arg(organism)
  if (organism == "hsa") {
    if (!requireNamespace("org.Hs.eg.db", quietly = TRUE)) {
      stop("Please install Bioconductor package org.Hs.eg.db")
    }
    orgdb <- org.Hs.eg.db::org.Hs.eg.db
  } else {
    if (!requireNamespace("org.Mm.eg.db", quietly = TRUE)) {
      stop("Please install Bioconductor package org.Mm.eg.db")
    }
    orgdb <- org.Mm.eg.db::org.Mm.eg.db
  }

  gene_ids <- rownames(count_matrix)
  if (is.null(gene_ids)) stop("count_matrix must have rownames (gene IDs)")

  if (all(grepl("^ENS[A-Z]*G[0-9]{11}$", gene_ids))) {
    id_type <- "ENSEMBL"
  } else if (all(grepl("^[0-9]+$", gene_ids))) {
    id_type <- "ENTREZID"
  } else {
    message("Row names are not ENSEMBL/ENTREZ; assuming SYMBOL, skip conversion.")
    return(count_matrix)
  }

  message("Detected ID type: ", id_type, " (organism: ", organism, "), mapping...")
  mapped <- AnnotationDbi::select(orgdb, keys = gene_ids, columns = "SYMBOL", keytype = id_type)
  mapped <- mapped[!is.na(mapped$SYMBOL) & mapped$SYMBOL != "", , drop = FALSE]
  mapped <- mapped[!duplicated(mapped[[id_type]]), , drop = FALSE]
  symbol_vec_all <- mapped$SYMBOL[match(gene_ids, mapped[[id_type]])]
  keep <- !is.na(symbol_vec_all) & symbol_vec_all != ""
  if (sum(keep) == 0) stop("No genes mapped to SYMBOL. Check ID type / OrgDb.")

  sub_mat <- count_matrix[keep, , drop = FALSE]
  mat_num <- as.matrix(sub_mat)
  if (!is.numeric(mat_num)) {
    mat_num <- matrix(as.numeric(mat_num), nrow = nrow(sub_mat), ncol = ncol(sub_mat))
    colnames(mat_num) <- colnames(sub_mat)
  }
  symbol_vec <- symbol_vec_all[keep]
  aggregated <- rowsum(mat_num, group = symbol_vec)
  rn <- rownames(aggregated)
  bad <- is.na(rn) | rn == ""
  if (any(bad)) aggregated <- aggregated[!bad, , drop = FALSE]
  message("Mapping done: kept ", nrow(aggregated), " genes (duplicates merged).")
  aggregated
}


#' Load ExprMatrix/ into a Seurat object (10x / h5 / csv-txt).
#' Sets meta.data$Source to the batch key used to join samples_info
#' (library index, GSM, folder name, or barcode prefix).
load_counts_to_seurat <- function(data_dir, organism, convert_id_to_symbols_offline) {
  data_dir <- normalizePath(data_dir, winslash = "/", mustWork = FALSE)
  if (!dir.exists(data_dir)) {
    stop("ExprMatrix directory not found: ", data_dir, call. = FALSE)
  }

  # ---- helpers (local) ----
  is_10x_dir <- function(d) {
    any(file.exists(file.path(d, c("matrix.mtx.gz", "matrix.mtx"))))
  }

  # Materialize clean barcodes/features/matrix names when GEO prefixes exist
  resolve_10x_dir <- function(d) {
    if (is_10x_dir(d)) return(d)
    mats <- list.files(d, pattern = "(^|_)matrix\\.mtx(\\.gz)?$", full.names = TRUE)
    if (length(mats) != 1L) return(NULL)
    mat <- mats[[1]]
    pref <- sub("(^|.*_)matrix\\.mtx(\\.gz)?$", "\\1", basename(mat))
    # pref may be "" or "GSM123_" 
    bc <- list.files(d, pattern = paste0("^", pref, "barcodes\\.tsv(\\.gz)?$"), full.names = TRUE)
    ft <- list.files(d, pattern = paste0("^", pref, "(features|genes)\\.tsv(\\.gz)?$"), full.names = TRUE)
    if (length(bc) != 1L || length(ft) != 1L) return(NULL)
    tmp <- tempfile(pattern = "tenx_")
    dir.create(tmp)
    file.copy(mat, file.path(tmp, ifelse(grepl("\\.gz$", mat), "matrix.mtx.gz", "matrix.mtx")))
    file.copy(bc, file.path(tmp, ifelse(grepl("\\.gz$", bc), "barcodes.tsv.gz", "barcodes.tsv")))
    ft_dest <- if (grepl("genes", basename(ft), ignore.case = TRUE)) {
      ifelse(grepl("\\.gz$", ft), "genes.tsv.gz", "genes.tsv")
    } else {
      ifelse(grepl("\\.gz$", ft), "features.tsv.gz", "features.tsv")
    }
    file.copy(ft, file.path(tmp, ft_dest))
    message(">>> Normalized prefixed 10x triplet under temporary dir")
    tmp
  }

  gsm_prefix <- function(fname) {
    b <- basename(fname)
    m <- regmatches(b, regexpr("^GSM[0-9]+", b))
    if (length(m) == 1L && nzchar(m)) return(m)
    stringr::str_split(b, "_|\\.", n = 2)[[1]][1]
  }

  list_text_matrices <- function(d) {
    files <- list.files(
      d,
      pattern = "\\.(csv|txt|tsv)(\\.(gz|bz2))?$",
      full.names = FALSE,
      ignore.case = TRUE
    )
    # Exclude 10x sidecar names
    files[!grepl("^(.*_)?(barcodes|features|genes)\\.", files, ignore.case = TRUE)]
  }

  read_text_matrix <- function(path) {
    ct <- data.table::fread(path, data.table = FALSE, check.names = FALSE)
    if (ncol(ct) < 2) stop("Matrix has <2 columns: ", path)
    # First column = gene IDs (header may be empty)
    gene_col <- ct[[1]]
    mat <- as.matrix(ct[, -1, drop = FALSE])
    storage.mode(mat) <- "numeric"
    rownames(mat) <- as.character(gene_col)
    # Drop empty / NA gene rows
    keep <- !is.na(rownames(mat)) & nzchar(rownames(mat))
    mat <- mat[keep, , drop = FALSE]
    # If orientation looks like cells x genes, transpose
    if (nrow(mat) > 0 && ncol(mat) > 0) {
      gene_like_rows <- mean(grepl("^[A-Za-z0-9].*", rownames(mat)[seq_len(min(20, nrow(mat)))]))
      barcode_like_cols <- mean(grepl("^[ACGT]{6,}|-", colnames(mat)[seq_len(min(20, ncol(mat)))], ignore.case = TRUE))
      if (nrow(mat) < ncol(mat) / 5 && barcode_like_cols < 0.2 && gene_like_rows < 0.5) {
        message("Transposing matrix (detected cells x genes): ", basename(path))
        mat <- t(mat)
      }
    }
    mat
  }

  sub_dirs_all <- list.dirs(data_dir, recursive = FALSE, full.names = TRUE)
  tenx_subs <- sub_dirs_all[vapply(sub_dirs_all, function(d) {
    !is.null(resolve_10x_dir(d)) || is_10x_dir(d)
  }, logical(1))]
  h5_files <- list.files(data_dir, pattern = "\\.h5$", full.names = TRUE, ignore.case = TRUE)
  txt_files <- list_text_matrices(data_dir)
  root_10x <- resolve_10x_dir(data_dir)

  scRNA_all <- NULL

  if (!is.null(root_10x) && length(tenx_subs) == 0L) {
    message(">>> Detected 10x format (single folder)...")
    counts <- Seurat::Read10X(data.dir = root_10x)
    scRNA_all <- Seurat::CreateSeuratObject(counts = counts, min.cells = 3, min.features = 200)
    # Merged multi-sample 10x: barcodes usually end with -1, -2, ...
    bc <- colnames(scRNA_all)
    if (all(grepl("-[0-9]+$", bc))) {
      scRNA_all$Source <- sub(".*-", "", bc)
      message("Source = barcode library suffix (-N); map via samples_info$ID")
    } else {
      scRNA_all$Source <- as.character(scRNA_all$orig.ident)
      message("Source = orig.ident")
    }
    print(table(scRNA_all$Source))

  } else if (length(tenx_subs) > 0L) {
    message(">>> Detected multiple 10x sample folders...")
    resolved <- vapply(tenx_subs, function(d) {
      r <- resolve_10x_dir(d)
      if (is.null(r)) d else r
    }, character(1))
    sample_name <- basename(tenx_subs)
    print(sample_name)
    # Name dirs so cell barcodes / orig.ident use folder names (usually GSM)
    names(resolved) <- sample_name
    counts <- Seurat::Read10X(data.dir = resolved)
    scRNA_all <- Seurat::CreateSeuratObject(counts = counts, min.cells = 3, min.features = 200)
    # Cell names: <folder>_<barcode>; join via samples_info$Sample
    scRNA_all$Source <- stringr::str_split_fixed(colnames(scRNA_all), "_", 2)[, 1]
    message("Source = folder name (usually GSM); map via samples_info$Sample")
    print(table(scRNA_all$Source))

  } else if (length(h5_files) > 0L) {
    message(">>> Detected h5 files...")
    sceList <- lapply(h5_files, function(filepath) {
      message("Reading: ", basename(filepath))
      obj <- Seurat::Read10X_h5(filepath)
      if (is.list(obj) && "Gene Expression" %in% names(obj)) {
        obj <- obj[["Gene Expression"]]
      }
      obj
    })
    ids <- vapply(h5_files, gsm_prefix, character(1))
    names(sceList) <- ids
    for (i in seq_along(sceList)) {
      colnames(sceList[[i]]) <- paste0(ids[[i]], "_", colnames(sceList[[i]]))
    }
    # Align genes across samples
    common_genes <- Reduce(intersect, lapply(sceList, rownames))
    if (length(common_genes) < 100) {
      stop("Too few common genes across h5 files: ", length(common_genes))
    }
    sceList <- lapply(sceList, function(m) m[common_genes, , drop = FALSE])
    merge_matrix <- do.call(cbind, sceList)
    scRNA_all <- Seurat::CreateSeuratObject(counts = merge_matrix, min.cells = 3, min.features = 200)
    scRNA_all$Source <- stringr::str_split_fixed(colnames(scRNA_all), "_", 2)[, 1]
    message("Source = GSM prefix from h5 filename; map via samples_info$Sample")
    print(table(scRNA_all$Source))

  } else if (length(txt_files) > 1L) {
    message(">>> Detected multiple text matrices (csv/txt/tsv)...")
    scelist <- lapply(txt_files, function(pro) {
      message("Reading: ", pro)
      mat <- read_text_matrix(file.path(data_dir, pro))
      sid <- gsm_prefix(pro)
      colnames(mat) <- paste(sid, colnames(mat), sep = "_")
      mat
    })
    common_genes <- Reduce(intersect, lapply(scelist, rownames))
    message("Common genes found: ", length(common_genes))
    if (length(common_genes) < 100) {
      stop("Too few common genes across text matrices: ", length(common_genes))
    }
    bigct <- do.call(cbind, lapply(scelist, function(ct) ct[common_genes, , drop = FALSE]))
    bigct <- convert_id_to_symbols_offline(bigct, organism)
    rownames(bigct) <- gsub("__chr.*", "", rownames(bigct))
    scRNA_all <- Seurat::CreateSeuratObject(counts = bigct, min.cells = 3, min.features = 200)
    scRNA_all$Source <- stringr::str_split_fixed(colnames(scRNA_all), "_", 2)[, 1]
    message("Source = GSM/file prefix; map via samples_info$Sample")
    print(table(scRNA_all$Source))

  } else if (length(txt_files) == 1L) {
    message(">>> Detected single merged text matrix (csv/txt/tsv)...")
    mat <- read_text_matrix(file.path(data_dir, txt_files[[1]]))
    mat <- convert_id_to_symbols_offline(mat, organism)
    rownames(mat) <- gsub("__chr.*", "", rownames(mat))
    scRNA_all <- Seurat::CreateSeuratObject(counts = mat, min.cells = 3, min.features = 200)
    cn <- colnames(scRNA_all)
    if (all(grepl("_", cn))) {
      scRNA_all$Source <- stringr::str_split_fixed(cn, "_", 2)[, 1]
      message("Source = barcode prefix before '_'; map via samples_info (Sample/Source/ID or aliases)")
    } else if (all(grepl("-[0-9]+$", cn))) {
      scRNA_all$Source <- sub(".*-", "", cn)
      message("Source = barcode library suffix; map via samples_info$ID")
    } else {
      scRNA_all$Source <- as.character(scRNA_all$orig.ident)
    }
    print(table(scRNA_all$Source))

  } else {
    stop(
      "No supported expression matrix format found under: ", data_dir, "\n",
      "Expected one of: 10x (matrix.mtx), multiple 10x folders, .h5, or csv/txt/tsv matrices.",
      call. = FALSE
    )
  }

  scRNA_all
}


#' Load organism-specific GeneralFile resources (SingleR, CellMarker, scType, msigdbr, ssGSEA).
load_scRNA_resources <- function(GeneralFile, organism) {
  res <- list()

  # SingleR references
  if (organism == "hsa") {
    res$ref_singleR <- readRDS(file.path(GeneralFile, "SingleR", "HumanPrimaryCellAtlasData.rds"))
    res$OrgDb <- "org.Hs.eg.db"
    res$species <- "Homo sapiens"
    res$bcv_value <- 0.4
    res$tab <- "^MT-"
    cm_path <- file.path(GeneralFile, "CellMarker", "cellMarker_Hs.txt")
  } else if (organism == "mmu") {
    res$ref_singleR <- readRDS(file.path(GeneralFile, "SingleR", "MouseRNAseqData.rds"))
    res$OrgDb <- "org.Mm.eg.db"
    res$species <- "Mus musculus"
    res$bcv_value <- 0.1
    res$tab <- "^mt-"
    cm_path <- file.path(GeneralFile, "CellMarker", "cellMarker_Mm.txt")
  } else {
    stop("organism must be hsa or mmu", call. = FALSE)
  }

  if (file.exists(cm_path)) {
    res$cellmarker <- data.table::fread(cm_path)
  } else {
    warning("CellMarker file missing: ", cm_path)
    res$cellmarker <- data.table::data.table()
  }

  ss_path <- file.path(GeneralFile, "ssGSEA", "ssGSEA_Hs.rds")
  if (file.exists(ss_path)) {
    res$ssGSEA_list <- readRDS(ss_path)
  } else {
    warning("ssGSEA resource missing: ", ss_path, " (ssGSEA steps will be skipped if reached)")
    res$ssGSEA_list <- NULL
  }

  # MSigDB gene sets
  KEGG_df_all <- msigdbr::msigdbr(species = res$species, category = "C2", subcategory = "CP:KEGG")
  KEGG_df <- dplyr::select(KEGG_df_all, gs_name, gs_exact_source, gene_symbol)
  res$kegg_list <- split(KEGG_df$gene_symbol, KEGG_df$gs_name)

  GO_df_all <- msigdbr::msigdbr(species = res$species, category = "C5")
  GO_df <- dplyr::select(GO_df_all, gs_name, gene_symbol, gs_exact_source, gs_subcat)
  GO_df <- GO_df[GO_df$gs_subcat != "HPO", ]
  res$go_list <- split(GO_df$gene_symbol, GO_df$gs_name)
  res$gsva_term_id_map <- build_gsva_term_id_map(GO_df, KEGG_df)
  kegg_index <- resolve_kegg_pathway_index(organism, GeneralFile = GeneralFile)
  kegg_id2name <- load_kegg_id2name(kegg_index)
  if (!length(kegg_id2name)) {
    warning(
      "KEGG pathway name index not found for organism=", organism,
      " (expected GeneralFile/KEGG/kegg_pathway_", organism, ".tsv); ",
      "GSVA term_name for KEGG will fall back to stripped MSigDB names."
    )
  }
  res$gsva_term_name_map <- build_gsva_term_name_map(res$gsva_term_id_map, kegg_id2name)

  # scType helpers + tissue vocabulary from ScTypeDB_full.xlsx
  source(file.path(GeneralFile, "scType", "gene_sets_prepare.R"))
  source(file.path(GeneralFile, "scType", "sctype_score_.R"))
  res$db_ <- file.path(GeneralFile, "scType", "ScTypeDB_full.xlsx")
  if (!file.exists(res$db_)) {
    stop("ScType database not found: ", res$db_, call. = FALSE)
  }
  res$sctype_tissues <- list_sctype_tissues(res$db_)

  res
}

#' Read allowed ScType tissueType values from ScTypeDB_full.xlsx.
list_sctype_tissues <- function(db_path) {
  if (!requireNamespace("openxlsx", quietly = TRUE)) {
    stop("Package 'openxlsx' is required to read ScTypeDB_full.xlsx", call. = FALSE)
  }
  if (!file.exists(db_path)) {
    stop("ScType database not found: ", db_path, call. = FALSE)
  }
  db <- openxlsx::read.xlsx(db_path)
  if (!"tissueType" %in% colnames(db)) {
    stop("ScTypeDB missing required column 'tissueType': ", db_path, call. = FALSE)
  }
  sort(unique(as.character(db$tissueType)))
}

#' Validate a tissue label against ScTypeDB_full.xlsx tissueType values.
#'
#' @param tissue character; requested tissue
#' @param allowed character vector from list_sctype_tissues(); or db_path to load
#' @param db_path optional path used in error messages / loading allowed values
#' @return validated tissue string (exact DB spelling)
validate_sctype_tissue <- function(tissue, allowed = NULL, db_path = NULL) {
  tissue <- as.character(tissue)[1]
  if (is.na(tissue) || !nzchar(tissue)) {
    stop(
      "ScType tissue is empty. Set --tissue, comparisons$tissue_type, or samples_info$tissue ",
      "to a tissueType value from GeneralFile/scType/ScTypeDB_full.xlsx.",
      call. = FALSE
    )
  }
  if (is.null(allowed)) {
    if (is.null(db_path)) stop("validate_sctype_tissue needs allowed or db_path", call. = FALSE)
    allowed <- list_sctype_tissues(db_path)
  }
  if (tissue %in% allowed) return(tissue)
  # Case-insensitive rescue to the DB spelling
  hit <- allowed[tolower(allowed) == tolower(tissue)]
  if (length(hit) == 1) {
    message("ScType tissue '", tissue, "' matched to '", hit, "' (from ScTypeDB_full.xlsx).")
    return(hit)
  }
  stop(
    "Invalid ScType tissue: '", tissue, "'.\n",
    "Tissue must be a tissueType value from GeneralFile/scType/ScTypeDB_full.xlsx.\n",
    "Allowed values:\n  - ", paste(allowed, collapse = "\n  - "),
    call. = FALSE
  )
}


#' Run one cohort (single outdir or one comparison).
#'
#' @param scRNA_all Full Seurat object with Group metadata
#' @param samples_info Normalized samples_info
#' @param gse.number GSE accession
#' @param organism hsa|mmu
#' @param resources From load_scRNA_resources()
#' @param outdir Output directory name (created under gse_dir)
#' @param group1 Control group (NULL for single mode)
#' @param group2 Treatment group (NULL for single mode)
#' @param tissue Tissue for ScType; must be a tissueType in ScTypeDB_full.xlsx (empty skips ScType)
#' @param do_multi_de If TRUE, run CellRatio / DEGs / pseudobulk stack
#' @param gse_dir Absolute GSE directory (cohort output parent)
analyze_scRNA_cohort <- function(scRNA_all, samples_info, gse.number, organism,
                                 resources, outdir, group1 = NULL, group2 = NULL,
                                 tissue = "", do_multi_de = FALSE,
                                 gse_dir, perf = NULL) {
  if (is.null(perf)) perf <- resolve_perf_opts(list())
  OrgDb <- resources$OrgDb
  species <- resources$species
  bcv_value <- resources$bcv_value
  tab <- resources$tab
  db_ <- resources$db_
  do_sctype <- nzchar(as.character(tissue)[1]) && !is.na(tissue)
  if (do_sctype) {
    tissue <- validate_sctype_tissue(
      tissue,
      allowed = resources$sctype_tissues,
      db_path = db_
    )
    gs_list <- gene_sets_prepare(db_, tissue)
  } else {
    message("ScType tissue not set; skipping ScType annotation (celltype_scType=Unknown).")
    gs_list <- NULL
  }
  ref_singleR <- resources$ref_singleR
  cellmarker <- resources$cellmarker
  ssGSEA_list <- resources$ssGSEA_list
  kegg_list <- resources$kegg_list
  go_list <- resources$go_list
  gsva_term_id_map <- resources$gsva_term_id_map
  gsva_term_name_map <- resources$gsva_term_name_map

  cohort_dir <- file.path(gse_dir, outdir)
  dir.create(cohort_dir, showWarnings = FALSE, recursive = TRUE)
  clear_analysis_success(cohort_dir)
  compareName <- outdir

  if (isTRUE(do_multi_de)) {
    group_data <- subset(samples_info, Group %in% c(group1, group2))
    group_data$Group <- factor(group_data$Group, levels = c(group1, group2))
    info_Control <- subset(group_data, Group == group1)
    info_Treatment <- subset(group_data, Group == group2)
    scRNA_subset <- subset(scRNA_all, subset = Group %in% c(group1, group2))
  } else {
    # Single-cohort: keep all cells; group labels for marker tables
    group_data <- samples_info
    info_Control <- samples_info[0, , drop = FALSE]
    info_Treatment <- samples_info[0, , drop = FALSE]
    group1 <- if (length(unique(samples_info$Group)) == 1) as.character(unique(samples_info$Group)) else "all"
    group2 <- group1
    scRNA_subset <- scRNA_all
  }

  scRNA_subset@meta.data <- scRNA_subset@meta.data[colnames(scRNA_subset@assays$RNA$counts), ]

  # ---- Core Seurat pipeline (from MultiGroup body) ----
# Core analysis logic for one GSE (called by the batch loop above).
# Adapted for batch use; keep messages informative for end users.

  mito_genes <- rownames(scRNA_subset)[grep(tab, rownames(scRNA_subset))]
  # 13
  mito_genes
  scRNA_subset[["percent.mt"]] <- PercentageFeatureSet(scRNA_subset, pattern = tab)
  VlnPlot(scRNA_subset, 
          features = c("nFeature_RNA","nCount_RNA","percent.mt"),
          group.by = 'Sample',
          pt.size = 0.00,
          ncol = 1)
  upper <- quantile(scRNA_subset$nFeature_RNA, 0.99)
  lower <- 200
  scRNA_subset <- subset(scRNA_subset,
                         subset = nFeature_RNA > lower &
                           nFeature_RNA < upper &
                           percent.mt < 10)
  # 3
  scRNA_subset <- scRNA_subset[rowSums(scRNA_subset@assays$RNA$counts > 0) >= 3, ]

  # 4.2 PCA
  # 1SCTransform
  if (TRUE) {
    # SCTransform[["SCT"]]@scale.data@counts@data
    options(future.globals.maxSize = 32 * 1024^3)
    scRNA_subset <- SCTransform(scRNA_subset, vars.to.regress = "percent.mt", verbose = F)
    scRNA_subset <- RunPCA(scRNA_subset, verbose=F)
    n_sources <- length(unique(as.character(scRNA_subset$Source)))
    if (n_sources > 1) {
      scRNA_subset <- RunHarmony(scRNA_subset, group.by.vars = "Source", assay.use = "SCT")
    } else {
      message("Single Source detected: skip Harmony, use PCA reduction.")
    }

    # CCAseurat
    if (FALSE) {
      seurat_list <- SplitObject(scRNA_subset, split.by = "Sample")
      seurat_list <- lapply(seurat_list, function(x) SCTransform(x, vars.to.regress = "percent.mt", verbose = FALSE))
      features <- SelectIntegrationFeatures(object.list = seurat_list, nfeatures = 3000)
      seurat_list <- PrepSCTIntegration(object.list = seurat_list, anchor.features = features)
      anchors <- FindIntegrationAnchors(object.list = seurat_list, normalization.method = "SCT", anchor.features = features)
      seurat_obj_integrated <- IntegrateData(anchorset =
                                               anchors, normalization.method = "SCT")
    }

    scRNA_subset_inter <- scRNA_subset
  }

  # 2seurat
  if (FALSE) {
    # layer
    scRNA_subset[["RNA"]] <- split(scRNA_subset[["RNA"]],f = scRNA_subset$Sample)
    DefaultAssay(scRNA_subset) <- "RNA"
    scRNA_subset <- NormalizeData(scRNA_subset)
    scRNA_subset <- FindVariableFeatures(scRNA_subset)
    scRNA_subset <- ScaleData(scRNA_subset, vars.to.regress = c("percent.mt"))
    scRNA_subset <- RunPCA(scRNA_subset, verbose=F)
    # Harmony(SCTransform)
    if (FALSE) {
      # methods of Integration
      # CCA integration (method=CCAIntegration)
      # RPCA integration (method=RPCAIntegration)
      # Harmony (method=HarmonyIntegration)
      # JointPCA (method= JointPCAIntegration)
      # FastMNN (method= FastMNNIntegration)
      # scVI (method=scVIIntegration)python
      ###Integrated with CCA
      if (FALSE) {
        scRNA_subset_cca <- IntegrateLayers(object = scRNA_subset, 
                                            method = CCAIntegration, 
                                            orig.reduction = "pca", 
                                            new.reduction = "integrated.cca",verbose = FALSE)
        # re-join layers after integration
        scRNA_subset_cca[["RNA"]] <- JoinLayers(scRNA_subset_cca[["RNA"]])
      }

      ###Integrated with Harmony
      if (FALSE) {
        scRNA_subset_harmony <- IntegrateLayers(object = scRNA_subset, 
                                                method = HarmonyIntegration, 
                                                orig.reduction = "pca", 
                                                new.reduction = "harmony",verbose = FALSE)
        # re-join layers after integration
        scRNA_subset_harmony[["RNA"]] <- JoinLayers(scRNA_subset_harmony[["RNA"]])
      }
      scRNA_subset_inter <- scRNA_subset_harmony
    }
  }

  # 4.3
  #Perform reduction
  DefaultAssay(scRNA_subset_inter) <- "SCT"
  n_sources <- length(unique(as.character(scRNA_subset_inter$Source)))
  reduction <- if (n_sources > 1 && "harmony" %in% names(scRNA_subset_inter@reductions)) "harmony" else "pca"
  message("Using reduction: ", reduction) 

  # pca_std <- scRNA_subset_inter[["pca"]]@stdev
  # KneeLocator
  # knee_locator <- kneed$KneeLocator(x = seq_along(pca_std), y = pca_std, 
  #                                   curve = "convex", direction = "decreasing")
  # elbow_point <- knee_locator$knee

  # PCA
  # pca_std <- scRNA_subset_inter@reductions$pca@stdev
  # variances <- pca_std^2
  # 
  # PC
  # elbow_point <- PCAtools::findElbowPoint(variances)

  meta_data <- scRNA_subset_inter@meta.data
  Seurat::ElbowPlot(scRNA_subset_inter, reduction = "pca", ndims = 50)
  scRNA_subset_inter <- FindNeighbors(scRNA_subset_inter, reduction = reduction, dims = 1:10)
  cluster_resolutions <- perf$resolutions
  message("FindClusters resolutions: ", paste(cluster_resolutions, collapse = ", "))
  scRNA_subset_inter <- FindClusters(scRNA_subset_inter, resolution = cluster_resolutions)
  # umap
  scRNA_subset_inter <- RunUMAP(scRNA_subset_inter, dims = 1:10, reduction = reduction, n.components = 3L)
  umap <- scRNA_subset_inter@reductions[["umap"]]@cell.embeddings %>% as.data.frame()
  #umap <- umap[rownames(meta_data), ]
  umap <- data.frame(cell = meta_data[rownames(umap), "new_rownames"],umap,row.names = rownames(umap))
  write_csv_if_nonempty(umap, file.path(cohort_dir, "umap.csv"), row.names = FALSE)
  # tsne
  scRNA_subset_inter <- RunTSNE(scRNA_subset_inter, dims = 1:10, reduction = reduction, dim.embed = 3)
  tsne <- scRNA_subset_inter@reductions[["tsne"]]@cell.embeddings %>% as.data.frame()
  tsne <- data.frame(cell = meta_data[rownames(tsne), "new_rownames"],tsne,row.names = rownames(tsne))
  #tsne <- cbind(cell = rownames(tsne), tsne)
  write_csv_if_nonempty(tsne, file.path(cohort_dir, "tsne.csv"), row.names = FALSE)

  {
    if (!isTRUE(perf$skip_gene_cell_exp)) {
      gene_cell_exp <- scRNA_subset_inter@assays[["SCT"]]@data %>% as.data.frame()
      gene_cell_exp <- t(gene_cell_exp)
      gene_cell_exp <- data.frame(cell = meta_data[rownames(gene_cell_exp), "new_rownames"],gene_cell_exp,row.names = rownames(gene_cell_exp))
      fwrite_if_nonempty(gene_cell_exp, file.path(cohort_dir, "gene_cell_exp.csv"))
    } else {
      message("skip_gene_cell_exp=TRUE; skipping gene_cell_exp.csv")
    }
  }

  # 5.resolutionclustercelltype
  for (res in cluster_resolutions) { #
    resolution_s <- res
    resolution=paste0("resolution_",res)
    res_dir <- file.path(cohort_dir, resolution)
    dir.create(res_dir, showWarnings = FALSE, recursive = TRUE)
    res_ident <- paste0("SCT_snn_res.",res)
    Idents(scRNA_subset_inter) <- res_ident
    scRNA_subset_inter$seurat_clusters <- scRNA_subset_inter@active.ident
    DimPlot(scRNA_subset_inter,reduction = "umap",group.by = "seurat_clusters")

    # marker_genes <- FindAllMarkers(scRNA_subset_inter, only.pos = TRUE, logfc.threshold = 0.25)
    # RunPrestoAllFindAllMarkers
    # scRNA_subset_inter <- PrepSCTFindMarkers(scRNA_subset_inter)
    marker_genes <- RunPrestoAll(scRNA_subset_inter, assay = "SCT", only.pos = TRUE, logfc.threshold = 0.25)

    # top marker
    # top_markers <- marker_genes %>% 
    #   group_by(cluster) %>% 
    # top_n(n = 5, wt = avg_log2FC)  # 5

    # 5.1
    # 1CellMarker
    if (FALSE) {
      annotated_markers <- merge(marker_genes, cellmarker_scRNA, by.x = "gene", by.y = "geneSymbol")
      cell_type_annotations <- rep("Unknown", length(unique(scRNA_subset_inter@active.ident)))
      names(cell_type_annotations) <- unique(annotated_markers$cluster)
      for (k in unique(annotated_markers$cluster)) {
        cluster_annotations <- annotated_markers[annotated_markers$cluster == k, "CellType"]
        if (length(cluster_annotations) > 0) {
          cell_type_annotations[k] <- names(sort(table(cluster_annotations), decreasing = TRUE))[1]
        }
      }
      # Seurat
      scRNA_subset_inter <- RenameIdents(scRNA_subset_inter, cell_type)
    }

    # 2SingleR
    if (TRUE) {
      count_for_SingleR <- GetAssayData(scRNA_subset_inter, assay = "SCT", layer = "data")
      pred_SingleR <- SingleR(test = count_for_SingleR, 
                              clusters = scRNA_subset_inter@meta.data$seurat_clusters,
                              ref = ref_singleR,  #list(BP=bpe.se, HPCA = hpca.se, DICE = dice.se, NHD = nhd.se, MID = mid.se)
                              labels = ref_singleR$label.main) #list(BP = bpe.se$label.main, HPCA = hpca.se$label.main, DICE = dice.se$label.main, NHD = nhd.se$label.main, MID = mid.se$label.main)
      scRNA_subset_inter@meta.data$celltype_SingleR <- pred_SingleR$labels[match(scRNA_subset_inter@meta.data$seurat_clusters,
                                                                                 rownames(pred_SingleR))]
      #scRNA_subset_inter@meta.data$celltype_SingleR <- pred_SingleR$labels
    }

    # 3ScType
    if (TRUE) {
      if (do_sctype && !is.null(gs_list)) {
      # assign cell types
      scRNAseqData_scaled <- as.matrix(scRNA_subset_inter[["SCT"]]$scale.data)
      es.max <- sctype_score(scRNAseqData = scRNAseqData_scaled, scaled = TRUE, gs = gs_list$gs_positive, gs2 = gs_list$gs_negative)
      # merge by cluster
      cL_resutls <- do.call("rbind", lapply(unique(scRNA_subset_inter@meta.data$seurat_clusters), function(cl){
        es.max.cl = sort(rowSums(es.max[ ,rownames(scRNA_subset_inter@meta.data[scRNA_subset_inter@meta.data$seurat_clusters==cl, ])]), decreasing = !0)
        head(data.frame(cluster = cl, type = names(es.max.cl), scores = es.max.cl, ncells = sum(scRNA_subset_inter@meta.data$seurat_clusters==cl)), 10)
      }))
      sctype_scores <- cL_resutls %>% group_by(cluster) %>% top_n(n = 1, wt = scores)  
      # set low-confident (low ScType score) clusters to "unknown"
      sctype_scores$type[as.numeric(as.character(sctype_scores$scores)) < 1] <- "Unknown"
      print(sctype_scores[,1:3])
      scRNA_subset_inter@meta.data$celltype_scType = ""
      for(j in unique(sctype_scores$cluster)){
        cl_type = sctype_scores[sctype_scores$cluster==j,];
        scRNA_subset_inter@meta.data$celltype_scType[scRNA_subset_inter@meta.data$seurat_clusters == j] = as.character(cl_type$type[1])
      } 
      DimPlot(scRNA_subset_inter, reduction = "umap", label = TRUE, repel = TRUE, group.by = 'celltype_scType')
      } else {
        scRNA_subset_inter@meta.data$celltype_scType <- "Unknown"
      }
    }

    if (FALSE) {
      # sctype
      scRNAseqData_scaled <- as.matrix(scRNA_subset_inter[["SCT"]]$scale.data)
      es.max <- sctype_score(scRNAseqData = scRNAseqData_scaled, scaled = TRUE, gs = gs_list$gs_positive, gs2 = gs_list$gs_negative)

      cell_types <- apply(es.max, 2, function(cell_scores) {
        cell_type <- names(which.max(cell_scores))
        score <- max(cell_scores)
        return(c(cell_type = cell_type, score = score))
      })
      cell_types_df <- as.data.frame(t(cell_types), stringsAsFactors = FALSE)
      colnames(cell_types_df) <- c("celltype_scType", "score")
      scRNA_subset_inter@meta.data <- cbind(scRNA_subset_inter@meta.data, cell_types_df)
      # “Unknown”
      scRNA_subset_inter@meta.data$celltype_scType[as.numeric(scRNA_subset_inter@meta.data$score) < 1] <- "Unknown"
      DimPlot(scRNA_subset_inter, reduction = "umap", label = TRUE, repel = TRUE, group.by = 'celltype_scType')
    }

    # 4gptcelltypeGPTkeyifT“celltype_gptcelltype”
    if (FALSE) {
      # "scRNA_subset_inter" is the Seurat object; 5"markers" is the output from FindAllMarkers(obj)
      # Cell type annotation by GPT-4
      gptcelltype <- gptcelltype(marker_genes, model = 'gpt-4')
      # Assign cell type annotation back to Seurat object
      scRNA_subset_inter@meta.data$celltype_gptcelltype <- as.factor(gptcelltype[as.character(Idents(scRNA_subset_inter))])
      # Visualize cell type annotation on UMAP
      DimPlot(scRNA_subset_inter, reduction = "umap", group.by='celltype_gptcelltype')
    }

    if (TRUE) {
      cell_clusters_celltype <- scRNA_subset_inter@meta.data
      # gptcelltype”celltype_gptcelltype“
      cell_clusters_celltype <- cell_clusters_celltype[,c("new_rownames", "seurat_clusters","celltype_scType", "celltype_SingleR")]
      colnames(cell_clusters_celltype)[colnames(cell_clusters_celltype) == "new_rownames"] <- "cell"
      colnames(cell_clusters_celltype)[colnames(cell_clusters_celltype) == "seurat_clusters"] <- "cluster"
      write_csv_if_nonempty(cell_clusters_celltype, file.path(res_dir, "Cell_Clusters_Celltype.csv"), row.names = FALSE)
    }

    dir.create(file.path(res_dir, "cluster"), showWarnings = FALSE)
    dir.create(file.path(res_dir, "celltype_scType"), showWarnings = FALSE)
    dir.create(file.path(res_dir, "celltype_SingleR"), showWarnings = FALSE)

    ### 5.2 Cell Ratio (multi mode only)
    if (isTRUE(do_multi_de)) {
    # Cell Ratio
    if (TRUE) {
      # Cell Ratio
      cellratio <- function(type){
        type_dir <- file.path(res_dir, type)
        dir.create(type_dir, showWarnings = FALSE)
        proportions_list <- list()
        clusters <- unique(scRNA_subset_inter@active.ident)
        for (cluster in clusters) {
          cluster_cells <- scRNA_subset_inter@meta.data[scRNA_subset_inter@active.ident == cluster, ]
          cluster_group_counts <- table(cluster_cells$Group)
          cluster_group_props <- prop.table(cluster_group_counts)
          proportions_list[[cluster]] <- cluster_group_props
        }
        all_groups <- unique(unlist(lapply(proportions_list, names)))
        proportions_df <- do.call(rbind, lapply(names(proportions_list), function(cluster) {
          prop <- as.data.frame(as.list(proportions_list[[cluster]]))
          # prop  0
          missing_groups <- setdiff(all_groups, names(prop))
          for (Group in missing_groups) {
            prop[[Group]] <- 0
          }
          # all_groups
          prop <- prop[all_groups]
          prop$Cluster <- cluster
          prop <- prop[,c(3,1,2)]
          return(prop)
        }))
        fwrite_if_nonempty(proportions_df, file.path(type_dir, "CellRatio.csv"), sep = ",")
        #write.csv(proportions_df, file = paste0("CellRatio_",type,".csv"),row.names = F)
      }
      # cluster
      Idents(scRNA_subset_inter) <- res_ident
      cellratio("cluster")
      # celltype_scType
      Idents(scRNA_subset_inter) <- "celltype_scType"
      cellratio("celltype_scType")
      # celltype_SingleR
      Idents(scRNA_subset_inter) <- "celltype_SingleR"
      cellratio("celltype_SingleR")
    }

    } # end CellRatio multi gate

    # 5.3 Marker genes
    # FindMarkersMarker
    if (TRUE) {
      # Marker genes(celltype)
      Marker_genes_FM <- function(type){
        DefaultAssay(scRNA_subset_inter) <- "SCT"
        celltypes <- unique(scRNA_subset_inter@active.ident)
        Marker_genes <- list()
        if(length(celltypes)>=2) {
          type_dir <- file.path(res_dir, type)
          dir.create(type_dir, showWarnings = FALSE)
          for (celltype in celltypes) {
            deg = FindMarkers(scRNA_subset_inter, 
                              ident.1 = celltype, 
                              ident.2 = NULL,
                              only.pos = TRUE, 
                              min.pct = 0.25,
                              logfc.threshold = 0.25)
            if(nrow(deg)>0) {
              deg$cluster <- celltype
              Marker_genes[[celltype]] <- deg
            } 
          }
          if (length(Marker_genes) == 0) {
            message("No marker genes for type=", type, "; skip Marker_genes.csv")
            return(invisible(NULL))
          }
          Marker_genes_df <- do.call(rbind, Marker_genes)
          Marker_genes_df$gene <- row.names(Marker_genes_df)
          Marker_genes_df$gene <- sub("^.*?\\.", "", Marker_genes_df$gene)
          colnames(Marker_genes_df)[colnames(Marker_genes_df) == "pct.2"] <- "pct_control"
          colnames(Marker_genes_df)[colnames(Marker_genes_df) == "pct.1"] <- "pct_case"
          Marker_genes_df <- Marker_genes_df[Marker_genes_df$p_val < 0.01, , drop = FALSE]
          Marker_genes_df <- annotate_sc_csv_meta(
            Marker_genes_df,
            resolution = resolution_s,
            type = type,
            data = gse.number,
            group = compareName
          )
          fwrite_if_nonempty(Marker_genes_df, file.path(type_dir, "Marker_genes.csv"), sep = ",")
          #write.csv(Marker_genes_df, file = paste0("Marker_genes_",type,".csv"), row.names = F)
          return(Marker_genes_df)
        }

      }
      # clusterMarker genes
      Idents(scRNA_subset_inter) <- res_ident
      marker_gene1 <- Marker_genes_FM("cluster")
      # celltype_scTypeMarker genes
      Idents(scRNA_subset_inter) <- "celltype_scType"
      marker_gene2 <- Marker_genes_FM("celltype_scType")
      # celltype_SingleRMarker genes
      Idents(scRNA_subset_inter) <- "celltype_SingleR"
      marker_gene3 <- Marker_genes_FM("celltype_SingleR")
    }


    ### 5.4 DEGs in cluster/celltype (multi mode only)
    if (isTRUE(do_multi_de)) {
      # Between-group DEGs
    if(nrow(info_Control) < 2 | nrow(info_Treatment) < 2) {
      # (1)FindMarkersDEGs
      # DEGs(celltype)
      DEGs_scRNA_FM <- function(type){
        type_dir <- file.path(res_dir, type)
        dir.create(type_dir, showWarnings = FALSE)
        DefaultAssay(scRNA_subset_inter) <- "SCT"
        celltypes <- unique(scRNA_subset_inter@active.ident)
        DEGs <- list()
        for (celltype in celltypes) {
          cells_in_type <- WhichCells(object = scRNA_subset_inter, idents = celltype)
          # scRNA_subset_inter <- PrepSCTFindMarkers(scRNA_subset_inter)
          data <- subset(scRNA_subset_inter, cells = cells_in_type)
          Idents(data) <- "Group"
          cells_1 <- tryCatch({
            WhichCells(data, idents = group1)
          }, error = function(e) {
            warning(paste("Group", group1, "not found or contains no cells."))
            return(character(0))
          })

          cells_2 <- tryCatch({
            WhichCells(data, idents = group2)
          }, error = function(e) {
            warning(paste("Group", group2, "not found or contains no cells."))
            return(character(0))
          })

          if(length(cells_1) >= 3 & length(cells_2) >= 3) {
            deg = FindMarkers(data,
                              group.by="Group",
                              ident.1 = group2,
                              ident.2 = group1)
            deg$cluster <- celltype

            DEGs[[celltype]] <- deg
          }

        }
        if (length(DEGs) == 0) {
          message("No DEGs for type=", type, "; skip DEGs.csv")
          return(invisible(NULL))
        }
        DEGs_df <- do.call(rbind, DEGs)
        DEGs_df$gene <- row.names(DEGs_df)
        DEGs_df$gene <- sub("^.*?\\.", "", DEGs_df$gene)
        colnames(DEGs_df)[colnames(DEGs_df) == "pct.2"] <- "pct_control"
        colnames(DEGs_df)[colnames(DEGs_df) == "pct.1"] <- "pct_case"
        DEGs_df <- DEGs_df[DEGs_df$p_val_adj < 0.05, , drop = FALSE]
        DEGs_df <- annotate_sc_csv_meta(
          DEGs_df,
          resolution = resolution_s,
          type = type,
          data = gse.number,
          group = compareName
        )
        fwrite_if_nonempty(DEGs_df, file.path(type_dir, "DEGs.csv"), sep = ",")
        #write.csv(DEGs_df, file = paste0("DEGs_",type,".csv"), row.names = F)
        return(DEGs_df)
      }
      # clusterDEGs
      Idents(scRNA_subset_inter) <- res_ident
      deg1 <- DEGs_scRNA_FM("cluster")
      # celltype_scTypeDEGs
      Idents(scRNA_subset_inter) <- "celltype_scType"
      deg2 <- DEGs_scRNA_FM("celltype_scType")
      # celltype_SingleRDEGs
      Idents(scRNA_subset_inter) <- "celltype_SingleR"
      deg3 <- DEGs_scRNA_FM("celltype_SingleR")
    } else {
      # (2)muscat
      DEGs_scRNA_muscat <- function(cluster,type){
        type_dir <- file.path(res_dir, type)
        dir.create(type_dir, showWarnings = FALSE)
        DefaultAssay(scRNA_subset_inter) <- "SCT"
        scRNA_subset_deg <- as.SingleCellExperiment(scRNA_subset_inter)
        scRNA_subset_deg <- prepSCE(scRNA_subset_deg,
                                    kid = cluster, # "celltype" or res_ident
                                    gid = "Group",#group——id，
                                    sid = "Sample",#sample_id, 
                                    drop=T)
        scRNA_subset_deg$group_id <- factor(scRNA_subset_deg$group_id, levels=c(group1, group2))
        # ID
        nk <- length(kids <- levels(scRNA_subset_deg$cluster_id))
        ns <- length(sids <- levels(scRNA_subset_deg$sample_id))
        names(kids) <- kids
        names(sids) <- sids
        t(table(scRNA_subset_deg$cluster_id, scRNA_subset_deg$sample_id))

        # pseudobulk data
        pb <- aggregateData(scRNA_subset_deg,
                            assay = "counts", 
                            fun = "sum",
                            by = c("cluster_id", "sample_id"))
        (pb_mds <- pbMDS(pb))

        pb$group_id <- factor(pb$group_id, levels=c(group1, group2))
        res_deg <- pbDS(pb,filter = "none", min_cells = 1, verbose = FALSE)#pseudobulk DS analysis
        tmp <- scRNA_subset_deg
        counts(tmp) <- as.matrix(counts(tmp))
        result_table <- resDS(tmp, res_deg, bind = "row", frq = FALSE, cpm = FALSE)
        rm(tmp)

        if (is.null(result_table) || nrow(result_table) == 0) {
          message("No muscat DE results for type=", type, "; skip DEGs.csv")
          return(invisible(NULL))
        }

        # BM/GMFindmarkerpct1pct2
        count_mat <- as.matrix(scRNA_subset_inter[["SCT"]]@data) > 0
        cluster_list <- unique(result_table$cluster_id)

        result_table$pct_control <- 0
        control_cells <- colnames(scRNA_subset_inter)[scRNA_subset_inter$Group == group1]
        for (m in seq_along(cluster_list)) {
          cluster_cells <- colnames(scRNA_subset_inter)[scRNA_subset_inter@active.ident == cluster_list[m]]
          test_cells <- intersect(control_cells, cluster_cells)
          row_ind <- which(result_table$cluster_id == cluster_list[m])
          denom <- max(length(test_cells), 1)
          frq <- rowSums(count_mat[result_table$gene[row_ind], test_cells, drop = FALSE]) / denom
          result_table$pct_control[row_ind] <- frq
        }

        result_table$pct_case <- 0
        case_cells <- colnames(scRNA_subset_inter)[scRNA_subset_inter$Group == group2]
        for (n in seq_along(cluster_list)) {
          cluster_cells <- colnames(scRNA_subset_inter)[scRNA_subset_inter@active.ident == cluster_list[n]]
          test_cells <- intersect(case_cells, cluster_cells)
          row_ind <- which(result_table$cluster_id == cluster_list[n])
          denom <- max(length(test_cells), 1)
          frq <- rowSums(count_mat[result_table$gene[row_ind], test_cells, drop = FALSE]) / denom
          result_table$pct_case[row_ind] <- frq
        }

        result_table_sig <- result_table[result_table$p_adj.loc < 0.05, , drop = FALSE]
        # result_table_sig <- result_table[result_table$p_val < 0.05 &
        #                                         abs(result_table$logFC) > 0.25&
        #                                         result_table$pct_control>0.1&
        #                                         result_table$pct_case>0.1, ]
        if (nrow(result_table_sig) == 0) {
          message("No significant muscat DEGs for type=", type, "; skip DEGs.csv")
          return(invisible(NULL))
        }
        result_table_sig <- result_table_sig[, -c(4, 5, 8, 9), drop = FALSE]
        colnames(result_table_sig)[colnames(result_table_sig) == "logFC"] <- "avg_log2FC"
        colnames(result_table_sig)[colnames(result_table_sig) == "p_adj.loc"] <- "p_val_adj"
        colnames(result_table_sig)[colnames(result_table_sig) == "cluster_id"] <- "cluster"
        result_table_sig <- annotate_sc_csv_meta(
          result_table_sig,
          resolution = resolution_s,
          type = type,
          data = gse.number,
          group = compareName
        )
        fwrite_if_nonempty(result_table_sig, file.path(type_dir, "DEGs.csv"), sep = ",")
        #write.csv(result_table_sig, file = paste0("DEGs_",type,".csv"), row.names = F)
        return(result_table_sig)
      }
      # clusterDEGs
      Idents(scRNA_subset_inter) <- res_ident
      deg1 <- DEGs_scRNA_muscat(res_ident, "cluster")
      # celltype_scTypeDEGs
      Idents(scRNA_subset_inter) <- "celltype_scType"
      deg2 <- DEGs_scRNA_muscat("celltype_scType", "celltype_scType")
      # celltype_SingleRDEGs
      Idents(scRNA_subset_inter) <- "celltype_SingleR"
      deg3 <- DEGs_scRNA_muscat("celltype_SingleR", "celltype_SingleR")
    }


    } # end DEGs multi gate

    # 5.5 Slingshot
    if (TRUE) {
      scale_gene <- rownames(scRNA_subset_inter@assays$SCT@scale.data)
      counts <- scRNA_subset_inter@assays$RNA$counts
      counts <- counts[scale_gene,]
      sim <- SingleCellExperiment(assays = List(counts= counts))

      geneFilter <- apply(assays(sim)$counts,1,function(x){
        sum(x >= 3) >= 10
      })
      sim <- sim[geneFilter, ]

      FQnorm <- function(counts){
        rk <- apply(counts,2,rank,ties.method='min')
        counts.sort <- apply(counts,2,sort)
        refdist <- apply(counts.sort,1,median)
        norm <- apply(rk,2,function(r){ refdist[r] })
        rownames(norm) <- rownames(counts)
        return(norm)
      }
      assays(sim)$norm <- FQnorm(assays(sim)$counts)

      umap <- scRNA_subset_inter@reductions$umap@cell.embeddings[,c(1,2)]
      tsne <- scRNA_subset_inter@reductions$tsne@cell.embeddings[,c(1,2)]
      umap_3d <- scRNA_subset_inter@reductions$umap@cell.embeddings
      tsne_3d <- scRNA_subset_inter@reductions$tsne@cell.embeddings
      reducedDims(sim) <- SimpleList(UMAP = umap, TSNE = tsne, UMAP_3d = umap_3d, TSNE_3d = tsne_3d)

      if (TRUE) {
        traject <- function(method,type) {
          type_dir <- file.path(res_dir, type)
          dir.create(type_dir, showWarnings = FALSE)
          # Construct the target file path
          output_file <- file.path(type_dir, paste0("cell_trajectory_", method, ".csv"))

          # --- SKIP LOGIC START ---
          if (file.exists(output_file)) {
            message(paste("File already exists for", type, "-", method, ". Skipping analysis..."))
            return(NULL) 
          }
          # --- SKIP LOGIC END ---

          colData(sim)$cluster <- scRNA_subset_inter@active.ident
          cluster <- unique(scRNA_subset_inter@active.ident)

          pseudotime_df <- data.frame(row.names = colnames(sim))
          for(start in cluster) {

            sim_result <- tryCatch({
              # slingshot
              sim_cell <- slingshot(sim, clusterLabels = "cluster",
                                    reducedDim = method,
                                    start.clus = start,
                                    end.clus = NULL,
                                    allow.breaks = FALSE)
              sim_cell
            }, error = function(e) {
              # NULL
              message("Error occurred: ", e$message)
              return(NULL)
            })

            # sim_result  NULL
            if (!is.null(sim_result)) {
              # sim_result  NULL slingshot
              # slingPseudotime
              if (!is.null(slingPseudotime(sim_result))) {
                pseudotime_vals <- slingPseudotime(sim_result)[, 1]
                if (length(pseudotime_vals) == ncol(sim_result)) {
                  pseudotime_df[[paste0('pseudotime_', type, "_", start)]] <- pseudotime_vals
                } else {
                  warning(paste("Pseudotime length mismatch for start cluster:", start))
                }
              } else {
                warning(paste("No pseudotime found for start cluster:", start))
              }
            } else {
              # sim_result  NULL slingshot
              message("Slingshot failed. Skipping subsequent code.")
            }
          }         
          #pseudotime_df <- cbind(cell = rownames(pseudotime_df), pseudotime_df)
          pseudotime_df <- data.frame(cell = meta_data[rownames(pseudotime_df), "new_rownames"],pseudotime_df,row.names = rownames(pseudotime_df))
          fwrite_if_nonempty(pseudotime_df, file.path(type_dir, paste0("cell_trajectory_", method, ".csv")), sep = ",")
          #write.csv(pseudotime_df, file = paste0("cell_trajectory_",type,"_",method,".csv"), row.names = F)
        }

        Idents(scRNA_subset_inter) <- res_ident
        if(length(levels(scRNA_subset_inter@active.ident))>1) {
          traject("UMAP","cluster")
          traject("TSNE","cluster")
          traject("UMAP_3d","cluster")
          traject("TSNE_3d","cluster")
        }

        Idents(scRNA_subset_inter) <- "celltype_scType"
        if(length(levels(scRNA_subset_inter@active.ident))>1) {
          traject("UMAP","celltype_scType")
          traject("TSNE","celltype_scType")
          traject("UMAP_3d","celltype_scType")
          traject("TSNE_3d","celltype_scType")
        }

        Idents(scRNA_subset_inter) <- "celltype_SingleR"
        if(length(levels(scRNA_subset_inter@active.ident))>1) {
          traject("UMAP","celltype_SingleR")
          traject("TSNE","celltype_SingleR")
          traject("UMAP_3d","celltype_SingleR")
          traject("TSNE_3d","celltype_SingleR")
        }

        if (FALSE) {
          counts <- sim@assays@data$counts

          gene_traject<-function(method,type){
            type_dir <- file.path(res_dir, type)
            dir.create(type_dir, showWarnings = FALSE)
            colData(sim)$cluster <- scRNA_subset_inter@active.ident
            cluster <- unique(scRNA_subset_inter@active.ident)

            sim_gene <- slingshot(sim, clusterLabels = "cluster",
                                  # end.clus = NULL,
                                  # start.clus = start,
                                  reducedDim = method)
            crv <- SlingshotDataSet(sim_gene)

            if (FALSE) {
              gene_expression <- colSums(counts > 0)
              nGenes <- sum(gene_expression > 0.1 * ncol(counts))

              set.seed(111)
              icMat <- evaluateK(counts = counts,
                                 sds = crv,
                                 k = 3:10,
                                 nGenes = nGenes,
                                 verbose = T,
                                 BPPARAM = param,
                                 parallel = T)
              set.seed(111)
              nknots <- which.min(icMat$AIC) + 2 
            }

            pseudotime <- slingPseudotime(crv, na =F)
            cellWeights <- slingCurveWeights(crv)

            gene_sce <- fitGAM(counts = counts,
                               pseudotime = pseudotime,
                               cellWeights = cellWeights,
                               #genes = seq_len(100),
                               #nknots = 6,
                               verbose = T,
                               BPPARAM = param,
                               parallel = T)
            assoRes <- associationTest(gene_sce)
            startRes <- startVsEndTest(gene_sce)
            oStart <- order(startRes$waldStat, decreasing =T)
            coldata <- data.frame(cluster = sim_gene@colData$cluster)
            rownames(coldata) <- colnames(sim_gene)
            coldata$Pseudotime <- sim_gene$slingPseudotime_1

            #top5 <- names(gene_sce)[oStart[1:5]]
            all_gene <- names(gene_sce)[oStart]
            all_gene_exp <- gene_sce@assays@data$counts[all_gene,]
            all_gene_exp <- log2(all_gene_exp +1) %>% t()
            plt_data <- cbind(coldata, all_gene_exp)
            #plt_data <- cbind(cell = rownames(plt_data), plt_data)
            plt_data <- data.frame(cell = meta_data[rownames(plt_data), "new_rownames"],plt_data,row.names = rownames(plt_data))
            plt_data$Pseudotime[is.na(plt_data$Pseudotime)] <- 0
            write_csv_if_nonempty(plt_data, file.path(type_dir, paste0("gene_trajectory_", method, ".csv")), row.names = FALSE)
          }

          Idents(scRNA_subset_inter) <- res_ident
          gene_traject("UMAP","cluster")
          gene_traject("TSNE","cluster")

          Idents(scRNA_subset_inter) <- "celltype_scType"
          gene_traject("UMAP","celltype_scType")
          gene_traject("TSNE","celltype_scType")

          Idents(scRNA_subset_inter) <- "celltype_SingleR"
          gene_traject("UMAP","celltype_SingleR")
          gene_traject("TSNE","celltype_SingleR")

        }
      }
    }

    ### 5.6 pseudobulk (multi mode only)
    if (isTRUE(do_multi_de)) {
    if (TRUE) {
      # Shared write context for nested DEG/enrich/GSEA/GSVA helpers
      .pb_ctx <- new.env(parent = emptyenv())
      .pb_ctx$active <- FALSE
      .pb_ctx$write_dir <- NA_character_
      .pb_ctx$resolution <- NA_character_
      .pb_ctx$type <- NA_character_
      .pb_ctx$celltype <- NA_character_

      annotate_pb_csv <- function(df) {
        if (!isTRUE(.pb_ctx$active)) return(df)
        annotate_sc_csv_meta(
          df,
          resolution = .pb_ctx$resolution,
          type = .pb_ctx$type,
          celltype = .pb_ctx$celltype,
          data = gse.number,
          group = compareName
        )
      }
      fwrite_pb <- function(df, file, ..., sep = ",") {
        fwrite_if_nonempty(annotate_pb_csv(df), file, ..., sep = sep)
      }
      pb_write_dir <- function() {
        wd <- .pb_ctx$write_dir
        if (is.null(wd) || !nzchar(as.character(wd)[1])) {
          stop("pseudobulk write_dir is not set")
        }
        as.character(wd)[1]
      }

      # bulk
      # (1)DEG
      DEG_func <- function(current_counts){
        current_counts <- current_counts[,group_data$Sample]
        current_counts <- current_counts[rowSums(current_counts > 1 ) >= (ncol(current_counts)/2),]
        nC <- nrow(info_Control)
        nT <- nrow(info_Treatment)
        deg_method <- if (exists("choose_bulk_deg_method", mode = "function")) {
          choose_bulk_deg_method(nC, nT)
        } else if (nC >= 2 && nT >= 2) {
          if (nC >= 8 && nT >= 8) "wilcoxon" else "DESeq2"
        } else {
          "edgeR"
        }

        if (deg_method == "DESeq2") {
          dds <- DESeqDataSetFromMatrix(countData = current_counts,
                                        colData = group_data,
                                        design = ~ Group)
          dds <- DESeq(dds)
          res <- results(dds, contrast = c("Group", group2, group1))
          res <- res[order(res$padj), ]
          head(res)
          tempDEG <- as.data.frame(res)
          DEG_DESeq2 <- na.omit(tempDEG)
          DEG <- DEG_DESeq2
        } else if (deg_method == "edgeR") {
          if (exists("run_edger_low_replicate", mode = "function")) {
            DEG <- run_edger_low_replicate(current_counts, group_data$Group, bcv_value, group1, group2)
          } else {
            group <- factor(group_data$Group, levels = c(group1, group2))
            design <- model.matrix(~0+group)
            rownames(design) <- colnames(current_counts)
            colnames(design) <- levels(group)
            y <- DGEList(counts = current_counts, group = group)
            keep <- rowSums(edgeR::cpm(y) > 1) >= 2
            y <- y[keep, , keep.lib.sizes = FALSE]
            y <- calcNormFactors(y)
            disp <- bcv_value^2
            if (nC >= 2 || nT >= 2) {
              y <- edgeR::estimateDisp(y, design, robust = TRUE)
            } else {
              y$common.dispersion <- disp
              y$tagwise.dispersion <- rep(disp, nrow(y))
            }
            fit <- glmFit(y, design)
            lt <- glmLRT(fit, contrast=c(-1,1))
            tempDEG <- topTags(lt, n = Inf)
            tempDEG <- as.data.frame(tempDEG)
            DEG_edgeR <- na.omit(tempDEG)
            DEG <- cbind(name = rownames(DEG_edgeR),DEG_edgeR)
            colnames(DEG) <- c("name", "log2FoldChange", "logCPM", "F", "pvalue", "padj")
          }
        } else if (deg_method == "wilcoxon") {
          conditions <- factor(group_data$Group, levels = c(group1, group2))
          y <- DGEList(counts=current_counts,group=conditions)
          ##Remove rows conssitently have zero or very low counts
          keep <- filterByExpr(y)
          y <- y[keep,keep.lib.sizes=FALSE]
          ##Perform TMM normalization and transfer to CPM (Counts Per Million)
          y <- calcNormFactors(y,method="TMM")
          count_norm <- edgeR::cpm(y)
          count_norm <- as.data.frame(count_norm)

          # Run the Wilcoxon rank-sum test for each gene
          pvalues <- sapply(1:nrow(count_norm),function(i){
            data<-cbind.data.frame(gene=as.numeric(t(count_norm[i,])),conditions)
            p=wilcox.test(gene~conditions, data)$p.value
            return(p)
          })
          fdr <- p.adjust(pvalues,method = "fdr")

          # Calculate fold-change for each gene
          conditionsLevel<-levels(conditions)
          dataCon1 <- count_norm[,c(which(conditions==conditionsLevel[1]))]
          dataCon2 <- count_norm[,c(which(conditions==conditionsLevel[2]))]
          exp_control <- rowMeans(dataCon1)
          exp_case <- rowMeans(dataCon2)
          foldChanges <- log2(rowMeans(dataCon2)/rowMeans(dataCon1))

          # Output results based on FDR thresholda
          outRst<-data.frame(log2FoldChange=foldChanges, exp_control=exp_control, exp_case=exp_case, pvalue=pvalues, padj=fdr)
          rownames(outRst) <- rownames(count_norm)
          outRst <- na.omit(outRst)
          DEG <- cbind(name = rownames(outRst),outRst)
        }

        # regulation (prefer padj over pvalue when available)
        p_col <- if ("padj" %in% names(DEG)) "padj" else "pvalue"
        DEG$regulation <- ifelse(DEG$log2FoldChange > 1 & DEG[[p_col]] < 0.05, "up",
                                 ifelse(DEG$log2FoldChange < -1 & DEG[[p_col]] < 0.05, "down", "stable"))

        DEG$SYMBOL <- rownames(DEG)
        # Keep SYMBOL near the front for readability; meta cols added at write time
        prefer <- c("SYMBOL", "log2FoldChange", "pvalue", "padj", "regulation")
        prefer <- prefer[prefer %in% names(DEG)]
        DEG <- DEG[, c(prefer, setdiff(names(DEG), prefer)), drop = FALSE]

        {
          DEG_counts <- current_counts[rownames(DEG), , drop = FALSE]

          # group1
          if(nrow(info_Control) >= 2) {
            counts_Control <- DEG_counts[, info_Control$Sample, drop = FALSE]
            AveExpr_Control <- rowMeans(counts_Control)
          } else {
            AveExpr_Control <- DEG_counts[, info_Control$Sample]
          }

          # group2
          if(nrow(info_Treatment) >= 2 ) {
            counts_Treatment <- DEG_counts[, info_Treatment$Sample, drop = FALSE]
            AveExpr_Case <- rowMeans(counts_Treatment)
          } else {
            AveExpr_Case <- DEG_counts[, info_Treatment$Sample]
          }
          DEG$AveExpr_Control <- AveExpr_Control
          DEG$AveExpr_Case <- AveExpr_Case

          z_score_matrix <- scale(current_counts)
          z_aligned <- z_score_matrix[rownames(DEG), , drop = FALSE]
          DEG <- cbind(DEG, z_aligned)
        }

        fwrite_pb(DEG, file.path(pb_write_dir(), "DEG_all.csv"), sep = ",")
        DEG_significant <- subset(DEG, regulation != "stable")
        fwrite_pb(DEG_significant, file.path(pb_write_dir(), "DEG_significant.csv"), sep = ",")
        return(list(DEG=DEG, DEG_significant=DEG_significant))
      }

      # (2)GOKEGGCellMarker
      {
        # ①
        deg_rich_save <- function(df, gse.number, compareName, filename){
          if (!is_nonempty_df(df)) {
            message(filename, " No significant terms found. Skipping saving the file.")
            return(invisible(FALSE))
          }
          df$data <- gse.number
          df$group <- compareName
          fwrite_pb(df, file.path(pb_write_dir(), filename), sep = ",")
        }

        # ②
        network_save <- function(p,filename){
          if (!is.null(p) && inherits(p, "ggplot") && nrow(p$data) > 3) {
            ggsave(filename = file.path(pb_write_dir(), filename), plot = p,
                   width = 10, height = 10, units = "in")
          } else if (inherits(p, "ggplot")) {
            message("[msg]")
          } else {
            message("[msg]")
          }
        }

        # ③KEGG
        KEGG_enrich_Func <- function(gene,filename){
          kegg_enrich_results <- enrichKEGG(gene = gene,
                                            organism  = organism,
                                            pvalueCutoff = 0.05,
                                            qvalueCutoff = 0.2
          ) 
          # NULL
          if (is.null(kegg_enrich_results)) {
            message("No significant KEGG pathways found.")
          } else {
            # setReadable
            kegg_enrich_results <- DOSE::setReadable(kegg_enrich_results, OrgDb=OrgDb, 
                                                     keyType='ENTREZID')#ENTREZID to gene Symbol
            kegg_enrich <- kegg_enrich_results@result%>%
              filter(p.adjust < 0.05)
            deg_rich_save(kegg_enrich, gse.number, compareName, filename)
            return(kegg_enrich_results)
          }
        }

        # ④GO
        GO_enrich_Func <- function(gene,filename){
          ontologies <- c("BP", "MF", "CC")
          results_list <- list()
          # go_enrich_results
          go_enrich_results_list <- list()

          for (ont in ontologies) {
            # GO
            temp_results <- enrichGO(gene = gene,
                                     OrgDb = OrgDb,
                                     ont = ont,
                                     pvalueCutoff = 0.05,
                                     qvalueCutoff = 0.2)

            # NULL
            if (is.null(temp_results)) {
              message(paste("No significant GO terms found for ontology:", ont))
              next
            } else {
              go_enrich_results <- DOSE::setReadable(
                temp_results, OrgDb = OrgDb, keyType = "ENTREZID"
              )
              go_enrich <- go_enrich_results@result %>%
                filter(p.adjust < 0.05)

              if (nrow(go_enrich) == 0) {
                message(paste("No significant GO terms found after filtering for ontology:", ont))
              } else {
                # ONTOLOGY
                go_enrich$ONTOLOGY <- ont

                results_list[[ont]] <- go_enrich
                # go_enrich_results
                go_enrich_results_list[[ont]] <- go_enrich_results
              }
            }
          }

          if (length(results_list) == 0) {
            message("No significant results found for any ontology.")
            return(NULL)
          } else {
            combined_results <- bind_rows(results_list) %>%
              dplyr::select(ONTOLOGY, everything()) %>%
              as.data.frame()
            rownames(combined_results) <- combined_results$ID

            # enrichResult
            if (length(go_enrich_results_list) > 0) {
              combined_go_enrich_results <- go_enrich_results_list[[1]]
              combined_go_enrich_results@result <- combined_results
            } else {
              combined_go_enrich_results <- NULL
            }

            deg_rich_save(combined_results,gse.number,compareName,filename)
            return(combined_go_enrich_results)
          }

        }

        # ⑤CellMarker
        cellmarker_rich_func <- function(gene_select,gse.number,compareName, regulation, filename){
          cellmarker_rich <- enricher(gene = gene_select,
                                      TERM2GENE = cellmarker[, .(geneSymbol), by = CellType], 
                                      TERM2NAME = cellmarker[, .(Source), by = CellType], 
                                      pvalueCutoff = 0.05, 
                                      pAdjustMethod = 'BH', 
                                      qvalueCutoff = 0.2, 
                                      maxGSSize = 500)

          if (!is.null(cellmarker_rich)) {
            result <- cellmarker_rich@result
            result$data <- gse.number
            result$group <- compareName
            result$Regulation <- regulation
            result <- result[,c(13,14,1,2,15,3,4,8,9,10,11,12)]
            colnames(result) <- c("data", "group",
                                  "CellType", "Source", "Regulation", 
                                  "GeneRatio", "BgRatio", "P-value", "Adjusted P-value", 
                                  "qvalue", "MarkerGene", "count")
            fwrite_pb(result, file.path(pb_write_dir(), filename), sep = ",")
            return(result)
          }

        }

        # ⑥KEGG  GO
        networkDiagram_Func <- function(diff_enrich_results,pathway2gene_filename,pathway2pathway_filename){
          if(!is.null(diff_enrich_results) && nrow(diff_enrich_results) > 1) {
            gene_pathway <- diff_enrich_results@result[, c("Description", "geneID")]
            gene_pathway_long <- do.call(rbind, lapply(1:nrow(gene_pathway), function(i) {
              data.frame(Pathway = gene_pathway$Description[i], Gene = unlist(strsplit(gene_pathway$geneID[i], "/")))
            }))
            fwrite_pb(gene_pathway_long, file.path(pb_write_dir(), paste0(pathway2gene_filename, ".csv")), sep = ",")

            # GO
            pathway2 <- pairwise_termsim(diff_enrich_results)
            similarity_matrix <- as.data.frame(pathway2@termsim)
            similarity_matrix$Term1 <- rownames(similarity_matrix)
            similarity_matrix <- as.data.table(similarity_matrix)
            long_sim <- melt(similarity_matrix, id.vars = "Term1", variable.name = "Term2", value.name = "similarity")
            # 0
            long_sim <- long_sim[long_sim$similarity > 0, ]
            # countp.adjust
            long_sim <- merge(long_sim, diff_enrich_results@result[,c("Description","p.adjust","Count")], by.x = "Term1", by.y ="Description",all.x = T)
            fwrite_pb(long_sim, file.path(pb_write_dir(), paste0(pathway2pathway_filename, ".csv")), sep = ",")

            if (!isTRUE(perf$skip_network_plots)) {
              # /
              p1 <- enrichplot::cnetplot(diff_enrich_results, circular = FALSE, color.params = list(edge = TRUE))
              network_save(p1, paste0(pathway2gene_filename,".pdf"))
              # /
              p2 <- enrichplot::emapplot(pathway2, showCategory = 50)
              network_save(p2, paste0(pathway2pathway_filename,".pdf"))
            }
          }
        }

        # ⑦
        enrich_ana_func <- function(DEG_significant){
          gene_select <- DEG_significant$SYMBOL
          DEG_significant_up <- DEG_significant[DEG_significant$regulation == "up",]
          gene_select_up <- DEG_significant_up$SYMBOL
          DEG_significant_down <- DEG_significant[DEG_significant$regulation == "down",]
          gene_select_down <- DEG_significant_down$SYMBOL

          # SymbolEntrez
          {
            gene_up_entrez <- tryCatch({
              # bitr  ID
              result <- bitr(
                gene_select_up,
                fromType = "SYMBOL",
                toType = "ENTREZID",
                OrgDb = OrgDb
              )

              # ENTREZID  NA
              entrez_ids <- as.character(na.omit(result[, 2]))

              if (length(entrez_ids) == 0) {
                warning("[msg]")
              }

              # ENTREZID
              entrez_ids
            }, error = function(e) {
              message("[msg]", e$message)
              return(NULL)
            })

            gene_down_entrez <- tryCatch({
              # bitr  ID
              result <- bitr(
                gene_select_down,
                fromType = "SYMBOL",
                toType = "ENTREZID",
                OrgDb = OrgDb
              )

              # ENTREZID  NA
              entrez_ids <- as.character(na.omit(result[, 2]))

              if (length(entrez_ids) == 0) {
                warning("[msg]")
              }

              # ENTREZID
              entrez_ids
            }, error = function(e) {
              message("[msg]", e$message)
              return(NULL)
            })

            gene_diff_entrez <- unique(c(gene_up_entrez ,gene_down_entrez ))
          }

          # 2.2.1
          if (!is.null(gene_up_entrez) && length(gene_up_entrez)>0) {
            go_up_enrich_results <- GO_enrich_Func(gene_up_entrez, "GO_enrich_up.csv")
            kegg_up_enrich_results <- KEGG_enrich_Func(gene_up_entrez, "KEGG_enrich_up.csv")

          }

          # 2.2.2
          if (!is.null(gene_down_entrez) && length(gene_down_entrez)>0) {
            go_down_enrich_results <- GO_enrich_Func(gene_down_entrez, "GO_enrich_down.csv")
            kegg_down_enrich_results <- KEGG_enrich_Func(gene_down_entrez, "KEGG_enrich_down.csv")
          }

          # 2.2.3
          if (!is.null(gene_diff_entrez) && length(gene_diff_entrez)>0){
            go_diff_enrich_results <- GO_enrich_Func(gene_diff_entrez, "GO_enrich_AllDiff.csv")
            networkDiagram_Func(go_diff_enrich_results, "GO_Gene_NetworkDiagram", "GO_GO_NetworkDiagram")

            kegg_diff_enrich_results <- KEGG_enrich_Func(gene_diff_entrez, "KEGG_enrich_AllDiff.csv")
            networkDiagram_Func(kegg_diff_enrich_results, "KEGG_Gene_NetworkDiagram", "KEGG_KEGG_NetworkDiagram")
          }

          # 2.2.4 CellMarker
          {
            if (length(gene_select_up)>0) {
              cellmarker_rich_up <- cellmarker_rich_func(gene_select_up,gse.number,compareName, "up","CellMarker_rich_up.csv")
            }
            if (length(gene_select_down)>0) {
              cellmarker_rich_down <- cellmarker_rich_func(gene_select_down,gse.number,compareName, "down","CellMarker_rich_down.csv")
            }
            if (exists("cellmarker_rich_up") && exists("cellmarker_rich_down")) {
              cellmarker_rich <- rbind(cellmarker_rich_up, cellmarker_rich_down)
              #cellmarker_rich <- cellmarker_rich[order(cellmarker_rich$`P-value`), ]
            } else if (!exists("cellmarker_rich_up") && exists("cellmarker_rich_down")) {
              cellmarker_rich <- cellmarker_rich_down #[order(cellmarker_rich_down$`P-value`), ]
            } else if (exists("cellmarker_rich_up") && !exists("cellmarker_rich_down")) {
              cellmarker_rich <- cellmarker_rich_up #[order(cellmarker_rich_up$`P-value`), ]
            }
            if(exists("cellmarker_rich") && !is.null(cellmarker_rich)) {
              fwrite_pb(cellmarker_rich, file.path(pb_write_dir(), "CellMarker_rich.csv"), sep = ",")

            }

          }
        }
      }

      # (3)GSEA
      # ①GSEA plotKEGGGOGSEA
      GSEA_plot <- function(kk_gse, kk_gse_cut) {
        kk_gse_cut <- cap_gsea_terms(kk_gse_cut, perf$max_gsea_plots)
        if (is.null(kk_gse_cut) || nrow(kk_gse_cut) == 0) return(invisible(NULL))
        message("GSEA plots: ", nrow(kk_gse_cut))
        for (i in seq_along(kk_gse_cut$ID)) {
          gseap1 <- gseaplot2(kk_gse,
                              kk_gse_cut$ID[i],
                              title = kk_gse_cut$Description[i],
                              color = "red",
                              base_size = 20,
                              rel_heights = c(1.5, 0.5, 1),
                              subplots = 1:3,
                              ES_geom = "line",
                              pvalue_table = T)
          filename <- paste0(gsub("[:\\/]", "_", kk_gse_cut$ID[i]), '.jpg')
          ggsave(filename = file.path(pb_write_dir(), filename), plot = gseap1,
                 width = 10, height = 8)
        }
      }

      # ②GOont
      gsea_go_func <- function(geneList, ont) {
        GO_kk_entrez <- gseGO(geneList     = geneList,
                              ont          = ont,
                              OrgDb        = OrgDb,
                              keyType      = "ENTREZID",
                              pvalueCutoff = 0.05,
                              pAdjustMethod = "BH")

        if (nrow(GO_kk_entrez@result) == 0) {
          message("No enriched terms found under the specific pvalueCutoff.")
        } else {
          GO_kk <- DOSE::setReadable(GO_kk_entrez, 
                                     OrgDb=OrgDb,
                                     keyType='ENTREZID')

          # |NES|>1NOM pvalue<0.05FDRpadj<0.25
          GO_kk_cut <- GO_kk[GO_kk$pvalue<0.05 & GO_kk$p.adjust<0.25 & abs(GO_kk$NES)>1]

          gsea_go <- as.data.frame(GO_kk_cut)
          gsea_go$data <- gse.number
          gsea_go$group <- compareName
          if (!"ONTOLOGY" %in% names(gsea_go)) gsea_go$ONTOLOGY <- ont

          GSEA_plot(GO_kk, GO_kk_cut)
          return(gsea_go)
        }
      }

      # ③KEGGGOGSEA
      GSEA_analysis <- function(need_DEG) {
        colnames(need_DEG) <- c('log2FoldChange','SYMBOL')
        need_DEG$SYMBOL <- rownames(need_DEG)

        # gseageneListlog2FoldChangeENTREZID
        # id
        df <- bitr(rownames(need_DEG),
                   fromType = "SYMBOL",
                   toType =  "ENTREZID",
                   OrgDb = OrgDb)
        need_DEG <- merge(need_DEG, df, by='SYMBOL')
        # ENTREZID log2FoldChange
        # need_DEG_avg <- need_DEG %>%
        #   group_by(ENTREZID) %>%
        #   summarise(log2FoldChange = median(log2FoldChange, na.rm = TRUE), .group = 'drop')

        geneList <- need_DEG$log2FoldChange
        names(geneList) <- need_DEG$ENTREZID
        geneList <- geneList[!duplicated(names(geneList))]
        geneList <- sort(geneList, decreasing = T)
        geneList <- geneList[is.finite(geneList)]

        # KEGGgsea
        KEGG_kk_entrez <- gseKEGG(geneList     = geneList,
                                  organism     = organism,
                                  pvalueCutoff = 0.05)

        if (nrow(KEGG_kk_entrez@result) == 0) {
          message("No enriched terms found under the specific pvalueCutoff.")
        } else {
          # ID
          KEGG_kk <- DOSE::setReadable(KEGG_kk_entrez, 
                                       OrgDb=OrgDb,
                                       keyType='ENTREZID')

          # |NES|>1NOM pvalue<0.05FDRpadj<0.25
          KEGG_kk_cut <- KEGG_kk[KEGG_kk$pvalue<0.05 & KEGG_kk$p.adjust<0.25 & abs(KEGG_kk$NES)>1]

          gsea_kegg <- KEGG_kk_cut
          gsea_kegg$data <- gse.number
          gsea_kegg$group <- compareName
          fwrite_pb(gsea_kegg, file.path(pb_write_dir(), "GSEA_KEGG.csv"), sep = ",")

          GSEA_plot(KEGG_kk, KEGG_kk_cut)
        }

        # GOgsea (ont=ALL once)
        gsea_go <- gsea_go_func(geneList, "ALL")
        if (!is.null(gsea_go) && nrow(gsea_go) > 0) {
          fwrite_pb(gsea_go, file.path(pb_write_dir(), "GSEA_GO.csv"), sep = ",")
          message("GSEA results saved to: GSEA_GO.csv")
        } else {
          warning("No GSEA results to save!")
        }

      }

      # (4)GSVA
      # ①GSVA
      GSVA_ana <- function(dat, geneset){
        gsvaPar <- gsvaParam(dat,geneset,
                             kcdf = "Poisson", #Gaussian" for logCPM,logRPKM,logTPM, "Poisson" for counts
                             minSize = 5,
                             maxSize = 500 )
        es.max <- gsva(gsvaPar, verbose = FALSE)
        return(es.max)
      }

      # ②limma
      deg_limma <- function(es_max, design, contrast_matrix, group_list){
        ##step1
        fit <- lmFit(es_max, design)
        ##step2
        fit2 <- contrasts.fit(fit, contrast_matrix) 

        # if (any(!is.finite(fit2$coefficients)) || any(!is.finite(fit2$sigma))) {
        #   warning("Non-finite values detected in the fit object. Replacing with NA.")
        #   fit2$coefficients[!is.finite(fit2$coefficients)] <- NA
        #   fit2$sigma[!is.finite(fit2$sigma)] <- NA
        # }

        fit2 <- eBayes(fit2)  ## default no trend !!!
        ##eBayes() with trend=TRUE
        ##step3
        res <- decideTests(fit2, p.value = 0.05)
        summary(res)
        tempOutput = topTable(fit2, coef=1, n=Inf)
        nrDEG = na.omit(tempOutput) 

        if(nrow(info_Control) >= 2 ) {
          control_mean <- rowMeans(es_max[, group_list == group1])
          nrDEG$AveExpr_Control <- control_mean[rownames(nrDEG)]
        } else {
          nrDEG$AveExpr_Control <- es_max[, group_list == group1]
        }

        if(nrow(info_Treatment) >= 2 ) {
          treatment_mean <- rowMeans(es_max[, group_list == group2])
          nrDEG$AveExpr_Case <- treatment_mean[rownames(nrDEG)]
        } else {
          nrDEG$AveExpr_Case <- es_max[, group_list == group2]
        }

        head(nrDEG)
        return(nrDEG)
      }


      # ③ ()
      safe_analysis <- function(expr, analysis_name) {
        tryCatch(
          {
            eval(expr)
          },
          error = function(e) {
            message("\n[!] ", analysis_name, "[msg]", e$message)
            return(NULL)
          }
        )
      }

      # ④GSVA
      GSVA_func <- function(current_counts) {
        current_counts <- current_counts[, group_data$Sample]
        data_GSVA <- data.frame(current_counts)
        dat <- as.matrix(data_GSVA)

        group_list <- factor(group_data$Group, levels = c(group1, group2))
        design <- model.matrix(~0 + group_list)
        rownames(design) <- colnames(data_GSVA)
        colnames(design) <- levels(group_list)

        contrast_formula <- paste0(group2, "-", group1)
        contrast_matrix <- makeContrasts(contrasts = contrast_formula, levels = design)

        # GOKEGGGSVA ()
        go_kegg_result <- safe_analysis(
          expr = {
            es_max_GO <- GSVA_ana(dat, go_list)
            es_max_KEGG <- GSVA_ana(dat, kegg_list)
            es_max <- rbind(es_max_GO, es_max_KEGG)

            nrDEG_GO <- safe_analysis(deg_limma(es_max_GO, design, contrast_matrix, group_list), "[msg]")
            nrDEG_KEGG <- safe_analysis(deg_limma(es_max_KEGG, design, contrast_matrix, group_list), "[msg]")

            if (is.null(nrDEG_GO)) nrDEG_GO <- data.frame()
            if (is.null(nrDEG_KEGG)) nrDEG_KEGG <- data.frame()

            nrDEG <- rbind(nrDEG_GO, nrDEG_KEGG)

            if (nrow(nrDEG) > 0) {
              nrDEG$data <- gse.number
              nrDEG$group <- compareName
              nrDEG <- nrDEG[, c(9,10,7,8,1,2,3,4,5,6)]
              nrDEG$Regulation <- base::as.factor(
                ifelse(nrDEG$P.Value < 0.05,
                       ifelse(nrDEG$logFC > 0, 'UP', 'DOWN'), 'Stable')
              )

              nrDEG_with_rownames <- nrDEG %>% rownames_to_column(var = "term")
              z_score_es_max <- t(scale(t(es_max)))
              es_max_hebin <- as.data.frame(z_score_es_max)
              es_max_with_rownames <- es_max_hebin %>% rownames_to_column(var = "term")
              nrDEG_all <- merge(nrDEG_with_rownames, es_max_with_rownames, by = "term")
              nrDEG_all <- annotate_gsva_term_meta(nrDEG_all, gsva_term_id_map, gsva_term_name_map)
              rownames(nrDEG_all) <- nrDEG_all$term

              nrDEG_significant <- nrDEG_all[nrDEG_all$P.Value < 0.05, ]
              nrDEG_significant <- nrDEG_significant[order(nrDEG_significant$P.Value), ]

              nrDEG_go_all <- nrDEG_all %>% filter(grepl("^GO", term))
              nrDEG_kegg_all <- nrDEG_all %>% filter(grepl("^KEGG", term))

              list(all = nrDEG_all, go = nrDEG_go_all, kegg = nrDEG_kegg_all, sig = nrDEG_significant)
            } else {
              message("[msg]")
            }
          },
          analysis_name = "GO/KEGG GSVA"
        )

        # GSVA ()
        try({
          if (!is.null(go_kegg_result)) {
            fwrite_pb(go_kegg_result$all, file.path(pb_write_dir(), "GSVA_DEG_all.csv"), sep = ",")
            fwrite_pb(go_kegg_result$go, file.path(pb_write_dir(), "GSVA_DEG_GO.csv"), sep = ",")
            fwrite_pb(go_kegg_result$kegg, file.path(pb_write_dir(), "GSVA_DEG_KEGG.csv"), sep = ",")
            fwrite_pb(go_kegg_result$sig, file.path(pb_write_dir(), "GSVA_DEG_significant.csv"), sep = ",")
          }
        })

        # ssGSEA (human only; skip if resource missing or perf$skip_ssgsea)
        if (organism == "hsa" && !is.null(ssGSEA_list) && !isTRUE(perf$skip_ssgsea)) {
          ssgsea_result <- safe_analysis(
            expr = {
              gsvaPar <- ssgseaParam(exprData = dat, geneSets = ssGSEA_list)
              ssGSEA_matrix <- gsva(gsvaPar, verbose = FALSE)

              nrDEG_ssGSEA <- safe_analysis(deg_limma(ssGSEA_matrix, design, contrast_matrix, group_list), "[msg]")

              if (is.null(nrDEG_ssGSEA)) nrDEG_ssGSEA <- data.frame()

              if (nrow(nrDEG_ssGSEA) > 0) {
                nrDEG_ssGSEA$data <- gse.number
                nrDEG_ssGSEA$group <- compareName
                nrDEG_ssGSEA <- nrDEG_ssGSEA[, c(9,10,7,8,1,2,3,4,5,6)]
                nrDEG_ssGSEA$Regulation <- base::as.factor(
                  ifelse(nrDEG_ssGSEA$P.Value < 0.05,
                         ifelse(nrDEG_ssGSEA$logFC > 0, 'UP', 'DOWN'), 'Stable')
                )

                # ssGSEA
                nrDEG_ssGSEA_with_rownames <- nrDEG_ssGSEA %>% rownames_to_column(var = "term")
                z_score_es_max_ssGSEA <- t(scale(t(ssGSEA_matrix)))
                es_max_hebin_ssGSEA <- as.data.frame(z_score_es_max_ssGSEA)
                es_max_with_rownames_ssGSEA <- es_max_hebin_ssGSEA %>% rownames_to_column(var = "term")
                nrDEG_ssGSEA_all <- merge(nrDEG_ssGSEA_with_rownames, es_max_with_rownames_ssGSEA, by = "term")
                rownames(nrDEG_ssGSEA_all) <- nrDEG_ssGSEA_all$term

                nrDEG_ssGSEA_significant <- nrDEG_ssGSEA_all[nrDEG_ssGSEA_all$P.Value < 0.05, ]
                nrDEG_ssGSEA_significant <- nrDEG_ssGSEA_significant[order(nrDEG_ssGSEA_significant$P.Value), ]

                list(all = nrDEG_ssGSEA_all, sig = nrDEG_ssGSEA_significant)
              } else {
                message("[msg]")
              }
            },
            analysis_name = "ssGSEA"
          )

          # ssGSEA ()
          try({
            if (!is.null(ssgsea_result)) {
              fwrite_pb(ssgsea_result$all, file.path(pb_write_dir(), "ssGSEA_DEG_all.csv"), sep = ",")
            }
          })
        }

      }

      # !!!pseudobulk
     pseudobulk_ana_func <- function(type){
        pb_root <- file.path(res_dir, type, "pseudobulk")
        dir.create(pb_root, recursive = TRUE, showWarnings = FALSE)
        DefaultAssay(scRNA_subset_inter) <- "SCT"

        celltypes <- unique(scRNA_subset_inter@active.ident)

        for (celltype in celltypes) {
          cells_in_type <- WhichCells(scRNA_subset_inter, idents = celltype)
          data <- subset(scRNA_subset_inter, cells = cells_in_type)

          if(length(unique(data@meta.data$Sample)) == nrow(group_data)) {
            ct_label <- celltype
            if (grepl("/", ct_label)) {
              ct_label <- gsub("/", "_", ct_label)
            } 
            ct_label <- gsub("\u03b1", "alpha", ct_label)
            ct_label <- gsub("\u03b2", "beta", ct_label)
            ct_label <- gsub("\u00a0", " ", ct_label)
            ct_label <- gsub(" ","_",ct_label)
            ct_dir <- file.path(pb_root, ct_label)
            dir.create(ct_dir, showWarnings = FALSE)

            .pb_ctx$active <- TRUE
            .pb_ctx$write_dir <- ct_dir
            .pb_ctx$resolution <- as.character(resolution_s)
            .pb_ctx$type <- as.character(type)
            .pb_ctx$celltype <- as.character(celltype)

            # bulk (RNA raw counts; slot= for Seurat v4, layer= for v5 if slot fails)
            counts <- AggregateExpression(data, group.by = "Sample", assays = "RNA",
                                          slot = "counts", return.seurat = FALSE)
            expr <- as.data.frame(counts[[1]])
            expr <- expr[rowSums(expr)>0,]
            expr <- cbind(gene=rownames(expr),expr)
            write_table_if_nonempty(expr, file.path(ct_dir, "count_expr.txt"), sep = "\t", quote = FALSE, row.names = FALSE)
            #fwrite(expr, file = file.path(ct_dir, "count_expr.tsv" ), sep = ",")

            # ①
            DEG_result <- DEG_func(expr)

            # ②GOKEGGCellMarker
            DEG_significant <- DEG_result$DEG_significant

            enrich_ana_func(DEG_significant)

            # ③GSEA
            DEG <- DEG_result$DEG
            need_DEG <- DEG[, c("log2FoldChange", "SYMBOL"), drop = FALSE]
            GSEA_analysis(need_DEG)

            # ④GSVA
            GSVA_func(expr)

            .pb_ctx$active <- FALSE

          } else {
            cat("[msg]")
          }

        }
      }
      # clusterpseudobulk
      Idents(scRNA_subset_inter) <- res_ident
      pseudobulk_ana_func("cluster")
      # celltype_scTypepseudobulk
      Idents(scRNA_subset_inter) <- "celltype_scType"
      pseudobulk_ana_func("celltype_scType")
      # celltype_SingleRpseudobulk
      Idents(scRNA_subset_inter) <- "celltype_SingleR"
      pseudobulk_ana_func("celltype_SingleR")

    }
    } # end pseudobulk multi gate

  }

  # gene trajectory (may be missing if slingshot block did not set `sim`)
  if (exists("sim", inherits = FALSE) && !is.null(sim)) {
    gene <- names(sim)
    gene_exp <- t(as.data.frame(sim@assays@data$counts))
    gene_traject_exp <- log2(gene_exp +1)
    gene_traject_exp <- data.frame(cell = meta_data[rownames(gene_traject_exp), "new_rownames"],gene_traject_exp,row.names = rownames(gene_traject_exp))
    fwrite_if_nonempty(gene_traject_exp, file.path(cohort_dir, "gene_trajectory_exp.csv"))
  } else {
    message("No slingshot `sim` object; skipping gene_trajectory_exp.csv")
  }

  if (!isTRUE(perf$skip_save_image)) {
    save(
      list = c("scRNA_subset_inter", "compareName", "gse.number", "organism",
               "group1", "group2", "do_multi_de"),
      file = file.path(cohort_dir, paste0(compareName, ".RData"))
    )
  } else {
    save(list = c("compareName", "gse.number", "organism"),
         file = file.path(cohort_dir, paste0(compareName, ".RData")))
    message("skip_save_image=TRUE; wrote lightweight .RData image")
  }

  write_analysis_success(cohort_dir, "scrna_seq", compareName)
  invisible(TRUE)
}


#' Attach Group / Sample / Source / new_rownames from samples_info.
#'
#' Joins cells to samples_info using meta$Source (batch key set by loader) against
#' samples_info columns in order: Source, Sample, ID. Falls back to control/treatment
#' alias matching when barcode prefixes (e.g. CTRL/GSI) do not match GSM labels.
add_group_metadata <- function(scRNA_all, samples_info) {
  samples_info <- as.data.frame(samples_info, stringsAsFactors = FALSE)
  if (!"ID" %in% colnames(samples_info)) {
    samples_info$ID <- as.character(seq_len(nrow(samples_info)))
  } else {
    samples_info$ID <- as.character(samples_info$ID)
  }
  samples_info$Sample <- as.character(samples_info$Sample)
  samples_info$Source <- as.character(samples_info$Source)
  samples_info$Group <- as.character(samples_info$Group)

  if (!"Source" %in% colnames(scRNA_all@meta.data) &&
      "orig.ident" %in% colnames(scRNA_all@meta.data)) {
    scRNA_all$Source <- as.character(scRNA_all$orig.ident)
  }
  cell_keys <- as.character(scRNA_all$Source)
  uk <- unique(cell_keys)

  # Build batch_key -> samples_info row index
  key_to_row <- NULL
  join_col <- NULL
  for (col in c("Source", "Sample", "ID")) {
    if (!col %in% colnames(samples_info)) next
    vals <- as.character(samples_info[[col]])
    if (length(vals) == nrow(samples_info) && all(uk %in% vals)) {
      key_to_row <- setNames(match(uk, vals), uk)
      join_col <- col
      break
    }
  }

  if (is.null(key_to_row)) {
    key_to_row <- .match_batch_keys_by_alias(uk, samples_info)
    if (!is.null(key_to_row)) {
      join_col <- "alias"
      message("Mapped barcode prefixes to samples_info via control/treatment aliases")
    }
  }

  if (is.null(key_to_row)) {
    stop(
      "Cannot map cell batch keys to samples_info.\n",
      "  Cell Source values: ", paste(uk, collapse = ", "), "\n",
      "  Tried samples_info columns Source / Sample / ID.\n",
      "  For merged 10x, Source is barcode -N and should match samples_info$ID.\n",
      "  For h5 / csv / per-sample 10x folders, Source is usually GSM and should match Sample.",
      call. = FALSE
    )
  }
  message("Joining cells to samples_info via ", join_col,
          " | batches: ", paste(names(key_to_row), collapse = ", "))

  row_idx <- unname(key_to_row[cell_keys])
  if (any(is.na(row_idx))) {
    stop("Some cells failed samples_info join. Unmapped keys: ",
         paste(unique(cell_keys[is.na(row_idx)]), collapse = ", "), call. = FALSE)
  }

  scRNA_all$original_rownames <- colnames(scRNA_all)
  scRNA_all$Sample <- samples_info$Sample[row_idx]
  scRNA_all$Group <- samples_info$Group[row_idx]
  # Canonical Source from samples_info (descriptive label used in outputs)
  scRNA_all$Source <- samples_info$Source[row_idx]

  orig <- scRNA_all$original_rownames
  if (!all(grepl("_", orig))) {
    message("Some barcodes lack '_'; prefixing Sample for new_rownames")
    scRNA_all$new_rownames <- paste0(scRNA_all$Sample, "_", orig)
  } else {
    scRNA_all$new_rownames <- paste0(
      scRNA_all$Sample, "_", sub("^[^_]*_", "", orig)
    )
  }

  print(table(scRNA_all$Group))
  scRNA_all
}

#' Map non-GSM batch prefixes (CTRL/GSI/...) to samples_info rows.
.match_batch_keys_by_alias <- function(uk, samples_info) {
  if (length(uk) != nrow(samples_info)) return(NULL)

  ctrl_batch_re <- "^(CTRL|CONTROL|CTRLS|VEH|VEHICLE|DMSO|UNTREATED|MOCK|WT)$"
  ctrl_sample_re <- "DMSO|CTRL|CONTROL|VEHICLE|UNTREATED|MOCK|\\bWT\\b"

  is_ctrl_batch <- grepl(ctrl_batch_re, uk, ignore.case = TRUE)
  is_ctrl_sample <- grepl(ctrl_sample_re, samples_info$Group, ignore.case = TRUE) |
    grepl(ctrl_sample_re, samples_info$Source, ignore.case = TRUE)

  # Also try: batch token appears inside Source/Group
  key_to_row <- setNames(rep(NA_integer_, length(uk)), uk)
  for (k in uk) {
    hit <- which(
      grepl(k, samples_info$Source, ignore.case = TRUE) |
        grepl(k, samples_info$Group, ignore.case = TRUE) |
        grepl(k, samples_info$Sample, ignore.case = TRUE)
    )
    if (length(hit) == 1L) key_to_row[[k]] <- hit
  }
  if (!anyNA(key_to_row) && length(unique(key_to_row)) == length(uk)) {
    return(key_to_row)
  }

  # Two-group CTRL vs treatment pattern (e.g. CTRL/GSI ↔ DMSO/DBZ)
  if (length(uk) == 2L && sum(is_ctrl_batch) == 1L && sum(is_ctrl_sample) == 1L) {
    key_to_row <- setNames(rep(NA_integer_, 2L), uk)
    key_to_row[is_ctrl_batch] <- which(is_ctrl_sample)
    key_to_row[!is_ctrl_batch] <- which(!is_ctrl_sample)
    if (!anyNA(key_to_row) && length(unique(unname(key_to_row))) == 2L) {
      return(key_to_row)
    }
  }

  NULL
}

#' Decide analysis mode: auto|single|multi.
resolve_scRNA_mode <- function(mode, comparisons) {
  mode <- tolower(as.character(mode))
  if (mode == "auto") {
    if (!is.null(comparisons) && nrow(comparisons) >= 1) return("multi")
    return("single")
  }
  if (!mode %in% c("single", "multi")) {
    stop("mode must be auto|single|multi", call. = FALSE)
  }
  mode
}

#' Check whether every expected output directory has a final success marker.
scRNA_outputs_complete <- function(gse_dir, outdirs) {
  outdirs <- as.character(outdirs)
  outdirs <- outdirs[nzchar(outdirs)]
  if (length(outdirs) == 0) return(FALSE)
  all(vapply(outdirs, function(od) {
    analysis_is_complete(file.path(gse_dir, od))
  }, logical(1)))
}