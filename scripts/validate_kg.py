#!/usr/bin/env python3
"""
validate_kg.py — Knowledge graph structure validation & report generation

Usage:
  python validate_kg.py                                    # Auto-detect latest KG build result
  python validate_kg.py organoid-kg-output/2026-07-18-1430/organoid_kg.json
  python validate_kg.py --gen-manual                       # Generate user manual (no KG needed)

Output:
  kg_test_output/YYYY-MM-DD-HHMM/test_report.json  — Structured test results
  kg_test_output/YYYY-MM-DD-HHMM/test_report.md    — Human-readable test report
  kg_test_output/user_manual.md                    — User manual
"""

import json
import os
import sys
import argparse
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Any

# Import query_tool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from query_tool import KnowledgeGraphQuery

# =============================================================================
# Expected Schema Definition
# =============================================================================

EXPECTED_NODE_TYPES = {
    "Sample", "Organ", "System", "Organism", "Source",
    "CellFactor", "Technology", "Drug", "Gene",
    "DiseaseModel", "Infection", "Biomarker", "Phenotype",
    "Test", "Omics", "Composition", "Application", "Publication",
    "CultureProtocol", "CultureTechnique", "CultureCondition",
    "ApplicationStrategy", "OrganoidProfile",
    "Platform", "CoCultureProtocol", "CoCultureTechnique",
    "GroupInfo",
    # Step F: GroupInfo sub-nodes
    "GroupDEGs", "IntraClusterDEGs", "ClusterMarkers", "GSVA", "GSEA",
    # Step G: Gene annotation
    "GeneAnnotation",
    # MaterialInfo: extracted from protocol material_sources
    "MaterialInfo",
}

EXPECTED_RELATION_TYPES = {
    "FROM_ORGAN", "BELONGS_TO_SYSTEM", "FROM_ORGANISM",
    "DERIVED_FROM", "USES_FACTOR", "USES_TECHNOLOGY", "SCREENS_DRUG",
    "TARGETS_GENE", "MODELS_DISEASE", "HAS_INFECTION", "HAS_BIOMARKER",
    "HAS_PHENOTYPE", "HAS_TEST", "HAS_OMICS", "HAS_COMPOSITION",
    "HAS_APPLICATION", "REPORTED_IN",
    "USES_PROTOCOL", "USES_TECHNIQUE", "HAS_CONDITION",
    "HAS_STRATEGY", "HAS_PROFILE", "USES_PLATFORM",
    "USES_COCULTURE_PROTOCOL", "USES_COCULTURE_TECHNIQUE",
    "HAS_GROUP_INFO",
    # Step F: GroupInfo → sub-nodes
    "HAS_DEG", "HAS_INTRACLUSTER_DEG", "HAS_CLUSTER_MARKER",
    "HAS_GSVA_PATHWAY", "HAS_GSEA_PATHWAY",
    # Step G: sub-nodes → GeneAnnotation; Gene → GeneAnnotation
    "HAS_GENE_ANNOTATION", "HAS_ANNOTATION",
    # Inferred relations (co-occurrence)
    "ASSOCIATED_WITH_DISEASE",
    # Protocol internal edges
    "USES_COMPONENT", "USES_MATERIAL",
}

# Expected source → target types for each relation (for edge direction validation)
# Structure check item name mapping
STRUCTURE_CHECK_NAMES = {
    "node_types_complete": "Node type completeness",
    "relation_types_complete": "Relationship type completeness",
    "node_counts_positive": "Non-zero node count check",
    "entity_dedup": "Entity deduplication check",
    "edge_direction": "Edge direction correctness",
    "coculture_context": "Co-culture context marking",
    "inferred_relations_exist": "Inferred relation existence",
    "no_orphan_types": "Orphan type check",
    "no_duplicate_edges": "Duplicate edge check",
    "edge_id_uniqueness": "Edge ID uniqueness",
}

