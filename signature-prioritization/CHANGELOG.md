# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2]

### Changed
- **Default background rule now matches the OCSP evaluation / paper setting.**
  `--pathway-mode` defaults to `majority`: per-record pairwise majority on
  enrich / gsea / gsva (a single non-empty method list is kept), then the
  automatic GSE recurrence cut (`min-dataset-freq` auto = 6 for data-rich
  conditions such as colorectal cancer). Previously the default was `union`,
  which inflated CRC backgrounds to ~10k terms and did not reproduce the
  deposited evaluation (`|B|` stored 1636 / effective 1629).
- Background filters accept **either** `--condition` **or** `--factor`
  (one is enough; both may be combined).

### Documentation
- Tutorial notebook and `examples/README.md` describe the new defaults and the
  condition-or-factor requirement.

## [0.1.1]

### Changed
- **Data bundle version is now tracked separately from the package version**
  (`DATA_VERSION` in `data_manager`, `orbit_ocsp/data_manager.py`). Previously
  the bundle URL and tarball names were derived from `__version__`, so any
  code-only release either required re-uploading ~155 MB of identical data or
  silently pointed `download-data` at a release tag nobody had created. Package
  0.1.1 keeps using the published `ocsp-data-v0.1.0` bundles.
- The release build stamps both versions and checks that the download URL tag
  and the tarball names agree on the data version. It no longer requires the two
  versions to be equal, which is the point of the split.

### Fixed
- Expression mode raised a bare `FileNotFoundError: ... 'Rscript'` when R was
  absent, naming neither the missing dependency nor a way forward. A preflight
  check now reports what is missing and the three options (conda environment,
  install R directly, or `--de-results` to skip R), and notes that gene-list and
  sequence modes are unaffected.

### Documentation
- The install section now leads with clone + conda rather than pip, because pip
  cannot install R and expression mode needs it. pip-only is documented as a
  valid path for gene-list and sequence modes.
- Corrected an instruction that could not work: `conda env create -f
  environment.yml` was shown as runnable after `pip install`, but
  `environment.yml` is not in the wheel and cannot be, since conda runs before
  the package exists. It is now fetched by URL or taken from the clone.
- Added a per-mode requirements table, and a section on working around slow or
  blocked bundle downloads (manual download, `--base-url` mirror, `--check`).

## [0.1.1]

### Changed
- Scoring-data version is now tracked separately from the package version via
  `DATA_VERSION`. The bundles are tens of megabytes and change far less often
  than the code; with a single shared version, every code-only release either
  required re-uploading identical data or pointed `download-data` at a release
  tag nobody created. 0.1.1 keeps using the existing `ocsp-data-v0.1.0`
  bundles.

### Fixed
- Expression mode raised a bare `FileNotFoundError: ... 'Rscript'` from
  subprocess when R was absent, naming neither the missing dependency nor a way
  forward. It now reports what is missing and the three options (conda
  environment, install R yourself, or `--de-results` to skip R), and notes that
  gene-list and sequence modes are unaffected.
- README recommended `conda env create -f environment.yml` after
  `pip install`, but that file is not in the wheel and cannot be — conda must
  run before the package exists. It is now fetched by URL, or taken from a
  clone.

### Documentation
- The install section leads with clone + conda rather than pip, because pip
  cannot supply the R stack that expression mode needs. pip-only is documented
  as valid for gene-list and sequence modes, with a per-mode requirements table.

## [Unreleased]

### Deployment

