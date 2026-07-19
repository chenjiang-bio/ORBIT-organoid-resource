#!/usr/bin/env python3
"""
test_kg.py — Knowledge graph functional test script (DeepSeek version)

Covers all Python code examples from the user manual, using DeepSeek as the LLM backend.

Usage:
  # Auto-detect latest KG, run all tests (requires DeepSeek API Key)
  set DEEPSEEK_API_KEY=sk-xxx
  python scripts/test_kg.py

  # Specify KG file
  python scripts/test_kg.py organoid-kg-output/2026-07-19-1138/organoid_kg.json

  # Skip LLM Q&A tests (search and graph traversal only)
  python scripts/test_kg.py --skip-llm

  # Run LLM Q&A only
  python scripts/test_kg.py --llm-only

  # Use another DeepSeek-compatible service
  python scripts/test_kg.py --base-url https://api.deepseek.com --model deepseek-chat

Output:
  Test results printed to terminal, including pass/fail status and elapsed time for each test.
"""

import os
import sys
import time
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from query_tool import KnowledgeGraphQuery


# =============================================================================
# Helpers
# =============================================================================

class TestRunner:
    """Test runner"""

    def __init__(self, kg: KnowledgeGraphQuery,
                 api_key: str = None, base_url: str = None, model: str = None):
        self.kg = kg
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.passed = 0
        self.failed = 0
        self.errors = 0

    def run(self, name: str, fn, *args, **kwargs):
        """Run a single test and record the result"""
        print(f"\n{'='*60}")
        print(f"  TEST: {name}")
        print(f"{'='*60}")
        start = time.time()
        try:
            result = fn(*args, **kwargs)
            elapsed_ms = int((time.time() - start) * 1000)
            if result:
                self.passed += 1
                print(f"  [PASS] ({elapsed_ms}ms)")
            else:
                self.failed += 1
                print(f"  [FAIL] ({elapsed_ms}ms) — result is empty or does not meet expectations")
        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            self.errors += 1
            print(f"  [ERROR] ({elapsed_ms}ms) — {e}")
        return result


# =============================================================================
# Test functions
# =============================================================================