EXPECTED_EDGE_DIRECTION = {
    # Each relation maps to a LIST of valid (source_type, target_type) pairs.
    # Multi-source relations (USES_COMPONENT, USES_MATERIAL, HAS_GENE_ANNOTATION,
    # ASSOCIATED_WITH_DISEASE) have multiple entries to cover all valid sources.
    "FROM_ORGAN":          [("Sample",    "Organ")],
    "BELONGS_TO_SYSTEM":   [("Organ",     "System")],
    "FROM_ORGANISM":       [("Sample",    "Organism")],
    "DERIVED_FROM":        [("Sample",    "Source")],
    "USES_FACTOR":         [("Sample",    "CellFactor")],
    "USES_TECHNOLOGY":     [("Sample",    "Technology")],
    "SCREENS_DRUG":        [("Sample",    "Drug")],
    "TARGETS_GENE":        [("Sample",    "Gene")],
    "MODELS_DISEASE":      [("Sample",    "DiseaseModel")],
    "HAS_INFECTION":       [("Sample",    "Infection")],
    "HAS_BIOMARKER":       [("Sample",    "Biomarker")],
    "HAS_PHENOTYPE":       [("Sample",    "Phenotype")],
    "HAS_TEST":            [("Sample",    "Test")],
    "HAS_OMICS":           [("Sample",    "Omics")],
    "HAS_COMPOSITION":     [("Sample",    "Composition")],
    "HAS_APPLICATION":     [("Sample",    "Application")],
    "REPORTED_IN":         [("Sample",    "Publication")],
    # v3.0 sample → compound entity edges
    "USES_PROTOCOL":            [("Sample",         "CultureProtocol")],
    "USES_TECHNIQUE":           [("Sample",         "CultureTechnique")],
    "HAS_CONDITION":            [("Sample",         "CultureCondition")],
    "HAS_STRATEGY":             [("Sample",         "ApplicationStrategy")],
    "HAS_PROFILE":              [("Sample",         "OrganoidProfile")],
    "USES_PLATFORM":            [("Omics",          "Platform")],
    "USES_COCULTURE_PROTOCOL":  [("Sample",         "CoCultureProtocol")],
    "USES_COCULTURE_TECHNIQUE": [("Sample",         "CoCultureTechnique")],
    "HAS_GROUP_INFO":           [("Sample",         "GroupInfo")],
    # Inferred relations (co-occurrence, confidence=0.5) — Drug or Biomarker → DiseaseModel
    "ASSOCIATED_WITH_DISEASE":  [("Drug",           "DiseaseModel"),
                                  ("Biomarker",      "DiseaseModel")],
    # Step F: GroupInfo → sub-node edges
    "HAS_DEG":                  [("GroupInfo",      "GroupDEGs")],
    "HAS_INTRACLUSTER_DEG":     [("GroupInfo",      "IntraClusterDEGs")],
    "HAS_CLUSTER_MARKER":       [("GroupInfo",      "ClusterMarkers")],
    "HAS_GSVA_PATHWAY":         [("GroupInfo",      "GSVA")],
    "HAS_GSEA_PATHWAY":         [("GroupInfo",      "GSEA")],
    # Step G: GeneAnnotation edges (source can be GroupDEGs, IntraClusterDEGs, or ClusterMarkers)
    "HAS_GENE_ANNOTATION":      [("GroupDEGs",      "GeneAnnotation"),
                                  ("IntraClusterDEGs", "GeneAnnotation"),
                                  ("ClusterMarkers",  "GeneAnnotation")],
    "HAS_ANNOTATION":           [("Gene",           "GeneAnnotation")],
    # Protocol internal edges — CultureProtocol OR CoCultureProtocol as source
    "USES_COMPONENT":           [("CultureProtocol",   "CellFactor"),
                                  ("CoCultureProtocol", "CellFactor")],
    "USES_MATERIAL":            [("CultureProtocol",   "MaterialInfo"),
                                  ("CoCultureProtocol", "MaterialInfo")],
}


# =============================================================================
# StructureValidator
# =============================================================================

