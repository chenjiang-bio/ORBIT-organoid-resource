# Soft dependencies only — do not attach conflicted (breaks batch runners).
suppressPackageStartupMessages({
  if (!requireNamespace("stringr", quietly = TRUE)) {
    stop("Package 'stringr' is required for GEOMods.R")
  }
  if (!requireNamespace("data.table", quietly = TRUE)) {
    stop("Package 'data.table' is required for GEOMods.R")
  }
})

#' Extract annotation table from a GEO GPL object.
#'
#' @param GPLObject GPL S4 object with annotation in `@dataTable@table`
#' @return data.table of probe annotations
#' @export
getGPLTable <- function(GPLObject) {
  GPL.data <- data.table::as.data.table(GPLObject@dataTable@table)
  return(GPL.data)
}


#' Plot PCA cumulative variance and a simple UMAP embedding.
#'
#' @param umap.plot.data data.frame / data.table: rows = samples, columns = features
#' @param scale logical; scale features before PCA (default TRUE)
#' @return list with `plot.pca` and `plot.umap` ggplot objects
#' @export
run.pca.umap <- function(umap.plot.data, scale = TRUE) {
  pca.result <- prcomp(umap.plot.data, scale. = scale)
  pca.plot.data <- data.table(pca.cum = cumsum(pca.result$sdev^2 / sum(pca.result$sdev^2)) * 100,
                              number = NA) %>% mutate(number = seq_len(length(pca.cum)))
  plot.pca <- ggplot(pca.plot.data, aes(x = number, y = pca.cum)) +
    geom_point() +
    labs(x = "Number of PCs",
         y = "Cumulative Variance Explained (%)") +
    geom_hline(yintercept = 85, colour = "red", linetype = "dashed") +
    geom_vline(xintercept = min(pca.plot.data$number[pca.plot.data$pca.cum >= 85]), colour = "blue", linetype = "dashed") +
    annotate("text", x = 0, y = 88, label = "85% Variance Explained", colour = "red", hjust = 0) +
    theme_bw()

  umap.result <- umap.plot.data %>%
    uwot::umap(n_neighbors = min(5, ceiling(nrow(geo.meta) / 3) + 1), pca = min(pca.plot.data$number[pca.plot.data$pca.cum >= 85]) + 1) %>%
    data.table::as.data.table(keep.rownames = "Sample")

  plot.umap <- ggplot(umap.result, aes(x = V1, y = V2)) +
    geom_point(size = 2, color = "blue") +
    ggrepel::geom_text_repel(aes(label = Sample), size = 4, color = "black", max.overlaps = 50) +
    theme_minimal() +
    labs(title = "UMAP Result", x = "UMAP1", y = "UMAP2")

  return(list(plot.pca = plot.pca, plot.umap = plot.umap))
}


#' Map original sequence positions to MSA alignment coordinates.
#'
#' @param x named character vector of MSA sequences (gaps as "-")
#' @return named list; each element maps original base index -> MSA column index
#' @export
run.map <- function(x) {
  map.list <- vector("list", length = length(x)) %>%
    {setNames(., purrr::map_chr(names(x), function(y) {stringr::str_split(y, " ")[[1]][1]}))}

  for (i in seq_along(x)) {
    tmp.bp <- stringr::str_split(x[i], "") %>% unlist()
    original.position <- 1
    map.list[[i]] <- integer(sum(tmp.bp != "-"))

    for (j in seq_along(tmp.bp)) {
      if (tmp.bp[j] != "-") {
        map.list[[i]][original.position] <- j
        original.position <- original.position + 1
      }
    }
  }
  return(map.list)
}

#' Sanitize phenotype / group labels for use as file-safe tokens.
replace_chars <- function(x) {
  x <- stringr::str_replace_all(x, "[\\s\\-\\,/]", "_")
  x <- stringr::str_replace_all(x, "\\+", "__")
  x <- stringr::str_replace_all(x, "[^0-9a-zA-Z_]", "")
  return(x)
}
