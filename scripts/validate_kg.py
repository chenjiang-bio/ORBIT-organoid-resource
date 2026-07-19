#!/usr/bin/env python3
"""
validate_kg.py — Knowledge graph validation & query simulation testing & report generation

Usage:
  python validate_kg.py                                    # Auto-detect latest KG build result
  python validate_kg.py organoid-kg-output/2026-07-18-1430/organoid_kg.json
  python validate_kg.py --structure-only
  python validate_kg.py --query-only
  python validate_kg.py --gen-manual

Output:
  kg_test_output/YYYY-MM-DD-HHMM/test_report.json  — Structured test results
  kg_test_output/YYYY-MM-DD-HHMM/test_report.md    — Human-readable test report
  kg_test_output/user_manual.md                    — User manual
"""

import json
import os
import sys
import time
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
    "Sample", "Organoid", "Organ", "System", "Organism", "Source",
    "CellFactor", "Technology", "Drug", "Gene",
    "DiseaseModel", "Infection", "Biomarker", "Phenotype",
    "Omics", "Composition", "Application", "Publication",
}

EXPECTED_RELATION_TYPES = {
    "HAS_ORGANOID", "FROM_ORGAN", "BELONGS_TO_SYSTEM", "FROM_ORGANISM",
    "DERIVED_FROM", "USES_FACTOR", "USES_TECHNOLOGY", "SCREENS_DRUG",
    "HAS_GENE_EDIT", "MODELS_DISEASE", "HAS_INFECTION", "HAS_BIOMARKER",
    "HAS_PHENOTYPE", "HAS_OMICS", "HAS_COMPOSITION",
    "HAS_APPLICATION", "CITES", "TREATS_DISEASE", "INDICATES_DISEASE",
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
    "HAS_ORGANOID":        ("Sample",    "Organoid"),
    "FROM_ORGAN":          ("Organoid",  "Organ"),
    "BELONGS_TO_SYSTEM":   ("Organ",     "System"),
    "FROM_ORGANISM":       ("Sample",    "Organism"),
    "DERIVED_FROM":        ("Organoid",  "Source"),
    "USES_FACTOR":         ("Sample",    "CellFactor"),
    "USES_TECHNOLOGY":     ("Sample",    "Technology"),
    "SCREENS_DRUG":        ("Sample",    "Drug"),
    "HAS_GENE_EDIT":       ("Sample",    "Gene"),
    "MODELS_DISEASE":      ("Organoid",  "DiseaseModel"),
    "HAS_INFECTION":       ("Sample",    "Infection"),
    "HAS_BIOMARKER":       ("Sample",    "Biomarker"),
    "HAS_PHENOTYPE":       ("Sample",    "Phenotype"),
    "HAS_OMICS":           ("Sample",    "Omics"),
    "HAS_COMPOSITION":     ("Sample",    "Composition"),
    "HAS_APPLICATION":     ("Organoid",  "Application"),
    "CITES":               ("Sample",    "Publication"),
    "TREATS_DISEASE":      ("Drug",      "DiseaseModel"),
    "INDICATES_DISEASE":   ("Biomarker", "DiseaseModel"),
}


# =============================================================================
# Test Case Definitions (30 tests)
# =============================================================================

class TestCase:
    """Single query test"""
    def __init__(self, test_id: int, question: str, keywords: str,
                 expected_types: List[str], expected_relations: List[str],
                 max_hops: int = 2, min_results: int = 1,
                 category: str = "single_hop"):
        self.id = test_id
        self.question = question
        self.keywords = keywords
        self.expected_types = expected_types
        self.expected_relations = expected_relations
        self.max_hops = max_hops
        self.min_results = min_results
        self.category = category