class StructureValidator:
    """Knowledge graph structure correctness check"""

    def __init__(self, kg: KnowledgeGraphQuery):
        self.kg = kg
        self.results: List[dict] = []

    def run_all(self) -> List[dict]:
        checks = [
            self.check_node_types_complete,
            self.check_relation_types_complete,
            self.check_node_counts_positive,
            self.check_entity_dedup,
            self.check_edge_direction,
            self.check_coculture_context,
            self.check_inferred_relations_exist,
            self.check_no_orphan_types,
            self.check_no_duplicate_edges,
            self.check_edge_id_uniqueness,
        ]
        for check in checks:
            try:
                result = check()
            except Exception as e:
                result = {"check": check.__name__, "status": "ERROR",
                          "detail": str(e)}
            self.results.append(result)
        return self.results

    # ---- Check items ----

    def check_node_types_complete(self) -> dict:
        actual = set(self.kg.meta.get("node_types", []))
        missing = EXPECTED_NODE_TYPES - actual
        extra = actual - EXPECTED_NODE_TYPES
        return {
            "check": "node_types_complete",
            "status": "PASS" if not missing else "FAIL",
            "detail": f"{len(actual)}/{len(EXPECTED_NODE_TYPES)} types present",
            "missing": list(missing),
            "extra": list(extra),
            "suggestion": f"Missing types: {missing}" if missing else "",
        }

    def check_relation_types_complete(self) -> dict:
        actual = set(self.kg.meta.get("relationship_types", []))
        missing = EXPECTED_RELATION_TYPES - actual
        return {
            "check": "relation_types_complete",
            "status": "PASS" if not missing else "FAIL",
            "detail": f"{len(actual)}/{len(EXPECTED_RELATION_TYPES)} types present",
            "missing": list(missing),
            "suggestion": f"Missing relations: {missing}" if missing else "",
        }

    def check_node_counts_positive(self) -> dict:
        counts = defaultdict(int)
        for node in self.kg.nodes.values():
            counts[node.type] += 1
        zero_types = [
            t for t in EXPECTED_NODE_TYPES
            if t != "Sample" and counts.get(t, 0) == 0
        ]
        return {
            "check": "node_counts_positive",
            "status": "WARN" if zero_types else "PASS",
            "detail": f"zero-count types: {zero_types}" if zero_types else "all types have nodes",
            "counts": {t: counts.get(t, 0) for t in sorted(EXPECTED_NODE_TYPES)},
            "suggestion": (f"The following types have zero count, check if MySQL columns are empty or JSON parsing: {zero_types}"
                           if zero_types else ""),
        }

    def check_entity_dedup(self) -> dict:
        """Check if same type + same name has only one node"""
        name_index = defaultdict(list)
        for node in self.kg.nodes.values():
            name = node.properties.get("name")
            if name:
                name_index[(node.type, str(name).lower().strip())].append(node.id)

        dup_count = sum(1 for ids in name_index.values() if len(ids) > 1)
        dups = {k: v for k, v in name_index.items() if len(v) > 1}
        return {
            "check": "entity_dedup",
            "status": "PASS" if dup_count == 0 else "FAIL",
            "detail": f"{dup_count} duplicate entity groups found",
            "duplicates": {str(k): v for k, v in list(dups.items())[:5]},
            "suggestion": ("Entity deduplication failed, check _get_or_create_entity() registry key logic"
                           if dup_count > 0 else ""),
        }

    def check_edge_direction(self) -> dict:
        """Check edge direction: actual (source_type→target_type) matches any valid direction"""
        type_map = {nid: n.type for nid, n in self.kg.nodes.items()}
        wrong_edges = []
        checked = 0
        for edge in self.kg.edges:
            expected_list = EXPECTED_EDGE_DIRECTION.get(edge.relation)
            if not expected_list:
                continue
            src_type = type_map.get(edge.source, "?")
            tgt_type = type_map.get(edge.target, "?")
            checked += 1
            # Match if actual direction matches ANY valid (src, tgt) pair
            if not any(src_type == exp_src and tgt_type == exp_tgt
                       for exp_src, exp_tgt in expected_list):
                expected_strs = [f"({s}→{t})" for s, t in expected_list]
                wrong_edges.append({
                    "edge_id": edge.id,
                    "relation": edge.relation,
                    "actual": f"({src_type}→{tgt_type})",
                    "expected": " | ".join(expected_strs),
                })
        return {
            "check": "edge_direction",
            "status": "PASS" if not wrong_edges else "FAIL",
            "detail": f"checked {checked}, {len(wrong_edges)} wrong",
            "wrong_edges": wrong_edges[:5],
            "suggestion": ("Edge direction error, check _build_from_wide_table() deferred edge resolution"
                           if wrong_edges else ""),
        }

    def check_coculture_context(self) -> dict:
        """Check co-culture edge context marking"""
        coculture_edges = [e for e in self.kg.edges
                           if e.relation in ("USES_FACTOR", "HAS_BIOMARKER")
                           and e.properties.get("context") == "coculture"]
        return {
            "check": "coculture_context",
            "status": "PASS" if coculture_edges else "WARN",
            "detail": f"{len(coculture_edges)} coculture edges found",
            "suggestion": ("No co-culture marked edges, check COCULTURE_COLUMNS config"
                           if not coculture_edges else ""),
        }

    def check_inferred_relations_exist(self) -> dict:
        counts = defaultdict(int)
        for e in self.kg.edges:
            counts[e.relation] += 1
        associated = counts.get("ASSOCIATED_WITH_DISEASE", 0)
        issues = []
        if associated == 0:
            issues.append("ASSOCIATED_WITH_DISEASE=0")
        return {
            "check": "inferred_relations_exist",
            "status": "WARN" if issues else "PASS",
            "detail": f"ASSOCIATED_WITH_DISEASE={associated}",
            "suggestion": (f"Inferred relations missing: {issues}, check INFERRED_RELATIONS config"
                           if issues else ""),
        }

    def check_no_orphan_types(self) -> dict:
        """Each type should have at least one node with edge connections"""
        connected = set()
        for e in self.kg.edges:
            connected.add(e.source)
            connected.add(e.target)
        type_connected = defaultdict(set)
        for nid in connected:
            if nid in self.kg.nodes:
                type_connected[self.kg.nodes[nid].type].add(nid)

        orphans = []
        for ntype in EXPECTED_NODE_TYPES:
            total = sum(1 for n in self.kg.nodes.values() if n.type == ntype)
            conn = len(type_connected.get(ntype, set()))
            if total > 0 and conn == 0:
                orphans.append(ntype)

        return {
            "check": "no_orphan_types",
            "status": "PASS" if not orphans else "FAIL",
            "detail": f"orphan types: {orphans}" if orphans else "all types connected",
            "suggestion": (f"Orphan types {orphans} have no edge connections" if orphans else ""),
        }

    def check_no_duplicate_edges(self) -> dict:
        seen = set()
        dups = 0
        for e in self.kg.edges:
            key = (e.source, e.target, e.relation)
            if key in seen:
                dups += 1
            seen.add(key)
        return {
            "check": "no_duplicate_edges",
            "status": "PASS" if dups == 0 else "WARN",
            "detail": f"{dups} duplicate edges found",
            "suggestion": (f"{dups} duplicate edges, check edge creation logic" if dups > 0 else ""),
        }

    def check_edge_id_uniqueness(self) -> dict:
        ids = [e.id for e in self.kg.edges]
        dup_ids = len(ids) - len(set(ids))
        return {
            "check": "edge_id_uniqueness",
            "status": "PASS" if dup_ids == 0 else "FAIL",
            "detail": f"{dup_ids} duplicate edge IDs",
            "suggestion": (f"{dup_ids} duplicate edge IDs" if dup_ids > 0 else ""),
        }


# =============================================================================
# ReportGenerator
# =============================================================================

