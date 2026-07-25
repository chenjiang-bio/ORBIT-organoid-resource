"""Extract unique B_terms metadata values for CLI / UI listing."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from orbit_ocsp.b_terms_schema import b_get, b_list_values
from orbit_ocsp.data_manager import resolve_data_path

# Same facets as handoff/ocsp_min/scripts/build_filter_index.py
FILTER_FIELDS: tuple[str, ...] = (
    "category",
    "condition",
    "factor",
    "additional_condition",
    "organ_condition",
    "organ_control",
    "organ_system_condition",
    "organ_system_control",
    "source_condition",
    "source_control",
    "time_condition",
    "time_control",
    "cell_type",
    "comparison_condition",
    "comparison_control",
    "model_condition",
    "model_control",
)

_LIST_FIELDS = frozenset(
    {
        "category",
        "organ_system_condition",
        "organ_system_control",
    }
)

_LEGACY_FIELD_ALIASES = {
    "organ": "organ_condition",
    "model": "model_condition",
    "source": "source_condition",
    "time": "time_condition",
    "day": "time_condition",
}


def default_b_terms_path(species: str) -> str:
    key = species.strip().lower()
    if key not in {"hsa", "mmu"}:
        raise ValueError(f"Unsupported species {species!r}; use hsa or mmu")
    return resolve_data_path(f"data/data_b/B_terms_{key}.json")


def _field_value(obj: dict, field: str) -> list[str]:
    if field in _LIST_FIELDS:
        return b_list_values(obj, field)
    if field == "organ_condition":
        text = b_get(obj, "organ_condition").strip()
        return [text] if text else []
    if field == "organ_control":
        text = b_get(obj, "organ_control").strip()
        return [text] if text else []
    if field == "model_condition":
        text = b_get(obj, "model_condition").strip()
        return [text] if text else []
    if field == "model_control":
        text = b_get(obj, "model_control").strip()
        return [text] if text else []
    if field == "source_condition":
        text = b_get(obj, "source_condition").strip()
        return [text] if text else []
    if field == "source_control":
        text = b_get(obj, "source_control").strip()
        return [text] if text else []
    if field == "time_condition":
        text = b_get(obj, "time_condition").strip()
        return [text] if text else []
    if field == "time_control":
        text = b_get(obj, "time_control").strip()
        return [text] if text else []
    raw = obj.get(field)
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw).strip()
    return [text] if text else []


def _iter_b_records(b_terms_path: str | Path) -> Iterable[dict]:
    path = Path(b_terms_path)
    try:
        import ijson
    except ImportError:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            yield data
        else:
            yield from data
        return

    with path.open("rb") as handle:
        for obj in ijson.items(handle, "item"):
            if isinstance(obj, dict):
                yield obj


def collect_field_counts(
    b_terms_path: str | Path,
    fields: Iterable[str] | None = None,
) -> dict[str, dict[str, int]]:
    """Return each metadata value with the number of B records carrying it.

    A record is counted once per distinct value, so list-valued fields like
    ``category`` cannot inflate a single record into several counts.

    Values are ordered by descending record count, then alphabetically, so the
    best-supported choices surface first. The empty value sorts last.
    """
    want = list(fields) if fields else list(FILTER_FIELDS)
    buckets: dict[str, Counter] = {field: Counter() for field in want}

    for obj in _iter_b_records(b_terms_path):
        for field in want:
            for value in set(_field_value(obj, field)):
                buckets[field][value] += 1

    return {
        field: dict(
            sorted(
                counter.items(),
                key=lambda kv: (kv[0] == "", -kv[1], kv[0].lower()),
            )
        )
        for field, counter in buckets.items()
    }


def collect_field_values(
    b_terms_path: str | Path,
    fields: Iterable[str] | None = None,
    *,
    order: str = "alpha",
) -> dict[str, list[str]]:
    """Return unique values per B_terms metadata field.

    ``order='alpha'`` (default) sorts alphabetically; ``order='frequency'``
    sorts by descending record count so the best-supported values come first.
    """
    if order not in {"alpha", "frequency"}:
        raise ValueError(f"order must be 'alpha' or 'frequency', got {order!r}")

    counts = collect_field_counts(b_terms_path, fields)
    if order == "frequency":
        # collect_field_counts already emits frequency order.
        return {field: list(values) for field, values in counts.items()}
    return {
        field: sorted(values, key=lambda x: (x == "", x.lower()))
        for field, values in counts.items()
    }


def collect_condition_tree(
    b_terms_path: str | Path,
    *,
    order: str = "alpha",
) -> dict[str, list[str]]:
    """Map condition -> unique additional_condition values.

    ``order='frequency'`` orders conditions by descending record count.
    """
    if order not in {"alpha", "frequency"}:
        raise ValueError(f"order must be 'alpha' or 'frequency', got {order!r}")

    tree: dict[str, set[str]] = defaultdict(set)
    counts: Counter = Counter()
    for obj in _iter_b_records(b_terms_path):
        cond = str(obj.get("condition", "") or "").strip()
        addc = str(obj.get("additional_condition", "") or "").strip()
        tree[cond].add(addc)
        counts[cond] += 1

    if order == "frequency":
        key = lambda kv: (kv[0] == "", -counts[kv[0]], kv[0].lower())  # noqa: E731
    else:
        key = lambda kv: (kv[0] == "", kv[0].lower())  # noqa: E731

    return {
        cond: sorted(adds, key=lambda x: (x == "", x.lower()))
        for cond, adds in sorted(tree.items(), key=key)
    }


def normalize_field_name(name: str) -> str:
    key = (name or "").strip()
    if not key:
        raise ValueError("Field name cannot be empty")
    if key in FILTER_FIELDS:
        return key
    alias = _LEGACY_FIELD_ALIASES.get(key)
    if alias:
        return alias
    raise ValueError(
        f"Unknown field {name!r}. Choose from: {', '.join(FILTER_FIELDS)}"
    )


def format_text_listing(
    field_values: dict[str, list[str]],
    *,
    condition_tree: dict[str, list[str]] | None = None,
    field_counts: dict[str, dict[str, int]] | None = None,
) -> str:
    """Render a listing. When ``field_counts`` is given, show record counts.

    Counts tell the reader how much evidence backs each value, which matters
    because a condition supported by 3 records yields a much weaker background
    than one supported by 300.
    """
    lines: list[str] = []
    if condition_tree is not None:
        lines.append("condition → additional_condition")
        lines.append("")
        counts = (field_counts or {}).get("condition", {})
        for cond, adds in condition_tree.items():
            label = cond if cond else "(empty condition)"
            if cond in counts:
                label = f"{label}  [{counts[cond]} records]"
            add_text = ", ".join(adds) if adds else "(none)"
            lines.append(f"- {label}")
            lines.append(f"    additional_condition: {add_text}")
        lines.append("")

    for field, values in field_values.items():
        if field == "condition" and condition_tree is not None:
            continue
        counts = (field_counts or {}).get(field, {})
        header = f"{field} ({len(values)} values"
        header += ", most records first)" if counts else ")"
        lines.append(header)
        width = max((len(str(c)) for c in counts.values()), default=0)
        for value in values:
            label = value if value else "(empty)"
            if value in counts:
                lines.append(f"  - {str(counts[value]).rjust(width)}  {label}")
            else:
                lines.append(f"  - {label}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
