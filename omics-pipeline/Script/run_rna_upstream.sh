#!/usr/bin/env bash
# =============================================================================
# run_rna_upstream.sh
# Bulk RNA-seq upstream pipeline: download, QC, align, and quantify.
#
# Stages (--stage): download | meta | analyze | build-index | all
# Modes  (--mode):  srr (one GSM ↔ one SRR) | srx (one GSM ↔ many SRR)
#
# Default references: ../GeneralFile/ref_genome/ (FASTA, GTF, HISAT2 index)
# Override with --fasta / --gtf / --hisat-index as needed.
#
# Usage:
#   bash Script/run_rna_upstream.sh \
#       --gse-list FILE --species hsa|mmu --mode srr|srx \
#       --outdir DIR [--stage all] [options]
#
# Examples:
#   # Full pipeline
#   bash Script/run_rna_upstream.sh \
#       --gse-list list.txt --species hsa --mode srr \
#       --outdir ./rna_out --logfile ./rna_out.log
#
#   # Download only
#   bash Script/run_rna_upstream.sh --gse-list list.txt --species hsa \
#       --mode srx --stage download
#
#   # Build HISAT2 index once (requires FASTA under GeneralFile/ref_genome)
#   bash Script/run_rna_upstream.sh --species hsa --stage build-index
#
#   # Align + quantify when FASTQ and ID maps are already present
#   bash Script/run_rna_upstream.sh --gse-list list.txt --species mmu \
#       --mode srr --outdir ./mmu_out --stage analyze
#
# Required tools: iseq, fastp, hisat2, samtools, featureCounts
# See: bash Script/run_rna_upstream.sh --help
# =============================================================================

set -euo pipefail

# -------------------- Paths --------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GENERAL_FILE="$(cd "${SCRIPT_DIR}/../GeneralFile" && pwd)"
REF_DIR="${GENERAL_FILE}/ref_genome"
WORKDIR="$(pwd)"

# -------------------- Defaults --------------------
GSE_LIST=""
SPECIES=""
MODE="srr"              # srr: one GSM <-> one SRR; srx: one GSM <-> many SRR (iseq -e ex)
OUTDIR="./rna_upstream_out"
LOGFILE=""
STAGE="all"             # download | meta | analyze | build-index | all
THREADS_FASTP=16
THREADS_ALIGN=32
THREADS_SORT=32
THREADS_FC=32
THREADS_INDEX=16
JOBS=1                 # parallel samples within a GSE (QC+align)
DOWNLOAD_JOBS=1        # parallel GSE downloads
KEEP_CLEAN_FQ=0        # 1 = keep *.clean.fq.gz after alignment
REMOVE_BAM=0           # 1 = delete BAM after successful count merge

# Default references under GeneralFile/ref_genome
REF_HSA_FA="${REF_DIR}/GRCh38.p14.genome.fa.gz"
REF_HSA_INDEX="${REF_DIR}/GRCh38.p14"
REF_HSA_GTF="${REF_DIR}/gencode.v46.annotation.gtf.gz"
REF_MMU_FA="${REF_DIR}/GRCm39.genome.fa.gz"
REF_MMU_INDEX="${REF_DIR}/GRCm39"
REF_MMU_GTF="${REF_DIR}/gencode.vM35.annotation.gtf.gz"

