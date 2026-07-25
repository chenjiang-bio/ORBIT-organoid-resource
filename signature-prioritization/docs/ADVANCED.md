# Advanced usage

Optional. The three `--mode` commands in the README cover normal use.

## Filtering the background beyond `--condition`

The background library keys every contrast to organ, condition, model type, cell
type and study category, paired as condition/control arms. `--condition` alone
pools all matching contrasts; narrow it further with `--b-terms` filters exposed
through the Python API:

```python
from orbit_ocsp.expression_pipeline import load_condition_terms

terms = load_condition_terms(
    "data/data_b/B_terms_hsa.json",
    condition="Colorectal Cancer",
    organ_condition="Colon",
    model_condition="Organoid",
)
print(len(terms), "background terms")
```

Available filters:

| Filter | Selects on |
|--------|------------|
| `category`, `factor` | Study classification |
| `organ_condition` / `organ_control` | Organ, per arm |
| `organ_system_condition` / `organ_system_control` | Organ system |
| `model_condition` / `model_control` | Model system |
| `source_condition` / `source_control` | Sample source |
| `time_condition` / `time_control` | Timepoint |
| `cell_type` | Cell type |
| `comparison_condition` / `comparison_control` | Comparison arms |
| `additional_condition` | Sub-condition |

Discover valid values first. Values are listed best-supported first, with the
number of backing records:

```bash
orbit-ocsp-list-fields --species hsa --field organ_condition
orbit-ocsp-list-fields --species hsa --field organ_condition --top 20
orbit-ocsp-list-fields --species hsa --all
```

| Flag | Effect |
|------|--------|
| `--top N` | Only the N best-supported values per field |
| `--sort alpha` | Alphabetical instead of by record count |
| `--no-counts` | Hide the counts |
| `--format json` | Machine-readable, includes a `field_counts` map |

Use the counts to judge a filter before you apply it. Stacking several filters
multiplies the narrowing, and the record count tells you when you are about to
cut the background down to almost nothing.

A narrower background is more specific but smaller; a background of a few dozen
terms yields unstable permutation p-values. `n_b_terms` in the output records
the size actually used.

## Scoring a precomputed term set directly

If you already have the pathway terms for a gene, skip lookup entirely by
passing them as sequence-mode input — the schema is the same:

```json
[{"gene_name": "MYGENE", "similarity_gene_name": "MYGENE",
  "ENTREZ_ID": "", "pathway": ["hsa04310", "GO:0016055"]}]
```

```bash
orbit-ocsp --mode sequence --merged-json terms.json \
  --species hsa --condition "Colorectal Cancer" --outdir out/
```

## Tuning

| Option | Default | Effect |
|--------|---------|--------|
| `--alpha` | `0.005` | Significance threshold for the enriched call |
| `--seed` | `42` | Permutation RNG seed |
| `--top-k` | `20` | Candidates carried from DE into scoring (expression mode) |
| `--padj-max` | `0.05` | DE adjusted p-value cutoff (expression mode) |
| `--abs-log2fc-min` | `1.0` | DE effect-size cutoff (expression mode) |
| `--deepgo-min-score` | `0` | DeepGOPlus confidence cutoff (sequence mode) |

Same inputs, seed and data version give deterministic results.

## Data location

Resolution order for `data/`:

1. `$ORBIT_OCSP_DATA`
2. `~/.orbit_ocsp/data/`
3. `<repo>/data/` (editable install)
4. `./data/`

```bash
export ORBIT_OCSP_DATA=/shared/orbit-ocsp-data   # share one copy across users
```

Check what is present:

```python
from orbit_ocsp.data_manager import data_status
print(data_status("hsa"))
```

## Mouse data

Everything works identically with `--species mmu`, against the mouse background
and KO map. Condition names differ between species, so list them per species.
