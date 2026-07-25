"""Gene-ID → Entrez ID → canonical protein sequence lookup.

Accepts mixed user identifiers:
  - Entrez gene ID (e.g. ``6934``)
  - Ensembl gene ID (e.g. ``ENSG00000148737`` / ``ENSMUSG...``)
  - gene symbol (e.g. ``TCF7L2``)

All are resolved to Entrez ID before loading FASTA under ``data/protein/``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# Project root: orbit-ocsp/ (parent of the package directory)
_PKG_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PROTEIN_REL = Path("data") / "protein"

_SPECIES_TO_DIR = {
    "hsa": "human",
    "human": "human",
    "homo sapiens": "human",
    "mmu": "mouse",
    "mouse": "mouse",
    "mus musculus": "mouse",
}

_ANNOTATION_FILES = {
    "human": "Gene_Annotation_Human.txt",
    "mouse": "Gene_Annotation_Mouse.txt",
}

_ENTREZ_RE = re.compile(r"^\d+$")
_ENSEMBL_RE = re.compile(
    r"^(ENSG|ENSMUSG)\d{11,}(\.\d+)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GeneAnnotationIndex:
    """In-memory annotation maps for one species."""

    symbol_to_entrez: Dict[str, str]
    ensembl_to_entrez: Dict[str, str]
    entrez_to_symbol: Dict[str, str]
    entrez_to_ensembl: Dict[str, str]


def project_root() -> Path:
    """Return the orbit-ocsp project root directory."""
    return _PKG_ROOT


def resolve_protein_root(protein_root: Optional[Path | str] = None) -> Path:
    """Resolve ``data/protein``, honouring the active data root.

    Delegates to :func:`orbit_ocsp.data_manager.resolve_data_path` so that a
    pip-installed package with downloaded data (``ORBIT_OCSP_DATA`` or
    ``~/.orbit_ocsp/data``) resolves correctly instead of only looking next to
    the package directory.
    """
    from orbit_ocsp.data_manager import resolve_data_path

    if protein_root is None:
        return Path(resolve_data_path(_DEFAULT_PROTEIN_REL)).resolve()
    path = Path(protein_root)
    if path.is_absolute():
        return path.resolve()
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    resolved = Path(resolve_data_path(str(path)))
    if resolved.exists():
        return resolved.resolve()
    return (_PKG_ROOT / path).resolve()


def normalize_species(species: str) -> str:
    """Map species aliases to ``human`` or ``mouse`` protein directory names."""
    key = (species or "").strip().lower()
    if key not in _SPECIES_TO_DIR:
        raise ValueError(
            f"Unsupported species {species!r}; expected one of "
            f"{sorted(set(_SPECIES_TO_DIR))}"
        )
    return _SPECIES_TO_DIR[key]


def annotation_path(
    species: str,
    protein_root: Optional[Path | str] = None,
) -> Path:
    """Return the annotation TSV path for a species."""
    species_dir = normalize_species(species)
    root = resolve_protein_root(protein_root)
    return root / _ANNOTATION_FILES[species_dir]


def fasta_path(
    entrez_id: str,
    species: str,
    protein_root: Optional[Path | str] = None,
) -> Path:
    """Return the FASTA path for an Entrez gene ID."""
    species_dir = normalize_species(species)
    root = resolve_protein_root(protein_root)
    return root / species_dir / f"{entrez_id}.fasta"


def detect_id_type(gene_id: str) -> str:
    """Classify a gene identifier as ``entrez``, ``ensembl``, or ``symbol``."""
    text = (gene_id or "").strip()
    if not text:
        return "unknown"
    if _ENTREZ_RE.match(text):
        return "entrez"
    # Strip version suffix for detection (ENSG00000148737.1)
    core = text.split(".", 1)[0]
    if _ENSEMBL_RE.match(core) or core.upper().startswith(("ENSG", "ENSMUSG")):
        return "ensembl"
    return "symbol"


@lru_cache(maxsize=4)
def _load_annotation_index_cached(annotation_file: str) -> GeneAnnotationIndex:
    path = Path(annotation_file)
    symbol_to_entrez: Dict[str, str] = {}
    ensembl_to_entrez: Dict[str, str] = {}
    entrez_to_symbol: Dict[str, str] = {}
    entrez_to_ensembl: Dict[str, str] = {}

    with path.open("r", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        try:
            entrez_idx = header.index("entrez_id")
            ensembl_idx = header.index("ensembl")
            symbol_idx = header.index("symbol")
        except ValueError as exc:
            raise ValueError(
                "Annotation file must contain 'entrez_id', 'ensembl' and "
                f"'symbol' columns: {path}"
            ) from exc

        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(entrez_idx, ensembl_idx, symbol_idx):
                continue
            entrez = parts[entrez_idx].strip()
            ensembl = parts[ensembl_idx].strip()
            symbol = parts[symbol_idx].strip()
            if not entrez:
                continue

            # Prefer first mapping for ambiguous keys.
            if symbol:
                symbol_to_entrez.setdefault(symbol.upper(), entrez)
                entrez_to_symbol.setdefault(entrez, symbol)
            if ensembl:
                ensembl_key = ensembl.split(".", 1)[0].upper()
                ensembl_to_entrez.setdefault(ensembl_key, entrez)
                entrez_to_ensembl.setdefault(entrez, ensembl.split(".", 1)[0])

    return GeneAnnotationIndex(
        symbol_to_entrez=symbol_to_entrez,
        ensembl_to_entrez=ensembl_to_entrez,
        entrez_to_symbol=entrez_to_symbol,
        entrez_to_ensembl=entrez_to_ensembl,
    )


def load_annotation_index(
    species: str,
    protein_root: Optional[Path | str] = None,
) -> GeneAnnotationIndex:
    """Load symbol/Ensembl/Entrez cross-maps for a species."""
    path = annotation_path(species, protein_root)
    if not path.exists():
        raise FileNotFoundError(f"Gene annotation file not found: {path}")
    return _load_annotation_index_cached(str(path.resolve()))


def load_symbol_to_entrez(
    species: str,
    protein_root: Optional[Path | str] = None,
) -> Dict[str, str]:
    """Load symbol→Entrez map (keys are upper-cased symbols)."""
    return dict(load_annotation_index(species, protein_root).symbol_to_entrez)


def resolve_to_entrez(
    gene_id: str,
    species: str,
    protein_root: Optional[Path | str] = None,
    index: Optional[GeneAnnotationIndex] = None,
) -> Tuple[Optional[str], str, Optional[str], Optional[str]]:
    """Resolve any supported gene ID to Entrez.

    Returns
    -------
    (entrez_id, id_type, symbol, ensembl_id)
    """
    query = (gene_id or "").strip()
    id_type = detect_id_type(query)
    if not query or id_type == "unknown":
        return None, id_type, None, None

    idx = index or load_annotation_index(species, protein_root)

    if id_type == "entrez":
        entrez = query
        if entrez not in idx.entrez_to_symbol and entrez not in idx.entrez_to_ensembl:
            # Still allow direct FASTA lookup even if annotation row is absent.
            return entrez, id_type, None, None
        return (
            entrez,
            id_type,
            idx.entrez_to_symbol.get(entrez),
            idx.entrez_to_ensembl.get(entrez),
        )

    if id_type == "ensembl":
        ensembl_key = query.split(".", 1)[0].upper()
        entrez = idx.ensembl_to_entrez.get(ensembl_key)
        if not entrez:
            return None, id_type, None, ensembl_key
        return (
            entrez,
            id_type,
            idx.entrez_to_symbol.get(entrez),
            idx.entrez_to_ensembl.get(entrez, ensembl_key),
        )

    # symbol
    entrez = idx.symbol_to_entrez.get(query.upper())
    if not entrez:
        return None, id_type, query, None
    return (
        entrez,
        id_type,
        idx.entrez_to_symbol.get(entrez, query),
        idx.entrez_to_ensembl.get(entrez),
    )


def lookup_entrez(
    symbol: str,
    species: str,
    protein_root: Optional[Path | str] = None,
    symbol_map: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Resolve a gene symbol (or any supported ID) to Entrez ID."""
    if symbol_map is not None and detect_id_type(symbol) == "symbol":
        return symbol_map.get((symbol or "").strip().upper())
    entrez, _, _, _ = resolve_to_entrez(symbol, species, protein_root)
    return entrez


