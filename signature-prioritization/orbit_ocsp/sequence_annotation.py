"""Sequence-mode annotation merging (KOfam + InterProScan + DeepGOPlus).

orbit-ocsp does **not** run the annotation tools. Users run KOfam, InterProScan
and DeepGOPlus themselves; this module parses their native outputs, merges the
terms per query sequence, and emits an ``A_terms`` JSON that the existing
ensemble scoring engine can consume.

Two entry points:

* **A** — native tool outputs -> merged JSON -> scoring
* **B** — pre-merged JSON -> validate -> scoring

All parsing lives inside the ``orbit-ocsp`` package: no ``sys.path`` injection,
no import of the out-of-tree ``org_pipeline`` prototype.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

SOURCE_KOFAM = "kofam"
SOURCE_INTERPRO = "interproscan"
SOURCE_DEEPGO = "deepgoplus"
SOURCE_ORDER = (SOURCE_KOFAM, SOURCE_INTERPRO, SOURCE_DEEPGO)

#: DeepGOPlus default threshold — 0 keeps every parseable prediction.
DEFAULT_DEEPGO_MIN_SCORE = 0.0

_GO_RE = re.compile(r"GO:\d{7}")
_KEGG_RE = re.compile(r"^([A-Za-z]{2,4})(\d{5})$")
_KOFAM_ROW_RE = re.compile(
    r"^(?P<qid>\S+)\s+(?P<ko>K\d+)\s+(?P<thr>\S+)\s+(?P<score>\S+)\s+"
    r"(?P<evalue>\S+)(?:\s+(?P<definition>.*))?$"
)

CONTRACT_FIELDS = ("gene_name", "similarity_gene_name", "ENTREZ_ID", "pathway")
EXTENSION_FIELDS = ("pathway_sources", "term_evidence", "id_source", "id_evidence")


class SequenceInputError(Exception):
    """Bad user input: caller maps this to a non-zero exit code."""


def _dedup(items: Iterable[str]) -> List[str]:
    """Deduplicate while preserving first-seen order."""
    seen = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _read_lines(path: PathLike) -> List[str]:
    return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()


def _check_readable(path: PathLike, label: str) -> Path:
    p = Path(path)
    if not p.exists():
        raise SequenceInputError(f"{label} file not found: {p}")
    if not p.is_file():
        raise SequenceInputError(f"{label} path is not a file: {p}")
    return p


# --------------------------------------------------------------------------
# KO -> pathway mapping
# --------------------------------------------------------------------------

def load_ko_pathway_map(path: PathLike) -> Dict[str, List[str]]:
    """Load a KO->pathway mapping.

    Two accepted layouts:

    * species map with a ``KO<TAB>Pathway`` header (``K00001<TAB>hsa00010``)
    * generic headerless map (``ko:K00001<TAB>path:map00010``); ``ko:``/``path:``
      prefixes are stripped and ``map*`` pathway IDs are dropped because they
      carry no species and cannot align with the species-specific B background.
    """
    p = _check_readable(path, "KO->pathway mapping")
    lines = _read_lines(p)
    if not lines:
        raise SequenceInputError(f"KO->pathway mapping is empty: {p}")

    first = [c.strip() for c in lines[0].split("\t")]
    has_header = len(first) >= 2 and first[0].upper() == "KO"
    if has_header:
        if first[1].strip().lower() != "pathway":
            raise SequenceInputError(
                f"KO->pathway mapping {p} must have columns 'KO' and 'Pathway'; "
                f"found {first[:2]}"
            )
        body = lines[1:]
    else:
        if len(first) < 2:
            raise SequenceInputError(
                f"KO->pathway mapping {p} must be a two-column TSV "
                f"('KO'/'Pathway' header, or headerless 'ko:K.../path:...')"
            )
        body = lines

    mapping: Dict[str, List[str]] = {}
    for line in body:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        ko = parts[0].strip()
        pathway = parts[1].strip()
        if ko.lower().startswith("ko:"):
            ko = ko[3:]
        if pathway.lower().startswith("path:"):
            pathway = pathway[5:]
        if not ko or not pathway:
            continue
        # Species-agnostic KEGG reference maps cannot be scored against a
        # species-specific B background.
        if pathway.startswith("map"):
            continue
        mapping.setdefault(ko, [])
        if pathway not in mapping[ko]:
            mapping[ko].append(pathway)
    return mapping


def default_ko_pathway_path(species: str) -> str:
    """Bundled KO->pathway mapping for ``hsa`` / ``mmu``."""
    from orbit_ocsp.data_manager import resolve_data_path

    key = species.strip().lower()
    if key in {"hsa", "human"}:
        return resolve_data_path("data/ko2pathway/ko2hsa.txt")
    if key in {"mmu", "mouse"}:
        return resolve_data_path("data/ko2pathway/ko2mmu.txt")
    raise SequenceInputError(
        f"Unsupported species {species!r}; supported values: hsa, mmu"
    )


def kegg_species_prefix(term: str) -> Optional[str]:
    match = _KEGG_RE.match(str(term))
    return match.group(1).lower() if match else None


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------

class ParseStats:
    """Per-file parse counters for the diagnostic report."""

    def __init__(self, path: Optional[PathLike] = None, source: str = ""):
        self.path = str(path) if path else None
        self.source = source
        self.parsed_lines = 0
        self.skipped_lines = 0
        self.skipped_examples: List[str] = []
        self.filtered_lines = 0
        self.empty_file = False

    def skip(self, lineno: int, raw: str, reason: str = "") -> None:
        self.skipped_lines += 1
        if len(self.skipped_examples) < 5:
            detail = f"L{lineno}: {raw.strip()[:120]}"
            if reason:
                detail = f"{detail}  ({reason})"
            self.skipped_examples.append(detail)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "path": self.path,
            "parsed_lines": self.parsed_lines,
            "skipped_lines": self.skipped_lines,
            "filtered_lines": self.filtered_lines,
            "empty_file": self.empty_file,
            "skipped_examples": self.skipped_examples,
        }


def parse_kofam(
    path: PathLike,
    ko_pathway_map: Optional[Dict[str, List[str]]] = None,
    *,
    min_score: Optional[float] = None,
) -> Tuple[Dict[str, List[str]], ParseStats]:
    """Parse a KOfam native output into ``{query_id: [pathway terms]}``.

    Layout is whitespace-aligned: ``gene name / KO / thrshld / score / E-value /
    KO definition``. ``#`` lines are comments; a leading ``*`` marks a hit above
    the adaptive threshold. ``-`` in the threshold or score column becomes 0.0.
    """
    stats = ParseStats(path, SOURCE_KOFAM)
    p = _check_readable(path, "KOfam")
    if p.stat().st_size == 0:
        stats.empty_file = True
        return {}, stats

    ko_pathway_map = ko_pathway_map or {}
    terms: Dict[str, List[str]] = {}

    for lineno, raw in enumerate(_read_lines(p), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("*"):
            line = line[1:].strip()

        match = _KOFAM_ROW_RE.match(line)
        if not match:
            stats.skip(lineno, raw, "does not match KOfam row layout")
            continue

        def _num(value: str) -> float:
            if value == "-":
                return 0.0
            try:
                return float(value)
            except ValueError:
                return 0.0

        score = _num(match.group("score"))
        if min_score is not None and score < min_score:
            stats.filtered_lines += 1
            continue

        stats.parsed_lines += 1
        qid = match.group("qid")
        ko = match.group("ko")
        terms.setdefault(qid, [])
        for pathway in ko_pathway_map.get(ko, []):
            if pathway not in terms[qid]:
                terms[qid].append(pathway)

    return terms, stats


def parse_interproscan(path: PathLike) -> Tuple[Dict[str, List[str]], ParseStats]:
    """Parse an InterProScan TSV, extracting GO terms from column 14.

    Column 15 (pathway) holds MetaCyc / Reactome cross-references which are not
    part of the GO/KEGG universe used for scoring, so it is ignored.
    """
    stats = ParseStats(path, SOURCE_INTERPRO)
    p = _check_readable(path, "InterProScan")
    if p.stat().st_size == 0:
        stats.empty_file = True
        return {}, stats

    terms: Dict[str, List[str]] = {}
    for lineno, raw in enumerate(_read_lines(p), start=1):
        if not raw.strip():
            continue
        parts = raw.rstrip("\n").split("\t")
        if lineno == 1:
            head = parts[0].strip().lower()
            if "protein" in head or "accession" in head:
                continue
        if len(parts) < 14:
            stats.skip(lineno, raw, f"only {len(parts)} columns, need >= 14")
            continue

        stats.parsed_lines += 1
        qid = parts[0].strip()
        if not qid:
            continue
        terms.setdefault(qid, [])
        go_field = parts[13].strip()
        if go_field and go_field != "-":
            for go in _GO_RE.findall(go_field):
                if go not in terms[qid]:
                    terms[qid].append(go)

    return terms, stats


def parse_deepgoplus(
    path: PathLike,
    *,
    min_score: float = DEFAULT_DEEPGO_MIN_SCORE,
) -> Tuple[Dict[str, List[str]], Dict[str, Dict[str, Optional[float]]], ParseStats]:
    """Parse a DeepGOPlus TSV (``query_id``, ``GO term``, ``score``).

    Returns ``(terms, scores, stats)``. Default ``min_score`` of 0 keeps every
    parseable prediction. Records whose score cannot be parsed are kept with a
    ``None`` score and are never threshold-filtered. Duplicate (query, term)
    pairs collapse to the highest score.
    """
    stats = ParseStats(path, SOURCE_DEEPGO)
    p = _check_readable(path, "DeepGOPlus")
    if p.stat().st_size == 0:
        stats.empty_file = True
        return {}, {}, stats

    best: Dict[str, Dict[str, Optional[float]]] = {}
    order: Dict[str, List[str]] = {}

    for lineno, raw in enumerate(_read_lines(p), start=1):
        if not raw.strip():
            continue
        parts = raw.rstrip("\n").split("\t")
        if len(parts) < 2:
            stats.skip(lineno, raw, f"only {len(parts)} columns, need >= 2")
            continue
        qid = parts[0].strip()
        go = parts[1].strip()
        if not qid or not _GO_RE.fullmatch(go):
            stats.skip(lineno, raw, "missing query ID or malformed GO term")
            continue

        score: Optional[float]
        if len(parts) < 3 or not parts[2].strip():
            score = None
        else:
            try:
                score = float(parts[2].strip())
            except ValueError:
                score = None

        # None scores bypass the threshold entirely.
        if score is not None and score < min_score:
            stats.filtered_lines += 1
            continue

        stats.parsed_lines += 1
        best.setdefault(qid, {})
        order.setdefault(qid, [])
        if go not in best[qid]:
            best[qid][go] = score
            order[qid].append(go)
        else:
            prev = best[qid][go]
            if prev is None or (score is not None and score > prev):
                best[qid][go] = score

    terms = {qid: list(go_list) for qid, go_list in order.items()}
    return terms, best, stats


# --------------------------------------------------------------------------
# Query ID -> gene identifier resolution
# --------------------------------------------------------------------------

ID_SOURCE_MAP = "id_map"
ID_SOURCE_FALLBACK = "fallback_query_id"


def load_id_map(path: PathLike) -> Dict[str, dict]:
    """Load the user-supplied query_id -> gene identifier TSV.

    Required column ``query_id``; optional ``entrez_id``, ``gene_symbol``,
    ``identity``, ``evalue``. Matching is exact string equality — no prefix
    heuristics. The first row wins when a ``query_id`` repeats.
    """
    p = _check_readable(path, "ID map")
    lines = [line for line in _read_lines(p) if line.strip()]
    if not lines:
        raise SequenceInputError(f"ID map is empty: {p}")

    header = [c.strip().lower() for c in lines[0].split("\t")]
    if "query_id" not in header:
        raise SequenceInputError(
            f"ID map {p} is missing the required column 'query_id'; "
            f"found columns: {', '.join(header) or '(none)'}"
        )
    idx = {name: i for i, name in enumerate(header)}

    def _cell(parts: List[str], name: str) -> str:
        i = idx.get(name)
        if i is None or i >= len(parts):
            return ""
        return parts[i].strip()

    mapping: Dict[str, dict] = {}
    duplicates: List[str] = []
    for raw in lines[1:]:
        parts = raw.split("\t")
        qid = _cell(parts, "query_id")
        if not qid:
            continue
        if qid in mapping:
            duplicates.append(qid)
            continue
        evidence = {}
        for field in ("identity", "evalue"):
            value = _cell(parts, field)
            if value:
                evidence[field] = value
        mapping[qid] = {
            "entrez_id": _cell(parts, "entrez_id"),
            "gene_symbol": _cell(parts, "gene_symbol"),
            "id_evidence": evidence or None,
        }
    if duplicates:
        logger.warning(
            "ID map %s has %d duplicate query_id value(s); keeping first "
            "occurrence: %s",
            p,
            len(duplicates),
            ", ".join(_dedup(duplicates)[:10]),
        )
    return mapping


def _load_symbol_by_entrez(species: str) -> Dict[str, str]:
    """Entrez ID -> gene symbol from the bundled gene annotation table."""
    from orbit_ocsp.data_manager import resolve_data_path

    key = species.strip().lower()
    filename = (
        "Gene_Annotation_Mouse.txt"
        if key in {"mmu", "mouse"}
        else "Gene_Annotation_Human.txt"
    )
    path = Path(resolve_data_path(f"data/protein/{filename}"))
    if not path.exists():
        logger.warning("Gene annotation table not found: %s", path)
        return {}

    lookup: Dict[str, str] = {}
    lines = _read_lines(path)
    if not lines:
        return lookup
    header = [c.strip().lower() for c in lines[0].split("\t")]
    try:
        entrez_col = next(
            i for i, name in enumerate(header) if "entrez" in name or name == "geneid"
        )
        symbol_col = next(
            i for i, name in enumerate(header) if "symbol" in name
        )
    except StopIteration:
        logger.warning(
            "Cannot locate entrez/symbol columns in %s (header: %s)", path, header
        )
        return lookup

    for raw in lines[1:]:
        parts = raw.split("\t")
        if len(parts) <= max(entrez_col, symbol_col):
            continue
        entrez = parts[entrez_col].strip()
        symbol = parts[symbol_col].strip()
        if entrez and symbol and entrez not in lookup:
            lookup[entrez] = symbol
    return lookup


class IdResolver:
    """Resolve a query ID to ``(entrez_id, similarity_gene_name, id_source)``.

    Unmapped sequences fall back to using the query ID itself as
    ``similarity_gene_name``. That matters: ``load_gene_pathways`` only indexes
    ``similarity_gene_name`` and ``ENTREZ_ID`` — never ``gene_name`` — so the
    fallback is what keeps novel sequences scorable.
    """

    def __init__(
        self,
        id_map: Optional[Dict[str, dict]] = None,
        species: str = "hsa",
    ):
        self.id_map = id_map or {}
        self.species = species
        self._symbol_by_entrez: Optional[Dict[str, str]] = None

    def _symbol_for_entrez(self, entrez: str) -> str:
        if self._symbol_by_entrez is None:
            self._symbol_by_entrez = _load_symbol_by_entrez(self.species)
        return self._symbol_by_entrez.get(entrez, "")

    def resolve(self, query_id: str) -> dict:
        entry = self.id_map.get(query_id)
        if not entry:
            return {
                "ENTREZ_ID": "",
                "similarity_gene_name": query_id,
                "id_source": ID_SOURCE_FALLBACK,
                "id_evidence": None,
            }
        entrez = str(entry.get("entrez_id") or "").strip()
        symbol = str(entry.get("gene_symbol") or "").strip()
        if not symbol and entrez:
            symbol = self._symbol_for_entrez(entrez)
        return {
            "ENTREZ_ID": entrez,
            "similarity_gene_name": symbol or query_id,
            "id_source": ID_SOURCE_MAP,
            "id_evidence": entry.get("id_evidence"),
        }


# --------------------------------------------------------------------------
# Merge engine
# --------------------------------------------------------------------------

def merge_annotations(
    *,
    kofam_terms: Optional[Dict[str, List[str]]] = None,
    interpro_terms: Optional[Dict[str, List[str]]] = None,
    deepgo_terms: Optional[Dict[str, List[str]]] = None,
    deepgo_scores: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    id_resolver: Optional[IdResolver] = None,
    query_id: Optional[str] = None,
) -> Tuple[List[dict], List[dict]]:
    """Merge the three annotation sources into A_terms records.

    Terms are concatenated in KOfam -> InterProScan -> DeepGOPlus order, then
    deduplicated keeping first occurrence. Every retained term gets a
    ``pathway_sources`` entry; DeepGOPlus scores land in ``term_evidence``.

    Returns ``(records, excluded)`` where ``excluded`` lists query IDs dropped
    for having zero terms.
    """
    kofam_terms = kofam_terms or {}
    interpro_terms = interpro_terms or {}
    deepgo_terms = deepgo_terms or {}
    deepgo_scores = deepgo_scores or {}
    resolver = id_resolver or IdResolver()

    per_source = (
        (SOURCE_KOFAM, kofam_terms),
        (SOURCE_INTERPRO, interpro_terms),
        (SOURCE_DEEPGO, deepgo_terms),
    )

    query_ids = _dedup(
        [qid for _, mapping in per_source for qid in mapping.keys()]
    )
    if query_id is not None:
        query_ids = [qid for qid in query_ids if qid == query_id]

    records: List[dict] = []
    excluded: List[dict] = []

    for qid in query_ids:
        ordered: List[str] = []
        sources: Dict[str, List[str]] = {}
        for source, mapping in per_source:
            for term in mapping.get(qid, []):
                if term not in sources:
                    sources[term] = []
                    ordered.append(term)
                if source not in sources[term]:
                    sources[term].append(source)

        if not ordered:
            excluded.append({"query_id": qid, "reason": "no_terms"})
            continue

        evidence: Dict[str, dict] = {}
        for term in ordered:
            score = deepgo_scores.get(qid, {}).get(term)
            if SOURCE_DEEPGO in sources[term]:
                evidence[term] = {"deepgoplus_score": score}

        ids = resolver.resolve(qid)
        record = {
            "gene_name": qid,
            "similarity_gene_name": ids["similarity_gene_name"],
            "ENTREZ_ID": ids["ENTREZ_ID"],
            "pathway": ordered,
            "pathway_sources": sources,
            "id_source": ids["id_source"],
        }
        if evidence:
            record["term_evidence"] = evidence
        if ids.get("id_evidence"):
            record["id_evidence"] = ids["id_evidence"]
        records.append(record)

    return records, excluded


def term_counts_by_source(record: dict) -> Dict[str, int]:
    counts = {source: 0 for source in SOURCE_ORDER}
    for sources in (record.get("pathway_sources") or {}).values():
        for source in sources:
            if source in counts:
                counts[source] += 1
    return counts


# --------------------------------------------------------------------------
# Merged JSON I/O
# --------------------------------------------------------------------------

def _normalize_record(record: dict) -> dict:
    """Coerce contract fields to their serialized types, preserving extensions."""
    out = {
        "gene_name": str(record.get("gene_name", "") or ""),
        "similarity_gene_name": str(record.get("similarity_gene_name", "") or ""),
        "ENTREZ_ID": str(record.get("ENTREZ_ID", "") or ""),
        "pathway": [str(t) for t in (record.get("pathway") or [])],
    }
    for field in EXTENSION_FIELDS:
        if field in record and record[field] is not None:
            out[field] = record[field]
    for key, value in record.items():
        if key not in out and key not in CONTRACT_FIELDS:
            out[key] = value
    return out


def write_merged_json(records: Sequence[dict], path: PathLike) -> Path:
    """Serialize A_terms records to a Merged_JSON file (UTF-8, non-ASCII kept)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [_normalize_record(record) for record in records]
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return p