TEST_CASES = [
    # ===== Single-hop: Sample → Entity (12) =====
    TestCase(1,  "Which samples cultured intestinal organoids?",
             "intestinal organoid", ["Sample", "Organoid"], ["HAS_ORGANOID"]),
    TestCase(2,  "Which samples are from human?",
             "Human", ["Sample", "Organism"], ["FROM_ORGANISM"]),
    TestCase(3,  "Which samples are from mouse?",
             "Mouse", ["Sample", "Organism"], ["FROM_ORGANISM"]),
    TestCase(4,  "Which samples used EGF factor?",
             "EGF", ["Sample", "CellFactor"], ["USES_FACTOR"]),
    TestCase(5,  "Which samples used Wnt factor?",
             "Wnt", ["Sample", "CellFactor"], ["USES_FACTOR"]),
    TestCase(6,  "Which samples used CRISPR technology?",
             "CRISPR", ["Sample", "Technology"], ["USES_TECHNOLOGY"]),
    TestCase(7,  "Which samples screened Cisplatin?",
             "Cisplatin", ["Sample", "Drug"], ["SCREENS_DRUG"]),
    TestCase(8,  "Which samples involve APC gene?",
             "APC", ["Sample", "Gene"], ["HAS_GENE_EDIT"]),
    TestCase(9,  "Which samples involve H1N1 influenza infection?",
             "H1N1 influenza", ["Sample", "Infection"], ["HAS_INFECTION"]),
    TestCase(10, "Which samples involve SARS-CoV-2 or COVID?",
             "SARS-CoV-2 COVID", ["Sample", "Infection"], ["HAS_INFECTION"], min_results=0),
    TestCase(11, "Which samples express Lgr5 marker?",
             "Lgr5", ["Sample", "Biomarker"], ["HAS_BIOMARKER"]),
    TestCase(12, "Which samples express Ki67 marker?",
             "Ki67", ["Sample", "Biomarker"], ["HAS_BIOMARKER"]),

    # ===== Single-hop: Phenotype / Omics / Composition (4) =====
    TestCase(13, "Which samples show specific phenotypes?",
             "phenotype morphology", ["Sample", "Phenotype"], ["HAS_PHENOTYPE"]),
    TestCase(14, "Which samples have scRNA-seq data?",
             "scRNA-seq", ["Sample", "Omics"], ["HAS_OMICS"]),
    TestCase(15, "Which samples have bulk RNA-seq data?",
             "RNA-seq transcriptome", ["Sample", "Omics"], ["HAS_OMICS"]),
    TestCase(16, "Which samples contain Matrigel?",
             "Matrigel", ["Sample", "Composition"], ["HAS_COMPOSITION"]),

    # ===== Multi-hop: Organoid → Organ → System (6) =====
    TestCase(17, "What liver organoids exist?",
             "Liver hepatic", ["Organ", "Organoid"], ["FROM_ORGAN"], max_hops=2),
    TestCase(18, "What intestinal organoids exist?",
             "intestine intestinal colon", ["Organ", "Organoid"],
             ["FROM_ORGAN"], max_hops=2),
    TestCase(19, "What brain organoids exist?",
             "brain cerebral", ["Organ", "Organoid"],
             ["FROM_ORGAN"], max_hops=2, min_results=0),
    TestCase(20, "Which organoids belong to the digestive system?",
             "Digestive", ["System", "Organ", "Organoid"],
             ["BELONGS_TO_SYSTEM", "FROM_ORGAN"], max_hops=3),
    TestCase(21, "What tissues are liver organoids derived from?",
             "Liver source tissue", ["Organoid", "Organ", "Source"],
             ["FROM_ORGAN", "DERIVED_FROM"], max_hops=3),
    TestCase(22, "What applications do organoids have?",
             "application", ["Organoid", "Application"],
             ["HAS_APPLICATION"], max_hops=2),

    # ===== Inferred relationships (2) =====
    TestCase(23, "What drugs are associated with diseases?",
             "drug disease", ["Drug", "DiseaseModel"],
             ["TREATS_DISEASE"], min_results=0),
    TestCase(24, "What biomarkers are associated with diseases?",
             "biomarker disease", ["Biomarker", "DiseaseModel"],
             ["INDICATES_DISEASE"], min_results=0),

    # ===== Co-culture / Disease model / Publication (6) =====
    TestCase(25, "What cell factors are used in co-culture?",
             "coculture factor", ["Sample", "CellFactor"],
             ["USES_FACTOR"]),
    TestCase(26, "Which samples involve disease modeling?",
             "disease model cancer tumor", ["Sample", "DiseaseModel"],
             ["MODELS_DISEASE"], max_hops=2),
    TestCase(27, "What tumor organoid disease models exist?",
             "tumor cancer organoid", ["Organoid", "DiseaseModel"],
             ["MODELS_DISEASE", "HAS_ORGANOID"], max_hops=2, min_results=0),
    TestCase(28, "What publications do samples cite?",
             "10.", ["Sample", "Publication"], ["CITES"]),
    TestCase(29, "Cross-query: organoid drug screening and disease models?",
             "organoid drug disease", ["Sample", "Organoid", "Drug", "DiseaseModel"],
             ["HAS_ORGANOID", "SCREENS_DRUG", "MODELS_DISEASE"], max_hops=3),
    TestCase(30, "Which airway organoids have infection models?",
             "airway lung respiratory infection", ["Sample", "Organ", "Infection"],
             ["FROM_ORGAN", "HAS_INFECTION"], max_hops=3),
]


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
        """Sample check edge direction"""
        type_map = {nid: n.type for nid, n in self.kg.nodes.items()}
        wrong_edges = []
        checked = 0
        for edge in self.kg.edges:
            expected = EXPECTED_EDGE_DIRECTION.get(edge.relation)
            if not expected:
                continue
            src_type = type_map.get(edge.source, "?")
            tgt_type = type_map.get(edge.target, "?")
            checked += 1
            if src_type != expected[0] or tgt_type != expected[1]:
                wrong_edges.append({
                    "edge_id": edge.id,
                    "relation": edge.relation,
                    "actual": f"({src_type}→{tgt_type})",
                    "expected": f"({expected[0]}→{expected[1]})",
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
        treats = counts.get("TREATS_DISEASE", 0)
        indicates = counts.get("INDICATES_DISEASE", 0)
        issues = []
        if treats == 0:
            issues.append("TREATS_DISEASE=0")
        if indicates == 0:
            issues.append("INDICATES_DISEASE=0")
        return {
            "check": "inferred_relations_exist",
            "status": "WARN" if issues else "PASS",
            "detail": f"TREATS_DISEASE={treats}, INDICATES_DISEASE={indicates}",
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
# QueryTester
# =============================================================================

class QueryTester:
    """Query simulation testing

    For each question, execute search() → traverse() to check if expected types/relations are hit.
    If LLM config is provided, additionally call kg.ask() to generate readable answers and store in report.
    """

    def __init__(self, kg: KnowledgeGraphQuery,
                 api_key: str = None, base_url: str = None, model: str = None):
        self.kg = kg
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.results: List[dict] = []

    def run_all(self) -> List[dict]:
        for tc in TEST_CASES:
            start = time.time()
            try:
                result = self._run_one(tc)
            except Exception as e:
                result = {
                    "id": tc.id, "question": tc.question,
                    "status": "ERROR", "reason": str(e),
                }
            result["duration_ms"] = int((time.time() - start) * 1000)
            self.results.append(result)
        return self.results

    def _run_one(self, tc: TestCase) -> dict:
        # Step 1: Keyword search
        search_results = self.kg.search(tc.keywords, top_k=20)
        search_types = set()
        for node, score in search_results:
            search_types.add(node.type)

        search_passed = bool(search_results)

        # Collect summary of top 5 hit nodes
        search_preview = []
        for node, score in search_results[:5]:
            name = node.properties.get("name", node.properties.get("sample_id", node.id))
            # Truncate overly long names
            name_str = str(name)
            if len(name_str) > 60:
                name_str = name_str[:57] + "..."
            search_preview.append(f"[{node.type}]{name_str}")
        search_preview_str = ", ".join(search_preview)

        # Step 2: Graph traversal from hit nodes
        subgraph_nodes = set()
        subgraph_edges = set()
        relation_types = set()
        for node, _ in search_results[:5]:
            sub = self.kg.traverse(node.id, depth=tc.max_hops)
            for n in sub["nodes"]:
                subgraph_nodes.add(n.id)
            for e in sub["edges"]:
                subgraph_edges.add(e.id)
                relation_types.add(e.relation)

        # Step 3: Check if expected types are hit
        subgraph_node_types = set()
        for nid in subgraph_nodes:
            if nid in self.kg.nodes:
                subgraph_node_types.add(self.kg.nodes[nid].type)

        types_found = [t for t in tc.expected_types if t in search_types or t in subgraph_node_types]
        types_missing = [t for t in tc.expected_types if t not in search_types and t not in subgraph_node_types]
        types_passed = len(types_missing) == 0

        # Step 4: Check if expected relations exist
        rels_found = [r for r in tc.expected_relations if r in relation_types]
        rels_missing = [r for r in tc.expected_relations if r not in relation_types]
        rels_passed = len(rels_missing) == 0

        # Step 5: Check minimum hit count
        count_passed = len(search_results) >= tc.min_results

        overall = "PASS" if (search_passed and types_passed and rels_passed and count_passed) else "FAIL"
        if tc.min_results == 0 and not rels_passed:
            overall = "WARN"

        reasons = []
        if not search_passed:
            reasons.append(f"No hits for '{tc.keywords}'")
        if not types_passed:
            reasons.append(f"Expected types not found: {types_missing}")
        if not rels_passed:
            reasons.append(f"Expected relations not found: {rels_missing}")
        if not count_passed:
            reasons.append(f"Hits {len(search_results)} < expected {tc.min_results}")

        # Build subgraph object (for LLM context reuse)
        subgraph_obj = {
            "nodes": [self.kg.nodes[nid] for nid in subgraph_nodes if nid in self.kg.nodes],
            "edges": [e for e in self.kg.edges if e.id in subgraph_edges]
        }

        result = {
            "id": tc.id,
            "question": tc.question,
            "category": tc.category,
            "status": overall,
            "keywords": tc.keywords,
            "search_hits": len(search_results),
            "search_preview": search_preview_str,
            "search_types_found": list(search_types),
            "subgraph_nodes": len(subgraph_nodes),
            "subgraph_edges": len(subgraph_edges),
            "expected_types_found": types_found,
            "expected_types_missing": types_missing,
            "expected_relations_found": rels_found,
            "expected_relations_missing": rels_missing,
            "reason": "; ".join(reasons) if reasons else "",
            "suggestion": self._suggest(types_missing, rels_missing),
        }

        # Step 6 (optional): LLM-readable answer — reuse existing search_results & subgraph
        if self.api_key and search_passed and overall != "ERROR":
            llm_result = self._ask_llm_for_result(tc, search_results, subgraph_obj)
            if llm_result:
                result["llm_answer"] = llm_result

        return result

    def _ask_llm_for_result(self, tc: TestCase,
                            seed_results: list, subgraph: dict) -> Optional[str]:
        """Reuse existing search_results and subgraph, directly construct context to call LLM.

        Avoid duplicating the full search + traverse inside kg.ask().
        Add 30s timeout to prevent API hang blocking the entire validation process.
        """
        try:
            # Format with sample-centric context
            from query_tool import KnowledgeGraphQuery
            kg_q = self.kg
            context = kg_q._build_sample_context(seed_results, subgraph, max_samples=5)
            prompt = kg_q.PROMPT_TEMPLATE.format(context=context, question=tc.question)

            # Set 30 second timeout
            from openai import OpenAI
            api_key = self.api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
            client_kwargs = {"api_key": api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            client = OpenAI(**client_kwargs)

            response = client.chat.completions.create(
                model=self.model or "gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a scientific assistant. Answer concisely."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=500,
                timeout=30,  # 30 second timeout
            )
            answer = response.choices[0].message.content
            if not answer:
                return None
            # Take first 300 characters as report summary
            if len(answer) > 300:
                answer = answer[:297] + "..."
            return answer
        except Exception:
            return None

    @staticmethod
    def _suggest(types_missing: list, rels_missing: list) -> str:
        suggestions = []
        if types_missing:
            suggestions.append(f"Types {types_missing} missing: check MySQL column data or WIDE_TABLE_ENTITY_MAPPING")
        if rels_missing:
            for r in rels_missing:
                if r in ("TREATS_DISEASE", "INDICATES_DISEASE"):
                    suggestions.append(f"{r} missing: check INFERRED_RELATIONS and co-occurrence data")
                else:
                    suggestions.append(f"{r} missing: check WIDE_TABLE_ENTITY_MAPPING config")
        return "; ".join(suggestions)


# =============================================================================
# ReportGenerator
# =============================================================================

class ReportGenerator:
    """Report generator"""

    def __init__(self, kg_path: str, structure_results: List[dict],
                 query_results: List[dict], kg: "KnowledgeGraphQuery" = None):
        self.kg_path = kg_path
        self.kg = kg
        self.structure = structure_results
        self.queries = query_results
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
    def query_passed(self):
        return sum(1 for r in self.queries if r["status"] == "PASS")

    @property
    def query_total(self):
        return len(self.queries)

    @property
    def total_passed(self):
        return self.structure_passed + self.query_passed

    @property
    def total_checks(self):
        return self.structure_total + self.query_total

    @property
    def pass_rate(self):
        return self.total_passed / self.total_checks if self.total_checks > 0 else 0.0

    @property
    def health_score(self):
        """Comprehensive health score 0-100"""
        struct_score = (self.structure_passed / self.structure_total * 50) if self.structure_total else 0
        query_score = (self.query_passed / self.query_total * 50) if self.query_total else 0
        return int(struct_score + query_score)

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
                "query_passed": self.query_passed,
                "query_total": self.query_total,
            },
            "structure_checks": self.structure,
            "query_tests": self.queries,
            "coverage": self._build_coverage(),
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[OK] JSON report: {path}")

    def save_markdown(self, path: str):
        md = []
        md.append("# Knowledge Graph Validation Test Report\n")
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

        # Query tests
        md.append("## Query Test Results\n")

        def _subgraph_scale(r: dict) -> str:
            """Subgraph scale: nodes / edges"""
            sn = r.get("subgraph_nodes", 0)
            se = r.get("subgraph_edges", 0)
            return f"{sn}n / {se}e"

        has_llm = any(r.get("llm_answer") for r in self.queries)
        if has_llm:
            md.append("| # | Question | Status | Subgraph scale | LLM answer (summary) | Missing types | Missing relations |")
            md.append("|---|------|------|----------|------------------|----------|----------|")
            for r in self.queries:
                icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "ERROR": "💥"}.get(r["status"], "?")
                types_missing = ", ".join(r.get("expected_types_missing", [])) or "—"
                rels_missing = ", ".join(r.get("expected_relations_missing", [])) or "—"
                answer = r.get("llm_answer") or r.get("search_preview", "—")
                if len(answer) > 200:
                    answer = answer[:197] + "..."
                answer = answer.replace("|", "\\|").replace("\n", " ")
                md.append(f"| {r['id']} | {r['question'][:30]} | {icon} | {_subgraph_scale(r)} | {answer} | {types_missing} | {rels_missing} |")
        else:
            md.append("| # | Question | Status | Subgraph scale | Search hits | Missing types | Missing relations |")
            md.append("|---|------|------|----------|----------|----------|----------|")
            for r in self.queries:
                icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "ERROR": "💥"}.get(r["status"], "?")
                types_missing = ", ".join(r.get("expected_types_missing", [])) or "—"
                rels_missing = ", ".join(r.get("expected_relations_missing", [])) or "—"
                preview = r.get("search_preview", "—")
                if len(preview) > 200:
                    preview = preview[:197] + "..."
                md.append(f"| {r['id']} | {r['question'][:30]} | {icon} | {_subgraph_scale(r)} | {preview} | {types_missing} | {rels_missing} |")

        # Failed query details
        failed_queries = [r for r in self.queries if r["status"] in ("FAIL", "ERROR")]
        if failed_queries:
            md.append("\n### Failed Query Details\n")
            for r in failed_queries:
                md.append(f"**#{r['id']} {r['question']}**")
                md.append(f"- Keywords: `{r.get('keywords', '')}`")
                md.append(f"- Search hits: {r.get('search_hits', 0)}")
                md.append(f"- Reason: {r.get('reason', '')}")
                if r.get("suggestion"):
                    md.append(f"- Suggestion: {r['suggestion']}")
                md.append("")

        # Coverage
        md.append("## Coverage Analysis\n")
        cov = self._build_coverage()
        md.append(f"- Node type test coverage: {len(cov['node_types_tested'])}/{len(EXPECTED_NODE_TYPES)}")
        md.append(f"- Relation type test coverage: {len(cov['relation_types_tested'])}/{len(EXPECTED_RELATION_TYPES)}")
        if cov.get("untested_nodes"):
            md.append(f"- Untested node types: {', '.join(cov['untested_nodes'])}")
        if cov.get("untested_relations"):
            md.append(f"- Untested relation types: {', '.join(cov['untested_relations'])}")

        # Fix suggestions
        all_failed = failed_struct + failed_queries
        if all_failed:
            md.append("\n## Fix Suggestions\n")
            md.append("| Failed item | Suggestion |")
            md.append("|--------|------|")
            for r in all_failed:
                raw_name = r.get("check", f"Query #{r.get('id', '?')}")
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
        "Organoid": "Organoid",
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
        "Omics": "Omics data",
        "Composition": "Cell composition profile",
        "Application": "Application direction",
        "Publication": "Publication source",
    }
    # Relationship type descriptions
    RELATION_DESC = {
        "HAS_ORGANOID": "Sample cultured organoid",
        "FROM_ORGAN": "Organoid derived from organ",
        "BELONGS_TO_SYSTEM": "Organ belongs to physiological system",
        "FROM_ORGANISM": "Sample species source",
        "DERIVED_FROM": "Organoid tissue source",
        "USES_FACTOR": "Used cell factor",
        "USES_TECHNOLOGY": "Used technology",
        "SCREENS_DRUG": "Screened drug",
        "HAS_GENE_EDIT": "Gene editing",
        "MODELS_DISEASE": "Modeled disease",
        "HAS_INFECTION": "Infection challenge experiment",
        "HAS_BIOMARKER": "Expressed/detected biomarker",
        "HAS_PHENOTYPE": "Observed phenotype",
        "HAS_OMICS": "Associated omics data",
        "HAS_COMPOSITION": "Cell composition profile",
        "HAS_APPLICATION": "Organoid application direction",
        "CITES": "Cited publication",
        "TREATS_DISEASE": "Drug-disease association (inferred)",
        "INDICATES_DISEASE": "Biomarker-disease association (inferred)",
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

        # ---- 3. Query Guide (deduplicated typical questions) ----
        lines.append("## 3. Query Guide\n")
        lines.append("The following lists typical questions and query methods categorized by query scenario.\n")

        # Deduplication: deduplicate by question text, take top 3 per category
        seen_questions = set()
        unique_queries = []
        for q in self.queries:
            if q["question"] not in seen_questions:
                seen_questions.add(q["question"])
                unique_queries.append(q)

        # Query scenario grouping (more precise matching logic)
        scene_groups = [
            ("Query by sample", ["Sample"]),
            ("Query by organoid/organ/system", ["Organoid", "Organ", "System"]),
            ("Query by species/source", ["Organism", "Source"]),
            ("Query by cell factor", ["CellFactor"]),
            ("Query by technology/gene editing", ["Technology", "Gene"]),
            ("Query by drug screening", ["Drug"]),
            ("Query by disease model", ["DiseaseModel"]),
            ("Query by infection model", ["Infection"]),
            ("Query by biomarker", ["Biomarker"]),
            ("Query by phenotype/omics/composition", ["Phenotype", "Omics", "Composition"]),
            ("Query by application/publication", ["Application", "Publication"]),
        ]

        for section, types in scene_groups:
            # Find queries matching expected types (after dedup)
            relevant = [q for q in unique_queries
                        if any(t in q.get("expected_types", []) for t in types)]
            if not relevant:
                # Fallback to found type matching
                relevant = [q for q in unique_queries
                            if any(t in str(q.get("expected_types_found", [])) for t in types)]

            lines.append(f"### {section}\n")
            for q in relevant[:3]:
                lines.append(f"**Q: {q['question']}**")
                lines.append("```python")
                lines.append(f"results = kg.search(\"{q['keywords']}\", top_k=10)")
                lines.append(f"for node, score in results:")
                lines.append(f"    if node.type in {q.get('expected_types', [])}:")
                lines.append(f"        sub = kg.traverse(node.id, depth={q.get('max_hops', 2)})")
                lines.append("```")
                types_found = q.get('expected_types_found') or q.get('expected_types', [])
                rels_found = q.get('expected_relations_found') or q.get('expected_relations', [])
                zh_types = [f"{t} ({self.NODE_TYPE_DESC.get(t, '')})" for t in types_found]
                zh_rels = [f"{r} ({self.RELATION_DESC.get(r, '')})" for r in rels_found]
                lines.append(f"Involved nodes: {', '.join(zh_types) if zh_types else ', '.join(types_found)}")
                lines.append(f"Involved relations: {', '.join(zh_rels) if zh_rels else ', '.join(rels_found)}\n")
            if not relevant:
                lines.append("(No test cases for this type)\n")

        # ---- 4. Frequently Asked Questions (Q&A) ----
        lines.append("## 4. Frequently Asked Questions (Q&A)\n")
        # Sample evenly by category: single-hop, multi-hop, inference, cross-query each take representative questions
        sampled_ids = {1, 4, 7, 9, 11, 14, 17, 20, 23, 26, 29, 30}
        sampled = [q for q in self.queries if q.get("id") in sampled_ids]
        if len(sampled) < 8:
            # fallback: take first 12 deduped
            sampled = unique_queries[:12]

        for q in sampled:
            qid = q.get("id", "?")
            lines.append(f"### Q{qid}: {q['question']}\n")
            lines.append("**Graph query method**:")
            lines.append("```python")
            lines.append(f"results = kg.search(\"{q['keywords']}\", top_k=10)")
            lines.append("for node, score in results:")
            lines.append("    print(f'[{node.type}] {node.properties.get(\"name\", node.id)}')")
            lines.append("")
            lines.append("# Graph traversal to expand subgraph")
            lines.append(f"if results:")
            lines.append(f"    subgraph = kg.traverse(results[0][0].id, depth={q.get('max_hops', 2)})")
            lines.append("```")
            lines.append("**CLI command**:")
            lines.append("```bash")
            lines.append(f"python scripts/query_tool.py --graph kg.json --search \"{q['keywords']}\"")
            lines.append("```")
            types_found = q.get('expected_types_found') or q.get('expected_types', [])
            rels_found = q.get('expected_relations_found') or q.get('expected_relations', [])
            zh_types = [f"{t} ({self.NODE_TYPE_DESC.get(t, '')})" for t in types_found]
            zh_rels = [f"{r} ({self.RELATION_DESC.get(r, '')})" for r in rels_found]
            lines.append(f"**Involved nodes**: {', '.join(zh_types) if zh_types else ', '.join(types_found)}")
            lines.append(f"**Involved relations**: {', '.join(zh_rels) if zh_rels else ', '.join(rels_found)}\n")

        # ---- 5. Node ID System ----
        lines.append("## 5. Node ID System\n")
        lines.append("| Prefix | Node type | Example |")
        lines.append("|------|---------|------|")
        id_table = [
            ("smp_", "Sample"), ("org_", "Organoid"), ("orn_", "Organ"),
            ("sys_", "System"), ("osm_", "Organism"), ("src_", "Source"),
            ("cf_", "CellFactor"), ("tec_", "Technology"), ("drg_", "Drug"),
            ("gen_", "Gene"), ("dm_", "DiseaseModel"), ("inf_", "Infection"),
            ("bmk_", "Biomarker"), ("phn_", "Phenotype"), ("omc_", "Omics"),
            ("cmp_", "Composition"), ("app_", "Application"), ("pub_", "Publication"),
        ]
        for prefix, ntype in id_table:
            lines.append(f"| `{prefix}` | {ntype} ({self.NODE_TYPE_DESC.get(ntype, '')}) | `{prefix}xxxx` |")
        lines.append("")

        # ---- 6. Query Tips ----
        lines.append("## 6. Query Tips\n")
        lines.append("- **Precise type filtering**: `kg.search(\"Cisplatin\", node_type=\"Drug\")` searches only Drug nodes")
        lines.append("- **Deep traversal**: Increase `depth` parameter to expand subgraph scope; note that high depth may cause excessively large subgraphs")
        lines.append("- **Path finding**: `kg.find_paths(\"smp_A\", \"drg_B\")` discovers all relationship paths between two nodes")
        lines.append("- **Combined queries**: Use `search()` to find seed nodes, then `traverse()` to expand subgraph, finally filter on the subgraph")
        lines.append("- **Inferred relations**: `TREATS_DISEASE` and `INDICATES_DISEASE` are based on co-occurrence inference; confidence is in edge properties")
        lines.append("- **Co-culture distinction**: Differentiate via edge property `context` (`\"primary\"` vs `\"coculture\"`)")
        lines.append("- **Batch queries**: Load KG once and call `search()` / `traverse()` multiple times to avoid repeated file loading\n")

        # ---- 7. Known Limitations ----
        lines.append("## 7. Known Limitations\n")
        lines.append("1. Culture conditions/steps/materials are retained as JSON properties of Sample; fine-grained filtering by temperature, CO2 concentration, etc. is not supported")
        lines.append("2. Co-culture data shares CellFactor/Biomarker node types, differentiated by edge property `context`; filtering is required")
        lines.append("3. Inferred relations (TREATS_DISEASE / INDICATES_DISEASE) are based on co-occurrence statistics and do not represent causality")
        lines.append("4. JSON column entity extraction depends on the key name list in `_extract_entity_name()`; uncovered key names may miss entities")
        lines.append("5. Currently only processes the `public_general_2026` single table; if there are other related tables, `build_kg.py` needs to be extended")
        lines.append("6. Uses JSON + SQLite file storage, no graph database required, suitable for standalone distribution but limited performance for very large subgraph traversal\n")

        # ---- 8. References ----
        lines.append("## 8. References\n")
        lines.append("1. Pruyn, T. M. et al. MOF-Chemunity. *J. Am. Chem. Soc.* **2025**, *147*, 43474-43486.")
        lines.append("2. MOF-Chemunity open source code: https://github.com/AI4ChemS/MOF_ChemUnity")
        lines.append("3. Schema design document: `docs/schema_design.md`")
        lines.append("4. Complete tutorial: `build_tutorial.md`\n")

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[OK] User manual: {path}")

    def _build_coverage(self) -> dict:
        """Build coverage matrix"""
        nodes_tested = set()
        rels_tested = set()
        for q in self.queries:
            for t in q.get("expected_types_found", []):
                nodes_tested.add(t)
            for r in q.get("expected_relations_found", []):
                rels_tested.add(r)

        return {
            "node_types_tested": sorted(nodes_tested),
            "relation_types_tested": sorted(rels_tested),
            "untested_nodes": sorted(EXPECTED_NODE_TYPES - nodes_tested),
            "untested_relations": sorted(EXPECTED_RELATION_TYPES - rels_tested),
        }


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
        description="Validate organoid knowledge graph and generate test reports")
    parser.add_argument("kg_file", nargs="?", default=None,
                        help="Path to organoid_kg.json (auto-detect latest if omitted)")
    parser.add_argument("--kg-dir", default="./organoid-kg-output",
                        help="Directory to scan for latest KG build (default: ./organoid-kg-output)")
    parser.add_argument("--output-dir", default="./kg_test_output",
                        help="Output directory for reports (default: ./kg_test_output)")
    parser.add_argument("--structure-only", action="store_true",
                        help="Only run structure validation")
    parser.add_argument("--query-only", action="store_true",
                        help="Only run query tests")
    parser.add_argument("--gen-manual", action="store_true",
                        help="Only generate user manual from existing test definitions")
    parser.add_argument("--api-key", help="LLM API key for readable query answers (or set OPENAI_API_KEY / DEEPSEEK_API_KEY)")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="LLM API base URL (for compatible services)")
    parser.add_argument("--model", default="deepseek-v4-pro", help="LLM model (default: gpt-4o)")
    args = parser.parse_args()

    # Auto-detect latest KG file
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
    # Test report written to timestamp subdirectory, user manual placed in output_dir root
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    report_subdir = os.path.join(output_dir, timestamp)

    print(f"\n{'='*60}")
    print(f"  KG file:     {args.kg_file}")
    print(f"  Output dir:  {output_dir}")
    print(f"{'='*60}")

    kg = KnowledgeGraphQuery.load(args.kg_file)
    print(f"  Loaded {len(kg.nodes)} nodes, {len(kg.edges)} edges")

    run_structure = not args.query_only and not args.gen_manual
    run_queries = not args.structure_only and not args.gen_manual

    structure_results = []
    query_results = []

    if run_structure:
        print(f"\n[Phase 1] Structure Validation...")
        validator = StructureValidator(kg)
        structure_results = validator.run_all()
        for r in structure_results:
            icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]", "ERROR": "[ERR ]"}.get(r["status"], "[????]")
            print(f"  {icon} {r['check']}: {r.get('detail', '')}")

    if run_queries:
        print(f"\n[Phase 2] Query Testing...")
        llm_api_key = args.api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
        tester = QueryTester(kg, api_key=llm_api_key,
                             base_url=args.base_url, model=args.model)
        query_results = tester.run_all()
        for r in query_results:
            icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]", "ERROR": "[ERR ]"}.get(r["status"], "[????]")
            sn = r.get("subgraph_nodes", 0)
            se = r.get("subgraph_edges", 0)
            has_llm = " [LLM]" if r.get("llm_answer") else ""
            print(f"  {icon} #{r['id']:2d} | subgraph={sn}n/{se}e{has_llm} | {r['question'][:40]}")

    if args.gen_manual:
        print(f"\n[Phase 3] Generating user manual...")
        # Use test case definitions to generate manual directly (no need to run tests)
        gen = ReportGenerator(args.kg_file, [], [], kg=kg)
        gen.queries = [{
            "id": tc.id, "question": tc.question, "keywords": tc.keywords,
            "expected_types": tc.expected_types,
            "expected_types_found": tc.expected_types,
            "expected_relations": tc.expected_relations,
            "expected_relations_found": tc.expected_relations,
            "search_hits": "?",
            "max_hops": tc.max_hops,
        } for tc in TEST_CASES]
        gen.save_manual(os.path.join(output_dir, "user_manual.md"))
        return

    if not args.gen_manual:
        print(f"\n[Phase 3] Generating reports...")
        gen = ReportGenerator(args.kg_file, structure_results, query_results, kg=kg)

        gen.save_json(os.path.join(report_subdir, "test_report.json"))
        gen.save_markdown(os.path.join(report_subdir, "test_report.md"))
        gen.save_manual(os.path.join(output_dir, "user_manual.md"))

        print(f"\n{'='*60}")
        print(f"  Summary")
        print(f"{'='*60}")
        print(f"  Structure: {gen.structure_passed}/{gen.structure_total} passed")
        print(f"  Queries:   {gen.query_passed}/{gen.query_total} passed")
        print(f"  Overall:   {gen.total_passed}/{gen.total_checks} ({gen.pass_rate:.1%})")
        print(f"  Health:    {gen.health_score}/100")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
