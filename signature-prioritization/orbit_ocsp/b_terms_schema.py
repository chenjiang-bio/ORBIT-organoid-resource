"""Canonical accessors for current B_terms JSON schema.

Current ``data/data_b/B_terms_*.json`` records use paired ``*_condition`` /
``*_control`` fields. Both arms are first-class filter parameters.

``organ_candidates_*`` are deprecated and must never be used for filtering.
``pathway`` is an object ``{enrich, gsea, gsva}`` (legacy list still accepted).
``category`` may be a list.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Optional, Sequence


# Explicit schema keys (+ legacy flat-name fallbacks where noted).
_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "organ_condition": ("organ_condition", "organ"),
    "organ_control": ("organ_control",),
    "organ_system_condition": ("organ_system_condition",),
    "organ_system_control": ("organ_system_control",),
    "model_condition": ("model_condition", "model"),
    "model_control": ("model_control",),
    "source_condition": ("source_condition", "source"),
    "source_control": ("source_control",),
    "time_condition": ("time_condition", "day", "time"),
    "time_control": ("time_control",),
    # Short aliases used for grouping keys / reports (experimental arm).
    "organ": ("organ_condition", "organ"),
    "model": ("model_condition", "model"),
    "source": ("source_condition", "source"),
    "time": ("time_condition", "day", "time"),
    "day": ("time_condition", "day"),
}

# Fields stored as JSON arrays in B_terms (membership match).
_LIST_FIELDS = frozenset(
    {
        "category",
        "organ_system_condition",
        "organ_system_control",
    }
)

DEPRECATED_FIELDS = frozenset(
    {
        "organ_candidates_control",
        "organ_candidates_condition",
    }
)

DEFAULT_PATHWAY_SOURCES: tuple[str, ...] = ("enrich", "gsea", "gsva")

#: Product default for the experimental-arm model filter. Organoid is the
#: primary ORBIT use case; pass ``model=""`` (or ``None`` into library APIs
#: that you want unfiltered) to disable.
DEFAULT_MODEL = "Organoid"

#: Conditions with at least this many matched GSE IDs are treated as data-rich
#: (Colorectal Cancer has 57 overall / 41 Organoid). Their auto
#: ``min_dataset_freq`` is raised so single-study pathway noise is dropped.
DATA_RICH_N_DATASETS = 30
DATA_RICH_MIN_DATASET_FREQ = 6


def default_min_dataset_freq(n_datasets: int) -> int:
    """Choose an automatic dataset-frequency floor from matched coverage.

    Data-rich conditions (dozens of GSE IDs, e.g. Colorectal Cancer) default
    to 6. Sparse conditions keep 1 so the background is not emptied.
    """
    n = max(0, int(n_datasets or 0))
    if n >= DATA_RICH_N_DATASETS:
        return min(DATA_RICH_MIN_DATASET_FREQ, n)
    return 1


def resolve_min_dataset_freq(
    n_datasets: int,
    explicit: Optional[int] = None,
) -> int:
    """Return the effective ``min_dataset_freq``.

    ``explicit=None`` selects :func:`default_min_dataset_freq`; any provided
    integer is used as a hard floor (at least 1).
    """
    if explicit is None:
        return default_min_dataset_freq(n_datasets)
    return max(1, int(explicit))


def count_condition_datasets(
    records: Iterable[dict],
    condition: str,
    *,
    model: Optional[str] = None,
    **filters: Any,
) -> int:
    """Count unique GSE IDs among records matching ``condition`` and filters.

    Extra ``filters`` are forwarded to :func:`b_record_matches` (category,
    organ_condition, factor, …). Empty / omitted filters are ignored.
    """
    want_model = (model or "").strip()
    match_kwargs = {
        key: ("" if value is None else str(value))
        for key, value in filters.items()
    }
    # Prefer explicit model_condition from filters; else use ``model``.
    if want_model and not str(match_kwargs.get("model_condition") or "").strip():
        match_kwargs["model"] = want_model
    gses: set[str] = set()
    for obj in records:
        if not isinstance(obj, dict):
            continue
        if not b_record_matches(
            obj,
            condition=condition or "",
            **match_kwargs,
        ):
            continue
        gse = str(obj.get("GSE_ID") or "").strip() or f"row:{id(obj)}"
        gses.add(gse)
    return len(gses)


# Optional B_terms metadata filters exposed to CLI / pipelines. ``condition``
# is required separately; ``model`` remains the Organoid default alias for
# ``model_condition``.
B_TERM_FILTER_KEYS: tuple[str, ...] = (
    "category",
    "model",
    "model_condition",
    "model_control",
    "organ",
    "organ_condition",
    "organ_control",
    "organ_system_condition",
    "organ_system_control",
    "factor",
    "source",
    "source_condition",
    "source_control",
    "cell_type",
    "time",
    "time_condition",
    "time_control",
    "additional_condition",
    "comparison_control",
    "comparison_condition",
)


def coerce_optional_str(value: Any) -> Optional[str]:
    """Strip strings; treat None / blank as absent."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_b_term_filters(**kwargs: Any) -> dict[str, str]:
    """Keep only known B_terms filter fields.

    ``None`` is dropped. Blank strings are dropped except for ``model`` /
    ``model_condition``, where blank means "do not filter on model".
    """
    out: dict[str, str] = {}
    for key in B_TERM_FILTER_KEYS:
        if key not in kwargs:
            continue
        value = kwargs.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text and key not in {"model", "model_condition"}:
            continue
        out[key] = text
    return out