# -------------------- Helpers --------------------
usage() {
    cat <<EOF
Usage:
  bash run_rna_upstream.sh --gse-list FILE --species hsa|mmu [options]

Required (except --stage build-index):
  --gse-list FILE       GSE ID list, one ID per line
  --species hsa|mmu     Species

Options:
  --mode srr|srx        Sample mode (default: srr)
                          srr: one GSM per SRR (prefixes SRR*/ERR*)
                          srx: multi-SRR per GSM; iseq uses -e ex (prefix SRX*)
  --outdir DIR          Output directory for final counts (default: ./rna_upstream_out)
  --logfile FILE        Log file (default: <outdir>/run_rna_upstream.log)
  --stage STAGE         Pipeline stage (default: all)
                          download | meta | analyze | build-index | all
  --threads-fastp N     fastp threads (default: 16; auto-divided by --jobs)
  --threads-align N     hisat2 threads (default: 32; auto-divided by --jobs)
  --threads-sort N      samtools sort threads (default: 32; auto-divided by --jobs)
  --threads-fc N        featureCounts threads (default: 32)
  --threads-index N     hisat2-build threads (default: 16)
  --jobs N              Parallel samples per GSE for QC+align (default: 1)
  --download-jobs N     Parallel GSE downloads (default: 1)
  --keep-clean-fq       Keep *.clean.fq.gz after alignment (default: delete)
  --remove-bam          Delete BAM after successful count matrix (default: keep)
  --ref-hsa-index PATH  Human HISAT2 index prefix
  --ref-hsa-gtf PATH    Human GTF
  --ref-hsa-fa PATH     Human genome FASTA (for build-index)
  --ref-mmu-index PATH  Mouse HISAT2 index prefix
  --ref-mmu-gtf PATH    Mouse GTF
  --ref-mmu-fa PATH     Mouse genome FASTA (for build-index)
  -h, --help            Show this help

Stages:
  download     Download raw data with iseq
  meta         Build srr2GSM/srx2GSM + samples_info; check fastq completeness
  analyze      fastp -> hisat2|samtools -> batch featureCounts -> merge counts
  build-index  Build HISAT2 index from bundled FASTA under GeneralFile/ref_genome
  all          Run download, meta, then analyze

Speed tips:
  Prefer --jobs 2-4 with lower per-tool threads (auto-scaled), e.g.
    --jobs 4 --threads-align 32   # ~8 threads per sample
  Use --download-jobs 2-4 for multi-GSE download (respect NCBI/ENA limits).

Default reference directory:
  ${REF_DIR}
EOF
}

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    if [[ -n "${LOGFILE:-}" ]]; then
        echo "$msg" | tee -a "$LOGFILE"
    else
        echo "$msg"
    fi
}

die() {
    log "ERROR: $*"
    exit 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Command not found: $1"
}

clean_gse_id() {
    tr -d '\t\r\n ' <<<"$1"
}

read_gse_list() {
    local file="$1"
    local tmp
    tmp="$(mktemp)"
    sed 's/\r//g' "$file" > "$tmp"
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="$(clean_gse_id "$line")"
        [[ -z "$line" || "$line" == \#* ]] && continue
        echo "$line"
    done < "$tmp"
    rm -f "$tmp"
}

index_exists() {
    local prefix="$1"
    [[ -e "${prefix}.1.ht2" || -e "${prefix}.1.ht2l" ]]
}

# -------------------- Argument parsing --------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --gse-list) GSE_LIST="$2"; shift 2 ;;
        --species) SPECIES="$2"; shift 2 ;;
        --mode) MODE="$2"; shift 2 ;;
        --outdir) OUTDIR="$2"; shift 2 ;;
        --logfile) LOGFILE="$2"; shift 2 ;;
        --stage) STAGE="$2"; shift 2 ;;
        --threads-fastp) THREADS_FASTP="$2"; shift 2 ;;
        --threads-align) THREADS_ALIGN="$2"; shift 2 ;;
        --threads-sort) THREADS_SORT="$2"; shift 2 ;;
        --threads-fc) THREADS_FC="$2"; shift 2 ;;
        --threads-index) THREADS_INDEX="$2"; shift 2 ;;
        --jobs) JOBS="$2"; shift 2 ;;
        --download-jobs) DOWNLOAD_JOBS="$2"; shift 2 ;;
        --keep-clean-fq) KEEP_CLEAN_FQ=1; shift ;;
        --remove-bam) REMOVE_BAM=1; shift ;;
        --ref-hsa-index) REF_HSA_INDEX="$2"; shift 2 ;;
        --ref-hsa-gtf) REF_HSA_GTF="$2"; shift 2 ;;
        --ref-hsa-fa) REF_HSA_FA="$2"; shift 2 ;;
        --ref-mmu-index) REF_MMU_INDEX="$2"; shift 2 ;;
        --ref-mmu-gtf) REF_MMU_GTF="$2"; shift 2 ;;
        --ref-mmu-fa) REF_MMU_FA="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown argument: $1 (use --help)" ;;
    esac
done

[[ -n "$SPECIES" ]] || { usage; die "--species is required"; }
[[ "$SPECIES" == "hsa" || "$SPECIES" == "mmu" ]] || die "species must be hsa or mmu"
[[ "$MODE" == "srr" || "$MODE" == "srx" ]] || die "mode must be srr or srx"
case "$STAGE" in
    download|meta|analyze|build-index|all) ;;
    *) die "stage must be download|meta|analyze|build-index|all" ;;
