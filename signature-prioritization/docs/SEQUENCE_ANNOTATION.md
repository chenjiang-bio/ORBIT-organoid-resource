# Sequence mode: annotation input

orbit-ocsp scores functional annotations. It **does not run** the annotation
tools — you run them yourself and hand orbit-ocsp the result files.

Two ways in:

| Entry | You provide | orbit-ocsp does |
|-------|-------------|----------------|
| **A** | Raw output from KOfam / InterProScan / DeepGOPlus | parse → merge → deduplicate → score |
| **B** | One merged JSON you assembled yourself (**recommended**) | validate → score |

Entry B is recommended for anything beyond a handful of sequences: you keep
control of the annotation step and orbit-ocsp only scores. Entry A exists so you
do not have to write the merge yourself for a quick run.

---

## The three tools

Install whichever you need. All are free; none is bundled with orbit_ocsp.

### KOfam / KofamScan — KEGG pathways

- Tool: <https://github.com/takaram/kofam_scan>
- Database (`profiles/` + `ko_list`): <ftp://ftp.genome.jp/pub/db/kofam/>
- Conda: `conda install -c bioconda kofamscan`
- Web server (no install): <https://www.genome.jp/tools/kofamkoala/>

```bash
exec_annotation -f detail -o kofam_out.txt protein.fasta
```

Use the default `-f detail` format. orbit-ocsp reads the whitespace-aligned
columns `gene name / KO / thrshld / score / E-value / KO definition`, skips `#`
comment lines, and strips the leading `*` that marks a hit above the adaptive
threshold.

```text
# gene name           KO     thrshld  score   E-value KO definition
  NP_570602.2         K26168  316.13  176.3   2.9e-56 immunoglobulin superfamily member 1
```

KO numbers are expanded to species KEGG pathway IDs (`hsa04350`) via
`data/ko2pathway/ko2{hsa,mmu}.txt`. A KO mapping to several pathways
contributes all of them.

### InterProScan — GO terms from domains

- Tool and docs: <https://interproscan-docs.readthedocs.io/>
- Download: <https://github.com/ebi-pf-team/interproscan>
- Web server: <https://www.ebi.ac.uk/interpro/search/sequence/>

```bash
interproscan.sh -i protein.fasta -f tsv --goterms -o interproscan_out.tsv
```

`--goterms` is required — without it column 14 is empty and orbit-ocsp extracts
nothing. Output is a 15-column TSV with no header; GO terms come from
**column 14**. Column 15 (MetaCyc / Reactome cross-references) is ignored
because those IDs are outside the GO/KEGG universe used for scoring.

### DeepGOPlus — predicted GO terms

- Tool: <https://github.com/bio-ontology-research-group/deepgoplus>
- Install: `pip install deepgoplus` (model data downloaded separately)
- Web server: <https://deepgo.cbrc.kaust.edu.sa/>

```bash
deepgoplus --data-root <model_dir> --in-file protein.fasta --out-file deepgo_out.tsv
```

orbit-ocsp reads three tab-separated columns: query ID, GO term, score.

```text
NP_570602.2	GO:0001775	0.129
```

The default cutoff is `--deepgo-min-score 0`, i.e. every prediction is kept.
Raise it to drop low-confidence terms. Scores that cannot be parsed are kept
with a `null` score and never threshold-filtered.

---

## Entry B — merge it yourself (recommended)

Build one JSON array, one record per sequence:

```json
[
  {
    "gene_name": "NP_570602.2",
    "similarity_gene_name": "A1BG",
    "ENTREZ_ID": "1",
    "pathway": ["hsa04350", "hsa04514", "GO:0005886", "GO:0005515"]
  }
]
```

| Field | Required | Meaning |
|-------|----------|---------|
| `gene_name` | yes | Your sequence ID. Free-form label. |
| `similarity_gene_name` | one of the two | Gene symbol. **Used as the lookup key.** |
| `ENTREZ_ID` | one of the two | Entrez ID. Also a lookup key. |
| `pathway` | yes | KEGG pathway IDs and/or GO terms, flat array of strings |

Rules that matter:

- `pathway` mixes both namespaces freely: `hsa04350` (KEGG) and `GO:0005886`.
- KEGG IDs must carry the species prefix matching `--species` (`hsa*` / `mmu*`).
  Species-agnostic `map*` IDs cannot be scored.
- Lookup uses `similarity_gene_name` (case-insensitive) or `ENTREZ_ID` — never
  `gene_name`. **If a sequence has no known gene, set `similarity_gene_name` to
  the sequence ID itself** so the record stays scorable.