def read_merged_json(path: PathLike) -> List[dict]:
    """Deserialize a Merged_JSON file into normalized records."""
    p = _check_readable(path, "Merged JSON")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SequenceInputError(
            f"{p} is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    if not isinstance(data, list):
        raise SequenceInputError(
            f"{p} must contain a JSON array of records; found "
            f"{type(data).__name__}.\n"
            f"Note: --merged-json expects the A_terms record array produced by "
            f"sequence mode (see gene/input/merged_result_1.json). The bundled "
            f"pathway library all_merged_result.json goes to --merged-result."
        )
    return [_normalize_record(item) for item in data]


def validate_merged_records(records: Sequence[dict]) -> Tuple[List[dict], List[dict]]:
    """Split records into (scorable, excluded).

    Hard errors (missing / wrong-typed ``pathway``) raise; soft problems
    (``empty_pathway``, ``no_index_key``) are reported and skipped.
    """
    scorable: List[dict] = []
    excluded: List[dict] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SequenceInputError(
                f"record {index}: expected a JSON object, found "
                f"{type(record).__name__}"
            )
        if "pathway" not in record:
            raise SequenceInputError(
                f"record {index}: missing required field 'pathway'"
            )
        if not isinstance(record["pathway"], list):
            raise SequenceInputError(
                f"record {index}: field 'pathway' must be an array, found "
                f"{type(record['pathway']).__name__}"
            )
        label = (
            record.get("similarity_gene_name")
            or record.get("ENTREZ_ID")
            or record.get("gene_name")
            or f"record[{index}]"
        )
        if not record["pathway"]:
            excluded.append(
                {"index": index, "query_id": label, "reason": "empty_pathway"}
            )
            continue
        if not record.get("similarity_gene_name") and not record.get("ENTREZ_ID"):
            excluded.append(
                {"index": index, "query_id": label, "reason": "no_index_key"}
            )
            continue
        scorable.append(record)
    return scorable, excluded


def records_to_gene_pathways(records: Sequence[dict]) -> Dict[str, List[str]]:
    """Index records the same way ``load_gene_pathways`` does.

    Keys: ``similarity_gene_name`` (as-is and upper-cased) plus ``ENTREZ_ID``.
    ``gene_name`` is intentionally not indexed, matching the existing loader.
    """
    gene_pathways: Dict[str, List[str]] = {}
    for record in records:
        pathways = list(record.get("pathway") or [])
        if not pathways:
            continue
        name = str(record.get("similarity_gene_name", "") or "").strip()
        entrez = str(record.get("ENTREZ_ID", "") or "").strip()
        if name:
            gene_pathways.setdefault(name, pathways)
            gene_pathways.setdefault(name.upper(), pathways)
        if entrez:
            gene_pathways.setdefault(entrez, pathways)
    return gene_pathways


def species_prefix_mismatches(
    records: Sequence[dict], species: str
) -> Optional[dict]:
    """Detect KEGG terms whose species prefix disagrees with ``species``."""
    expected = species.strip().lower()
    found: Dict[str, int] = {}
    for record in records:
        for term in record.get("pathway") or []:
            prefix = kegg_species_prefix(term)
            if prefix and prefix != expected:
                found[prefix] = found.get(prefix, 0) + 1
    if not found:
        return None
    return {
        "expected_species_prefix": expected,
        "found_prefixes": found,
        "n_mismatched_terms": sum(found.values()),
    }


# --------------------------------------------------------------------------
# Batch discovery
# --------------------------------------------------------------------------

_IGNORED_KOFAM_PREFIXES = ("all_", "ko_result_")


def discover_annotation_dir(directory: PathLike) -> Dict[str, Dict[str, Path]]:
    """Group ``<dir>/{kofam,interproscan,deepgoplus}/*`` files by sample key.

    Sample key = filename stem. Files under ``kofam/`` whose name starts with
    ``all_`` or ``ko_result_`` are aggregate outputs and are ignored.
    """
    root = Path(directory)
    if not root.is_dir():
        raise SequenceInputError(f"--annotation-dir is not a directory: {root}")

    layout = (
        (SOURCE_KOFAM, "kofam", ("*.txt", "*.tsv")),
        (SOURCE_INTERPRO, "interproscan", ("*.tsv", "*.txt")),
        (SOURCE_DEEPGO, "deepgoplus", ("*.tsv", "*.txt")),
    )
    groups: Dict[str, Dict[str, Path]] = {}
    for source, subdir, patterns in layout:
        folder = root / subdir
        if not folder.is_dir():
            continue
        for pattern in patterns:
            for path in sorted(folder.glob(pattern)):
                if source == SOURCE_KOFAM and path.name.startswith(
                    _IGNORED_KOFAM_PREFIXES
                ):
                    continue
                groups.setdefault(path.stem, {}).setdefault(source, path)

    if not groups:
        raise SequenceInputError(
            f"No annotation files found under {root}. Expected "
            f"{root}/kofam/*.txt, {root}/interproscan/*.tsv, "
            f"{root}/deepgoplus/*.tsv"
        )
    return groups


# --------------------------------------------------------------------------
# Entry point A: native tool outputs -> merged JSON
# --------------------------------------------------------------------------

def build_merged_records(
    *,
    kofam: Optional[PathLike] = None,
    interproscan: Optional[PathLike] = None,
    deepgo: Optional[PathLike] = None,
    species: str = "hsa",
    ko2pathway: Optional[PathLike] = None,
    deepgo_min_score: float = DEFAULT_DEEPGO_MIN_SCORE,
    kofam_min_score: Optional[float] = None,
    id_resolver: Optional[IdResolver] = None,
    query_id: Optional[str] = None,
) -> Tuple[List[dict], dict]:
    """Parse whichever native outputs are supplied and merge them.

    Returns ``(records, diagnostics)``. Missing sources simply contribute zero
    terms rather than failing.
    """
    if not any([kofam, interproscan, deepgo]):
        raise SequenceInputError(
            "At least one of --kofam / --interproscan / --deepgo is required"
        )

    file_stats: List[dict] = []

    kofam_terms: Dict[str, List[str]] = {}
    if kofam:
        ko_map_path = ko2pathway or default_ko_pathway_path(species)
        ko_map = load_ko_pathway_map(ko_map_path)
        kofam_terms, stats = parse_kofam(
            kofam, ko_map, min_score=kofam_min_score
        )
        entry = stats.to_dict()
        entry["ko2pathway"] = str(ko_map_path)
        entry["n_ko_in_map"] = len(ko_map)
        file_stats.append(entry)

    interpro_terms: Dict[str, List[str]] = {}
    if interproscan:
        interpro_terms, stats = parse_interproscan(interproscan)
        file_stats.append(stats.to_dict())

    deepgo_terms: Dict[str, List[str]] = {}
    deepgo_scores: Dict[str, Dict[str, Optional[float]]] = {}
    if deepgo:
        deepgo_terms, deepgo_scores, stats = parse_deepgoplus(
            deepgo, min_score=deepgo_min_score
        )
        entry = stats.to_dict()
        entry["min_score"] = deepgo_min_score
        file_stats.append(entry)

    records, excluded = merge_annotations(
        kofam_terms=kofam_terms,
        interpro_terms=interpro_terms,
        deepgo_terms=deepgo_terms,
        deepgo_scores=deepgo_scores,
        id_resolver=id_resolver,
        query_id=query_id,
    )

    diagnostics = {
        "inputs": file_stats,
        "queries": [
            {
                "query_id": record["gene_name"],
                "similarity_gene_name": record["similarity_gene_name"],
                "entrez_id": record["ENTREZ_ID"],
                "id_source": record.get("id_source"),
                "n_terms": len(record["pathway"]),
                "terms_by_source": term_counts_by_source(record),
            }
            for record in records
        ],
        "excluded": excluded,
        "warnings": [],
    }
    mismatch = species_prefix_mismatches(records, species)
    if mismatch:
        diagnostics["warnings"].append(
            {"code": "species_prefix_mismatch", **mismatch}
        )
    return records, diagnostics


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _score_records(
    records: Sequence[dict],
    *,
    condition: str,
    species: str,
    outdir: Path,
    b_terms: Optional[PathLike],
    alpha: float,
    seed: int,
    pathway_mode: str = "union",
    pathway_sources: Sequence[str] = ("enrich", "gsea", "gsva"),
    min_dataset_freq: Optional[int] = None,
    model: Optional[str] = "Organoid",
) -> Tuple[List[dict], dict]:
    """Score merged records with the existing ensemble engine.

    Returns ``(ranked_rows, score_meta)`` where ``score_meta`` records the
    resolved pathway-background parameters.
    """
    from orbit_ocsp.b_terms_schema import (
        DEFAULT_MODEL,
        DEFAULT_PATHWAY_SOURCES,
        count_condition_datasets,
        resolve_min_dataset_freq,
    )
    from orbit_ocsp.expression_pipeline import (
        _resolve_default,
        default_score_gene,
        load_universe_and_meta,
    )

    scoring_species = (
        "hsa"
        if species.strip().lower() in {"hsa", "human"}
        else "mmu"
        if species.strip().lower() in {"mmu", "mouse"}
        else species.strip().lower()
    )
    b_terms_path = Path(
        b_terms or _resolve_default(f"data/data_b/B_terms_{scoring_species}.json")
    )
    if not b_terms_path.exists():
        raise SequenceInputError(f"B_terms file not found: {b_terms_path}")

    u_terms, go_meta, kegg_meta = load_universe_and_meta(scoring_species)
    gene_pathways = records_to_gene_pathways(records)
    pathway_sources = (
        tuple(pathway_sources) if pathway_sources else DEFAULT_PATHWAY_SOURCES
    )
    if model is None:
        model = DEFAULT_MODEL
    model = str(model).strip()
    with open(b_terms_path, "r", encoding="utf-8") as handle:
        b_records = json.load(handle)
    if isinstance(b_records, dict):
        b_records = [b_records]
    n_condition_datasets = count_condition_datasets(
        b_records, condition, model=model or None
    )
    resolved_min_dataset_freq = resolve_min_dataset_freq(
        n_condition_datasets, min_dataset_freq
    )
    score_meta = {
        "pathway_mode": pathway_mode,
        "pathway_sources": list(pathway_sources),
        "min_dataset_freq_requested": min_dataset_freq,
        "min_dataset_freq": resolved_min_dataset_freq,
        "n_condition_datasets": int(n_condition_datasets),
        "model": model or None,
    }

    ranked: List[dict] = []
    for record in records:
        query_id = record.get("gene_name") or record.get("similarity_gene_name") or ""
        score_key = record.get("similarity_gene_name") or record.get("ENTREZ_ID") or query_id
        entrez = record.get("ENTREZ_ID") or None
        row = {
            "de_rank": None,
            "query_id": query_id,
            "id_type": record.get("id_source"),
            "gene_symbol": record.get("similarity_gene_name") or None,
            "ensembl_id": None,
            "log2FoldChange": None,
            "padj": None,
            "entrez_id": entrez,
            "mapping_status": record.get("id_source"),
            "fasta_relpath": None,
            "n_isoforms": 0,
            "sequence_preview": None,
            "ncbi_gene_url": (
                f"https://www.ncbi.nlm.nih.gov/gene/{entrez}" if entrez else None
            ),
            "condition": condition,
            "biomarker_score": None,
            "scoring_status": "pending",
            "sample_key": record.get("sample_key"),
            "n_a_terms_input": len(record.get("pathway") or []),
        }
        if not record.get("pathway"):
            row["scoring_status"] = "no_pathway_annotation"
            ranked.append(row)
            continue
        try:
            score = default_score_gene(
                gene=score_key,
                condition=condition,
                gene_pathways=gene_pathways,
                b_terms_file=b_terms_path,
                u_terms=u_terms,
                go_meta=go_meta,
                kegg_meta=kegg_meta,
                output_dir=outdir,
                species=scoring_species,
                alpha=alpha,
                seed=seed,
                pathway_mode=pathway_mode,
                pathway_sources=pathway_sources,
                min_dataset_freq=resolved_min_dataset_freq,
                model=model or None,
            )
        except Exception as exc:  # pragma: no cover - defensive
            row["scoring_status"] = f"error: {exc}"
            ranked.append(row)
            continue
        if score is None:
            row["scoring_status"] = "score_unavailable"
        else:
            row["scoring_status"] = "ok"
            row["biomarker_score"] = score
            if score.get("ncbi_gene_url") is None and row["ncbi_gene_url"]:
                score["ncbi_gene_url"] = row["ncbi_gene_url"]
        ranked.append(row)

    def _sort_key(row: dict):
        """Rank by primary p-value, ties broken by consensus.

        Matches the other two modes: the primary hypergeometric test decides
        the call and the ranking; consensus only separates equal p-values.
        """
        score = row.get("biomarker_score") or {}
        consensus = score.get("consensus_score")
        primary_p = score.get("primary_p_value", score.get("combined_p_value"))
        return (
            0 if row.get("scoring_status") == "ok" else 1,
            float(primary_p) if primary_p is not None else 1.0,
            -float(consensus) if consensus is not None else 0.0,
            str(row.get("gene_symbol") or row.get("query_id") or ""),
        )

    ranked.sort(key=_sort_key)
    for index, row in enumerate(ranked, start=1):
        row["biomarker_rank"] = index
    return ranked, score_meta


def run_sequence_pipeline(
    *,
    condition: str,
    outdir: PathLike,
    species: str = "hsa",
    kofam: Optional[PathLike] = None,
    interproscan: Optional[PathLike] = None,
    deepgo: Optional[PathLike] = None,
    annotation_dir: Optional[PathLike] = None,
    merged_json: Optional[PathLike] = None,
    id_map: Optional[PathLike] = None,
    ko2pathway: Optional[PathLike] = None,
    deepgo_min_score: float = DEFAULT_DEEPGO_MIN_SCORE,
    kofam_min_score: Optional[float] = None,
    query_id: Optional[str] = None,
    b_terms: Optional[PathLike] = None,
    alpha: float = 0.005,
    seed: int = 42,
    merge_only: bool = False,
    pathway_mode: str = "union",
    pathway_sources: Sequence[str] = ("enrich", "gsea", "gsva"),
    min_dataset_freq: Optional[int] = None,
    model: Optional[str] = "Organoid",
) -> dict:
    """Run sequence mode end to end.

    Entry A: ``kofam`` / ``interproscan`` / ``deepgo`` / ``annotation_dir``.
    Entry B: ``merged_json``.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    native_inputs = [kofam, interproscan, deepgo, annotation_dir]
    if merged_json and any(native_inputs):
        raise SequenceInputError(
            "--merged-json (entry B) is mutually exclusive with --kofam / "
            "--interproscan / --deepgo / --annotation-dir (entry A). Pick one."
        )
    if not merged_json and not any(native_inputs):
        raise SequenceInputError(
            "sequence mode needs either:\n"
            "  entry A: --kofam / --interproscan / --deepgo (or --annotation-dir)\n"
            "  entry B: --merged-json <path>"
        )

    resolver = IdResolver(
        load_id_map(id_map) if id_map else None, species=species
    )
    diagnostics: dict = {
        "mode": "sequence",
        "entry": "B" if merged_json else "A",
        "condition": condition,
        "species": species,
        "inputs": [],
        "queries": [],
        "excluded": [],
        "warnings": [],
        "samples": {},
    }

    if merged_json:
        records = read_merged_json(merged_json)
        scorable, excluded = validate_merged_records(records)
        diagnostics["inputs"].append(
            {
                "source": "merged_json",
                "path": str(merged_json),
                "n_records": len(records),
                "n_scorable": len(scorable),
            }
        )
        diagnostics["excluded"].extend(excluded)
        diagnostics["queries"] = [
            {
                "query_id": r.get("gene_name"),
                "similarity_gene_name": r.get("similarity_gene_name"),
                "entrez_id": r.get("ENTREZ_ID"),
                "id_source": r.get("id_source"),
                "n_terms": len(r.get("pathway") or []),
            }
            for r in scorable
        ]
        mismatch = species_prefix_mismatches(scorable, species)
        if mismatch:
            diagnostics["warnings"].append(
                {"code": "species_prefix_mismatch", **mismatch}
            )
        merged_path = Path(merged_json)
    else:
        if annotation_dir:
            groups = discover_annotation_dir(annotation_dir)
            scorable = []
            for sample_key, files in sorted(groups.items()):
                try:
                    recs, diag = build_merged_records(
                        kofam=files.get(SOURCE_KOFAM),
                        interproscan=files.get(SOURCE_INTERPRO),
                        deepgo=files.get(SOURCE_DEEPGO),
                        species=species,
                        ko2pathway=ko2pathway,
                        deepgo_min_score=deepgo_min_score,
                        kofam_min_score=kofam_min_score,
                        id_resolver=resolver,
                        query_id=query_id,
                    )
                except Exception as exc:
                    diagnostics["samples"][sample_key] = {
                        "status": "failed",
                        "error": str(exc),
                    }
                    diagnostics["excluded"].append(
                        {"query_id": sample_key, "reason": f"sample_error: {exc}"}
                    )
                    continue
                for record in recs:
                    record["sample_key"] = sample_key
                scorable.extend(recs)
                diagnostics["samples"][sample_key] = {
                    "status": "ok",
                    "n_records": len(recs),
                }
                diagnostics["inputs"].extend(diag["inputs"])
                diagnostics["queries"].extend(diag["queries"])
                diagnostics["excluded"].extend(diag["excluded"])
                diagnostics["warnings"].extend(diag["warnings"])
            if not scorable:
                raise SequenceInputError(
                    "No scorable records from --annotation-dir. Failed samples: "
                    + ", ".join(
                        key
                        for key, info in diagnostics["samples"].items()
                        if info.get("status") == "failed"
                    )
                )
        else:
            scorable, diag = build_merged_records(
                kofam=kofam,
                interproscan=interproscan,
                deepgo=deepgo,
                species=species,
                ko2pathway=ko2pathway,
                deepgo_min_score=deepgo_min_score,
                kofam_min_score=kofam_min_score,
                id_resolver=resolver,
                query_id=query_id,
            )
            diagnostics["inputs"].extend(diag["inputs"])
            diagnostics["queries"].extend(diag["queries"])
            diagnostics["excluded"].extend(diag["excluded"])
            diagnostics["warnings"].extend(diag["warnings"])

        merged_path = write_merged_json(scorable, outdir / "merged_a_terms.json")

    if not scorable:
        report_path = _write_report(diagnostics, outdir)
        raise SequenceInputError(
            f"No scorable records (every record was excluded). "
            f"See {report_path} for per-record reasons."
        )

    diagnostics["merged_json"] = str(merged_path)
    diagnostics["n_scorable"] = len(scorable)

    if merge_only:
        report_path = _write_report(diagnostics, outdir)
        return {
            "merged_json": str(merged_path),
            "report": str(report_path),
            "n_records": len(scorable),
            "ranked": [],
        }

    ranked, score_meta = _score_records(
        scorable,
        condition=condition,
        species=species,
        outdir=outdir,
        b_terms=b_terms,
        alpha=alpha,
        seed=seed,
        pathway_mode=pathway_mode,
        pathway_sources=pathway_sources,
        min_dataset_freq=min_dataset_freq,
        model=model,
    )

    from orbit_ocsp.expression_pipeline import write_biomarker_outputs

    summary = {
        "mode": "sequence",
        "entry": diagnostics["entry"],
        "n_input": len(scorable),
        "n_ranked": len(ranked),
        "condition": condition,
        "model": score_meta.get("model"),
        "species": species,
        "alpha": alpha,
        "pathway_mode": score_meta["pathway_mode"],
        "pathway_sources": score_meta["pathway_sources"],
        "min_dataset_freq_requested": score_meta["min_dataset_freq_requested"],
        "min_dataset_freq": score_meta["min_dataset_freq"],
        "n_condition_datasets": score_meta["n_condition_datasets"],
        "merged_json": str(merged_path),
        "deepgo_min_score": deepgo_min_score,
        "outputs": {},
    }
    summary = write_biomarker_outputs(ranked, outdir, summary)
    report_path = _write_report(diagnostics, outdir)
    return {
        "merged_json": str(merged_path),
        "report": str(report_path),
        "n_records": len(scorable),
        "ranked": ranked,
        "summary": summary,
    }


def _write_report(diagnostics: dict, outdir: PathLike) -> Path:
    path = Path(outdir) / "sequence_merge_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
