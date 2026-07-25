# Output reference

All three modes write the same files into `--outdir`.

```text
out/
├── biomarker_ranked.tsv        ← start here: one row per gene
├── biomarker_ranked.json         same data, nested
├── method_scores.tsv             one row per gene × method
├── pipeline_summary.json         run metadata
└── gene_reports/<GENE>__<CONDITION>/
    ├── ENSEMBLE.md               human-readable per-gene report
    ├── ENSEMBLE.json             structured version
    ├── ensemble_summary.tsv      method table
    └── method_reports/*.md       per-method detail
```

Mode-specific extras:

| Mode | Extra files |
|------|-------------|
| expression | `de_results.tsv` — full DE table before filtering |
| sequence, entry A | `merged_a_terms.json` — the merged annotation |
| sequence | `sequence_merge_report.json` — parse/merge diagnostics |

---

## biomarker_ranked.tsv

Genes are sorted best-first: successfully scored genes come before failures,
then by ascending `primary_p_value`, with `consensus_score` breaking ties.

**Identity**

| Column | Meaning |
|--------|---------|
| `biomarker_rank` | Final rank, 1 = best |
| `query_id` | What you supplied (symbol, ID, or sequence ID) |
| `gene_symbol`, `entrez_id`, `ensembl_id` | Resolved identifiers |
| `id_type` | How `query_id` was recognized |
| `mapping_status` | Whether ID resolution succeeded |
| `ncbi_gene_url` | Link to the NCBI Gene page |
| `report_dir` | Relative path to this gene's detailed report |

**Expression only** — `null` in the other modes:

| Column | Meaning |
|--------|---------|
| `de_rank` | Position within the filtered top-k shortlist (1..k) |
| `de_rank_full` | Position in the **full** DE ranking, before filtering |
| `rank_gain` | `de_rank_full − biomarker_rank`. Positive = promoted by context-guided reranking, negative = demoted |
| `log2FoldChange` | Fold change, case vs control |
| `padj` | BH-adjusted DE p-value |

`rank_gain` is the ΔRank quantity in the reranking analysis: it measures how
far a candidate moved once scored against the organoid context instead of by
fold change alone. It uses `de_rank_full`, not `de_rank` — a gene can sit at
position 364 of the full DE ranking while being 5th in the shortlist, and only
the former expresses the reranking effect.

**Scoring**

| Column | Meaning |
|--------|---------|
| `scoring_status` | `ok`, or why scoring did not happen (see below) |
| `verdict` | `enriched` or `not_sig`. Decided by the primary hypergeometric test alone |
| `confidence` | `HIGH` (consensus ≥ 0.8), `MEDIUM` (≥ 0.6), `LOW`, when the primary call is enriched |
| `consensus_score` | Fraction of the five statistics independently calling the gene enriched |
| `primary_p_value` | Hypergeometric p-value, unadjusted |
| `primary_q_value` | `primary_p_value` after BH adjustment across all candidates in the run |
| `n_shared_pathways` | Terms shared by the gene and the background |
| `<method>_p_value`, `<method>_effect_size` | Per-method values, flattened |

Every column above maps onto a quantity the methods section defines. Raw
per-method statistics and two-stage bookkeeping (`semantic_stage`,
`n_a_terms`, `n_b_terms`, `overlap_terms`, `agreement`) are deliberately kept
out of this table; they live in `biomarker_ranked.json` and
`method_scores.tsv` where their units and meaning are explicit.

The primary test is the sole determinant of the `enriched` call. The four
sensitivity statistics neither veto nor rescue it; they only inform
`consensus_score` and therefore `confidence`.

`scoring_status` values:

| Value | Meaning |
|-------|---------|
| `ok` | Scored |
| `no_pathway_annotation` | No GO/KEGG terms known for this gene |
| `score_unavailable` | Terms found, but no overlap with the universe or background |
| `error: ...` | Unexpected failure; the message is kept |

## method_scores.tsv

One row per gene × method, for inspecting how the ensemble was reached.