class ReportGenerator:
    """Report generator — structure validation reports + user manual"""

    def __init__(self, kg_path: str, structure_results: List[dict],
                 kg: "KnowledgeGraphQuery" = None):
        self.kg_path = kg_path
        self.kg = kg
        self.structure = structure_results
        self.test_time = datetime.now().isoformat()

    def _kg_overview_md(self) -> list:
        """Generate knowledge graph overview Markdown fragment"""
        md = []
        md.append("## KG Overview\n")

        # File size
        file_size_bytes = os.path.getsize(self.kg_path)
        if file_size_bytes >= 1024 * 1024:
            file_size_str = f"{file_size_bytes / (1024 * 1024):.1f} MB"
        else:
            file_size_str = f"{file_size_bytes / 1024:.1f} KB"

        # Basic info
        md.append(f"| Item | Value |")
        md.append(f"|------|------|")
        md.append(f"| KG file | `{os.path.basename(self.kg_path)}` |")
        md.append(f"| File size | {file_size_str} |")

        if self.kg is not None:
            # Node & edge totals
            total_nodes = len(self.kg.nodes)
            total_edges = len(self.kg.edges)
            md.append(f"| Total nodes | {total_nodes:,} |")
            md.append(f"| Total edges | {total_edges:,} |")
            md.append(f"| Node type count | {len(self.kg.meta.get('node_types', []))} |")
            md.append(f"| Relation type count | {len(self.kg.meta.get('relationship_types', []))} |")

            # Node type distribution
            from collections import Counter
            node_type_counts = Counter(n.type for n in self.kg.nodes.values())
            edge_type_counts = Counter(e.relation for e in self.kg.edges)

            md.append("")
            md.append("### Node Type Distribution\n")
            md.append("| Node type | Count |")
            md.append("|----------|------|")
            for ntype in sorted(node_type_counts.keys()):
                md.append(f"| {ntype} | {node_type_counts[ntype]:,} |")

            md.append("")
            md.append("### Relation Type Distribution\n")
            md.append("| Relation type | Count |")
            md.append("|----------|------|")
            for rtype in sorted(edge_type_counts.keys()):
                md.append(f"| {rtype} | {edge_type_counts[rtype]:,} |")
        else:
            # Fallback: extract from structure check result counts field
            node_count_result = next(
                (r for r in self.structure if r.get("check") == "node_counts_positive"), None)
            if node_count_result and "counts" in node_count_result:
                counts = node_count_result["counts"]
                total_from_counts = sum(counts.values())
                md.append(f"| Total nodes | {total_from_counts:,} |")
                md.append("")
                md.append("### Node Type Distribution\n")
                md.append("| Node type | Count |")
                md.append("|----------|------|")
                for ntype in sorted(counts.keys()):
                    md.append(f"| {ntype} | {counts[ntype]:,} |")

        md.append("")
        return md

    @property
    def structure_passed(self):
        return sum(1 for r in self.structure if r["status"] == "PASS")

    @property
    def structure_total(self):
        return len(self.structure)

    @property
    def total_passed(self):
        return self.structure_passed

    @property
    def total_checks(self):
        return self.structure_total

    @property
    def pass_rate(self):
        return self.total_passed / self.total_checks if self.total_checks > 0 else 0.0

    @property
    def health_score(self):
        """Health score 0-100 based on structure checks"""
        return int(self.structure_passed / self.structure_total * 100) if self.structure_total else 0

    def save_json(self, path: str):
        report = {
            "test_time": self.test_time,
            "kg_file": self.kg_path,
            "summary": {
                "total": self.total_checks,
                "passed": self.total_passed,
                "failed": self.total_checks - self.total_passed,
                "pass_rate": round(self.pass_rate, 3),
                "health_score": self.health_score,
                "structure_passed": self.structure_passed,
                "structure_total": self.structure_total,
            },
            "structure_checks": self.structure,
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[OK] JSON report: {path}")

    def save_markdown(self, path: str):
        md = []
        md.append("# Knowledge Graph Structure Validation Report\n")
        md.append(f"**Test time**: {self.test_time}")
        md.append(f"**KG file**: `{self.kg_path}`\n")

        # KG overview
        md.extend(self._kg_overview_md())

        # Summary
        md.append("## Executive Summary\n")
        md.append(f"| Metric | Value |")
        md.append(f"|------|-----|")
        md.append(f"| Total checks | {self.total_checks} |")
        md.append(f"| Passed | {self.total_passed} |")
        md.append(f"| Failed | {self.total_checks - self.total_passed} |")
        md.append(f"| Pass rate | {self.pass_rate:.1%} |")
        md.append(f"| Health score | **{self.health_score}/100** |\n")

        # Structure checks
        md.append("## Structure Check Results\n")
        md.append("| # | Check item | Status | Details |")
        md.append("|---|--------|------|------|")
        for i, r in enumerate(self.structure, 1):
            icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "ERROR": "💥"}.get(r["status"], "?")
            zh_name = STRUCTURE_CHECK_NAMES.get(r["check"], r["check"])
            md.append(f"| {i} | {zh_name} (`{r['check']}`) | {icon} {r['status']} | {r.get('detail', '')} |")

        # Failed structure item details
        failed_struct = [r for r in self.structure if r["status"] in ("FAIL", "ERROR")]
        if failed_struct:
            md.append("\n### Failed Item Details\n")
            for r in failed_struct:
                zh_name = STRUCTURE_CHECK_NAMES.get(r["check"], r["check"])
                md.append(f"**{zh_name} (`{r['check']}`)**")
                md.append(f"- Details: {r.get('detail', '')}")
                if r.get("suggestion"):
                    md.append(f"- Suggestion: {r['suggestion']}")
                md.append("")

        # Fix suggestions
        if failed_struct:
            md.append("\n## Fix Suggestions\n")
            md.append("| Failed item | Suggestion |")
            md.append("|--------|------|")
            for r in failed_struct:
                raw_name = r.get("check", "?")
                name = STRUCTURE_CHECK_NAMES.get(raw_name, raw_name)
                sug = r.get("suggestion", "Check corresponding code logic")
                md.append(f"| {name} | {sug} |")

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(md))
        print(f"[OK] Markdown report: {path}")

    # Node type descriptions
    NODE_TYPE_DESC = {
        "Sample": "Sample record",
        "Organ": "Organ",
        "System": "Physiological system",
        "Organism": "Species",
        "Source": "Tissue/cell source",
        "CellFactor": "Cell factor/growth factor",
        "Technology": "Culture/analysis technology",
        "Drug": "Drug",
        "Gene": "Gene editing target",
        "DiseaseModel": "Disease model",
        "Infection": "Infection/microbial challenge",
        "Biomarker": "Biomarker",
        "Phenotype": "Phenotype",
        "Test": "Detection method",
        "Omics": "Omics data",
        "Composition": "Cell composition profile",
        "Application": "Application direction",
        "Publication": "Publication source",
        "CultureProtocol": "Culture protocol (steps/time/materials)",
        "CultureTechnique": "Culture technique",
        "CultureCondition": "Culture conditions",
        "ApplicationStrategy": "Application strategy",
        "OrganoidProfile": "Organoid descriptive profile",
        "Platform": "Sequencing/detection platform",
        "CoCultureProtocol": "Co-culture protocol",
        "CoCultureTechnique": "Co-culture technique",
        "GroupInfo": "Group-level metadata (GSE_ID cross-reference)",
        "GroupDEGs": "Group-level differentially expressed genes",
        "IntraClusterDEGs": "Intra-cluster differentially expressed genes (scRNA-seq)",
        "ClusterMarkers": "Cluster marker genes (scRNA-seq)",
        "GSVA": "GSVA differentially enriched pathways",
        "GSEA": "GSEA enriched pathways",
        "GeneAnnotation": "Gene annotation (entrez, pfam, STRING, CRISPick, etc.)",
        "MaterialInfo": "Material information (Matrigel, collagen, etc. with catalog/lot/source)",
    }
    # Relationship type descriptions
    RELATION_DESC = {
        # HAS_ORGANOID removed — Organoid node type eliminated
        "FROM_ORGAN": "Sample derived from organ",
        "BELONGS_TO_SYSTEM": "Organ belongs to physiological system",
        "FROM_ORGANISM": "Sample species source",
        "DERIVED_FROM": "Sample tissue source",
        "USES_FACTOR": "Used cell factor",
        "USES_TECHNOLOGY": "Used technology",
        "SCREENS_DRUG": "Screened drug",
        "TARGETS_GENE": "Gene editing target",
        "MODELS_DISEASE": "Modeled disease",
        "HAS_INFECTION": "Infection challenge experiment",
        "HAS_BIOMARKER": "Expressed/detected biomarker",
        "HAS_PHENOTYPE": "Observed phenotype",
        "HAS_TEST": "Detection method used",
        "HAS_OMICS": "Associated omics data",
        "HAS_COMPOSITION": "Cell composition profile",
        "HAS_APPLICATION": "Sample application direction",
        "REPORTED_IN": "Cited publication",
        "ASSOCIATED_WITH_DISEASE": "Drug/Biomarker-disease co-occurrence association (inferred, confidence=0.5)",
        "USES_PROTOCOL": "Culture protocol used",
        "USES_TECHNIQUE": "Culture technique used",
        "HAS_CONDITION": "Culture conditions",
        "HAS_STRATEGY": "Application strategy",
        "HAS_PROFILE": "Sample descriptive profile",
        "USES_PLATFORM": "Omics sequencing platform",
        "USES_COCULTURE_PROTOCOL": "Co-culture protocol used",
        "USES_COCULTURE_TECHNIQUE": "Co-culture technique used",
        "HAS_GROUP_INFO": "Sample has group-level omics metadata",
        "HAS_DEG": "GroupInfo has differentially expressed genes",
        "HAS_INTRACLUSTER_DEG": "GroupInfo has intra-cluster DEGs",
        "HAS_CLUSTER_MARKER": "GroupInfo has cluster marker genes",
        "HAS_GSVA_PATHWAY": "GroupInfo has GSVA pathway",
        "HAS_GSEA_PATHWAY": "GroupInfo has GSEA pathway",
        "HAS_GENE_ANNOTATION": "Gene/marker node has annotation data",
        "HAS_ANNOTATION": "Gene node linked to GeneAnnotation",
        "USES_COMPONENT": "Protocol uses component (growth factor, supplement, medium, small molecule)",
        "USES_MATERIAL": "Protocol uses material (Matrigel, collagen, etc.)",
    }

    def save_manual(self, path: str):
        """Generate user manual (with real statistics)"""
        lines = []
        lines.append("# Organoid Knowledge Graph — User Manual\n")
        lines.append(f"> Data source: MySQL `public_general_2026` table")
        lines.append(f"> Methodology reference: MOF-Chemunity (JACS 2025)")
        lines.append(f"> Generated on: {self.test_time}\n")

        # ---- 1. KG Overview ----
        lines.append("## 1. KG Overview\n")
        lines.append("This knowledge graph is built from the organoid culture database `public_general_2026`, "
                     "extracting structured data from the wide table "
                     f"into **{len(EXPECTED_NODE_TYPES)} node types** and **{len(EXPECTED_RELATION_TYPES)} relationship types**, "
                     "supporting keyword search, graph traversal, inference queries, and LLM GraphRAG Q&A.\n")

        if self.kg is not None:
            total_nodes = len(self.kg.nodes)
            total_edges = len(self.kg.edges)
            from collections import Counter
            ntc = Counter(n.type for n in self.kg.nodes.values())
            etc = Counter(e.relation for e in self.kg.edges)

            lines.append("### 1.1 Core Statistics\n")
            lines.append("| Metric | Value |")
            lines.append("|------|-----|")
            lines.append(f"| Total nodes | {total_nodes:,} |")
            lines.append(f"| Total edges | {total_edges:,} |")
            avg_deg = 2 * total_edges / total_nodes if total_nodes else 0
            lines.append(f"| Average degree | {avg_deg:.2f} |")
            lines.append("")

            lines.append("### 1.2 Node Type Distribution\n")
            lines.append("| Node type | Description | Count |")
            lines.append("|----------|----------|------|")
            for ntype in sorted(ntc.keys()):
                zh = self.NODE_TYPE_DESC.get(ntype, "")
                lines.append(f"| {ntype} | {zh} | {ntc[ntype]:,} |")
            lines.append("")

            lines.append("### 1.3 Relation Type Distribution\n")
            lines.append("| Relation type | Description | Count |")
            lines.append("|----------|----------|------|")
            for rtype in sorted(etc.keys()):
                zh = self.RELATION_DESC.get(rtype, "")
                lines.append(f"| {rtype} | {zh} | {etc[rtype]:,} |")
            lines.append("")
        else:
            lines.append(f"### Node types: {', '.join(sorted(EXPECTED_NODE_TYPES))}\n")
            lines.append(f"### Relation types: {', '.join(sorted(EXPECTED_RELATION_TYPES))}\n")

        # ---- 2. Quick Start ----
        lines.append("## 2. Quick Start\n")
        lines.append("### 2.1 Build Knowledge Graph\n")
        lines.append("```bash")
        lines.append("# Explore database structure")
        lines.append("python scripts/build_kg.py --host localhost --database organoid_db --user root --password xxx --explore")
        lines.append("")
        lines.append("# Build knowledge graph")
        lines.append("python scripts/build_kg.py --host localhost --database organoid_db --user root --password xxx --output-dir ./organoid-kg-output")
        lines.append("```\n")

        lines.append("### 2.2 Query the Graph\n")
        lines.append("```bash")
        lines.append("# Graph statistics")
        lines.append(f"python scripts/query_tool.py --graph {self.kg_path} --stats")
        lines.append("")
        lines.append("# Keyword search")
        lines.append(f"python scripts/query_tool.py --graph {self.kg_path} --search \"intestinal organoid\"")
        lines.append("")
        lines.append("# View subgraph")
        lines.append(f"python scripts/query_tool.py --graph {self.kg_path} --subgraph smp_XXXXX")
        lines.append("")
        lines.append("# Interactive GraphRAG Q&A")
        lines.append(f"python scripts/query_tool.py --graph {self.kg_path} --api-key sk-xxx --interactive")
        lines.append("```\n")

        lines.append("### 2.3 Validate Graph Quality\n")
        lines.append("```bash")
        lines.append("python scripts/validate_kg.py   # Auto-detect latest build output")
        lines.append("```\n")

        lines.append("### 2.4 Python API Usage\n")
        lines.append("```python")
        lines.append("from query_tool import KnowledgeGraphQuery")
        lines.append(f"kg = KnowledgeGraphQuery.load(\"{self.kg_path}\")")
        lines.append("results = kg.search(\"intestinal organoid\", top_k=10)")
        lines.append("subgraph = kg.traverse(\"smp_0000001\", depth=2)")
        lines.append("answer = kg.ask(\"Which media contain EGF?\", api_key=\"sk-xxx\", model=\"gpt-4o\")")
        lines.append("```\n")

        # ---- 3. Schema Overview ----
        lines.append("## 3. Schema Overview\n")
        lines.append(f"This knowledge graph contains **{len(EXPECTED_NODE_TYPES)} node types** "
                     f"and **{len(EXPECTED_RELATION_TYPES)} relationship types**.\n")

        lines.append("### 3.1 Node Types\n")
        lines.append("| Node type | ID prefix | Description |")
        lines.append("|----------|----------|------|")
        for ntype in sorted(EXPECTED_NODE_TYPES):
            prefix_map = {
                "Sample": "smp_", "Organ": "orn_", "System": "sys_", "Organism": "osm_",
                "Source": "src_", "CellFactor": "cf_", "Technology": "tec_", "Drug": "drg_",
                "Gene": "gen_", "DiseaseModel": "dm_", "Infection": "inf_",
                "Biomarker": "bmk_", "Phenotype": "phn_", "Test": "tst_",
                "Omics": "omc_", "Composition": "cmp_", "Application": "app_",
                "Publication": "pub_", "CultureProtocol": "cpr_", "CultureTechnique": "cte_",
                "CultureCondition": "ccn_", "ApplicationStrategy": "ast_",
                "OrganoidProfile": "opr_", "Platform": "pla_",
                "CoCultureProtocol": "ccp_", "CoCultureTechnique": "cct_",
                "GroupInfo": "gin_", "GroupDEGs": "gde_", "IntraClusterDEGs": "icd_",
                "ClusterMarkers": "clm_", "GSVA": "gsv_", "GSEA": "gse_",
                "GeneAnnotation": "gan_", "MaterialInfo": "mat_",
            }
            desc = self.NODE_TYPE_DESC.get(ntype, "")
            prefix = prefix_map.get(ntype, "?")
            lines.append(f"| {ntype} | `{prefix}` | {desc} |")
        lines.append("")

        lines.append("### 3.2 Relationship Types\n")
        lines.append("| Relation | Direction | Description |")
        lines.append("|----------|----------|------|")
        for rtype in sorted(EXPECTED_RELATION_TYPES):
            dirs = EXPECTED_EDGE_DIRECTION.get(rtype, [("?", "?")])
            dir_str = " | ".join(f"{s}→{t}" for s, t in dirs)
            desc = self.RELATION_DESC.get(rtype, "")
            lines.append(f"| {rtype} | {dir_str} | {desc} |")
        lines.append("")
        lines.append("## 4. Node ID System\n")
        lines.append("| Prefix | Node type | Example |")
        lines.append("|------|---------|------|")
        id_table = [
            ("smp_", "Sample"), ("orn_", "Organ"),
            ("sys_", "System"), ("osm_", "Organism"), ("src_", "Source"),
            ("cf_", "CellFactor"), ("tec_", "Technology"), ("drg_", "Drug"),
            ("gen_", "Gene"), ("dm_", "DiseaseModel"), ("inf_", "Infection"),
            ("bmk_", "Biomarker"), ("phn_", "Phenotype"), ("tst_", "Test"),
            ("omc_", "Omics"), ("cmp_", "Composition"), ("app_", "Application"),
            ("pub_", "Publication"),
            ("cpr_", "CultureProtocol"), ("cte_", "CultureTechnique"),
            ("ccn_", "CultureCondition"),
            ("ast_", "ApplicationStrategy"), ("opr_", "OrganoidProfile"),
            ("pla_", "Platform"),
            ("ccp_", "CoCultureProtocol"), ("cct_", "CoCultureTechnique"),
            ("gin_", "GroupInfo"),
            ("gde_", "GroupDEGs"), ("icd_", "IntraClusterDEGs"),
            ("clm_", "ClusterMarkers"), ("gsv_", "GSVA"), ("gse_", "GSEA"),
            ("gan_", "GeneAnnotation"), ("mat_", "MaterialInfo"),
        ]
        for prefix, ntype in id_table:
            lines.append(f"| `{prefix}` | {ntype} ({self.NODE_TYPE_DESC.get(ntype, '')}) | `{prefix}xxxx` |")
        lines.append("")

        # ---- 5. Query Tips ----
        lines.append("## 5. Query Tips\n")
        lines.append("- **Precise type filtering**: `kg.search(\"Cisplatin\", node_type=\"Drug\")` searches only Drug nodes")
        lines.append("- **Deep traversal**: Increase `depth` parameter to expand subgraph scope; note that high depth may cause excessively large subgraphs")
        lines.append("- **Path finding**: `kg.find_paths(\"smp_A\", \"drg_B\")` discovers all relationship paths between two nodes")
        lines.append("- **Combined queries**: Use `search()` to find seed nodes, then `traverse()` to expand subgraph, finally filter on the subgraph")
        lines.append("- **Inferred relations**: `ASSOCIATED_WITH_DISEASE` is based on co-occurrence inference; confidence is in edge properties")
        lines.append("- **Co-culture distinction**: Differentiate via edge property `context` (`\"primary\"` vs `\"coculture\"`)")
        lines.append("- **Batch queries**: Load KG once and call `search()` / `traverse()` multiple times to avoid repeated file loading\n")

        # ---- 6. Known Limitations ----
        lines.append("## 6. Known Limitations\n")
        lines.append("1. Culture protocols/techniques/conditions are extracted as independent nodes (CultureProtocol, CultureTechnique, CultureCondition); culture_days and endpoints are merged into CultureProtocol, eliminating the former CultureMetrics node")
        lines.append("2. Co-culture data has dedicated node types (CoCultureProtocol, CoCultureTechnique) parallel to primary culture; shared entity types (CellFactor, Biomarker) still use edge `context` markers")
        lines.append("3. Inferred relations (ASSOCIATED_WITH_DISEASE) are based on co-occurrence statistics and do not represent causality")
        lines.append("4. JSON column entity extraction depends on the key name list in `_extract_entity_name()`; uncovered key names may miss entities")
        lines.append("5. GroupInfo sub-nodes (GroupDEGs/IntraClusterDEGs/ClusterMarkers/GSVA/GSEA) are cross-referenced from public_GDS_omics → public_search_pathway → sub-tables via GSE_ID")
        lines.append("6. GeneAnnotation nodes enrich DEG/marker symbols with species-specific annotation data (gene_annotation, site, disease, STRING, CRISPick tables)")
        lines.append("7. Currently only processes the `public_general_2026` single table plus sub-tables; if there are other related tables, `build_kg.py` needs to be extended")
        lines.append("8. Uses JSON + SQLite file storage, no graph database required, suitable for standalone distribution but limited performance for very large subgraph traversal\n")

        # ---- 7. References ----
        lines.append("## 7. References\n")
        lines.append("1. Pruyn, T. M. et al. MOF-Chemunity. *J. Am. Chem. Soc.* **2025**, *147*, 43474-43486.")
        lines.append("2. MOF-Chemunity open source code: https://github.com/AI4ChemS/MOF_ChemUnity")
        lines.append("3. Schema design document: `docs/schema_design.md`")
        lines.append("4. Complete tutorial: `build_tutorial.md`\n")

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[OK] User manual: {path}")

