# Examples

Sample inputs for all three modes, organized by mode so that each folder maps
to exactly one command. Every file here is small enough to ship in git and is
exercised by `tests/integration/test_example_data.py`, so these commands stay
correct as the code changes.

```text
examples/
├── data/
│   ├── expression/            Mode 1 — expression matrix
│   │   ├── matrix.tsv           GSE50760 counts (primary CRC vs normal)
│   │   └── groups.tsv           sample_id, group (case=CRC / control=normal)
│   ├── genes/                 Mode 2 — gene list
│   │   ├── genes.txt            Wnt / stem markers (4 symbols)
│   │   ├── genes_epms.txt       receptor / oncogene set (4 symbols)
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
is used throughout because it exists in the shipped background library and
matches the GSE50760 disease contrast.

---

## Mode 1 — Expression

**RNA-seq demo** — subset of [GSE50760](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE50760)
(primary colorectal cancer vs adjacent normal colon; 18 vs 18 samples, 60
annotated genes, integer counts). Default DE thresholds already clear dozens
of genes that score against the Colorectal Cancer organoid background:

```bash
orbit-ocsp --mode expression \
  --matrix examples/data/expression/matrix.tsv \
  --groups examples/data/expression/groups.tsv \
  --data-type rnaseq_count \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_expression
```

`--data-type rnaseq` is accepted as an alias for `rnaseq_count`.

Needs R + Bioconductor (DESeq2 / limma / edgeR). For a no-R smoke test add
`--de-backend mock` — the DE numbers are synthetic, only the plumbing is real.

## Mode 2 — Gene list

**Wnt / stem markers** (`LEF1`, `CD44`, `LGR5`, `AXIN2`):

```bash
orbit-ocsp --mode genes \
  --genes-file examples/data/genes/genes.txt \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_genes
```

**Receptor / oncogene set** (`EPHB2`, `PROM1`, `MYC`, `SOX9`):

```bash
orbit-ocsp --mode genes \
  --genes-file examples/data/genes/genes_epms.txt \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_genes_epms
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
|-------|------|----|-------|
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
