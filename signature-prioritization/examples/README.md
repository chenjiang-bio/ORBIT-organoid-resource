# Examples

Sample inputs for all three modes, organized by mode so that each folder maps
to exactly one command. Every file here is small enough to ship in git and is
exercised by `tests/integration/test_example_data.py`, so these commands stay
correct as the code changes.

```text
examples/
├── data/
│   ├── expression/            Mode 1 — expression matrix
│   │   ├── matrix.tsv           genes × samples, first column `gene`
│   │   └── groups.tsv           sample_id, group (case/control)
│   ├── genes/                 Mode 2 — gene list
│   │   ├── genes.txt            one symbol per line
│   │   └── a_terms.json         precomputed A_terms (for orbit-ocsp-ensemble)
│   └── sequence/              Mode 3 — annotation output
│       ├── native/            Entry A: raw tool output
│       │   ├── kofam/1.txt
│       │   ├── interproscan/1.tsv
│       │   ├── deepgoplus/1.tsv
│       │   └── id_map.tsv       query_id → entrez_id (optional)
│       └── merged/            Entry B: already merged
│           └── merged_result_1.json
├── config.no_llm.yaml         orbit-ocsp-ensemble config, no LLM
├── config.ensemble_test.yaml  orbit-ocsp-ensemble config, ensemble tuning
└── orbit_ocsp_tutorial.ipynb   Runnable walkthrough of all modes
```

All sample data is human (`--species hsa`). `--condition "Colorectal Cancer"`
is used throughout because it exists in the shipped background library.

---

## Mode 1 — Expression

```bash
orbit-ocsp --mode expression \
  --matrix examples/data/expression/matrix.tsv \
  --groups examples/data/expression/groups.tsv \
  --data-type microarray \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_expression
```

Needs R + Bioconductor (DESeq2 / limma / edgeR). For a no-R smoke test add
`--de-backend mock` — the DE numbers are synthetic, only the plumbing is real.

This demo matrix is tiny (a handful of genes), so few or no genes may clear the
default `--padj-max 0.05 --abs-log2fc-min 1.0`. Loosen with
`--padj-max 0.1 --abs-log2fc-min 0.5`.

## Mode 2 — Gene list

```bash
orbit-ocsp --mode genes \
  --genes-file examples/data/genes/genes.txt \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_genes
```

`a_terms.json` is for the low-level CLI, which takes pathway terms directly
instead of looking them up:

```bash
orbit-ocsp-ensemble --A examples/data/genes/a_terms.json \
  --species hsa --condition "Colorectal Cancer" \
  --stat ensemble --outdir out_enrichment
```

## Mode 3 — Sequence

orbit-ocsp does **not** run KOfam / InterProScan / DeepGOPlus. You run them; it
parses their output.

**Entry A — native tool output**

```bash
orbit-ocsp --mode sequence \
  --kofam examples/data/sequence/native/kofam/1.txt \
  --interproscan examples/data/sequence/native/interproscan/1.tsv \
  --deepgo examples/data/sequence/native/deepgoplus/1.tsv \
  --id-map examples/data/sequence/native/id_map.tsv \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_sequence
```

Batch form, using the same tree (`kofam/`, `interproscan/`, `deepgoplus/`
subfolders keyed by filename stem):

```bash
orbit-ocsp --mode sequence \
  --annotation-dir examples/data/sequence/native \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_sequence_batch
```

**Entry B — pre-merged JSON**

```bash
orbit-ocsp --mode sequence \
  --merged-json examples/data/sequence/merged/merged_result_1.json \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_sequence_merged
```

Inspect the merge without scoring:

```bash
orbit-ocsp --mode sequence \
  --kofam examples/data/sequence/native/kofam/1.txt \
  --interproscan examples/data/sequence/native/interproscan/1.tsv \
  --deepgo examples/data/sequence/native/deepgoplus/1.tsv \
  --merge-only --outdir out_merge
```

### Note on the two sequence samples

`native/` and `merged/` describe the **same protein** (`NP_570602.2`), but they
do not produce identical term sets:

| Input | KEGG | GO | Total |
|-------|------|----|----|
| `native/` merged by current code | 95 | 132 | 227 |
| `merged/merged_result_1.json` | 30 | 132 | 162 |

The pre-merged file came from an older script whose KO→pathway lookup kept only
one pathway per KO, dropping the rest. The GO half matches exactly; the KEGG
half is a strict subset. Entry B is kept as-is on purpose, so the difference is
visible and regression-tested.

## Notebook

```bash
pip install -e ".[notebook]"
jupyter notebook examples/orbit_ocsp_tutorial.ipynb
```

Runs all three modes against the files above, including merge-only inspection
of the term provenance.
