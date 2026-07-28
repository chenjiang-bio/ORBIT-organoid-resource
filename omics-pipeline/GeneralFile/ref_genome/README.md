# Reference genomes

Genome FASTA (`.fa` / `.fa.gz`) and HISAT2 indexes are not stored in git.
Place human / mouse FASTA here and build indexes with:

```bash
bash Script/run_rna_upstream.sh --species hsa --stage build-index
bash Script/run_rna_upstream.sh --species mmu --stage build-index
```
