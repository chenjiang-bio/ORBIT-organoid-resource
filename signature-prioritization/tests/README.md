# Tests

```bash
pytest tests/unit -q          # fast, no scoring data needed
pytest tests/integration -q   # exercises examples/data/ through the CLI
pytest tests -q               # everything
```

R is never required — expression tests use `--de-backend mock`.

## Layout

```text
tests/
├── unit/          Module-level, self-contained (data built in tmp_path)
├── integration/   CLI-level, driven by examples/data/
└── README.md
```

## Unit tests

Each file targets one module and fabricates its own fixtures, so no unit test
depends on the shipped sample files or on the downloaded scoring data.

| File | Covers |
|------|--------|
| `test_sequence_annotation.py` | KOfam / InterProScan / DeepGOPlus parsing, merging, JSON round-trip, ID resolution |
| `test_expression_pipeline.py` | DE → lookup → scoring plumbing |
| `test_expression_de.py`, `test_expression_concordance.py` | DE backends and concordance |
| `test_data_manager.py` | Data path resolution, `required_paths`, bundle packing |
| `test_protein_lookup.py` | Gene ID normalization |
| `test_b_terms_schema.py`, `test_b_terms_listing.py` | Background library schema and filters |
| `test_semantic_resources.py`, `test_semantic_two_stage.py` | GO semantics, 50→999 staging |
| `test_statistics.py`, `test_statistical_rigor.py` | Statistical methods |
| `test_caching.py`, `test_memory_optimizer.py`, `test_parallel_processing.py` | Infrastructure |

## Integration tests

`test_example_data.py` runs the real CLI against `examples/data/`, organized by
input mode so each group mirrors one documented command:

| Test class | Mode | Sample data |
|------------|------|-------------|
| `TestSampleDataLayout` | — | asserts every file the docs reference exists and parses |
| `TestExpressionMode` | expression | `examples/data/expression/` |
| `TestGenesMode` | genes | `examples/data/genes/` |
| `TestSequenceModeNative` | sequence, entry A | `examples/data/sequence/native/` |
| `TestSequenceModeMerged` | sequence, entry B | `examples/data/sequence/merged/` |
| `TestSequenceEntriesAgreeOnGO` | sequence, both | pins the known KEGG gap between the two samples |

Sequence mode has **two** entry points, tested separately because the inputs
differ: entry A takes raw tool output and merges it; entry B takes an
already-merged A_terms JSON and only validates it.

### Skipping behavior

Tests needing the large scoring data carry `@needs_scoring_data` and skip
automatically when it is absent:

```bash
orbit-ocsp-download-data --species hsa
# or
export ORBIT_OCSP_DATA=/path/to/data
```

Parsing, merging and argument validation never need it, so those run everywhere
— including CI without the data bundle.

## Not shipped in the release tree

| Test | Requires |
|------|----------|
| `test_expression_cases.py` | `tests/Ana_Meta_example/` (387 MB GEO corpus) |
| `test_batch_training_controls.py` | internal training scripts |

Regenerate the corpus locally with
`python scripts/convert_ana_meta_example.py` if you need the first one.