OCSP is published as the `signature-prioritization/` module of
[chenjiang-bio/ORBIT-organoid-resource](https://github.com/chenjiang-bio/ORBIT-organoid-resource),
alongside the other ORBIT modules, rather than as a standalone repository. The
release build now resolves this automatically:

- All placeholder org URLs resolve to the real repository, pointing at the
  module subdirectory for docs and the repository root for issues.
- The data-bundle release tag is namespaced `ocsp-data-v<version>`, since
  releases are shared across the monorepo and a bare `data-v…` tag would
  collide with sibling modules.
- **Fixed**: `data_manager.__version__` (which builds the data download URL and
  tarball names) still read 0.3.4 while the released package declared 0.1.0, so
  `download-data` requested a release tag that does not exist. The build now
  forces them to match and fails if they diverge.
- Data bundle version decoupled from the package version. `DATA_VERSION` in
  `data_manager` now drives the bundle filenames and the release tag, so a
  code-only release keeps using the published `ocsp-data-v0.1.0` assets instead
  of pointing at a data release tag nobody created. Bump it only when the data
  itself changes.
- **Fixed**: `download-data` wrote to the wrong directory. `data_root()` gives
  `ORBIT_OCSP_DATA` top priority, but the download default ignored it and used
  the home directory, so the download reported success — or `already_present`
  from a stale home copy — for a directory the tool never reads, and the
  validation step immediately after failed with "17 files missing".
- **Fixed**: the user data directory was `~/.orbit-ocsp/data` while every
  docstring and `--help` string said `~/.orbit_ocsp/data`. The release rename
  maps a bare package name onto the hyphenated CLI name, which is right for
  commands and wrong for a dot-directory. A build guard now rejects the
  hyphenated form.
- **Fixed**: `R/run_de.R` was not installed by pip, so expression mode failed
  for anyone who installed the package rather than running from a checkout —
  `_DEFAULT_RSCRIPT` resolved to a path that does not exist in site-packages.
  The script now also ships inside the package (`orbit_ocsp/R/run_de.R`),
  declared via `[tool.setuptools.package-data]`, and lookup prefers the packaged
  copy while still falling back to the repo-root copy in a source checkout.
  A build guard now fails if it is missing.
- **Fixed**: `pack_data_release.py` printed "Upload to GitHub release:
  data-v<version>" while the downloader fetches from `ocsp-data-v<version>`.
  Following that hint would have produced a release whose assets
  `download-data` could never find. The hint is now derived from the download
  URL itself, so it cannot drift again.
- **Fixed**: `README.md` was never copied into the release tree even though
  `pyproject.toml` declares it as the readme, so the wheel shipped an empty
  long description and the published folder had no landing page.
- **Fixed**: the CI workflow was written to `.github/workflows/` inside the
  module, a path GitHub Actions ignores for subdirectories, so it would never
  have run. It now ships as `ci-workflow-for-repo-root.yml` with install
  instructions, scoped by `paths:` and `working-directory:` so it triggers only
  on this module.
- README leads with `pip install orbit-ocsp` and documents the other routes
  under a collapsed section: `git+…#subdirectory=` (needed for a package in a
  monorepo subdirectory, and the only route that works before the PyPI upload),
  and an editable clone install.
- Added `environment.yml` for conda. There is no `conda install orbit-ocsp` and
  the README states that outright; conda's real value here is that it installs
  the R/Bioconductor packages (DESeq2, edgeR, limma) that expression mode needs
  and pip cannot provide. Package names verified against bioconda/conda-forge.
- `docs/RELEASE.md`: the PyPI upload is now marked required rather than
  optional, because the README's headline install command does not resolve until
  it happens.
- LICENSE copyright aligned with the host repository.
- New build guards, all failing the build: unresolved placeholders or template
  tokens, package/data version mismatch, and files referenced by
  `pyproject.toml` that are absent from the tree.

### Changed
- **Output fields audited against the manuscript.** Every column in
  `biomarker_ranked.*` and `method_scores.tsv` now uses vocabulary the methods
  section actually defines.
  - **BREAKING**: `method_scores.tsv` column `score` → `observed_statistic`.
    The old name implied the values were comparable across methods; they are
    raw statistics on different scales (an overlap count vs a Jaccard ratio).
  - **BREAKING**: `biomarker_ranked.tsv` columns `<method>_score` →
    `<method>_statistic`, for the same reason.
  - **BREAKING**: per-method `effect_size` is now the *standardized* deviation
    from the permutation null, `(observed − null mean) / null SD`, matching the
    paper. The unstandardized value is kept as `raw_deviation` in
    `metadata_json`. Sign is preserved, so verdicts and the label-blind
    semantic promotion rule are unaffected.
  - **BREAKING**: per-method verdicts `screening_enriched` / `screening_not_sig`
    → `enriched` / `not_sig`. The two-stage position moved to a separate
    `inference_stage` column, so no internal state leaks into a call.
  - Confidence tier `MODERATE` → `MEDIUM`, matching the paper's
    high/medium/low grades and the module's own tier map.
- Ranking and tie-breaking documented as primary p-value first, consensus
  second, matching the methods section.

- **BREAKING**: `biomarker_ranked.tsv` narrowed to columns the manuscript
  defines. `semantic_stage`, `semantic_permutations` and the per-method raw
  statistic columns moved out of the flat table; they remain in
  `biomarker_ranked.json` and `method_scores.tsv`. Per-method
  `<method>_effect_size` columns were added in their place, since standardized
  effect sizes *are* comparable across methods.
- `rank_gain` and `de_rank_full` in expression mode, reproducing the ΔRank
  column of the within-model reranking analysis. `rank_gain` is
  `de_rank_full − biomarker_rank`; it is `null` in genes and sequence modes,
  which have no differential-expression input. `de_rank_full` ranks across the
  whole DE table, since the existing `de_rank` only numbers within the filtered
  shortlist and cannot express a move from a deep DE position.
- `orbit_ocsp.expression_de.add_full_table_de_rank` for the full-table ranking.
- Field listing now reports how many background records support each value and
  orders values by that count, so `--condition` can be chosen on evidence
  instead of alphabetical accident. New flags: `--top N`, `--sort`,
  `--no-counts`; JSON output gains a `field_counts` map. New
  `collect_field_counts()`; `collect_field_values()` and
  `collect_condition_tree()` take `order=`. The library default stays
  alphabetical, the CLI default is frequency.

### Fixed
- No longer warns on import when `statsmodels` is absent. It is deliberately
  not a dependency, and the built-in Benjamini-Hochberg implementation agrees
  with `statsmodels` to floating-point precision including on ties, so the
  warning suggested a problem that did not exist. Equivalence is now tested.
- `n_overlap_terms` is surfaced in the flat table as `n_shared_pathways`,
  matching the wording of the Figure 5C/5D legends, which size dots by and
  tabulate the shared-pathway count.

### Added
- `primary_q_value` on every scored candidate: the primary hypergeometric
  p-value BH-adjusted across candidates. The paper states this adjustment is
  applied, but no pipeline ever called it — the correction function existed and
  was unreachable.
- `consensus_score`, `gene_verdict` and `gene_confidence` in
  `method_scores.tsv`, so the file is interpretable without joining back to
  `biomarker_ranked.tsv`. `consensus_score` is central to the paper and was
  previously absent from this file.
- `tests/unit/test_output_field_vocabulary.py`: pins output field names to the
  manuscript, and checks BH monotonicity and that q ≥ p.

### Removed
- **BREAKING**: per-method `q_value` column. It was emitted as NaN in every row
  ever produced — set to `None` unconditionally before serialization — and the
  paper claims no per-method FDR. Use `primary_q_value` instead.
- **BREAKING**: `combined_p_value` column. It duplicated `primary_p_value`
  while the docs described it as Fisher-combined; the paper explicitly declines
  to pool the five p-values into a combined statistic.

## [0.3.4] - 2026-07-20

### Added
- **Expression → biomarker pipeline** (`orbit-ocsp-expression` / `scripts/run_expression_biomarker.py`)
  - R DE with sample-size dispatch: 1vs1→edgeR; both n>8→Wilcoxon; else DESeq2/limma (`R/run_de.R`)
  - Gene ID resolution: symbol / Ensembl / Entrez → Entrez → protein FASTA (`data/protein/`)
  - Pathway lookup from `data/protein/all_merged_result.json` into ensemble scoring
- Ana_Meta example converter: `scripts/convert_ana_meta_example.py`

### Changed
- Default DE backend is **R** (Python simplified DE removed)
- Pathway JSON default path: `data/protein/all_merged_result.json`
- Documentation focused on the analysis flow only (`README.md`, `QUICK_START.md`); weight-training guides removed from user docs
- `.gitignore` tightened; large regenerable artifacts and `orbit-ocsp_training/` copy removed from the working tree

### Removed
- Pure-Python DESeq2/limma-style DE engines as the production path
- Bundled `orbit-ocsp_training/` duplicate tree and backup `*_bak.py` modules from the cleaned workspace

## [0.3.1] - 2025-10-29

### Fixed
- Package version bump to resolve PyPI upload conflict

## [0.3.0] - 2025-10-29

### Fixed
- **Statistical Logic**: Removed inappropriate FDR correction on Fisher's combined p-value
  - Fisher's method already combines p-values from multiple tests
  - Applying additional FDR correction to a single combined value is statistically meaningless
  - `combined_q_value`, `combined_q_value_go`, `combined_q_value_kegg` fields removed from dataclass, JSON output, and all reports
  - Confidence grading now correctly uses `combined_p_value` instead of `combined_q_value`

### Changed
- **Ensemble Report**: Simplified statistical reporting
  - "Fisher's Combined Q-value" → "Fisher's Combined P-value" throughout documentation
  - Removed misleading "Stage 3: Fisher's Q-value Validation" explanations
  - Confidence levels now correctly reference "Fisher's combined p-value"
  - LLM guard messages updated to show p-value threshold (e.g., "p<0.05") instead of q-value
- **JSON Structure**: Enhanced hierarchical parsing for reviewer interpretations
  - `consensus_findings`: Now properly structured with sub-items (e.g., enrichment_verdict, core_pathway, etc.)
  - `unique_insights`: Correctly parsed as expert-specific insights list
  - `resolution_of_disagreements`: Multi-level hierarchical structure with proper nesting
  - `final_recommendations`: Structured items with content and agreement metadata
- **LLM Prompt Engineering**: Reviewer prompt extensively updated
  - Explicit Markdown formatting rules and indentation guidelines
  - Clear examples for hierarchical structure output
  - Consistent formatting expectations for better JSON parsing

### Added
- **Robust JSON Parser**: New hierarchical parsing functions
  - `_parse_hierarchical_items()`: Stack-based parser for multi-level Markdown structures
  - `_parse_expert_section()`: Specialized parser for expert-specific insights
  - `_parse_section_hierarchically()`: Orchestrator for different section types
  - Correctly extracts categories, sub-categories, content, and agreement metadata

### Removed
- **BREAKING**: `combined_q_value` field from `EnsembleResult` dataclass
- **BREAKING**: `combined_q_value`, `combined_q_value_go`, `combined_q_value_kegg` from JSON output
- All explanatory text about "Fisher's Combined Q-value" from Markdown reports

## [0.2.6] - 2025-10-27

### Added
- **Ontology-Specific Q-values**: Separate FDR-corrected Q-values for GO and KEGG analyses
  - `combined_q_value_go`: Q-value specifically for Gene Ontology terms
  - `combined_q_value_kegg`: Q-value specifically for KEGG pathways
  - `q_value_GO` and `q_value_KEGG` in TSV output for individual methods
- **Ontology-Specific P-values**: Fisher's combined p-values for GO and KEGG
  - `combined_p_value_go`: Combined p-value across methods for GO terms
  - `combined_p_value_kegg`: Combined p-value across methods for KEGG pathways
- **Enhanced JSON Output**: Dual-format numeric representation (Option C)
  - Original numerical values preserved as floats
  - Formatted scientific notation in `_formatted` fields for readability
  - Applies to all p-values and q-values (overall, GO, KEGG, and individual methods)
- **LLM Guard Customization**: User-configurable conditions for LLM API calls
  - `--llm-guard-confidence`: Set minimum confidence score threshold (default: 0.7)
  - `--llm-guard-min-consensus`: Set minimum consensus score threshold (default: 0.6)
  - `--llm-guard-verdict`: Specify required verdict (default: "enriched", advanced)
  - `--llm-guard-max-qvalue`: Set maximum Q-value threshold (default: 0.05, advanced)
  - Informative messages when LLM generation is skipped due to filters
- **Comprehensive Documentation**:
  - Complete column descriptions for all 47 TSV columns in `RESULTS_GUIDE.md`
  - Categorized columns (Gene Info, Experimental Conditions, Statistical Method, Overall Stats, GO Stats, KEGG Stats)
  - Added GO vs KEGG analysis explanation section
  - Added practical TSV usage examples
  - Updated README with accurate command-line parameter documentation
  - Simplified and streamlined `examples/README.md`

### Changed
- **Markdown Reports**: Enhanced Executive Summary section
  - Added GO and KEGG specific P-values under "Combined P-value (Fisher's)"
  - Added GO and KEGG specific Q-values under "Combined Q-value (FDR-corrected)"
  - Improved clarity of statistical significance reporting
- **Individual Method Reports**: Added GO and KEGG Q-values to each method's report
- **TSV Output**: Expanded to include ontology-specific Q-values (47 total columns)
- **Dependency Versions**: Updated to NumPy 2.x compatible versions
  - numpy>=1.24.0, scipy>=1.11.0, pandas>=2.0.0, statsmodels>=0.14.0
  - Eliminates NumPy 2.x compatibility warnings
- **LLM Guard Logic**: Centralized and modularized in `_check_llm_guard_ensemble()` function
- **Configuration Examples**: Updated `config.ensemble_test.yaml` with clearer parameter documentation
- **Documentation Clarity**: Simplified verbose sections while maintaining technical accuracy

### Fixed
- **Q-value Calculation**: Corrected FDR calculation to use ontology-specific p-values
- **JSON Formatting**: Fixed potential dictionary overwriting issues in metadata expansion
- **Format String Error**: Fixed NoneType error when LLM interpretation is skipped
- **Parameter Documentation**: Corrected `--ensemble-r-values` to individual parameters
  - `--ensemble-r-hypergeometric`, `--ensemble-r-jaccard`, `--ensemble-r-overlap`, `--ensemble-r-semantic`
- **Configuration Syntax**: Fixed ensemble R-values format in example configs
- **NumPy Compatibility**: Resolved `_ARRAY_API not found` warnings with updated dependencies

### Removed
- **Emoji Characters**: Removed all emoji usage from code and outputs for better compatibility
- **Redundant LLM Guard Parameters**: Simplified default behavior documentation
- **Debug Scripts**: Removed temporary upload testing scripts

## [0.2.0] - 2024-10-11

### Added
- **Ensemble Analysis Framework**: Complete ensemble analysis with 5 statistical methods (hypergeometric, jaccard, lin_bma, overlap, resnik_bma)
- **Dynamic Weighted Voting**: Evidence-based weighting system that prioritizes methods with stronger statistical support
- **FDR Correction**: Benjamini-Hochberg procedure for multiple testing control
- **Fisher Validation**: Combined p-value validation for final decision
- **MoE (Mixture of Experts) Integration**: Multi-expert LLM collaboration with 3 experts + 1 reviewer
- **Structured JSON Output**: Hierarchical parsing with direct sub-category fields for better data access
- **Comprehensive Results Guide**: Detailed documentation for all output files
- **Configuration Examples**: Updated configuration files for ensemble analysis

### Changed
- **Default Analysis Method**: Ensemble analysis is now the default and recommended method
- **Output Structure**: Enhanced output with gene-level reports, structured JSON, and detailed statistics
- **Documentation**: Updated README and examples to focus on ensemble analysis
- **Performance**: Optimized R values for different methods in ensemble analysis

### Fixed
- **TSV Output**: Fixed column alignment and data population in ensemble_summary.tsv
- **LLM Integration**: Improved prompt structure and response parsing
- **JSON Serialization**: Fixed tuple key serialization issues
- **Code Quality**: Removed Chinese characters and emojis, improved internationalization

### Removed
- **Single Method Focus**: Reduced emphasis on individual statistical methods in documentation
- **Outdated Examples**: Removed references to non-existent configuration files

## [0.1.5] - Previous Version

### Features
- Basic permutation testing functionality
- Individual statistical methods (semantic, hypergeometric, jaccard, overlap)
- LLM integration for biological interpretation
- KEGG topology enhancement
- Parallel processing and performance optimization
