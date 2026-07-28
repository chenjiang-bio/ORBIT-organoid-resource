# Contributing

Thank you for helping improve the ORBIT omics analysis pipeline.

## Scope

Prefer changes to the entry points under `Script/` (`run_*.R`, `run_rna_upstream.sh`, `install_deps.R`, and `Script/lib/`).

## Pull requests

1. Keep comments and user-facing messages in English, written for people running the pipelines.
2. Document new CLI flags in the script header and in `OPERATING_INSTRUCTIONS.md`.
3. Do not commit secrets, API keys, large genomes, HISAT2 indexes, or analysis outputs (see `.gitignore`).
4. When adding examples, include only small prepared inputs (`samples_info.txt`, `comparisons.txt`, count/expression matrices). Do not commit generated analysis results.

## Local checks

```bash
Rscript Script/install_deps.R --type all --check_only TRUE
# Smoke-test with Example/ inputs from OPERATING_INSTRUCTIONS.md
```
