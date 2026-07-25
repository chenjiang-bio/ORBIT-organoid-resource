"""The package must work with only the core dependencies installed.

Optional extras (``llm``, ``plots``, ``benchmark``) must never be needed to
import the package or run the three ``--mode`` commands. This test hides those
modules from the import system to prove it.
"""

from __future__ import annotations

import builtins
import importlib
import sys

import pytest

CORE_MODULES = [
    "orbit_ocsp.cli",
    "orbit_ocsp.data_manager",
    "orbit_ocsp.sequence_annotation",
    "orbit_ocsp.protein_lookup",
    "orbit_ocsp.expression_pipeline",
    "orbit_ocsp.expression_de",
    "orbit_ocsp.list_b_fields",
    "orbit_ocsp.download_data",
    "orbit_ocsp.b_terms_listing",
    "orbit_ocsp.b_terms_schema",
    "orbit_ocsp.semantic_two_stage",
]

OPTIONAL_PACKAGES = (
    "sklearn",
    "matplotlib",
    "seaborn",
    "statsmodels",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_community",
    "openai",
    "google.generativeai",
    "dashscope",
    "ollama",
)


@pytest.fixture()
def without_optional_packages(monkeypatch):
    """Make every optional dependency raise ImportError."""
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        root = name.split(".")[0]
        if root in {p.split(".")[0] for p in OPTIONAL_PACKAGES}:
            raise ImportError(f"{name} is hidden by this test")
        return real_import(name, *args, **kwargs)

    for mod in list(sys.modules):
        if mod.split(".")[0] in {p.split(".")[0] for p in OPTIONAL_PACKAGES}:
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_module_imports_without_optional_packages(
    module, without_optional_packages, monkeypatch
):
    monkeypatch.delitem(sys.modules, module, raising=False)
    importlib.import_module(module)


def test_cli_parser_builds_without_optional_packages(
    without_optional_packages, monkeypatch
):
    monkeypatch.delitem(sys.modules, "orbit_ocsp.cli", raising=False)
    cli = importlib.import_module("orbit_ocsp.cli")
    parser = cli.build_parser()
    args = parser.parse_args(["--mode", "genes", "--genes", "CD44"])
    assert args.mode == "genes"


def test_all_three_modes_are_selectable(without_optional_packages, monkeypatch):
    monkeypatch.delitem(sys.modules, "orbit_ocsp.cli", raising=False)
    cli = importlib.import_module("orbit_ocsp.cli")
    parser = cli.build_parser()
    for mode in ("expression", "genes", "sequence"):
        assert parser.parse_args(["--mode", mode]).mode == mode


def test_sequence_merge_works_without_optional_packages(
    tmp_path, without_optional_packages, monkeypatch
):
    """Parsing and merging must not need any optional dependency."""
    monkeypatch.delitem(sys.modules, "orbit_ocsp.sequence_annotation", raising=False)
    seq = importlib.import_module("orbit_ocsp.sequence_annotation")

    deepgo = tmp_path / "d.tsv"
    deepgo.write_text("Q1\tGO:0005515\t0.9\n", encoding="utf-8")
    terms, scores, stats = seq.parse_deepgoplus(deepgo)
    assert terms == {"Q1": ["GO:0005515"]}

    records, excluded = seq.merge_annotations(deepgo_terms=terms, deepgo_scores=scores)
    assert excluded == []
    out = seq.write_merged_json(records, tmp_path / "m.json")
    assert seq.read_merged_json(out) == records