def parse_fasta_records(text: str) -> List[tuple[str, str]]:
    """Parse FASTA text into ``(header, sequence)`` records."""
    records: List[tuple[str, str]] = []
    header: Optional[str] = None
    chunks: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(chunks)))
            header = line[1:].strip()
            chunks = []
        else:
            chunks.append(line)
    if header is not None:
        records.append((header, "".join(chunks)))
    return records


def load_canonical_sequence(
    entrez_id: str,
    species: str,
    protein_root: Optional[Path | str] = None,
) -> Optional[dict]:
    """Load the first protein isoform for an Entrez ID.

    Returns ``None`` when the FASTA file is missing or empty. When multiple
    isoforms exist, the first record is used as the canonical sequence.
    """
    path = fasta_path(entrez_id, species, protein_root)
    if not path.exists():
        return None
    records = parse_fasta_records(path.read_text(encoding="utf-8"))
    if not records:
        return None
    header, sequence = records[0]
    return {
        "entrez_id": str(entrez_id),
        "fasta_relpath": str(
            Path("data") / "protein" / normalize_species(species) / f"{entrez_id}.fasta"
        ),
        "header": header,
        "sequence": sequence,
        "n_isoforms": len(records),
        "selected_isoform_index": 0,
    }


def map_gene_ids_to_proteins(
    gene_ids: Iterable[str],
    species: str = "hsa",
    protein_root: Optional[Path | str] = None,
) -> List[dict]:
    """Map mixed gene IDs → Entrez → canonical protein sequences."""
    root = resolve_protein_root(protein_root)
    index = load_annotation_index(species, root)
    rows: List[dict] = []
    for gene_id in gene_ids:
        query = (gene_id or "").strip()
        entrez, id_type, symbol, ensembl = resolve_to_entrez(
            query, species, root, index=index
        )
        row: dict = {
            "query_id": query,
            "id_type": id_type,
            "gene_symbol": symbol,
            "ensembl_id": ensembl,
            "entrez_id": entrez,
            "sequence": None,
            "fasta_relpath": None,
            "protein_header": None,
            "n_isoforms": 0,
            "mapping_status": "ok",
        }
        if not entrez:
            row["mapping_status"] = "entrez_not_found"
            rows.append(row)
            continue
        protein = load_canonical_sequence(entrez, species, root)
        if protein is None:
            row["mapping_status"] = "fasta_not_found"
            rows.append(row)
            continue
        row.update(
            {
                "sequence": protein["sequence"],
                "fasta_relpath": protein["fasta_relpath"],
                "protein_header": protein["header"],
                "n_isoforms": protein["n_isoforms"],
            }
        )
        rows.append(row)
    return rows


def map_symbols_to_proteins(
    symbols: Iterable[str],
    species: str = "hsa",
    protein_root: Optional[Path | str] = None,
) -> List[dict]:
    """Backward-compatible alias of :func:`map_gene_ids_to_proteins`."""
    rows = map_gene_ids_to_proteins(symbols, species=species, protein_root=protein_root)
    # Preserve legacy key used by older callers/tests.
    for row in rows:
        if row.get("gene_symbol") is None:
            row["gene_symbol"] = row.get("query_id")
    return rows
