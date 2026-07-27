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

**Recommended: clone, then let conda supply R.** Expression mode runs
differential expression in R (DESeq2/edgeR/limma), which pip cannot install.
Cloning also gives you `environment.yml`, the example data and the tutorial
notebook.

```bash
git clone https://github.com/chenjiang-bio/ORBIT-organoid-resource.git
cd ORBIT-organoid-resource/signature-prioritization

conda env create -f environment.yml   # Python deps + R + Bioconductor
conda activate orbit-ocsp
pip install -e .

orbit-ocsp-download-data --species hsa   # pathway background, 47 MB
```

<details>
<summary>pip only — fine for gene-list and sequence modes</summary>

If you are not using expression mode, R is irrelevant and pip alone is enough:

```bash
pip install orbit-ocsp
orbit-ocsp-download-data --species hsa
```

Expression mode will then fail with instructions until R is available, because
`pip` cannot install R packages. Two ways to proceed from there: create the
conda environment as above, or compute differential expression elsewhere and
feed the table in with `--de-results table.tsv` (columns `gene`,
`log2FoldChange`, `padj`), which skips R entirely.

Note that `environment.yml` is **not** in the wheel — conda has to run before
the package exists — so fetch it directly if you did not clone:

```bash
curl -O https://raw.githubusercontent.com/chenjiang-bio/ORBIT-organoid-resource/main/signature-prioritization/environment.yml
```

</details>

The pathway background is fetched once, separately, because one of its files is
199 MB and cannot ship in a package. Bundles: `hsa` 47 MB, `mmu` 35 MB, `full`
73 MB.

<details>
<summary>If the download is slow or blocked</summary>

The bundles are GitHub Release assets, which are slow or unreachable on some
networks. Three ways around it:

**Download by hand**, then point OCSP at the folder:

```bash
# Any downloader, or a browser, or a colleague's copy:
curl -LO https://github.com/chenjiang-bio/ORBIT-organoid-resource/releases/download/ocsp-data-v0.1.0/orbit-ocsp-data-hsa-0.1.1.tar.gz

mkdir -p ~/ocsp-data && tar xzf orbit-ocsp-data-hsa-0.1.1.tar.gz -C ~/ocsp-data
export ORBIT_OCSP_DATA=~/ocsp-data/data
```

Put the `export` line in your shell profile to make it permanent. Every command
reads this variable first, so nothing else needs configuring.

**Use a mirror** you control:

```bash
orbit-ocsp-download-data --species hsa --base-url https://your-mirror/path
```

The URL must be the directory holding the tarballs, whose names must be
unchanged. `ORBIT_OCSP_DATA_BASE_URL` sets the same thing for every run.

**Check what is already present** without downloading:

```bash
orbit-ocsp-download-data --check
```

`orbit-ocsp-download-data` also honours `ORBIT_OCSP_DATA`: when that variable is
set, the bundle is extracted there rather than into `~/.orbit_ocsp/data`.

</details>

<details>
<summary>Other ways to install</summary>

**Without cloning**, straight from the repository — OCSP is a subdirectory of
the ORBIT resource repository, hence the `#subdirectory=` fragment:

```bash
pip install "orbit-ocsp @ git+https://github.com/chenjiang-bio/ORBIT-organoid-resource.git#subdirectory=signature-prioritization"
```

**For development**, add the dev extra to the clone above:

```bash
pip install -e ".[dev]"
pytest -q
```

There is no `conda install orbit-ocsp`: OCSP is not on conda-forge or bioconda,
so conda supplies the environment and pip supplies the package.

</details>

### Requirements by mode

| Mode | Needs |
|------|-------|
| gene list | NumPy, SciPy, pandas |
| sequence | NumPy, SciPy, pandas |
| expression | the above **plus R** with DESeq2, edgeR and limma |

`conda env create -f environment.yml` covers all three. To add R to an existing
install instead:

```r
install.packages("BiocManager")
BiocManager::install(c("DESeq2", "limma", "edgeR"))
```

## Three ways in

```bash
# 1. Expression matrix with group labels — runs differential expression first
orbit-ocsp --mode expression \
  --matrix matrix.tsv --groups groups.tsv --data-type rnaseq_count \
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