| Column | Meaning |
|--------|---------|
| `gene`, `condition`, `biomarker_rank` | Which comparison |
| `method` | `hypergeometric`, `jaccard`, `overlap`, `resnik_bma`, `lin_bma` |
| `observed_statistic` | The method's raw statistic. **Not comparable across methods** — an overlap count and a Jaccard index are different units |
| `p_value` | Analytic for `hypergeometric`, empirical permutation p-value for the other four |
| `effect_size` | Standardized deviation of the observed statistic from its null, `(observed − null mean) / null SD`. This *is* comparable across methods |
| `verdict` | This method's own call, `enriched` or `not_sig` |
| `inference_stage` | `screening`, `formal`, or `final`. Semantic methods start at `screening` |
| `rank` | Method order by p-value within the gene |
| `permutations` | Permutations used, `0` for the analytic primary test |
| `gene_verdict`, `gene_confidence`, `consensus_score` | Gene-level call, repeated so this file reads on its own |
| `metadata_json` | Method-specific detail, JSON string. Includes `raw_deviation`, the unstandardized `observed − null mean` |

To compare methods, read `effect_size`, not `observed_statistic`. The raw
statistic for `overlap` is a count in the tens while `jaccard` is a ratio in
the thousandths, so the two columns are only meaningful within a method.

## pipeline_summary.json

```json
{
  "mode": "genes",
  "n_input": 1,
  "n_ranked": 1,
  "condition": "Colorectal Cancer",
  "species": "hsa",
  "alpha": 0.005,
  "outputs": { "biomarker_ranked_json": "...", "...": "..." }
}
```

Sequence mode adds `entry` (`A` or `B`), `merged_json`, and
`deepgo_min_score`.

## biomarker_ranked.json

Same rows, but `biomarker_score` stays nested and carries fields the TSV
flattens away:

| Field | Meaning |
|-------|---------|
| `n_a_terms` | Gene terms used (after intersecting the universe) |
| `n_b_terms` | Condition background terms |
| `n_overlap_terms`, `overlap_terms` | Shared terms, and the first 20 |
| `agreement`, `total_methods` | Methods calling enriched / methods run |
| `semantic_stage`, `semantic_permutations` | `screening` (50) or `formal` (999) |
| `individual_methods[]` | Full per-method records |
| `go_links`, `kegg_links` | Links for the overlapping terms |
| `formal_selection_methods` | Methods promoted to 999 permutations |

---

## How the score is produced

For each gene, its GO/KEGG terms (**A**) are compared against the condition's
background (**B**) within a universe (**U**) by five methods:

| Method | Measures |
|--------|----------|
| `hypergeometric` | Enrichment of the overlap |
| `jaccard` | Set similarity, permutation null |
| `overlap` | Overlap size, permutation null |
| `resnik_bma` | GO semantic similarity, information content |
| `lin_bma` | GO semantic similarity, normalized |

`hypergeometric` is the pre-specified primary test and decides `verdict` on its
own. The other four are equal-weight sensitivity analyses, calibrated against
structure-preserving permutation nulls; their agreement becomes
`consensus_score`, which sets `confidence`. The five p-values are deliberately
*not* pooled into one combined statistic.

Semantic methods run in two stages: 50 permutations to screen, then 999 for
those passing p ≤ 0.10 with a positive effect. The promotion rule is
label-blind. `semantic_stage` records which stage a gene reached.

`primary_q_value` applies BH across the candidates in the run, not across the
five methods — the methods are correlated views of the same overlap, not
independent hypotheses. Weights are equal and static; there is no training
step.

## Reading a result

0. In expression mode, sort by `rank_gain` descending to see which candidates
   the organoid context promoted most relative to fold change.
1. Sort by `biomarker_rank` and look at `verdict` plus `primary_q_value`.
2. Check `consensus_score`: it does not change the call, but low agreement
   means the four sensitivity analyses did not reproduce the primary result.
3. Check `n_overlap_terms`. A tiny overlap with a strong p-value is fragile.
4. Open `gene_reports/<gene>__<condition>/ENSEMBLE.md` for which specific
   pathways drove the call.
5. In expression mode, confirm `padj` and `log2FoldChange` agree with the
   biological direction you expect.

Genes with `scoring_status != "ok"` stay in the table on purpose, so an absent
result is distinguishable from a negative one.