def _norm_eq(a: Optional[str], b: Optional[str]) -> bool:
    if a is None or b is None:
        return False
    return a.strip().lower() == b.strip().lower()


def b_get(obj: dict, logical: str) -> str:
    """Return a string metadata field using current B schema (+ legacy fallback)."""
    keys = _FIELD_KEYS.get(logical)
    if keys is None:
        val = obj.get(logical, "")
        if isinstance(val, (list, tuple)):
            return ", ".join(str(x) for x in val if x is not None and str(x).strip())
        return str(val or "")
    for key in keys:
        if key in DEPRECATED_FIELDS:
            continue
        if key not in obj:
            continue
        val = obj.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def b_categories(obj: dict) -> list[str]:
    """Normalize category to a list of non-empty strings."""
    return b_list_values(obj, "category")


def b_list_values(obj: dict, key: str) -> list[str]:
    """Normalize a B list/string field to non-empty strings."""
    raw = obj.get(key)
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw).strip()
    return [text] if text else []


def b_list_match(obj: dict, key: str, want: str) -> bool:
    """True if filter empty or any list entry matches (case-insensitive)."""
    text = (want or "").strip()
    if not text:
        return True
    return any(_norm_eq(x, text) for x in b_list_values(obj, key))


def b_category_match(obj: dict, category_filter: str) -> bool:
    """True if filter is empty or matches any category entry (case-insensitive)."""
    return b_list_match(obj, "category", category_filter)

def b_pathway_terms(
    obj: dict,
    sources: Sequence[str] = DEFAULT_PATHWAY_SOURCES,
) -> list[str]:
    """Extract pathway term IDs from a B record (union across ``sources``).

    Prefer ``pathway.enrich`` (default). Legacy list/string ``pathway`` is supported.
    Does not flatten dicts via ``str()``.

    For evaluation / Analysis defaults use :func:`b_pathway_terms_combined`
    with ``mode="majority"`` instead.
    """
    raw = obj.get("pathway")
    if raw is None:
        raw = obj.get("pathways")
    if raw is None:
        return []

    if isinstance(raw, dict):
        out: list[str] = []
        seen: set[str] = set()
        for src in sources:
            chunk = raw.get(src)
            if chunk is None:
                continue
            for term in _as_term_list(chunk):
                if term not in seen:
                    seen.add(term)
                    out.append(term)
        return out

    return _as_term_list(raw)


