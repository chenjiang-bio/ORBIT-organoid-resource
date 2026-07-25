# OCSP — context-guided signature prioritization

Reprioritize candidate genes against an organoid-specific pathway background.

A differential-expression result usually leaves many candidates with no
indication of which matter in the organoid model under study, and most prior
functional knowledge comes from non-organoid systems. OCSP scores each candidate
not on its fold change but on how strongly its functional annotations match the
pathway background enriched in organoid models under matched conditions, and
returns a context-calibrated ranking with confidence grades.

One module of the [ORBIT organoid resource](https://github.com/chenjiang-bio/ORBIT-organoid-resource). Also available through
the ORBIT web platform.

[![CI](https://github.com/chenjiang-bio/ORBIT-organoid-resource/actions/workflows/signature-prioritization-ci.yml/badge.svg)](https://github.com/chenjiang-bio/ORBIT-organoid-resource/actions/workflows/signature-prioritization-ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://github.com/chenjiang-bio/ORBIT-organoid-resource/tree/main/signature-prioritization)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> OCSP reprioritizes and calibrates candidates within an organoid context. It
> does not identify validated biomarkers. Only genes carrying functional
> annotations can be scored (typically 3–10% of candidates per dataset), so
> results are context-calibrated rankings, not comprehensive assessments.

## Install

```bash
pip install orbit-ocsp
orbit-ocsp-download-data --species hsa   # pathway background, ~350 MB
```

Then fetch the pathway background once — it is not in the wheel, because one of
its files is 199 MB. Point at an existing copy instead with
`export ORBIT_OCSP_DATA=/path/to/data`.

<details>
<summary>Other ways to install</summary>

**Conda** — use this for expression mode. Differential expression runs in R, and
conda installs DESeq2/edgeR/limma alongside the Python dependencies in one step;
pip cannot install R packages.

```bash
conda env create -f environment.yml
conda activate orbit-ocsp
pip install orbit-ocsp
```

There is no `conda install orbit-ocsp`: OCSP is not on conda-forge or bioconda,
so conda provides the environment and pip provides the package.

**Straight from this repository**, without waiting for a release. OCSP is a
subdirectory of the ORBIT resource repository, hence the `#subdirectory=`
fragment:

```bash
pip install "orbit-ocsp @ git+https://github.com/chenjiang-bio/ORBIT-organoid-resource.git#subdirectory=signature-prioritization"
```

**From a local clone**, for development:

```bash
git clone https://github.com/chenjiang-bio/ORBIT-organoid-resource.git
cd ORBIT-organoid-resource/signature-prioritization
pip install -e ".[dev]"
```

</details>

Gene-list and sequence modes need only NumPy, SciPy and pandas. Expression mode
additionally needs R with:

```r
BiocManager::install(c("DESeq2", "limma", "edgeR"))
```

## Three ways in

```bash
# 1. Expression matrix with group labels — runs differential expression first
orbit-ocsp --mode expression \
  --matrix matrix.tsv --groups groups.tsv --data-type microarray \
  --species hsa --condition "Colorectal Cancer" --outdir out/

# 2. Gene list
orbit-ocsp --mode genes \
  --genes LEF1,CD44,LGR5 \
  --species hsa --condition "Colorectal Cancer" --outdir out/

# 3. Functional annotation for sequences with no existing annotation
orbit-ocsp --mode sequence \
  --merged-json annotations.json \
  --species hsa --condition "Colorectal Cancer" --outdir out/
```

`--condition` must match the background library. List valid values, best
supported first:

```bash
orbit-ocsp-list-fields --species hsa --field condition --top 15
```

```text
condition (15 values, most records first)
  - 6523  Normal
  -  326  Colorectal Cancer
  -  270  Retinoblastoma
  -  181  Coronavirus disease
  ...
```

The number is how many background records back that condition. More records
means a richer pathway background, so prefer well-supported conditions. Add
`--sort alpha` to browse by name instead, or drop `--top` for the full list.

### Input formats

**Expression** — `matrix.tsv` with first column `gene` then one column per
sample; `groups.tsv` with columns `sample_id` and `group` (`case` / `control`).

**Gene list** — `--genes SYM1,SYM2` or `--genes-file genes.txt`. Symbols,
Entrez or Ensembl IDs.

**Sequence** — for candidates with no existing pathway annotation. You run
KofamScan, InterProScan and/or DeepGOPlus; OCSP does not run them. Supply one
merged JSON (recommended):

```json
[
  {
    "gene_name": "NP_570602.2",
    "similarity_gene_name": "A1BG",
    "ENTREZ_ID": "1",
    "pathway": ["hsa04350", "GO:0005886"]
  }
]
```

or let OCSP merge the raw tool output:

```bash
orbit-ocsp --mode sequence \
  --kofam kofam_out.txt \
  --interproscan interproscan_out.tsv \
  --deepgo deepgo_out.tsv \
  --species hsa --condition "Colorectal Cancer" --outdir out/
```

Terms predicted this way are putative assignments. Tool links, commands and
formats: [`docs/SEQUENCE_ANNOTATION.md`](docs/SEQUENCE_ANNOTATION.md).

## How scoring works

For each candidate, its GO/KEGG annotations (**A**) are compared against the
condition-specific background (**B**) within a universe (**U**):

- **Primary test** — analytic hypergeometric enrichment. This determines the
  enriched call.
- **Four permutation-calibrated sensitivity statistics** — overlap count,
  Jaccard index, and Resnik- and Lin-based best-match-average semantic
  similarity. These are summarized as a consensus score.

Semantic statistics screen at 50 permutations and rerun survivors at 999.
Confidence is high when significant with agreement across methods
(consensus ≥ 0.8), medium at ≥ 0.6, and low when the primary test is
significant but the auxiliary methods largely disagree. Default significance
threshold is α = 0.005.

The background is assembled on the fly by filtering the pathway atlas on the
requested attributes and pooling enriched pathways of matching contrasts, so a
pathway is retained when it recurs across supporting datasets.

## Output

```text
out/
├── biomarker_ranked.tsv     one row per candidate — start here
├── biomarker_ranked.json    same data, nested
├── method_scores.tsv        per-method statistics
├── pipeline_summary.json    run metadata
└── gene_reports/<gene>/     per-candidate detail
```

Key columns: `biomarker_rank`, `verdict` (`enriched` / `depleted` /
`not_sig`), `consensus_score`, `primary_p_value`. Full reference:
[`docs/OUTPUTS.md`](docs/OUTPUTS.md).

## Try it

```bash
git clone https://github.com/chenjiang-bio/ORBIT-organoid-resource/tree/main/signature-prioritization.git && cd orbit-ocsp
pip install -e ".[dev]"

orbit-ocsp --mode genes --genes-file examples/data/genes/genes.txt \
  --species hsa --condition "Colorectal Cancer" --outdir out_demo
```

Sample inputs for all three modes are in `examples/data/`. Runnable
walkthrough: [`examples/orbit_ocsp_tutorial.ipynb`](examples/orbit_ocsp_tutorial.ipynb)
(`pip install -e ".[notebook]"`).

## Commands

| Command | Purpose |
|---------|---------|
| `orbit-ocsp` | Main entry point, `--mode expression\|genes\|sequence` |
| `orbit-ocsp-download-data` | Fetch the pathway background |
| `orbit-ocsp-list-fields` | Browse valid `--condition` and other filter values |

Filtering the background by organ, model type, cell type or timepoint:
[`docs/ADVANCED.md`](docs/ADVANCED.md).

## Documentation

| Doc | Content |
|-----|---------|
| [`docs/SEQUENCE_ANNOTATION.md`](docs/SEQUENCE_ANNOTATION.md) | Annotation tools, formats, merged JSON schema |
| [`docs/OUTPUTS.md`](docs/OUTPUTS.md) | Every output field |
| [`docs/ADVANCED.md`](docs/ADVANCED.md) | Background filters, single-method runs |
| [`examples/README.md`](examples/README.md) | Sample data, one command per mode |

## Tests

```bash
pytest -q
```

R is not required. Tests needing the downloaded background skip themselves when
it is absent.

## Citation

Jiang, C., Long, X.-Y., Luo, Y.-F., et al. ORBIT: transforming dispersed
organoid data into a computable knowledge resource.

## License

MIT — see [`LICENSE`](LICENSE).