- Duplicate terms are harmless; they are deduplicated.

```bash
orbit-ocsp --mode sequence \
  --merged-json my_annotations.json \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_sequence
```

Validation before scoring:

| Condition | Result |
|-----------|--------|
| Not valid JSON, or not a top-level array | error, exit 2 |
| Record missing `pathway`, or it is not an array | error, exit 2 |
| `pathway` empty | record skipped, logged as `empty_pathway` |
| Both `similarity_gene_name` and `ENTREZ_ID` missing | skipped, logged as `no_index_key` |
| Every record skipped | error, exit 1 |

A working example ships at
`examples/data/sequence/merged/merged_result_1.json`.

---

## Entry A — let orbit-ocsp merge

```bash
orbit-ocsp --mode sequence \
  --kofam kofam_out.txt \
  --interproscan interproscan_out.tsv \
  --deepgo deepgo_out.tsv \
  --species hsa --condition "Colorectal Cancer" \
  --outdir out_sequence
```

Any subset works; a missing tool simply contributes zero terms. Terms are
concatenated in KOfam → InterProScan → DeepGOPlus order and deduplicated,
keeping first occurrence.

Inspect the merge without scoring:

```bash
orbit-ocsp --mode sequence --kofam kofam_out.txt --merge-only --outdir out_merge
```

That writes `merged_a_terms.json` — the same schema as entry B, so you can use
it as a template for your own merger.

### Batch

```bash
orbit-ocsp --mode sequence --annotation-dir annotations/ \
  --species hsa --condition "Colorectal Cancer" --outdir out_batch
```

```text
annotations/
├── kofam/SAMPLE1.txt          ← sample key "SAMPLE1"
├── interproscan/SAMPLE1.tsv
└── deepgoplus/SAMPLE1.tsv
```

The filename stem is the sample key. Files under `kofam/` named `all_*` or
`ko_result_*` are treated as aggregates and skipped. All samples are scored into
one `biomarker_ranked.json` with a single cross-sample ranking; each record keeps
its `sample_key`. A sample that fails to parse is recorded in the report and
does not abort the run.

---

## Attaching gene identities (`--id-map`)

Novel sequences often have no Entrez ID. If you ran a similarity search
externally, supply the mapping:

```text
query_id	entrez_id	identity	evalue
NP_570602.2	1	99.5	1e-180
```

| Column | Required | Purpose |
|--------|----------|---------|
| `query_id` | yes | Must equal the sequence ID in the annotation files, exactly |
| `entrez_id` | no | Written to `ENTREZ_ID` |
| `gene_symbol` | no | Written to `similarity_gene_name`; otherwise looked up from `entrez_id` |
| `identity`, `evalue` | no | Recorded in `id_evidence` for audit |

Matching is exact string equality — no prefix guessing. Unmapped sequences fall
back to using the query ID as `similarity_gene_name` and are marked
`id_source: fallback_query_id`. They still score.

orbit-ocsp does not run BLAST or any similarity search.

---

## Options

| Option | Default | Purpose |
|--------|---------|---------|
| `--kofam` / `--interproscan` / `--deepgo` | — | Entry A inputs |
| `--annotation-dir` | — | Entry A batch directory |
| `--merged-json` | — | Entry B input |
| `--id-map` | — | query_id → gene identity |
| `--deepgo-min-score` | `0` | DeepGOPlus cutoff; 0 keeps everything |
| `--kofam-min-score` | none | KOfam score cutoff |
| `--ko2pathway` | `data/ko2pathway/ko2<species>.txt` | Override the KO map |
| `--query-id` | — | Keep only one query ID |
| `--merge-only` | off | Write the merged JSON, skip scoring |

---

## Term provenance

The merged JSON records which tool supplied each term, alongside the four
required fields:

```json
{
  "gene_name": "NP_570602.2",
  "similarity_gene_name": "A1BG",
  "ENTREZ_ID": "1",
  "pathway": ["hsa04350", "GO:0005886"],
  "pathway_sources": {
    "hsa04350": ["kofam"],
    "GO:0005886": ["interproscan", "deepgoplus"]
  },
  "term_evidence": { "GO:0005886": { "deepgoplus_score": 0.87 } },
  "id_source": "id_map"
}
```

Terms confirmed by more than one tool are the strongest evidence. These extra
fields are ignored by the scoring engine, so you may include or omit them in
your own merged JSON.

`sequence_merge_report.json` in the output directory records per-file parse
counts, per-query term counts by source, and every excluded record with a reason
code.