def b_pathway_terms_combined(
    obj: dict,
    *,
    mode: str = "majority",
    sources: Sequence[str] = DEFAULT_PATHWAY_SOURCES,
) -> list[str]:
    """Per-record pathway combine matching the OCSP evaluation freeze.

    ``mode``:
      - ``majority`` (default / paper): pairwise intersection then union across
        non-empty method lists among ``sources`` (typically enrich/gsea/gsva).
        If only one method list is non-empty, keep that list (single-method
        fallback used in the Jul 2026 CRC evaluation).
      - ``union``: union of all listed sources (legacy wide background).
    """
    raw = obj.get("pathway")
    if raw is None:
        raw = obj.get("pathways")
    if raw is None:
        return []

    mode_key = (mode or "majority").strip().lower()
    if not isinstance(raw, dict):
        # Legacy flat pathway list: treat as a single method set.
        return _as_term_list(raw)

    method_sets: list[set[str]] = []
    for src in sources:
        chunk = set(_as_term_list(raw.get(src)))
        if chunk:
            method_sets.append(chunk)

    if not method_sets:
        return []
    if mode_key == "union":
        out: set[str] = set()
        for s in method_sets:
            out |= s
        return sorted(out)
    # majority
    if len(method_sets) == 1:
        return sorted(method_sets[0])
    out = set()
    for i in range(len(method_sets)):
        for j in range(i + 1, len(method_sets)):
            out |= method_sets[i] & method_sets[j]
    return sorted(out)


def _as_term_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, dict):
        return []
    text = str(value).strip()
    if not text:
        return []
    if (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    ):
        text = text[1:-1]
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts if parts else [text]


def b_record_matches(
    obj: dict,
    *,
    condition: str = "",
    additional_condition: str = "",
    organ: str = "",
    organ_condition: str = "",
    organ_control: str = "",
    organ_system_condition: str = "",
    organ_system_control: str = "",
    model: str = "",
    model_condition: str = "",
    model_control: str = "",
    category: str = "",
    comparison_control: str = "",
    comparison_condition: str = "",
    cell_type: str = "",
    day: str = "",
    time: str = "",
    time_condition: str = "",
    time_control: str = "",
    factor: str = "",
    source: str = "",
    source_condition: str = "",
    source_control: str = "",
    allow_additional_all: bool = False,
) -> bool:
    """Case-insensitive exact match on non-empty filters against current B fields.

    Paired arms are independent. ``organ_system_*`` are list fields (membership).
    Legacy ``organ`` / ``source`` / ``day`` / ``model`` / ``time`` map to the
    ``*_condition`` arm when the explicit ``*_condition`` filter is empty.
    """
    if condition and not _norm_eq(str(obj.get("condition", "") or ""), condition):
        return False

    if additional_condition:
        if not (allow_additional_all and additional_condition.strip().lower() == "all"):
            if not _norm_eq(
                str(obj.get("additional_condition", "") or ""), additional_condition
            ):
                return False

    want_organ_cond = (organ_condition or organ or "").strip()
    want_organ_ctrl = (organ_control or "").strip()
    if want_organ_cond and not _norm_eq(b_get(obj, "organ_condition"), want_organ_cond):
        return False
    if want_organ_ctrl and not _norm_eq(b_get(obj, "organ_control"), want_organ_ctrl):
        return False
    if not b_list_match(obj, "organ_system_condition", organ_system_condition):
        return False
    if not b_list_match(obj, "organ_system_control", organ_system_control):
        return False

    want_model_cond = (model_condition or model or "").strip()
    want_model_ctrl = (model_control or "").strip()
    if want_model_cond and not _norm_eq(b_get(obj, "model_condition"), want_model_cond):
        return False
    if want_model_ctrl and not _norm_eq(b_get(obj, "model_control"), want_model_ctrl):
        return False

    if not b_category_match(obj, category):
        return False
    if comparison_control and not _norm_eq(
        str(obj.get("comparison_control", "") or ""), comparison_control
    ):
        return False
    if comparison_condition and not _norm_eq(
        str(obj.get("comparison_condition", "") or ""), comparison_condition
    ):
        return False
    if cell_type and not _norm_eq(str(obj.get("cell_type", "") or ""), cell_type):
        return False

    want_time_cond = (time_condition or time or day or "").strip()
    want_time_ctrl = (time_control or "").strip()
    if want_time_cond and not _norm_eq(b_get(obj, "time_condition"), want_time_cond):
        return False
    if want_time_ctrl and not _norm_eq(b_get(obj, "time_control"), want_time_ctrl):
        return False

    if factor and not _norm_eq(str(obj.get("factor", "") or ""), factor):
        return False

    want_source_cond = (source_condition or source or "").strip()
    want_source_ctrl = (source_control or "").strip()
    if want_source_cond and not _norm_eq(
        b_get(obj, "source_condition"), want_source_cond
    ):
        return False
    if want_source_ctrl and not _norm_eq(b_get(obj, "source_control"), want_source_ctrl):
        return False
    return True


