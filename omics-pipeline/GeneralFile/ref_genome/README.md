# Reference genomes

Genome FASTA (`.fa.gz`) and HISAT2 indexes are **not** stored in git. Download the FASTA files into this directory before building indexes.

## Download genome FASTA

| Species | File | Download |
|---------|------|----------|
| Human (`hsa`) | `GRCh38.p14.genome.fa.gz` | https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_50/GRCh38.p14.genome.fa.gz |
| Mouse (`mmu`) | `GRCm39.genome.fa.gz` | https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M39/GRCm39.genome.fa.gz |

Example:

```bash
cd GeneralFile/ref_genome
curl -L -O https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_50/GRCh38.p14.genome.fa.gz
curl -L -O https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M39/GRCm39.genome.fa.gz
```

## Expected files

| Species | FASTA | GTF (annotation) | HISAT2 index prefix |
|---------|-------|------------------|---------------------|
| Human | `GRCh38.p14.genome.fa.gz` | `gencode.v46.annotation.gtf.gz` | `GRCh38.p14` |
| Mouse | `GRCm39.genome.fa.gz` | `gencode.vM35.annotation.gtf.gz` | `GRCm39` |

## Build HISAT2 indexes

From the `omics-pipeline/` root:

```bash
bash Script/run_rna_upstream.sh --species hsa --stage build-index
bash Script/run_rna_upstream.sh --species mmu --stage build-index
```

See [OPERATING_INSTRUCTIONS.md](../../OPERATING_INSTRUCTIONS.md) for upstream RNA-seq usage.
