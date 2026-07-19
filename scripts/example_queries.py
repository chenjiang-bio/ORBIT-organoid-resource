#!/usr/bin/env python3
"""
Example: How to use KnowledgeGraphQuery for various queries

Prerequisites:
  1. Run build_kg.py to generate the organoid_kg.json file
  2. Set the OPENAI_API_KEY environment variable (for GraphRAG Q&A)
"""

from query_tool import KnowledgeGraphQuery

# ---------------------------------------------------------------------------
# 1. Load knowledge graph
# ---------------------------------------------------------------------------
kg = KnowledgeGraphQuery.load("organoid_kg.json")

# ---------------------------------------------------------------------------
# 2. View graph statistics
# ---------------------------------------------------------------------------
print("=" * 60)
print("2. Graph Statistics")
print("=" * 60)
kg.print_stats()

# ---------------------------------------------------------------------------
# 3. Keyword search
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("3. Search for nodes containing 'EGF'")
print("=" * 60)
results = kg.search("EGF R-spondin intestinal", top_k=10)
for node, score in results:
    name = node.properties.get("name", node.properties.get("sample_id", node.id))
    print(f"  [{node.type}] {name} — score: {score:.2f}")

# ---------------------------------------------------------------------------
# 4. Type-filtered search
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("4. Search only Drug type nodes")
print("=" * 60)
results = kg.search("Cisplatin", node_type="Drug", top_k=10)
for node, score in results:
    name = node.properties.get("name", "?")
    category = node.properties.get("category", "?")
    print(f"  [{node.type}] {name} ({category}) — score: {score:.2f}")

# ---------------------------------------------------------------------------
# 5. Graph traversal: view full information for an experiment
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("5. View subgraph associated with sample smp_ABC123")
print("=" * 60)
subgraph = kg.traverse("smp_ABC123", depth=2)
print(f"  Nodes: {len(subgraph['nodes'])}, Edges: {len(subgraph['edges'])}")
for node in subgraph["nodes"]:
    props_summary = ", ".join(
        f"{k}={v}" for k, v in list(node.properties.items())[:3]
    )
    print(f"    [{node.type}] {node.id} | {props_summary}")

# ---------------------------------------------------------------------------
# 6. Path finding: association paths between two nodes
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("6. Find Paths")
print("=" * 60)
paths = kg.find_paths("smp_ABC123", "drg_e5f6g7h8", max_length=4)
for i, path in enumerate(paths):
    print(f"  Path {i+1}:")
    for step in path:
        print(f"    [{step['from_node'].type}] {step['from_node'].id}")
        print(f"      --[{step['edge'].relation}]-->")
    last = path[-1]["to_node"] if path else None
    if last:
        print(f"    [{last.type}] {last.id}")

# ---------------------------------------------------------------------------
# 7. GraphRAG Q&A (requires LLM API key)
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("7. GraphRAG Q&A Examples")
print("=" * 60)

# Example question list
questions = [
    "Which cytokine combinations are commonly used for intestinal organoid culture?",
    "Which human liver organoid samples are used for drug screening?",
    "What phenotypes do APC gene knockout organoids exhibit?",
    "Which biomarkers are primarily detected in colorectal cancer organoids?",
]

# Select one question for testing
question = questions[0]
print(f"  Question: {question}")
print(f"  (Set OPENAI_API_KEY to enable LLM answering)")
print()

# Don't call the LLM, just show the retrieved context
results = kg.search(question, top_k=5)
print("  Retrieved relevant nodes (injected into LLM as context):")
for node, score in results:
    name = node.properties.get("name", node.properties.get("sample_id", node.id))
    print(f"    [{node.type}] {name} (score: {score:.2f})")

# Uncomment the following line to actually call the LLM:
# answer = kg.ask(question, model="gpt-4o", verbose=True)
# print(answer["response"])
# print(f"Sources: {answer['sources']}")

print("\nDone!")