def test_basic_search(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 1: Basic keyword search — search for intestinal organoids"""
    results = kg.search("intestinal organoid", top_k=10)
    print(f"  Found {len(results)} nodes:")
    for node, score in results[:5]:
        name = node.properties.get("name", node.properties.get("sample_id", node.id))
        print(f"    [{node.type}] {str(name)[:60]} (score: {score:.2f})")
    return len(results) > 0


def test_type_filtered_search(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 2: Type-filtered search — search only Drug nodes"""
    results_all = kg.search("Cisplatin", top_k=5)
    results_drug = kg.search("Cisplatin", node_type="Drug", top_k=5)

    print(f"  Unfiltered hits: {len(results_all)}")
    types_all = set(n.type for n, _ in results_all)
    print(f"  Types: {types_all}")

    print(f"  Filtered to Drug hits: {len(results_drug)}")
    types_drug = set(n.type for n, _ in results_drug)
    print(f"  Types: {types_drug}")

    # Filtered results should all be Drug
    return all(n.type == "Drug" for n, _ in results_drug) and len(results_drug) > 0


def test_graph_traversal(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 3: Graph traversal — traverse subgraph from search results"""
    # First find a Sample node
    results = kg.search("intestinal organoid", top_k=5)
    if not results:
        print("  Search results are empty, skipping")
        return False

    seed_node, seed_score = results[0]
    print(f"  Seed node: [{seed_node.type}] {seed_node.properties.get('name', seed_node.id)}")

    # BFS traversal depth=2
    sub = kg.traverse(seed_node.id, depth=2)
    print(f"  Subgraph: {len(sub['nodes'])} nodes, {len(sub['edges'])} edges")

    # Count node types in subgraph
    type_counts = defaultdict(int)
    for n in sub["nodes"]:
        type_counts[n.type] += 1
    print("  Node type distribution:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"    {t}: {c}")

    # Count relationship types in subgraph
    rel_counts = defaultdict(int)
    for e in sub["edges"]:
        rel_counts[e.relation] += 1
    print("  Relationship type distribution:")
    for r, c in sorted(rel_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"    {r}: {c}")

    return len(sub["nodes"]) > 0 and len(sub["edges"]) > 0


def test_path_finding(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 4: Path finding — find paths between two nodes"""
    # Find a Sample and a Drug
    samples = [nid for nid, n in kg.nodes.items() if n.type == "Sample"]
    drugs = [nid for nid, n in kg.nodes.items() if n.type == "Drug"]

    if not samples or not drugs:
        print("  Sample or Drug nodes are insufficient, skipping")
        return False

    # Use the first Sample and first Drug
    src = samples[0]
    tgt = drugs[0]
    src_name = kg.nodes[src].properties.get("sample_id", src)
    tgt_name = kg.nodes[tgt].properties.get("name", tgt)

    print(f"  Source: [{kg.nodes[src].type}] {src_name}")
    print(f"  Target: [{kg.nodes[tgt].type}] {tgt_name}")

    paths = kg.find_paths(src, tgt, max_length=4)
    print(f"  Found {len(paths)} paths (showing up to 3):")
    for i, path in enumerate(paths[:3]):
        steps = []
        for step in path:
            from_name = step["from_node"].properties.get("name", step["from_node"].id)
            to_name = step["to_node"].properties.get("name", step["to_node"].id)
            steps.append(f"[{step['from_node'].type}]{str(from_name)[:30]} "
                         f"-[:{step['edge'].relation}]-> "
                         f"[{step['to_node'].type}]{str(to_name)[:30]}")
        print(f"  Path {i+1}: " + "  →  ".join(steps))

    # Path finding does not require that a path is always found (Sample-Drug may not be directly connected in the full graph)
    return True


def test_search_organism(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 5: Search by species — samples from Human/Mouse sources"""
    for organism_name in ["Human", "Mouse"]:
        results = kg.search(organism_name, top_k=5)
        organoid_count = 0
        sample_count = 0
        for node, score in results:
            if node.type == "Organism":
                sub = kg.traverse(node.id, depth=2)
                for n in sub["nodes"]:
                    if n.type == "Organoid":
                        organoid_count += 1
                    elif n.type == "Sample":
                        sample_count += 1
        print(f"  {organism_name}: found {len(results)} nodes → "
              f"subgraph contains {organoid_count} Organoid, {sample_count} Sample")
    return True


def test_search_cell_factor(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 6: Search by cell factor — EGF / Wnt"""
    for factor_name in ["EGF", "Wnt"]:
        results = kg.search(factor_name, top_k=5)
        sample_count = 0
        for node, score in results:
            if node.type == "CellFactor":
                sub = kg.traverse(node.id, depth=1)
                for n in sub["nodes"]:
                    if n.type == "Sample":
                        sample_count += 1
        print(f"  {factor_name}: found {len(results)} nodes → "
              f"associated with ~{sample_count} Samples")
    return True


def test_multi_factor_intersection(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 7: Multi-factor intersection query — samples using EGF + Wnt + R-spondin simultaneously"""
    def find_samples(keyword: str) -> set:
        results = kg.search(keyword, top_k=20)
        sample_ids = set()
        for node, _ in results:
            if node.type == "CellFactor":
                sub = kg.traverse(node.id, depth=1)
                for n in sub["nodes"]:
                    if n.type == "Sample":
                        sample_ids.add(n.id)
            elif node.type == "Sample":
                sample_ids.add(node.id)
        return sample_ids

    egf_samples = find_samples("EGF")
    wnt_samples = find_samples("Wnt")
    rspo_samples = find_samples("R-spondin")

    common = egf_samples & wnt_samples & rspo_samples
    print(f"  EGF-associated samples:     {len(egf_samples)}")
    print(f"  Wnt-associated samples:     {len(wnt_samples)}")
    print(f"  R-spondin-associated samples: {len(rspo_samples)}")
    print(f"  Intersection of all three:  {len(common)} samples")

    if common:
        # Show details of intersecting samples
        for sid in list(common)[:3]:
            node = kg.nodes.get(sid)
            if node:
                name = node.properties.get("sample_id", sid)
                print(f"    Example: [{node.type}] {str(name)[:60]}")
    return True


def test_sample_similarity(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 8: Sample similarity calculation — Jaccard similarity based on shared neighbors"""
    samples = [nid for nid, n in kg.nodes.items() if n.type == "Sample"][:10]
    if len(samples) < 2:
        print("  Sample nodes are insufficient, skipping")
        return False

    s1, s2 = samples[0], samples[1]
    sub1 = kg.traverse(s1, depth=1)
    sub2 = kg.traverse(s2, depth=1)

    neighbors1 = {n.id for n in sub1["nodes"]} - {s1}
    neighbors2 = {n.id for n in sub2["nodes"]} - {s2}

    shared = neighbors1 & neighbors2
    union = neighbors1 | neighbors2
    jaccard = len(shared) / len(union) if union else 0

    name1 = kg.nodes[s1].properties.get("sample_id", s1)
    name2 = kg.nodes[s2].properties.get("sample_id", s2)

    print(f"  Sample A: {name1} ({len(neighbors1)} neighbors)")
    print(f"  Sample B: {name2} ({len(neighbors2)} neighbors)")
    print(f"  Shared neighbors: {len(shared)}")
    print(f"  Jaccard similarity: {jaccard:.4f}")

    # Show shared neighbors
    if shared:
        print("  Shared neighbor examples:")
        for nid in list(shared)[:5]:
            node = kg.nodes.get(nid)
            if node:
                name = node.properties.get("name", nid)
                print(f"    [{node.type}] {str(name)[:60]}")
    return True


def test_drug_disease_inference(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 9: Inferred relationships — TREATS_DISEASE / INDICATES_DISEASE"""
    # Count inferred relationships
    treats_count = 0
    indicates_count = 0
    treats_examples = []
    indicates_examples = []

    for e in kg.edges:
        if e.relation == "TREATS_DISEASE":
            treats_count += 1
            if len(treats_examples) < 3:
                src = kg.nodes.get(e.source)
                tgt = kg.nodes.get(e.target)
                if src and tgt:
                    conf = e.properties.get("confidence", "?")
                    treats_examples.append(
                        f"[Drug]{src.properties.get('name', '?')} "
                        f"--TREATS_DISEASE(conf={conf})--> "
                        f"[DiseaseModel]{tgt.properties.get('name', '?')}"
                    )
        elif e.relation == "INDICATES_DISEASE":
            indicates_count += 1
            if len(indicates_examples) < 3:
                src = kg.nodes.get(e.source)
                tgt = kg.nodes.get(e.target)
                if src and tgt:
                    conf = e.properties.get("confidence", "?")
                    indicates_examples.append(
                        f"[Biomarker]{src.properties.get('name', '?')} "
                        f"--INDICATES_DISEASE(conf={conf})--> "
                        f"[DiseaseModel]{tgt.properties.get('name', '?')}"
                    )

    print(f"  TREATS_DISEASE (Drug→Disease): {treats_count:,}")
    for ex in treats_examples:
        print(f"    {ex}")
    print(f"  INDICATES_DISEASE (Biomarker→Disease): {indicates_count:,}")
    for ex in indicates_examples:
        print(f"    {ex}")
    return treats_count > 0 or indicates_count > 0


def test_coculture_context(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 10: Co-culture tag check — edge property context distinction"""
    coculture_edges = [e for e in kg.edges
                       if e.properties.get("context") == "coculture"]
    primary_edges = [e for e in kg.edges
                     if e.properties.get("context") == "primary"]

    print(f"  Co-culture edges (context=coculture): {len(coculture_edges):,}")
    print(f"  Primary culture edges (context=primary):   {len(primary_edges):,}")

    if coculture_edges:
        # Show co-culture edge examples
        rel_types = defaultdict(int)
        for e in coculture_edges:
            rel_types[e.relation] += 1
        print("  Co-culture edge relationship type distribution:")
        for r, c in sorted(rel_types.items(), key=lambda x: -x[1]):
            print(f"    {r}: {c}")
    return True


def test_node_id_system(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 11: Node ID system — counts and examples for each prefix"""
    prefixes = {
        "smp_": "Sample", "org_": "Organoid", "orn_": "Organ",
        "sys_": "System", "osm_": "Organism", "src_": "Source",
        "cf_": "CellFactor", "tec_": "Technology", "drg_": "Drug",
        "gen_": "Gene", "dm_": "DiseaseModel", "inf_": "Infection",
        "bmk_": "Biomarker", "phn_": "Phenotype", "omc_": "Omics",
        "cmp_": "Composition", "app_": "Application", "pub_": "Publication",
    }
    print(f"  {'Prefix':<8} {'Type':<18} {'Count':<10} {'Example ID'}")
    print(f"  {'-'*8} {'-'*18} {'-'*10} {'-'*40}")
    for prefix, ntype in prefixes.items():
        ids = [nid for nid in kg.nodes if nid.startswith(prefix)]
        count = len(ids)
        example = ids[0] if ids else "N/A"
        print(f"  {prefix:<8} {ntype:<18} {count:<10,} {example}")
    return True


def test_kg_statistics(kg: KnowledgeGraphQuery, runner: TestRunner):
    """Test 12: KG statistics overview"""
    from collections import Counter

    total_nodes = len(kg.nodes)
    total_edges = len(kg.edges)
    avg_degree = 2 * total_edges / total_nodes if total_nodes else 0

    ntc = Counter(n.type for n in kg.nodes.values())
    etc = Counter(e.relation for e in kg.edges)

    # Find max-degree and isolated nodes
    degree_map = defaultdict(int)
    for e in kg.edges:
        degree_map[e.source] += 1
        degree_map[e.target] += 1
    max_degree_node = max(degree_map, key=degree_map.get, default=None)
    max_degree = degree_map.get(max_degree_node, 0)
    isolated = sum(1 for nid in kg.nodes if degree_map.get(nid, 0) == 0)

    print(f"  Total nodes:    {total_nodes:,}")
    print(f"  Total edges:    {total_edges:,}")
    print(f"  Node types:     {len(ntc)}")
    print(f"  Edge types:     {len(etc)}")
    print(f"  Avg degree:     {avg_degree:.2f}")
    print(f"  Max degree:     {max_degree} ({max_degree_node})")
    print(f"  Isolated nodes: {isolated}")
    print(f"\n  Top-5 node types:")
    for t, c in ntc.most_common(5):
        print(f"    {t}: {c:,}")
    print(f"\n  Top-5 edge types:")
    for r, c in etc.most_common(5):
        print(f"    {r}: {c:,}")
    return True


# =============================================================================
# LLM Q&A tests (DeepSeek)
# =============================================================================

LLM_QUESTIONS = [
    (
        "Q1: Which culture conditions are favorable for intestinal organoid differentiation?",
        "Which culture conditions are favorable for intestinal organoid differentiation?"
    ),
    (
        "Q2: What is the role of EGF in organoid culture? Which samples use EGF?",
        "What is the role of EGF in organoid culture? Which samples use EGF?"
    ),
    (
        "Q3: List the organoid models used for colorectal cancer research and the drugs they use.",
        "List the organoid models used for colorectal cancer research and the drugs they use."
    ),
    (
        "Q4: Compare the differences in culture conditions between human and mouse intestinal organoids",
        "Compare the differences in culture conditions between human and mouse intestinal organoids"
    ),
    (
        "Q5: Which biomarkers are associated with inflammatory bowel disease?",
        "Which biomarkers are associated with inflammatory bowel disease?"
    ),
]


def test_llm_qa(kg: KnowledgeGraphQuery, runner: TestRunner,
                verbose: bool = True):
    """Test 13: LLM GraphRAG Q&A (one question at a time)"""
    if not runner.api_key:
        print("  [SKIP] API Key not set, skipping LLM Q&A tests")
        print("  To set: set DEEPSEEK_API_KEY=sk-xxx")
        return False

    all_passed = True
    for label, question in LLM_QUESTIONS:
        print(f"\n  --- {label} ---")
        print(f"  Question: {question}")
        try:
            result = kg.ask(
                question,
                api_key=runner.api_key,
                base_url=runner.base_url,
                model=runner.model,
                top_k=15,
                traversal_depth=2,
                verbose=verbose,
            )
            response = result.get("response", "")
            sources = result.get("sources", [])
            stats = result.get("subgraph_stats", {})

            print(f"  Subgraph: {stats.get('nodes', '?')} nodes, "
                  f"{stats.get('edges', '?')} edges")
            print(f"  Answer ({len(response)} characters):")
            # Indent the answer
            for line in response.split("\n")[:20]:
                print(f"    {line}")
            if len(response.split("\n")) > 20:
                print(f"    ... (truncated, {len(response.splitlines())} lines total)")
            if sources:
                print(f"  Sources: {sources[:5]}")

        except Exception as e:
            print(f"  [LLM Error] {e}")
            all_passed = False

    return all_passed


# =============================================================================
# Find latest KG
# =============================================================================

def _find_latest_kg(kg_dir: str):
    """Find organoid_kg.json in the most recent timestamped subdirectory under kg_dir"""
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
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Knowledge graph functional test script (DeepSeek version)")
    parser.add_argument("kg_file", nargs="?", default=None,
                        help="Path to KG JSON file (auto-detect latest by default)")
    parser.add_argument("--kg-dir", default="./organoid-kg-output",
                        help="Directory to scan for the latest KG")
    parser.add_argument("--api-key", default=None,
                        help="DeepSeek API Key (can also use the DEEPSEEK_API_KEY environment variable)")
    parser.add_argument("--base-url", default="https://api.deepseek.com",
                        help="API base URL (default: https://api.deepseek.com)")
    parser.add_argument("--model", default="deepseek-v4-pro",
                        help="Model name (default: deepseek-chat)")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Skip LLM Q&A tests")
    parser.add_argument("--llm-only", action="store_true",
                        help="Run LLM Q&A tests only")
    args = parser.parse_args()

    # Resolve API Key
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY")

    # Auto-detect latest KG file
    if args.kg_file is None:
        args.kg_file = _find_latest_kg(args.kg_dir)
        if args.kg_file is None:
            print(f"[ERROR] No organoid_kg.json found under {args.kg_dir}/<timestamp>/")
            sys.exit(1)
        print(f"[INFO] Auto-detected latest KG: {args.kg_file}")

    if not os.path.exists(args.kg_file):
        print(f"[ERROR] File not found: {args.kg_file}")
        sys.exit(1)

    # Load the KG
    print(f"[INFO] Loading KG...")
    start = time.time()
    kg = KnowledgeGraphQuery.load(args.kg_file)
    load_time = int((time.time() - start) * 1000)
    print(f"       Loaded {len(kg.nodes):,} nodes, {len(kg.edges):,} edges "
          f"in {load_time}ms")

    runner = TestRunner(kg, api_key=api_key, base_url=args.base_url,
                        model=args.model)

    if api_key:
        print(f"[INFO] LLM: {args.model} @ {args.base_url}")
    else:
        print(f"[INFO] LLM: not configured (use --api-key or the DEEPSEEK_API_KEY environment variable)")

    # Define test suite
    search_tests = [
        ("Basic keyword search", test_basic_search),
        ("Type-filtered search (Drug)", test_type_filtered_search),
        ("Graph traversal (BFS depth=2)", test_graph_traversal),
        ("Path finding (find_paths)", test_path_finding),
        ("Search by species (Human/Mouse)", test_search_organism),
        ("Search by cell factor (EGF/Wnt)", test_search_cell_factor),
        ("Multi-factor intersection query", test_multi_factor_intersection),
        ("Sample similarity (Jaccard)", test_sample_similarity),
        ("Inferred relationship stats (TREATS/INDICATES)", test_drug_disease_inference),
        ("Co-culture context tags", test_coculture_context),
        ("Node ID system", test_node_id_system),
        ("KG statistics overview", test_kg_statistics),
    ]

    llm_tests = [
        ("GraphRAG Q&A (DeepSeek)", test_llm_qa),
    ]

    # Run tests
    print(f"\n{'#'*60}")
    print(f"  Knowledge Graph Test Suite")
    print(f"{'#'*60}")

    if not args.llm_only:
        print(f"\n{'='*60}")
        print(f"  Phase 1: Search & Graph Traversal Tests")
        print(f"{'='*60}")
        for name, fn in search_tests:
            runner.run(name, fn, kg, runner)

    if not args.skip_llm:
        print(f"\n{'='*60}")
        print(f"  Phase 2: LLM GraphRAG Q&A Tests")
        print(f"{'='*60}")
        for name, fn in llm_tests:
            runner.run(name, fn, kg, runner)

    # Summary
    total = runner.passed + runner.failed + runner.errors
    print(f"\n{'='*60}")
    print(f"  Test Summary")
    print(f"{'='*60}")
    print(f"  Total:  {total}")
    print(f"  Passed: {runner.passed}")
    print(f"  Failed: {runner.failed}")
    print(f"  Errors: {runner.errors}")
    print(f"  Rate:   {runner.passed / total * 100:.1f}%" if total > 0 else "")
    print(f"{'='*60}")

    # Return non-zero exit code if there were failures
    return 0 if runner.failed == 0 and runner.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