def load_condition_pathways(
    records: Iterable[dict],
    condition: str,
    *,
    category: Optional[str] = None,
    model: Optional[str] = DEFAULT_MODEL,
    model_condition: Optional[str] = None,
    model_control: Optional[str] = None,
    organ: Optional[str] = None,
    organ_condition: Optional[str] = None,
    organ_control: Optional[str] = None,
    organ_system_condition: Optional[str] = None,
    organ_system_control: Optional[str] = None,
    factor: Optional[str] = None,
    source: Optional[str] = None,
    source_condition: Optional[str] = None,
    source_control: Optional[str] = None,
    cell_type: Optional[str] = None,
    time: Optional[str] = None,
    time_condition: Optional[str] = None,
    time_control: Optional[str] = None,
    additional_condition: Optional[str] = None,
    comparison_control: Optional[str] = None,
    comparison_condition: Optional[str] = None,
    pathway_sources: Sequence[str] = DEFAULT_PATHWAY_SOURCES,
    pathway_mode: str = "majority",
    min_record_freq: int = 1,
    min_dataset_freq: Optional[int] = None,
) -> list[str]:
    """Filter B records and return pathway IDs.

    ``pathway_mode`` (matches OCSP evaluation / Analysis defaults):
      - ``majority`` (default): per-record pairwise majority on enrich/gsea/gsva
        (single non-empty method kept), then retain terms supported by at least
        ``min_dataset_freq`` independent GSE series
      - ``union``: per-record union of pathway sources, then the same
        ``min_dataset_freq`` recurrence cut

    ``min_dataset_freq``:
      - ``None`` (default): auto — 6 for data-rich conditions
        (>= :data:`DATA_RICH_N_DATASETS` matched GSE IDs), else 1
      - integer: hard floor (at least 1)
    """
    matched: list[dict] = []
    for obj in records:
        if not isinstance(obj, dict):
            continue
        if not b_record_matches(
            obj,
            condition=condition or "",
            additional_condition=additional_condition or "",
            organ=organ or "",
            organ_condition=organ_condition or "",
            organ_control=organ_control or "",
            organ_system_condition=organ_system_condition or "",
            organ_system_control=organ_system_control or "",
            model=model or "",
            model_condition=model_condition or "",
            model_control=model_control or "",
            category=category or "",
            comparison_control=comparison_control or "",
            comparison_condition=comparison_condition or "",
            cell_type=cell_type or "",
            time=time or "",
            time_condition=time_condition or "",
            time_control=time_control or "",
            factor=factor or "",
            source=source or "",
            source_condition=source_condition or "",
            source_control=source_control or "",
            allow_additional_all=True,
        ):
            continue
        matched.append(obj)

    if not matched:
        return []

    sources = tuple(pathway_sources) if pathway_sources else DEFAULT_PATHWAY_SOURCES
    mode = (pathway_mode or "majority").strip().lower()
    per_record_mode = "majority" if mode == "majority" else "union"
    record_counts: Counter[str] = Counter()
    dataset_sets: dict[str, set[str]] = defaultdict(set)
    for obj in matched:
        terms = b_pathway_terms_combined(
            obj, mode=per_record_mode, sources=sources
        )
        gse = str(obj.get("GSE_ID") or "").strip() or f"row:{id(obj)}"
        for term in set(terms):
            record_counts[term] += 1
            dataset_sets[term].add(gse)

    dataset_counts = {t: len(ds) for t, ds in dataset_sets.items()}
    n_datasets = len(
        {
            str(obj.get("GSE_ID") or "").strip() or f"row:{id(obj)}"
            for obj in matched
        }
    )

    floor_ds = resolve_min_dataset_freq(n_datasets, min_dataset_freq)
    floor_rec = max(1, int(min_record_freq or 1))

    kept = [
        term
        for term, n_rec in record_counts.items()
        if n_rec >= floor_rec and dataset_counts.get(term, 0) >= floor_ds
    ]
    return sorted(kept)
