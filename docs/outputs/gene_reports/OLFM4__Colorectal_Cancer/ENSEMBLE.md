# Ensemble Enrichment Analysis Report

**Generated:** 2026-07-25 11:52:38  
**Strategy:** Primary hypergeometric test (auxiliary methods = sensitivity only)  
**Species:** hsa  
**Condition:** Colorectal Cancer

---

## Executive Summary

**ENRICHED** with **MODERATE METHOD AGREEMENT**

- **Final Verdict**: enriched
- **Consensus Score**: 0.600 (3/5 methods agree)
- **Method-agreement tier**: MODERATE
- **Primary hypergeometric P-value**: 1.56e-02
  - GO primary P-value: None
  - KEGG primary P-value: None
- **Methods Used**: hypergeometric, jaccard, lin_bma, overlap, resnik_bma

---

## Decision Strategy

**Primary test plus correlated sensitivity analyses**

### Stage 1: Pre-specified primary test
- Exact right-tailed hypergeometric test
- Primary p-value: **1.56e-02**

### Stage 2: Unweighted robustness assessment (descriptive only)
- **3/5** methods support enrichment
- Consensus score: **60.0%**
- Overlap, Jaccard, Resnik-BMA and Lin-BMA are correlated sensitivity analyses
- Their p-values are not combined, do not veto the primary call, and are not treated as independent hypotheses

### Final Decision
- Verdict follows the **primary hypergeometric** call only: **enriched**
- Method-agreement tier (descriptive): **MODERATE**

The method-agreement tier is descriptive and is not a calibrated probability.
Benjamini-Hochberg correction must be applied across candidate hypotheses,
using their primary hypergeometric p-values.

---

## Inputs

- A file: `N/A`
- B file: `auto-selected`
- Species: `hsa`
- Universe: |U| = 40273
- |A| terms: 25
- |B| terms: 6706

---

## Ensemble Settings

| Parameter | Value |
|-----------|-------|
| Alpha | 0.05000 |
| Seed | 42 |
| Ensemble Strategy | Primary hypergeometric only; auxiliaries = sensitivity |
| R (hypergeometric) | 0 |
| R (jaccard) | 200 |
| R (lin_bma) | 50 |
| R (overlap) | 200 |
| R (resnik_bma) | 50 |

---

## Individual Methods Results

### Summary Table

| Method | P-value | Q-value | S_obs | mu | sd | Effect Size | Weight | Verdict | Runtime | Agrees |
|--------|---------|---------|-------|----|----|-------------|--------|---------|---------|--------|
| **hypergeometric** | 1.56e-02 | N/A | 9.00000 | 4.16284 | 0.00000 | 4.8372 | **1.00** | enriched | 0.02s | YES |
| **jaccard** | 3.48e-02 | N/A | 0.00134 | 0.00060 | 0.00030 | 0.0007 | **1.00** | enriched | 0.55s | YES |
| **lin_bma** | 4.90e-01 | N/A | 0.18538 | 0.18752 | 0.02657 | -0.0021 | **1.00** | screening_not_sig | 0.21s | NO |
| **overlap** | 3.48e-02 | N/A | 9.00000 | 4.05000 | 1.99686 | 4.9500 | **1.00** | enriched | 0.51s | YES |
| **resnik_bma** | 3.14e-01 | N/A | 0.75663 | 0.71743 | 0.10546 | 0.0392 | **1.00** | screening_not_sig | 0.57s | NO |


**Note**: For detailed statistics (null mean, SD, z-score, GO/KEGG breakdown, runtime, etc.), see `ensemble_summary.tsv`. For per-method enriched terms and full analysis reports, see individual method reports in `method_reports/`.

---


---

## Consensus Analysis

**Voting Results:**
- **enriched**: 3/5 methods (60.0%)
- **screening_not_sig**: 2/5 methods (40.0%)


**Consensus Score**: 0.600  
**Sensitivity agreement grading** (among the five methods; descriptive only):
- HIGH: ≥4 methods enriched
- MODERATE: exactly 3 methods enriched
- LOW: ≤2 methods enriched (primary still enriched)

**Agreement tier**: MODERATE


---

## Primary Test and Sensitivity Analysis

**Primary exact hypergeometric test:**
- Primary p-value: **1.56e-02**

**Sensitivity-analysis p-values:**
- hypergeometric=1.56e-02, jaccard=3.48e-02, lin_bma=4.90e-01, overlap=3.48e-02, resnik_bma=3.14e-01

**By Ontology:**

*GO Terms:*
- Primary p-value: **None**

*KEGG Pathways:*
- Primary p-value: **None**


---

## Enriched Terms Reference

### GO Terms (9)

- [GO:0035580](http://amigo.geneontology.org/amigo/term/GO:0035580) — specific granule lumen
- [GO:0042581](http://amigo.geneontology.org/amigo/term/GO:0042581) — specific granule
- [GO:0042582](http://amigo.geneontology.org/amigo/term/GO:0042582) — azurophil granule
- [GO:0043312](http://amigo.geneontology.org/amigo/term/GO:0043312) — neutrophil degranulation
- [GO:0045171](http://amigo.geneontology.org/amigo/term/GO:0045171) — intercellular bridge
- [GO:0045296](http://amigo.geneontology.org/amigo/term/GO:0045296) — cadherin binding
- [GO:0050764](http://amigo.geneontology.org/amigo/term/GO:0050764) — regulation of phagocytosis
- [GO:1900026](http://amigo.geneontology.org/amigo/term/GO:1900026) — positive regulation of substrate adhesion-dependent cell spreading
- [GO:1904724](http://amigo.geneontology.org/amigo/term/GO:1904724) — tertiary granule lumen


---

## Notes

- **Primary inference**: Exact hypergeometric enrichment is the pre-specified primary test.
- **Sensitivity analyses**: Overlap, Jaccard, Resnik-BMA and Lin-BMA assess robustness under complementary but correlated statistics.
- **Consensus Score**: Descriptive fraction of methods supporting enrichment; it is not a probability.
- **Multiple testing**: Apply BH correction across candidate genes or gene-condition hypotheses, not across methods.

*For method-specific details, refer to individual method sections above.*

---

*Generated by orgbioper v2.0 — Ensemble Enrichment Analysis*
