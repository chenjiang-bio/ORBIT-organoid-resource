# Ensemble Enrichment Analysis Report

**Generated:** 2026-07-25 11:52:34  
**Strategy:** Primary hypergeometric test (auxiliary methods = sensitivity only)  
**Species:** hsa  
**Condition:** Colorectal Cancer

---

## Executive Summary

**NOT_SIG** with **N/A METHOD AGREEMENT**

- **Final Verdict**: not_sig
- **Consensus Score**: 0.000 (0/5 methods agree)
- **Method-agreement tier**: N/A
- **Primary hypergeometric P-value**: 7.46e-02
  - GO primary P-value: None
  - KEGG primary P-value: None
- **Methods Used**: hypergeometric, jaccard, lin_bma, overlap, resnik_bma

---

## Decision Strategy

**Primary test plus correlated sensitivity analyses**

### Stage 1: Pre-specified primary test
- Exact right-tailed hypergeometric test
- Primary p-value: **7.46e-02**

### Stage 2: Unweighted robustness assessment (descriptive only)
- **0/5** methods support enrichment
- Consensus score: **0.0%**
- Overlap, Jaccard, Resnik-BMA and Lin-BMA are correlated sensitivity analyses
- Their p-values are not combined, do not veto the primary call, and are not treated as independent hypotheses

### Final Decision
- Verdict follows the **primary hypergeometric** call only: **not_sig**
- Method-agreement tier (descriptive): **N/A**

The method-agreement tier is descriptive and is not a calibrated probability.
Benjamini-Hochberg correction must be applied across candidate hypotheses,
using their primary hypergeometric p-values.

---

## Inputs

- A file: `N/A`
- B file: `auto-selected`
- Species: `hsa`
- Universe: |U| = 40273
- |A| terms: 23
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
| **hypergeometric** | 7.46e-02 | N/A | 7.00000 | 3.82981 | 0.00000 | 3.1702 | **1.00** | not_sig | 0.44s | YES |
| **jaccard** | 6.97e-02 | N/A | 0.00104 | 0.00057 | 0.00027 | 0.0005 | **1.00** | not_sig | 0.51s | YES |
| **lin_bma** | 5.49e-01 | N/A | 0.20901 | 0.20777 | 0.04873 | 0.0012 | **1.00** | screening_not_sig | 0.22s | NO |
| **overlap** | 6.97e-02 | N/A | 7.00000 | 3.82000 | 1.84788 | 3.1800 | **1.00** | not_sig | 0.44s | YES |
| **resnik_bma** | 5.88e-01 | N/A | 0.70985 | 0.71477 | 0.13101 | -0.0049 | **1.00** | screening_not_sig | 0.52s | NO |


**Note**: For detailed statistics (null mean, SD, z-score, GO/KEGG breakdown, runtime, etc.), see `ensemble_summary.tsv`. For per-method enriched terms and full analysis reports, see individual method reports in `method_reports/`.

---


---

## Consensus Analysis

**Voting Results:**
- **not_sig**: 3/5 methods (60.0%)
- **screening_not_sig**: 2/5 methods (40.0%)


**Consensus Score**: 0.000  
**Sensitivity agreement grading** (among the five methods; descriptive only):
- HIGH: ≥4 methods enriched
- MODERATE: exactly 3 methods enriched
- LOW: ≤2 methods enriched (primary still enriched)

**Agreement tier**: N/A


---

## Primary Test and Sensitivity Analysis

**Primary exact hypergeometric test:**
- Primary p-value: **7.46e-02**

**Sensitivity-analysis p-values:**
- hypergeometric=7.46e-02, jaccard=6.97e-02, lin_bma=5.49e-01, overlap=6.97e-02, resnik_bma=5.88e-01

**By Ontology:**

*GO Terms:*
- Primary p-value: **None**

*KEGG Pathways:*
- Primary p-value: **None**


---

## Enriched Terms Reference

### GO Terms (7)

- [GO:0001227](http://amigo.geneontology.org/amigo/term/GO:0001227) — DNA-binding transcription repressor activity, RNA polymerase II-specific
- [GO:0001666](http://amigo.geneontology.org/amigo/term/GO:0001666) — response to hypoxia
- [GO:0001890](http://amigo.geneontology.org/amigo/term/GO:0001890) — placenta development
- [GO:0035019](http://amigo.geneontology.org/amigo/term/GO:0035019) — somatic stem cell population maintenance
- [GO:0050767](http://amigo.geneontology.org/amigo/term/GO:0050767) — regulation of neurogenesis
- [GO:0070888](http://amigo.geneontology.org/amigo/term/GO:0070888) — E-box binding
- [GO:0090575](http://amigo.geneontology.org/amigo/term/GO:0090575) — RNA polymerase II transcription regulator complex


---

## Notes

- **Primary inference**: Exact hypergeometric enrichment is the pre-specified primary test.
- **Sensitivity analyses**: Overlap, Jaccard, Resnik-BMA and Lin-BMA assess robustness under complementary but correlated statistics.
- **Consensus Score**: Descriptive fraction of methods supporting enrichment; it is not a probability.
- **Multiple testing**: Apply BH correction across candidate genes or gene-condition hypotheses, not across methods.

*For method-specific details, refer to individual method sections above.*

---

*Generated by orgbioper v2.0 — Ensemble Enrichment Analysis*