# =============================================================================
# Main
# =============================================================================

def _find_latest_kg(kg_dir: str) -> Optional[str]:
    """Find organoid_kg.json in the latest timestamp subdirectory under kg_dir

    Scan subdirectories under kg_dir, directory name format is YYYY-MM-DD-HHMM,
    returns the organoid_kg.json path in the latest (lexicographically largest) subdirectory.
    Returns None if not found.
    """
    if not os.path.isdir(kg_dir):
        return None

    candidates = []
    for entry in os.listdir(kg_dir):
        subdir = os.path.join(kg_dir, entry)
        if not os.path.isdir(subdir):
            continue
        kg_file = os.path.join(subdir, "organoid_kg.json")
        if os.path.isfile(kg_file):
            candidates.append((entry, kg_file))

    if not candidates:
        return None

    # Take the lexicographically largest directory name (timestamp format guarantees lexicographic order = chronological order)
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def main():
    parser = argparse.ArgumentParser(
        description="Validate organoid knowledge graph structure and generate reports")
    parser.add_argument("kg_file", nargs="?", default=None,
                        help="Path to organoid_kg.json (auto-detect latest if omitted)")
    parser.add_argument("--kg-dir", default="./organoid-kg-output",
                        help="Directory to scan for latest KG build (default: ./organoid-kg-output)")
    parser.add_argument("--output-dir", default="./kg_test_output",
                        help="Output directory for reports (default: ./kg_test_output)")
    parser.add_argument("--gen-manual", action="store_true",
                        help="Only generate user manual from schema definitions (no KG needed)")
    args = parser.parse_args()

    # Auto-detect latest KG file
    if not args.gen_manual:
        if args.kg_file is None:
            args.kg_file = _find_latest_kg(args.kg_dir)
            if args.kg_file is None:
                print(f"[ERROR] No organoid_kg.json found under {args.kg_dir}/<timestamp>/")
                print(f"        Run build_kg.py first, or specify a KG file path explicitly.")
                sys.exit(1)
            print(f"[INFO] Auto-detected latest KG: {args.kg_file}")

        if not os.path.exists(args.kg_file):
            print(f"[ERROR] File not found: {args.kg_file}")
            sys.exit(1)

    output_dir = args.output_dir
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    report_subdir = os.path.join(output_dir, timestamp)

    # --gen-manual: generate user manual from schema definitions only (no KG needed)
    if args.gen_manual:
        print(f"\n[Generate] Creating user manual from schema definitions...")
        gen = ReportGenerator("N/A", [], kg=None)
        gen.save_manual(os.path.join(output_dir, "user_manual.md"))
        return

    print(f"\n{'='*60}")
    print(f"  KG file:     {args.kg_file}")
    print(f"  Output dir:  {output_dir}")
    print(f"{'='*60}")

    kg = KnowledgeGraphQuery.load(args.kg_file)
    print(f"  Loaded {len(kg.nodes)} nodes, {len(kg.edges)} edges")

    # Structure validation
    print(f"\n[Phase 1] Structure Validation...")
    validator = StructureValidator(kg)
    structure_results = validator.run_all()
    for r in structure_results:
        icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]", "ERROR": "[ERR ]"}.get(r["status"], "[????]")
        print(f"  {icon} {r['check']}: {r.get('detail', '')}")

    # Generate reports
    print(f"\n[Phase 2] Generating reports...")
    gen = ReportGenerator(args.kg_file, structure_results, kg=kg)

    gen.save_json(os.path.join(report_subdir, "test_report.json"))
    gen.save_markdown(os.path.join(report_subdir, "test_report.md"))
    gen.save_manual(os.path.join(output_dir, "user_manual.md"))

    print(f"\n{'='*60}")
    print(f"  Summary")
    print(f"{'='*60}")
    print(f"  Structure: {gen.structure_passed}/{gen.structure_total} passed")
    print(f"  Overall:   {gen.total_passed}/{gen.total_checks} ({gen.pass_rate:.1%})")
    print(f"  Health:    {gen.health_score}/100")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
