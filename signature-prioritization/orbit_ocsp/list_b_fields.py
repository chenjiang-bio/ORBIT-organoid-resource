#!/usr/bin/env python3
"""List available B_terms filter values (condition, organ, factor, …)."""

from __future__ import annotations

import argparse
import json
import sys

from orbit_ocsp.b_terms_listing import (
    FILTER_FIELDS,
    collect_condition_tree,
    collect_field_counts,
    default_b_terms_path,
    format_text_listing,
    normalize_field_name,
)
from orbit_ocsp.data_manager import ensure_data_available


def build_parser() -> argparse.ArgumentParser:
    fields_help = ", ".join(FILTER_FIELDS)
    parser = argparse.ArgumentParser(
        description=(
            "Print unique metadata values from B_terms for ORBIT filter fields.\n"
            "Use this to discover valid --condition, --organ_condition, --factor, etc."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  orbit-ocsp-list-fields --species hsa --field condition\n"
            "  orbit-ocsp-list-fields --species hsa --field condition --top 15\n"
            "  orbit-ocsp-list-fields --species hsa --field condition --sort alpha\n"
            "  orbit-ocsp-list-fields --species hsa --field organ_condition\n"
            "  orbit-ocsp-list-fields --species hsa --all\n"
            "  orbit-ocsp-list-fields --species hsa --condition-tree\n"
            "  orbit-ocsp-list-fields --species hsa --all --format json > filters_hsa.json\n\n"
            f"Available fields:\n  {fields_help}\n"
        ),
    )
    parser.add_argument("--species", choices=["hsa", "mmu"], required=True)
    parser.add_argument(
        "--b-terms",
        default=None,
        help="Override B_terms JSON path (default: data/data_b/B_terms_<species>.json)",
    )
    parser.add_argument(
        "--field",
        action="append",
        dest="fields",
        metavar="NAME",
        help="List one field (repeatable). Aliases: organ→organ_condition, model→model_condition",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="List all filter fields",
    )
    parser.add_argument(
        "--condition-tree",
        action="store_true",
        help="Print condition grouped with additional_condition values",
    )
    parser.add_argument(
        "--sort",
        choices=["frequency", "alpha"],
        default="frequency",
        help=(
            "Value order: 'frequency' shows the best-supported values first\n"
            "(default), 'alpha' sorts alphabetically"
        ),
    )
    parser.add_argument(
        "--counts",
        dest="counts",
        action="store_true",
        default=True,
        help="Show how many B records back each value (default)",
    )
    parser.add_argument(
        "--no-counts",
        dest="counts",
        action="store_false",
        help="Hide record counts",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Only print the N best-supported values per field",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        ensure_data_available(args.species)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    b_path = args.b_terms or default_b_terms_path(args.species)

    if args.all:
        fields = list(FILTER_FIELDS)
    elif args.fields:
        fields = [normalize_field_name(name) for name in args.fields]
    elif args.condition_tree:
        fields = []
    else:
        print("Specify --field NAME, --all, or --condition-tree", file=sys.stderr)
        return 2

    if args.top is not None and args.top < 1:
        print("--top must be >= 1", file=sys.stderr)
        return 2

    condition_tree = (
        collect_condition_tree(b_path, order=args.sort)
        if args.condition_tree
        else None
    )
    # Counts are needed to sort by frequency even when they are not displayed.
    field_counts = collect_field_counts(b_path, fields) if fields else {}
    field_values = (
        {
            field: (
                list(counts)
                if args.sort == "frequency"
                else sorted(counts, key=lambda x: (x == "", x.lower()))
            )
            for field, counts in field_counts.items()
        }
        if fields
        else {}
    )
    if args.top is not None:
        field_values = {
            field: values[: args.top] for field, values in field_values.items()
        }

    if args.format == "json":
        payload: dict = {"species": args.species, "b_terms": b_path}
        if field_values:
            payload["fields"] = field_values
            if args.counts:
                payload["field_counts"] = {
                    field: {
                        value: field_counts[field][value]
                        for value in field_values[field]
                    }
                    for field in field_values
                }
        if condition_tree is not None:
            payload["condition_tree"] = condition_tree
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(
        format_text_listing(
            field_values,
            condition_tree=condition_tree,
            field_counts=(
                (field_counts or collect_field_counts(b_path, ["condition"]))
                if args.counts
                else None
            ),
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