esac

re_pos_int='^[1-9][0-9]*$'
[[ "$JOBS" =~ $re_pos_int ]] || die "--jobs must be a positive integer"
[[ "$DOWNLOAD_JOBS" =~ $re_pos_int ]] || die "--download-jobs must be a positive integer"

if [[ "$STAGE" != "build-index" ]]; then
    [[ -n "$GSE_LIST" ]] || { usage; die "--gse-list is required"; }
    [[ -f "$GSE_LIST" ]] || die "GSE list not found: $GSE_LIST"
fi

mkdir -p "$OUTDIR"
OUTDIR="$(cd "$OUTDIR" && pwd)"
[[ -z "$LOGFILE" ]] && LOGFILE="${OUTDIR}/run_rna_upstream.log"
mkdir -p "$(dirname "$LOGFILE")"
: > "$LOGFILE"

# Effective per-sample threads when --jobs > 1 (avoid oversubscription)
per_job_threads() {
    local total="$1"
    local jobs="$JOBS"
    local t=$(( total / jobs ))
    (( t < 1 )) && t=1
    echo "$t"
}
EFF_THREADS_FASTP="$(per_job_threads "$THREADS_FASTP")"
EFF_THREADS_ALIGN="$(per_job_threads "$THREADS_ALIGN")"
EFF_THREADS_SORT="$(per_job_threads "$THREADS_SORT")"

# Species-specific reference selection
if [[ "$SPECIES" == "hsa" ]]; then
    HISAT2_INDEX="$REF_HSA_INDEX"
    GTF_FILE="$REF_HSA_GTF"
    GENOME_FA="$REF_HSA_FA"
else
    HISAT2_INDEX="$REF_MMU_INDEX"
    GTF_FILE="$REF_MMU_GTF"
    GENOME_FA="$REF_MMU_FA"
fi

# Mode-specific ID prefix, map file, and iseq flags
if [[ "$MODE" == "srr" ]]; then
    ID_PREFIX_RE='(SRR|ERR)'
    MAP_SUFFIX="srr2GSM"
    MAP_COL_NAME="run_accession"
    ISEQ_EXTRA=()
else
    ID_PREFIX_RE='SRX'
    MAP_SUFFIX="srx2GSM"
    MAP_COL_NAME="experiment_accession"
    ISEQ_EXTRA=(-e ex)
fi

map_file_for() {
    local gse="$1"
    echo "${gse}.${MAP_SUFFIX}.txt"
}

log "========== RNA-seq Upstream Pipeline =========="
log "Script   : $SCRIPT_DIR"
log "Ref dir  : $REF_DIR"
log "GSE list : ${GSE_LIST:-N/A}"
log "Species  : $SPECIES"
log "Mode     : $MODE"
log "Stage    : $STAGE"
log "Outdir   : $OUTDIR"
log "Logfile  : $LOGFILE"
log "HISAT2   : $HISAT2_INDEX"
log "GTF      : $GTF_FILE"
log "FASTA    : $GENOME_FA"
log "Jobs     : samples=$JOBS download=$DOWNLOAD_JOBS"
log "Threads  : fastp=$THREADS_FASTP(eff=$EFF_THREADS_FASTP) align=$THREADS_ALIGN(eff=$EFF_THREADS_ALIGN) sort=$THREADS_SORT(eff=$EFF_THREADS_SORT) fc=$THREADS_FC"
log "Cleanup  : keep_clean_fq=$KEEP_CLEAN_FQ remove_bam=$REMOVE_BAM"
log "Workdir  : $WORKDIR"
log "==============================================="

# -------------------- Stage: build-index --------------------
stage_build_index() {
    need_cmd hisat2-build
    [[ -f "$GENOME_FA" ]] || die "Genome FASTA not found: $GENOME_FA"

    if index_exists "$HISAT2_INDEX"; then
        log "[build-index] Index already exists: $HISAT2_INDEX"
        return 0
    fi

    log "[build-index] Building HISAT2 index from $GENOME_FA"
    log "[build-index] Output prefix: $HISAT2_INDEX"
    mkdir -p "$(dirname "$HISAT2_INDEX")"

    # hisat2-build accepts gzipped FASTA
    hisat2-build -p "$THREADS_INDEX" "$GENOME_FA" "$HISAT2_INDEX"
    index_exists "$HISAT2_INDEX" || die "HISAT2 index build failed: $HISAT2_INDEX"
    log "[build-index] Done: $HISAT2_INDEX"
}

# -------------------- Stage: download --------------------
download_one_gse() {
    local gse="$1"
    log "[download] Processing $gse"
    mkdir -p "${WORKDIR}/${gse}"
    (
        cd "${WORKDIR}/${gse}"
        rm -f success.log fail.log
        if iseq -i "$gse" -a -g "${ISEQ_EXTRA[@]}" > "${gse}_download.log" 2>&1; then
            log "[download] $gse succeeded"
        else
            log "[download] WARNING: $gse failed; see ${gse}_download.log"
        fi
    )
}

stage_download() {
    need_cmd iseq
    local -a gse_ids=()
    local gse
    while IFS= read -r gse; do
        gse_ids+=("$gse")
    done < <(read_gse_list "$GSE_LIST")

    if (( DOWNLOAD_JOBS <= 1 || ${#gse_ids[@]} <= 1 )); then
        for gse in "${gse_ids[@]}"; do
            download_one_gse "$gse"
        done
        return 0
    fi

    log "[download] Parallel downloads: jobs=$DOWNLOAD_JOBS nGSE=${#gse_ids[@]}"
    local -a pids=()
    local pid i
    for gse in "${gse_ids[@]}"; do
        while (( ${#pids[@]} >= DOWNLOAD_JOBS )); do
            for i in "${!pids[@]}"; do
                if ! kill -0 "${pids[$i]}" 2>/dev/null; then
                    wait "${pids[$i]}" || true
                    unset "pids[$i]"
                fi
            done
            pids=("${pids[@]}")
            if (( ${#pids[@]} >= DOWNLOAD_JOBS )); then
                sleep 0.5
            fi
        done
        download_one_gse "$gse" &
        pids+=("$!")
    done
    for pid in "${pids[@]}"; do
        wait "$pid" || true
    done
}

# -------------------- Stage: meta --------------------
# Count logical samples: SE files + PE pairs (require pe1 == pe2)
count_fastq_samples() {
    local pe1 pe2 all se_count sample_count
    pe1=$(find . -maxdepth 1 -type f -regextype posix-extended \
        -regex "./(${ID_PREFIX_RE})[0-9]+_1\\.fastq\\.gz" | wc -l)
    pe2=$(find . -maxdepth 1 -type f -regextype posix-extended \
        -regex "./(${ID_PREFIX_RE})[0-9]+_2\\.fastq\\.gz" | wc -l)
    all=$(find . -maxdepth 1 -type f -regextype posix-extended \
        -regex "./(${ID_PREFIX_RE})[0-9]+(_[12])?\\.fastq\\.gz" | wc -l)
    se_count=$((all - pe1 - pe2))
    sample_count=$((se_count + pe1))
    echo "$sample_count $pe1 $pe2 $all"
}

build_id_map_and_samples_info() {
    local gse="$1"
    local metadata="${gse}.metadata.tsv"
    local map_file
    map_file="$(map_file_for "$gse")"

    [[ -f "$metadata" ]] || { log "[meta] Missing $metadata"; return 1; }

    local header_line
    header_line=$(head -n 1 "$metadata")
    local id_col alias_col title_col lib_col
    id_col=$(echo "$header_line" | tr '\t' '\n' | grep -n "^${MAP_COL_NAME}$" | cut -d: -f1 || true)
    alias_col=$(echo "$header_line" | tr '\t' '\n' | grep -n "^sample_alias$" | cut -d: -f1 || true)
    title_col=$(echo "$header_line" | tr '\t' '\n' | grep -n "^experiment_title$" | cut -d: -f1 || true)
    lib_col=$(echo "$header_line" | tr '\t' '\n' | grep -n "^library_name$" | cut -d: -f1 || true)

    [[ -n "$id_col" ]] || { log "[meta] Column ${MAP_COL_NAME} not found in metadata"; return 1; }
    [[ -n "$alias_col" ]] || { log "[meta] Column sample_alias not found in metadata"; return 1; }

    # samples_info.txt
    if [[ -n "$title_col" ]]; then
        echo -e "counts\tsample" > samples_info.txt
        if [[ "$MODE" == "srr" ]]; then
            tail -n +2 "$metadata" \
            | awk -v a="$alias_col" -v b="$title_col" -v l="${lib_col:-0}" -F'\t' '{
                alias = $a
                if (alias ~ /^[[:space:]]*$/) alias = (l ? $l : "")
                print alias "\t" $b
            }' | sort -k1,1 >> samples_info.txt
        else
            tail -n +2 "$metadata" \
            | awk -v a="$alias_col" -v b="$title_col" -F'\t' '{print $a "\t" $b}' \
            | sort -k1,1 | awk '!seen[$1]++' >> samples_info.txt
        fi
        log "[meta] Wrote samples_info.txt"
    else
        log "[meta] WARNING: no experiment_title column; skip samples_info.txt"
    fi

    # ID -> GSM map
    declare -A sample_map=()
    local line id_val alias_val
    while IFS= read -r line; do
        id_val=$(echo "$line" | cut -f"$id_col")
        alias_val=$(echo "$line" | cut -f"$alias_col")
        if [[ -z "$(echo "$alias_val" | tr -d '[:space:]')" && -n "${lib_col:-}" ]]; then
            alias_val=$(echo "$line" | cut -f"$lib_col")
        fi
        [[ -n "$id_val" ]] || continue
        sample_map["$id_val"]="$alias_val"
    done < <(tail -n +2 "$metadata")

    echo -e "${MAP_COL_NAME}\tsample_alias" > "$map_file"
    local k
    for k in "${!sample_map[@]}"; do
        echo -e "${k}\t${sample_map[$k]}"
    done | sort -k1,1 >> "$map_file"
    log "[meta] Wrote $map_file"
    return 0
}

check_fastq_completeness() {
    local gse="$1"
    local map_file
    map_file="$(map_file_for "$gse")"
    [[ -f "$map_file" ]] || return 1

    local metadata_count sample_count pe1 pe2 all
    metadata_count=$(($(wc -l < "$map_file") - 1))
    read -r sample_count pe1 pe2 all <<<"$(count_fastq_samples)"

    log "[meta] $gse: metadata=$metadata_count samples, fastq_samples=$sample_count (pe1=$pe1 pe2=$pe2 all=$all)"

    if [[ "$sample_count" -eq "$metadata_count" && "$pe1" -eq "$pe2" && "$sample_count" -gt 0 ]]; then
        log "[meta] $gse fastq is complete"
        return 0
    fi

    log "[meta] $gse fastq incomplete; attempting re-download"
    rm -f success.log fail.log
    iseq -i "$gse" -a -g "${ISEQ_EXTRA[@]}" > "${gse}_download.log" 2>&1 || true
    return 1
}

stage_meta() {
    need_cmd iseq
    local gse
    while IFS= read -r gse; do
        if [[ ! -d "${WORKDIR}/${gse}" ]]; then
            log "[meta] Directory not found: $gse; skip"
            continue
        fi
        log "[meta] Processing $gse"
        (
            cd "${WORKDIR}/${gse}"
            build_id_map_and_samples_info "$gse" || true
            check_fastq_completeness "$gse" || true
        )
    done < <(read_gse_list "$GSE_LIST")
}

# -------------------- Stage: analyze --------------------
# QC + align only (quantification is batched later).
align_one_sample_pe() {
    local sample="$1"
    if [[ -s "${sample}.count" || -f "${sample}.bam" ]]; then
        [[ -f "${sample}.bam" ]] && log "[analyze] Skip existing bam: $sample"
        [[ -s "${sample}.count" ]] && log "[analyze] Skip existing count: $sample"
        return 0
    fi
    if [[ ! -f "${sample}_1.clean.fq.gz" || ! -f "${sample}_2.clean.fq.gz" ]]; then
        fastp -i "${sample}_1.fastq.gz" -o "${sample}_1.clean.fq.gz" \
              -I "${sample}_2.fastq.gz" -O "${sample}_2.clean.fq.gz" \
              -h "${sample}.html" -j "${sample}.json" -w "$EFF_THREADS_FASTP"
        if [[ ! -f "${sample}.html" ]]; then
            log "[analyze] WARNING: QC failed for $sample; removing fastq"
            rm -f "${sample}_1.fastq.gz" "${sample}_1.clean.fq.gz" \
                  "${sample}_2.fastq.gz" "${sample}_2.clean.fq.gz"
            return 1
        fi
    fi
    # hisat2 SAM stdout -> samtools sort (no intermediate .sam)
    if ! hisat2 -p "$EFF_THREADS_ALIGN" -x "$HISAT2_INDEX" \
            -1 "${sample}_1.clean.fq.gz" -2 "${sample}_2.clean.fq.gz" \
            --summary-file "${sample}.hisat2.summary" \
        | samtools sort -@ "$EFF_THREADS_SORT" -o "${sample}.bam" -; then
        log "[analyze] WARNING: PE alignment failed: $sample"
        rm -f "${sample}.bam"
        return 1
    fi
    samtools index "${sample}.bam"
    if (( KEEP_CLEAN_FQ == 0 )); then
        rm -f "${sample}_1.clean.fq.gz" "${sample}_2.clean.fq.gz"
    fi
    log "[analyze] PE alignment done: $sample"
    return 0
}

align_one_sample_se() {
    local sample="$1"
    if [[ -s "${sample}.count" || -f "${sample}.bam" ]]; then
        [[ -f "${sample}.bam" ]] && log "[analyze] Skip existing bam: $sample"
        [[ -s "${sample}.count" ]] && log "[analyze] Skip existing count: $sample"
        return 0
    fi
    if [[ ! -f "${sample}.clean.fq.gz" ]]; then
        fastp -i "${sample}.fastq.gz" -o "${sample}.clean.fq.gz" \
              -h "${sample}.html" -j "${sample}.json" -w "$EFF_THREADS_FASTP"
        if [[ ! -f "${sample}.html" ]]; then
            log "[analyze] WARNING: QC failed for $sample; removing fastq"
            rm -f "${sample}.fastq.gz" "${sample}.clean.fq.gz"
            return 1
        fi
    fi
    if ! hisat2 -p "$EFF_THREADS_ALIGN" -x "$HISAT2_INDEX" \
            -U "${sample}.clean.fq.gz" \
            --summary-file "${sample}.hisat2.summary" \
        | samtools sort -@ "$EFF_THREADS_SORT" -o "${sample}.bam" -; then
        log "[analyze] WARNING: SE alignment failed: $sample"
        rm -f "${sample}.bam"
        return 1
    fi
    samtools index "${sample}.bam"
    if (( KEEP_CLEAN_FQ == 0 )); then
        rm -f "${sample}.clean.fq.gz"
    fi
    log "[analyze] SE alignment done: $sample"
    return 0
}

# Run align jobs with a concurrency limit (shell functions OK in subshells via export -f).
run_align_pool() {
    local max_jobs="$1"
    shift
    local -a samples=("$@")
    local -a pids=()
    local sample pid i kind
    # samples entries are "pe:SAMPLE" or "se:SAMPLE"
    for sample in "${samples[@]}"; do
        kind="${sample%%:*}"
        sample="${sample#*:}"
        while (( ${#pids[@]} >= max_jobs )); do
            for i in "${!pids[@]}"; do
                if ! kill -0 "${pids[$i]}" 2>/dev/null; then
                    wait "${pids[$i]}" || true
                    unset "pids[$i]"
                fi
            done
            pids=("${pids[@]}")
            if (( ${#pids[@]} >= max_jobs )); then
                sleep 0.5
            fi
        done
        if [[ "$kind" == "pe" ]]; then
            align_one_sample_pe "$sample" &
        else
            align_one_sample_se "$sample" &
        fi
        pids+=("$!")
    done
    for pid in "${pids[@]}"; do
        wait "$pid" || true
    done
}

# Batch featureCounts on all BAMs; split into per-sample .count files.
# Args: mode(pe|se) out_prefix bam1 bam2 ...
batch_featurecounts() {
    local mode="$1"
    local out_prefix="$2"
    shift 2
    local -a bams=("$@")
    local -a need_bams=()
    local -a need_samples=()
    local bam sample
    for bam in "${bams[@]}"; do
        sample="$(basename "$bam" .bam)"
        if [[ -s "${sample}.count" ]]; then
            continue
        fi
        [[ -f "$bam" ]] || { log "[analyze] WARNING: missing BAM $bam"; continue; }
        need_bams+=("$bam")
        need_samples+=("$sample")
    done
    (( ${#need_bams[@]} == 0 )) && return 0

    local raw="${out_prefix}.batch.rawcount"
    local fc_args=(-T "$THREADS_FC" -a "$GTF_FILE" -g gene_id -o "$raw")
    if [[ "$mode" == "pe" ]]; then
        fc_args=(-p "${fc_args[@]}")
    fi
    log "[analyze] Batch featureCounts ($mode): ${#need_bams[@]} BAMs -> $raw"
    featureCounts "${fc_args[@]}" "${need_bams[@]}"

    # featureCounts: '# ...' comments, then header, then gene rows.
    # Columns: 1=Geneid, 2-6=anno, 7..=counts for each BAM in order.
    local i col
    for i in "${!need_samples[@]}"; do
        sample="${need_samples[$i]}"
        col=$((7 + i))
        awk -v c="$col" -v s="$sample" 'BEGIN {OFS="\t"}
             /^#/ {next}
             !hdr { print "Geneid", s; hdr=1; next }
             { print $1, $c }' "$raw" > "${sample}.count"
        [[ -s "${sample}.count" ]] || die "[analyze] Failed to write ${sample}.count from batch"
    done
    log "[analyze] Batch quantification done ($mode): ${#need_samples[@]} samples"
}

merge_counts_and_rename() {
    local gse="$1"
    local map_file
    map_file="$(map_file_for "$gse")"
    shift
    local sample_files=("$@")
    local metadata_count
    metadata_count=$(($(wc -l < "$map_file") - 1))

    local count_files=()
    local s
    for s in "${sample_files[@]}"; do
        [[ -s "${s}.count" ]] || die "[analyze] Missing ${s}.count"
        count_files+=("${s}.count")
    done

    [[ ${#count_files[@]} -eq "$metadata_count" ]] \
        || die "[analyze] count files (${#count_files[@]}) != metadata ($metadata_count)"

    paste "${count_files[@]}" > "${gse}.all.txt"
    local expected_lines actual_lines
    expected_lines=$(wc -l < "${count_files[0]}")
    actual_lines=$(wc -l < "${gse}.all.txt")
    [[ "$actual_lines" -eq "$expected_lines" ]] \
        || die "[analyze] Merged line count mismatch: $actual_lines vs $expected_lines"

    local columns="1" i
    for ((i = 1; i <= ${#count_files[@]}; i++)); do
        columns+=",$((i * 2))"
    done
    cut -f "$columns" "${gse}.all.txt" > "${gse}.counts.txt"

    awk 'BEGIN{FS=OFS="\t"} NR==1 {print; next} {sub(/\..*/, "", $1); print}' \
        "${gse}.counts.txt" > "${gse}.${SPECIES}.counts.id.txt"

    declare -A id_map=()
    local id_val alias_val
    while IFS=$'\t' read -r id_val alias_val; do
        [[ "$id_val" == "$MAP_COL_NAME" ]] && continue
        id_map["$id_val"]="$alias_val"
    done < "$map_file"

    local header k
    header=$(head -n1 "${gse}.${SPECIES}.counts.id.txt")
    for k in "${!id_map[@]}"; do
        header="${header//$k/${id_map[$k]}}"
    done

    local out_expr="${gse}.${SPECIES}.ExprMatrix.txt"
    echo "$header" > "$out_expr"
    tail -n +2 "${gse}.${SPECIES}.counts.id.txt" >> "$out_expr"

    local final_n
    final_n=$(head -1 "$out_expr" | tr '\t' '\n' | wc -l)
    final_n=$((final_n - 1))
    [[ "$final_n" -eq "$metadata_count" ]] \
        || die "[analyze] Final sample count ($final_n) != metadata ($metadata_count)"

    mkdir -p "${OUTDIR}/${gse}"
    cp "$out_expr" "${OUTDIR}/${gse}/"
    [[ -f samples_info.txt ]] && cp samples_info.txt "${OUTDIR}/${gse}/"
    log "[analyze] Success: ${OUTDIR}/${gse}/${out_expr}"

    if (( REMOVE_BAM == 1 )); then
        for s in "${sample_files[@]}"; do
            rm -f "${s}.bam" "${s}.bam.bai" "${s}.bai"
        done
        log "[analyze] Removed BAMs for $gse (--remove-bam)"
    fi
}

analyze_one_gse() {
    local gse="$1"
    local out_expr="${OUTDIR}/${gse}/${gse}.${SPECIES}.ExprMatrix.txt"
    local out_expr_legacy="${OUTDIR}/${gse}/${gse}.${SPECIES}.expr.txt"
    local out_counts_legacy="${OUTDIR}/${gse}/${gse}.${SPECIES}.counts.txt"
    if [[ -f "$out_expr" || -f "$out_expr_legacy" || -f "$out_counts_legacy" ]]; then
        log "[analyze] Skip completed: $gse"
        return 0
    fi

    local map_file
    map_file="$(map_file_for "$gse")"
    [[ -f "$map_file" ]] || { log "[analyze] Missing $map_file; skip $gse"; return 1; }

    # Completeness check; re-download if incomplete
    local sample_count pe1 pe2 all metadata_count
    read -r sample_count pe1 pe2 all <<<"$(count_fastq_samples)"
    metadata_count=$(($(wc -l < "$map_file") - 1))
    if [[ "$sample_count" -ne "$metadata_count" || "$pe1" -ne "$pe2" ]]; then
        log "[analyze] $gse incomplete; attempting re-download"
        iseq -i "$gse" -a -g "${ISEQ_EXTRA[@]}" > "${gse}_download.log" 2>&1 || true
        return 1
    fi

    local -a pe_samples=()
    local -a se_samples=()
    local -a sample_files=()
    local -a align_jobs=()
    local f sample

    # Paired-end
    while IFS= read -r f; do
        sample=$(basename "$f" _1.fastq.gz)
        pe_samples+=("$sample")
        sample_files+=("$sample")
        align_jobs+=("pe:$sample")
    done < <(find . -maxdepth 1 -type f -regextype posix-extended \
        -regex "./(${ID_PREFIX_RE})[0-9]+_1\\.fastq\\.gz" | sort)

    # Single-end
    while IFS= read -r f; do
        sample=$(basename "$f" .fastq.gz)
        se_samples+=("$sample")
        sample_files+=("$sample")
        align_jobs+=("se:$sample")
    done < <(find . -maxdepth 1 -type f -regextype posix-extended \
        -regex "./(${ID_PREFIX_RE})[0-9]+\\.fastq\\.gz" | sort)

    [[ ${#sample_files[@]} -gt 0 ]] || { log "[analyze] No sample files for $gse"; return 1; }
    [[ ${#sample_files[@]} -eq "$metadata_count" ]] \
        || die "[analyze] Sample count (${#sample_files[@]}) != metadata ($metadata_count)"

    log "[analyze] $gse: QC+align jobs=${JOBS} samples=${#align_jobs[@]}"
    run_align_pool "$JOBS" "${align_jobs[@]}"

    # Batch quantify PE / SE separately
    if (( ${#pe_samples[@]} > 0 )); then
        local -a pe_bams=()
        for sample in "${pe_samples[@]}"; do
            pe_bams+=("${sample}.bam")
        done
        batch_featurecounts pe "${gse}.pe" "${pe_bams[@]}"
    fi
    if (( ${#se_samples[@]} > 0 )); then
        local -a se_bams=()
        for sample in "${se_samples[@]}"; do
            se_bams+=("${sample}.bam")
        done
        batch_featurecounts se "${gse}.se" "${se_bams[@]}"
    fi

    merge_counts_and_rename "$gse" "${sample_files[@]}"
}

stage_analyze() {
    need_cmd fastp
    need_cmd hisat2
    need_cmd samtools
    need_cmd featureCounts
    need_cmd iseq

    if ! index_exists "$HISAT2_INDEX"; then
        log "[analyze] HISAT2 index not found: $HISAT2_INDEX"
        log "[analyze] Building index automatically..."
        stage_build_index
    fi
    [[ -f "$GTF_FILE" ]] || die "GTF not found: $GTF_FILE"

    local gse
    while IFS= read -r gse; do
        if [[ ! -d "${WORKDIR}/${gse}" ]]; then
            log "[analyze] Directory not found: $gse"
            continue
        fi
        log "[analyze] Entering $gse"
        (
            cd "${WORKDIR}/${gse}"
            analyze_one_gse "$gse"
        ) || log "[analyze] WARNING: $gse not completed"
    done < <(read_gse_list "$GSE_LIST")
}

# -------------------- Main --------------------
case "$STAGE" in
    build-index) stage_build_index ;;
    download)    stage_download ;;
    meta)        stage_meta ;;
    analyze)     stage_analyze ;;
    all)
        stage_download
        stage_meta
        stage_analyze
        ;;
esac

log "========== Finished (stage=$STAGE) =========="
