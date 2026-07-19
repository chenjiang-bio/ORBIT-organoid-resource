#!/usr/bin/env python3
"""
query_tool.py — Organoid Knowledge Graph Query Tool + LLM GraphRAG

Reference: Graph-enhanced RAG architecture from MOF-ChemUnity (JACS 2025) Figure 6

Features:
  1. Load knowledge graph files in JSON or SQLite format
  2. Keyword search for nodes
  3. Graph traversal to retrieve subgraphs
  4. LLM GraphRAG: natural language question → subgraph retrieval → LLM answer

Usage:
  # Interactive Q&A
  python query_tool.py --graph organoid_kg.json --api-key sk-xxx --interactive

  # Single query
  python query_tool.py --graph organoid_kg.json --api-key sk-xxx \\
      --question "Which culture conditions favor intestinal organoid differentiation?"

  # Pure graph search (no LLM needed)
  python query_tool.py --graph organoid_kg.json --search "Matrigel EGF"

  # View graph statistics
  python query_tool.py --graph organoid_kg.json --stats

  # View a node's subgraph
  python query_tool.py --graph organoid_kg.json --subgraph exp_001

Use as a Python library:
  from query_tool import KnowledgeGraphQuery

  kg = KnowledgeGraphQuery.load("organoid_kg.json")
  results = kg.search("intestinal organoid")
  subgraph = kg.traverse("exp_001", depth=2)
  answer = kg.ask("Which experiments used EGF?", api_key="sk-xxx")
"""

import json
import sqlite3
import re
import os
import sys
from typing import Dict, List, Optional, Tuple, Any, Set
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime


# =============================================================================
# Data structures
# =============================================================================

@dataclass
class GraphNode:
    id: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def text_content(self) -> str:
        """Combine all node properties into searchable text"""
        parts = [self.type, self.id]
        for key, val in self.properties.items():
            if isinstance(val, (str, int, float)):
                parts.append(str(val))
            elif isinstance(val, list):
                parts.extend(str(v) for v in val)
        return " ".join(parts).lower()


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    relation: str
    properties: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Knowledge Graph Query Engine
# =============================================================================

class KnowledgeGraphQuery:
    """Knowledge Graph Query Engine

    Load graph files in JSON or SQLite format, provide search, graph traversal,
    and GraphRAG Q&A capabilities.
    """

    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self.meta: Dict[str, Any] = {}

        # Indices: speed up queries
        self._type_index: Dict[str, List[str]] = defaultdict(list)      # type -> [node_ids]
        self._adjacency: Dict[str, List[GraphEdge]] = defaultdict(list) # node_id -> [edges]
        self._text_cache: Dict[str, str] = {}                           # node_id -> text

    # -------------------------------------------------------------------------
    # Load graph
    # -------------------------------------------------------------------------

    @classmethod
    def load(cls, path: str) -> "KnowledgeGraphQuery":
        """Load knowledge graph file (auto-detect JSON or SQLite format)"""
        kg = cls()
        ext = os.path.splitext(path)[1].lower()

        if ext == ".json":
            kg._load_json(path)
        elif ext in (".sqlite", ".db", ".sqlite3"):
            kg._load_sqlite(path)
        else:
            raise ValueError(f"Unsupported file format: {ext}. Use .json or .sqlite")

        kg._build_indices()
        print(f"[OK] Loaded knowledge graph: {len(kg.nodes)} nodes, {len(kg.edges)} edges")
        return kg

    def _load_json(self, path: str):
        """Load from JSON file"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.meta = data.get("meta", {})

        for node_data in data.get("nodes", []):
            node = GraphNode(
                id=node_data["id"],
                type=node_data["type"],
                properties=node_data.get("properties", {})
            )
            self.nodes[node.id] = node

        for edge_data in data.get("edges", []):
            edge = GraphEdge(
                id=edge_data.get("id", ""),
                source=edge_data["source"],
                target=edge_data["target"],
                relation=edge_data["relation"],
                properties=edge_data.get("properties", {})
            )
            # Verify that both endpoints of the edge exist
            if edge.source in self.nodes and edge.target in self.nodes:
                self.edges.append(edge)

    def _load_sqlite(self, path: str):
        """Load from SQLite file"""
        conn = sqlite3.connect(path)
        cursor = conn.cursor()

        # Load metadata
        try:
            cursor.execute("SELECT key, value FROM meta")
            self.meta = dict(cursor.fetchall())
        except sqlite3.OperationalError:
            pass

        # Load nodes
        cursor.execute("SELECT id, type, properties FROM nodes")
        for row in cursor.fetchall():
            node = GraphNode(
                id=row[0],
                type=row[1],
                properties=json.loads(row[2]) if row[2] else {}
            )
            self.nodes[node.id] = node

        # Load edges
        cursor.execute("SELECT edge_id, source, target, relation, properties FROM edges")
        for row in cursor.fetchall():
            edge = GraphEdge(
                id=row[0] or "",
                source=row[1],
                target=row[2],
                relation=row[3],
                properties=json.loads(row[4]) if row[4] else {}
            )
            if edge.source in self.nodes and edge.target in self.nodes:
                self.edges.append(edge)

        conn.close()

    def _build_indices(self):
        """Build acceleration indices"""
        for node_id, node in self.nodes.items():
            self._type_index[node.type].append(node_id)
            self._text_cache[node_id] = node.text_content()

        for edge in self.edges:
            self._adjacency[edge.source].append(edge)
            self._adjacency[edge.target].append(edge)

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    def search(self, query: str, node_type: str = None, top_k: int = 20) -> List[Tuple[GraphNode, float]]:
        """Keyword search for nodes

        Args:
            query: Search keywords (space-separated for AND logic)
            node_type: Optional, filter by node type
            top_k: Return top-k results

        Returns:
            [(node, score), ...] sorted by relevance score in descending order
        """
        keywords = query.lower().split()
        scored = []

        target_ids = self._type_index.get(node_type, list(self.nodes.keys())) if node_type else self.nodes.keys()

        for node_id in target_ids:
            text = self._text_cache.get(node_id, "")
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scored.append((self.nodes[node_id], score / len(keywords)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # -------------------------------------------------------------------------
    # Graph traversal
    # -------------------------------------------------------------------------

    def traverse(self, node_id: str, depth: int = 2) -> dict:
        """Starting from a node, BFS traversal to retrieve subgraph

        Args:
            node_id: Starting node ID
            depth: Traversal depth (1 = direct neighbors, 2 = neighbors of neighbors)

        Returns:
            {"nodes": [...], "edges": [...]}
        """
        if node_id not in self.nodes:
            return {"nodes": [], "edges": []}

        visited_nodes: Set[str] = set()
        visited_edges: Set[str] = set()
        frontier = {node_id}

        for _ in range(depth + 1):
            next_frontier = set()
            for nid in frontier:
                visited_nodes.add(nid)
                for edge in self._adjacency.get(nid, []):
                    edge_key = edge.id or f"{edge.source}-{edge.relation}-{edge.target}"
                    if edge_key not in visited_edges:
                        visited_edges.add(edge_key)
                        neighbor = edge.target if edge.source == nid else edge.source
                        if neighbor not in visited_nodes:
                            next_frontier.add(neighbor)
            frontier = next_frontier
            if not frontier:
                break

        subgraph = {
            "nodes": [self.nodes[nid] for nid in visited_nodes],
            "edges": [e for e in self.edges if (e.id or f"{e.source}-{e.relation}-{e.target}") in visited_edges]
        }
        return subgraph

    def find_paths(self, source_id: str, target_id: str, max_length: int = 4) -> List[List[dict]]:
        """Find all shortest paths between two nodes"""
        if source_id not in self.nodes or target_id not in self.nodes:
            return []

        # BFS pathfinding
        from collections import deque
        queue = deque([[source_id]])
        visited = {source_id}
        paths = []

        while queue and len(paths) < 10:  # Find at most 10 paths
            path = queue.popleft()
            current = path[-1]

            if len(path) > max_length:
                continue

            if current == target_id:
                paths.append(path)
                continue

            for edge in self._adjacency.get(current, []):
                neighbor = edge.target if edge.source == current else edge.source
                if neighbor not in visited or neighbor == target_id:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        # Convert path ID list to structured paths with edges
        structured_paths = []
        for path in paths:
            structured = []
            for i in range(len(path) - 1):
                a, b = path[i], path[i + 1]
                for edge in self._adjacency.get(a, []):
                    if (edge.source == a and edge.target == b) or (edge.source == b and edge.target == a):
                        structured.append({
                            "from_node": self.nodes[a],
                            "edge": edge,
                            "to_node": self.nodes[b]
                        })
                        break
            structured_paths.append(structured)

        return structured_paths

    # -------------------------------------------------------------------------
    # Format subgraph as text
    # -------------------------------------------------------------------------

    def format_subgraph(self, subgraph: dict, max_nodes: int = 200) -> str:
        """Format subgraph as LLM-readable text (legacy, kept for compatibility)"""
        return self._format_subgraph_legacy(subgraph, max_nodes)

    @staticmethod
    def _format_subgraph_legacy(subgraph: dict, max_nodes: int = 200) -> str:
        """Legacy format_subgraph, kept for backward compatibility"""
        nodes = subgraph["nodes"][:max_nodes]
        edges = subgraph["edges"]

        lines = []
        lines.append("## Knowledge Graph Context\n")

        nodes_by_type = defaultdict(list)
        for node in nodes:
            nodes_by_type[node.type].append(node)

        for ntype, nlist in nodes_by_type.items():
            lines.append(f"\n### {ntype} ({len(nlist)} nodes)")
            for node in nlist[:50]:
                props_str = ", ".join(
                    f"{k}={v}" for k, v in node.properties.items()
                    if k in ("name", "sample_id", "category", "value", "metric",
                             "drug_name", "gene_name", "marker_name", "factor_name",
                             "disease_name", "technology_name", "omics_type",
                             "cell_types", "canonical_name", "organism", "organ")
                )
                if not props_str:
                    props_str = ", ".join(
                        f"{k}={v}" for k, v in list(node.properties.items())[:3]
                    )
                lines.append(f"  - [{node.id}] {props_str}")

        lines.append(f"\n### Relationships ({len(edges)} edges)")
        edge_summary = defaultdict(int)
        for edge in edges:
            src_type = nodes[edge.source].type if edge.source in nodes else "?"
            tgt_type = nodes[edge.target].type if edge.target in nodes else "?"
            key = f"({src_type})-[:{edge.relation}]->({tgt_type})"
            edge_summary[key] += 1
        for key, count in sorted(edge_summary.items()):
            lines.append(f"  - {key} x{count}")

        lines.append(f"\n### Sample Relationships")
        shown = set()
        for edge in edges:
            key = edge.relation
            if key not in shown and edge.source in nodes and edge.target in nodes:
                shown.add(key)
                src = nodes[edge.source]
                tgt = nodes[edge.target]
                src_name = src.properties.get("name", src.properties.get("experiment_id", src.id))
                tgt_name = tgt.properties.get("name", tgt.properties.get("experiment_id", tgt.id))
                lines.append(f"  ({src_name}) -[:{edge.relation}]-> ({tgt_name})")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Sample-centric context builder (new version — core fix for "incoherent answers")
    # -------------------------------------------------------------------------

    # 2-hop relations from Organoid: Organoid→X
    _ORGANOID_OUT_RELATIONS = {
        "FROM_ORGAN", "DERIVED_FROM", "MODELS_DISEASE", "HAS_APPLICATION"
    }
    # Inferred relation markers
    _INFERRED_RELATIONS = {"TREATS_DISEASE", "INDICATES_DISEASE"}

    # Sample node summary properties (shown in card header)
    _SAMPLE_SUMMARY_KEYS = ["organ", "organism", "source", "culture_days",
                            "application_strategy", "gene_name"]

    def _build_sample_context(self, seed_results: list, subgraph: dict,
                              max_samples: int = 30) -> str:
        """Reorganize subgraph around samples into LLM-readable evidence text.

        Each matched sample forms an evidence card, showing related entities
        as a tree of edges. Organoid→X 2-hop relations are indented under
        HAS_ORGANOID.

        Args:
            seed_results: [(node, score), ...] from search()
            subgraph: {"nodes": [...], "edges": [...]} from traverse()
            max_samples: Maximum number of samples to display (prevent token explosion)

        Returns:
            Markdown text organized by sample
        """
        # Build indices within subgraph
        sub_node_ids = {n.id for n in subgraph["nodes"]}
        sub_node_map = {n.id: n for n in subgraph["nodes"]}
        # source → [(relation, target_id, edge_props)]
        adj_out: Dict[str, List[Tuple[str, str, dict]]] = defaultdict(list)
        for e in subgraph["edges"]:
            if e.source in sub_node_ids and e.target in sub_node_ids:
                adj_out[e.source].append((e.relation, e.target, e.properties))

        lines = ["## Retrieved Evidence\n"]

        sample_count = 0
        for seed_node, _ in seed_results:
            # Backtrack upward: if the seed is not a Sample, find its Sample parent node in reverse
            sample = self._resolve_sample(seed_node, sub_node_map, adj_out)

            if sample is None:
                # Current seed has no Sample association in subgraph → fall back to direct display
                sample = seed_node
            elif sample.id != seed_node.id and sample_count >= max_samples:
                continue

            if sample_count >= max_samples:
                break
            sample_count += 1

            is_seed = (sample.id == seed_node.id)
            is_sample_type = (sample.type == "Sample")

            # --- Card header ---
            header = f"### {'Sample' if is_sample_type else sample.type} {sample.id}"
            if is_sample_type:
                # Summary row: take a few key fields from Sample properties
                snippets = []
                for key in self._SAMPLE_SUMMARY_KEYS:
                    v = sample.properties.get(key)
                    if v is not None and v != "" and v != []:
                        snippet = str(v)
                        if len(snippet) > 80:
                            snippet = snippet[:77] + "..."
                        snippets.append(f"{key}={snippet}")
                if snippets:
                    header += "\n  " + " | ".join(str(s)[:60] for s in snippets)
            lines.append(header)

            if not is_sample_type:
                lines.append("")

            # --- Edges originating from this node ---
            if sample.id in adj_out:
                lines.extend(self._format_edges_tree(
                    sample.id, adj_out, sub_node_map, indent=0))
            elif is_sample_type:
                lines.append("  (no connections in retrieved subgraph)")

            lines.append("")

        if sample_count == 0:
            lines.append("_(no sample context resolved from search results)_\n")

        if sample_count >= max_samples:
            lines.append(f"... truncated at {max_samples} samples for readability\n")

        return "\n".join(lines)

    def _resolve_sample(self, node: GraphNode, node_map: Dict[str, GraphNode],
                        adj_out: Dict[str, list]) -> Optional[GraphNode]:
        """If node is not a Sample, backtrack along reverse edges to find the
        associated Sample node.

        Reverse edge matching: find which nodes have edges pointing to this node,
        prefer Sample type. Use BFS with at most 2 backtracking layers to avoid
        infinite search.
        """
        if node.type == "Sample":
            return node

        # Build reverse index: target → [source_node_ids]
        rev: Dict[str, List[str]] = defaultdict(list)
        for src_id, edges in adj_out.items():
            for _rel, tgt_id, _props in edges:
                rev[tgt_id].append(src_id)

        from collections import deque
        visited = {node.id}
        queue = deque([node.id])
        depth = 0
        while queue and depth < 2:
            for _ in range(len(queue)):
                cur = queue.popleft()
                for src_id in rev.get(cur, []):
                    if src_id in visited:
                        continue
                    visited.add(src_id)
                    src_node = node_map.get(src_id)
                    if src_node is None:
                        continue
                    if src_node.type == "Sample":
                        return src_node
                    queue.append(src_id)
            depth += 1

        # Cannot backtrack to Sample: return the original node
        return node

    def _format_edges_tree(self, node_id: str,
                           adj_out: Dict[str, list],
                           node_map: Dict[str, GraphNode],
                           indent: int = 0) -> List[str]:
        """Recursively format the edge tree starting from node_id.

        Args:
            node_id: Current node ID
            adj_out: Outgoing edge adjacency list
            node_map: node_id → GraphNode
            indent: Indentation level (0=first level from Sample)

        Returns:
            Formatted line list
        """
        prefix_chars = ["├── ", "└── "]
        indent_prefix = "│   " * indent
        lines = []

        edges = adj_out.get(node_id, [])
        for i, (relation, tgt_id, edge_props) in enumerate(edges):
            tgt_node = node_map.get(tgt_id)
            if tgt_node is None:
                continue

            is_last = (i == len(edges) - 1)
            branch = prefix_chars[1] if is_last else prefix_chars[0]

            tgt_name = tgt_node.properties.get("name", tgt_node.id)
            # Truncate overly long names (e.g. full JSON for Technology) to avoid wasting tokens
            if isinstance(tgt_name, str) and len(tgt_name) > 80:
                tgt_name = tgt_name[:77] + "..."
            label = f"{tgt_node.type} \"{tgt_name}\" ({tgt_id})"

            # Inferred relation marker
            inferred = " [inferred]" if relation in self._INFERRED_RELATIONS else ""

            # Extra edge properties
            extra = ""
            if edge_props:
                extras = []
                for k, v in edge_props.items():
                    if k in ("confidence",) and relation in self._INFERRED_RELATIONS:
                        extras.append(f"{k}={v}")
                    elif k not in ("source_column", "context", "confidence") and v:
                        extras.append(f"{k}={v}")
                if extras:
                    extra = f"  [{', '.join(extras)}]"

            lines.append(f"{indent_prefix}{branch}{relation}{inferred} → {label}{extra}")

            # For Organoid→X 2-hop from Organoid, go one level deeper
            if relation in self._ORGANOID_OUT_RELATIONS:
                # Don't recurse deeper, just indent one more level (Organoid itself doesn't expand its outgoing edges)
                pass

            # If the target node has outgoing edges in the subgraph and is not an already shown Organoid expansion,
            # expand one level more (only for non-inferred relations, to control depth)
            if (relation not in self._INFERRED_RELATIONS
                    and relation not in self._ORGANOID_OUT_RELATIONS
                    and tgt_id in adj_out
                    and indent < 1):  # Only expand one level
                child_lines = self._format_edges_tree(
                    tgt_id, adj_out, node_map, indent + 1)
                lines.extend(child_lines)

        return lines

    # -------------------------------------------------------------------------
    # GraphRAG Q&A
    # -------------------------------------------------------------------------

    PROMPT_TEMPLATE = """You are a scientific assistant for organoid culture and 3D cell biology research.
Answer the user's question based ONLY on the evidence provided below.
Each "Sample" block is a recorded experiment with its connected entities shown as a tree.

## Evidence
{context}

## User Question
{question}

## Instructions
- Each sample block shows its relationships: ├── RELATION → EntityType "name" (id).
- Edges marked [inferred] have lower confidence — note this when using them.
- The context is a SUBSET of the full knowledge graph; do not treat the sample count here as the global total.
- When the question asks for counts or totals, count from what you see but note the limit (e.g., "at least N samples found in the retrieved subset").
- Cite specific sample IDs, organoid names, drug names, or gene names.
- Use bullet points when listing multiple items.
- End with a "Sources:" line listing the specific node IDs you referenced.
- If the evidence is insufficient, clearly state what is missing.
- Be concise.

## Answer"""

    def ask(self, question: str,
            api_key: str = None,
            base_url: str = None,
            model: str = "gpt-4o",
            top_k: int = 20,
            traversal_depth: int = 1,
            max_samples: int = 30,
            verbose: bool = False) -> dict:
        """GraphRAG Q&A: retrieve relevant subgraph → LLM generates answer

        Args:
            question: User's natural language question
            api_key: OpenAI API key (or compatible service API key)
            base_url: API base URL (for Ollama/vLLM/DeepSeek and other compatible services)
            model: Model name
            top_k: Number of seed nodes to retrieve
            traversal_depth: Graph traversal depth
            max_samples: Maximum number of samples injected into LLM prompt (default: 30)
            verbose: Whether to print retrieved subgraph info

        Returns:
            {"question": ..., "response": ..., "sources": [...], "subgraph_stats": {...}}
        """
        # Step 1: Keyword search to find seed nodes
        seed_results = self.search(question, top_k=top_k)

        if verbose:
            print(f"\n[Search] Found {len(seed_results)} seed nodes:")
            for node, score in seed_results[:5]:
                name = node.properties.get("name", node.id)
                print(f"  [{node.type}] {name} (score: {score:.2f})")

        # Step 1.5: When initial search yields no results, use LLM to extract English keywords and retry
        if not seed_results and api_key:
            keywords = self._extract_keywords(question, api_key, base_url, model)
            if keywords and verbose:
                print(f"[Search] No results from raw query, LLM extracted keywords: {keywords}")
            if keywords:
                seed_results = self.search(keywords, top_k=top_k)
                if verbose:
                    print(f"[Search] Retry with keywords → {len(seed_results)} seed nodes")

        if not seed_results:
            return {
                "question": question,
                "response": "No relevant information found in the knowledge graph for this question.",
                "sources": [],
                "subgraph_stats": {"nodes": 0, "edges": 0}
            }

        # Step 2: Graph traversal from seed nodes, expand subgraph
        all_nodes = set()
        all_edges = set()
        source_ids = []

        for seed_node, _ in seed_results:
            sub = self.traverse(seed_node.id, depth=traversal_depth)
            for n in sub["nodes"]:
                all_nodes.add(n.id)
            for e in sub["edges"]:
                edge_key = e.id or f"{e.source}-{e.relation}-{e.target}"
                all_edges.add(edge_key)
            source_ids.append(seed_node.id)

        subgraph = {
            "nodes": [self.nodes[nid] for nid in all_nodes],
            "edges": [e for e in self.edges if (e.id or f"{e.source}-{e.relation}-{e.target}") in all_edges]
        }

        if verbose:
            print(f"[Traverse] Subgraph: {len(subgraph['nodes'])} nodes, {len(subgraph['edges'])} edges")

        # Step 3: Build sample-centric LLM context
        context = self._build_sample_context(seed_results, subgraph, max_samples=max_samples)
        prompt = self.PROMPT_TEMPLATE.format(context=context, question=question)

        # Step 4: Call LLM
        try:
            response_text = self._call_llm(prompt, api_key, base_url, model)
        except Exception as e:
            response_text = f"[Error calling LLM]: {e}\n\nRetrieved subgraph context (without LLM answer):\n\n{context}"

        return {
            "question": question,
            "response": response_text,
            "sources": source_ids,
            "subgraph_stats": {
                "nodes": len(subgraph["nodes"]),
                "edges": len(subgraph["edges"]),
                "seed_nodes": len(seed_results)
            }
        }

    def _call_llm(self, prompt: str, api_key: str, base_url: str, model: str) -> str:
        """Call LLM API (supports OpenAI and compatible services)"""
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return "[Error] No API key provided. Set --api-key or OPENAI_API_KEY environment variable."

        try:
            from openai import OpenAI
        except ImportError:
            return "[Error] openai package not installed. Run: pip install openai"

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = OpenAI(**client_kwargs)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a precise, evidence-based scientific assistant. Only answer based on provided context."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )

        return response.choices[0].message.content

    def _extract_keywords(self, question: str, api_key: str,
                          base_url: str, model: str) -> Optional[str]:
        """When questions cannot directly match search, let LLM extract English keywords

        Args:
            question: User's question
            api_key / base_url / model: LLM configuration

        Returns:
            Space-separated English keyword string, or None on failure
        """
        prompt = f"""You are a keyword extraction assistant for a knowledge graph search engine.

The knowledge graph contains organoid culture data with these node types:
Sample, Organoid, Organ, System, Organism, Source, CellFactor, Technology, Drug,
Gene, DiseaseModel, Infection, Biomarker, Phenotype, Omics, Composition,
Application, Publication.

Key relationships include: HAS_ORGANOID, FROM_ORGAN, USES_FACTOR, SCREENS_DRUG,
HAS_GENE_EDIT, MODELS_DISEASE, HAS_INFECTION, HAS_BIOMARKER, HAS_PHENOTYPE,
HAS_OMICS, HAS_COMPOSITION, TREATS_DISEASE, INDICATES_DISEASE.

A user asks a question about the organoid knowledge graph.
Your task: extract 3-8 English keywords that best represent the search intent.
Only output the keywords separated by spaces. No explanation, no Chinese.

Examples:
Q: "Which culture conditions favor intestinal organoid differentiation?"
Keywords: intestinal organoid differentiation culture condition EGF Wnt R-spondin

Q: "What is the role of EGF in organoid culture? Which samples used EGF?"
Keywords: EGF cell factor Sample USES_FACTOR

Q: "List organoid models used for colorectal cancer research and the drugs they used."
Keywords: colorectal cancer DiseaseModel organoid Drug SCREENS_DRUG

Q: "Compare differences in culture conditions between human and mouse intestinal organoids"
Keywords: Human Mouse intestinal organoid Organism

Q: "Which biomarkers are associated with inflammatory bowel disease?"
Keywords: inflammatory bowel disease IBD Biomarker INDICATES_DISEASE DiseaseModel

Q: "{question}"
Keywords:"""

        try:
            result = self._call_llm(prompt, api_key, base_url, model)
            # Clean output: take only the first line, remove extra whitespace
            line = result.strip().split("\n")[0].strip()
            # Remove possible quotes, prefix labels
            for prefix in ("Keywords:", "keywords:"):
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
            # Validate: at least 1 space-separated word
            if len(line.split()) >= 1:
                return line
            return None
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # Statistics and Analysis
    # -------------------------------------------------------------------------

    def _build_global_stats(self) -> str:
        """Generate global graph statistics text, inject into LLM prompt to prevent counting hallucinations"""
        from collections import Counter
        ntc = Counter(n.type for n in self.nodes.values())
        etc = Counter(e.relation for e in self.edges)

        lines = []
        lines.append(f"- Total nodes: {len(self.nodes):,}")
        lines.append(f"- Total edges: {len(self.edges):,}")
        lines.append(f"- Node types ({len(ntc)}):")
        for t, c in ntc.most_common():
            lines.append(f"    {t}: {c:,}")
        lines.append(f"- Relationship types ({len(etc)}):")
        for r, c in etc.most_common():
            lines.append(f"    {r}: {c:,}")
        return "\n".join(lines)

    def stats(self) -> dict:
        """Return graph statistics"""
        node_types = defaultdict(int)
        for node in self.nodes.values():
            node_types[node.type] += 1

        edge_relations = defaultdict(int)
        for edge in self.edges:
            edge_relations[edge.relation] += 1

        # Degree distribution
        degrees = [len(self._adjacency[nid]) for nid in self.nodes]
        avg_degree = sum(degrees) / len(degrees) if degrees else 0

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "nodes_by_type": dict(sorted(node_types.items(), key=lambda x: x[1], reverse=True)),
            "edges_by_relation": dict(sorted(edge_relations.items(), key=lambda x: x[1], reverse=True)),
            "avg_degree": round(avg_degree, 2),
            "max_degree": max(degrees) if degrees else 0,
            "isolated_nodes": sum(1 for d in degrees if d == 0)
        }

    def print_stats(self):
        """Print graph statistics"""
        s = self.stats()
        print(f"\n{'='*60}")
        print(f"  Knowledge Graph Statistics")
        print(f"{'='*60}")
        print(f"  Total nodes:       {s['total_nodes']:>8d}")
        print(f"  Total edges:       {s['total_edges']:>8d}")
        print(f"  Average degree:    {s['avg_degree']:>8.2f}")
        print(f"  Max degree:        {s['max_degree']:>8d}")
        print(f"  Isolated nodes:    {s['isolated_nodes']:>8d}")
        print(f"\n  Nodes by type:")
        for ntype, count in s["nodes_by_type"].items():
            print(f"    {ntype:25s}: {count:>6d}")
        print(f"\n  Edges by relation:")
        for rel, count in s["edges_by_relation"].items():
            print(f"    {rel:25s}: {count:>6d}")


# =============================================================================
# CLI
# =============================================================================

def run_interactive(kg: KnowledgeGraphQuery, api_key: str, base_url: str, model: str):
    """Interactive Q&A mode"""
    print(f"\n{'='*60}")
    print(f"  Organoid Knowledge Graph - Interactive Q&A")
    print(f"  Model: {model}")
    print(f"  Type 'quit' to exit, 'stats' for statistics, ':search <kw>' for search")
    print(f"{'='*60}\n")

    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() == "quit":
            break
        if question.lower() == "stats":
            kg.print_stats()
            continue
        if question.startswith(":search "):
            query = question[8:]
            results = kg.search(query, top_k=10)
            for node, score in results:
                name = node.properties.get("name", node.properties.get("experiment_id", node.id))
                print(f"  [{node.type}] {name} (score: {score:.2f}) — {node.id}")
            continue
        if question.startswith(":subgraph "):
            node_id = question[10:].strip()
            sub = kg.traverse(node_id, depth=2)
            print(f"  Subgraph for {node_id}: {len(sub['nodes'])} nodes, {len(sub['edges'])} edges")
            for node in sub["nodes"]:
                print(f"    [{node.type}] {node.id}")
            continue

        # GraphRAG Q&A
        print(f"\n  Searching knowledge graph...")
        result = kg.ask(question, api_key=api_key, base_url=base_url, model=model, verbose=True)

        print(f"\n{'─'*60}")
        print(result["response"])
        print(f"{'─'*60}")
        print(f"  Sources: {', '.join(result['sources'][:5])}")
        print(f"  Subgraph: {result['subgraph_stats']['nodes']} nodes, {result['subgraph_stats']['edges']} edges\n")


def main():
    parser = argparse.ArgumentParser(
        description="Organoid Knowledge Graph Query Tool with LLM GraphRAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive Q&A mode
  python query_tool.py --graph organoid_kg.json --api-key sk-xxx --interactive

  # Single question
  python query_tool.py --graph organoid_kg.json --api-key sk-xxx --question "Which conditions support intestinal organoid growth?"

  # Search without LLM
  python query_tool.py --graph organoid_kg.json --search "EGF Matrigel"

  # Show statistics
  python query_tool.py --graph organoid_kg.json --stats

  # View a node's subgraph
  python query_tool.py --graph organoid_kg.json --subgraph exp_001

  # Use Ollama local model
  python query_tool.py --graph organoid_kg.json --base-url http://localhost:11434/v1 \\
      --model llama3 --interactive
        """
    )

    parser.add_argument("--graph", required=True, help="Path to knowledge graph file (.json or .sqlite)")

    # LLM configuration
    parser.add_argument("--api-key", help="OpenAI API key (or compatible). Can also set OPENAI_API_KEY env var")
    parser.add_argument("--base-url", help="API base URL for compatible services (Ollama, vLLM, DeepSeek, etc.)")
    parser.add_argument("--model", default="gpt-4o", help="LLM model name (default: gpt-4o)")

    # Operation modes
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive Q&A mode")
    parser.add_argument("--question", "-q", help="Ask a single question using GraphRAG")
    parser.add_argument("--search", "-s", help="Search nodes by keyword (no LLM)")
    parser.add_argument("--subgraph", help="Show subgraph for a node ID")
    parser.add_argument("--stats", action="store_true", help="Print knowledge graph statistics")

    # Search parameters
    parser.add_argument("--top-k", type=int, default=20, help="Number of seed nodes to retrieve (default: 20)")
    parser.add_argument("--depth", type=int, default=1, help="Graph traversal depth (default: 1)")

    args = parser.parse_args()

    # Load graph
    kg = KnowledgeGraphQuery.load(args.graph)

    # --stats mode
    if args.stats:
        kg.print_stats()
        return

    # --search mode
    if args.search:
        results = kg.search(args.search, top_k=args.top_k)
        print(f"\nSearch results for: \"{args.search}\"\n")
        for node, score in results:
            name = node.properties.get("name", node.properties.get("experiment_id", node.id))
            print(f"[{node.type}] {name} (relevance: {score:.2f})")
            props_str = ", ".join(f"{k}={v}" for k, v in list(node.properties.items())[:5])
            print(f"  {props_str}")
            print(f"  ID: {node.id}\n")
        if not results:
            print("No results found.")
        return

    # --subgraph mode
    if args.subgraph:
        sub = kg.traverse(args.subgraph, depth=args.depth)
        print(f"\nSubgraph for: {args.subgraph}")
        print(f"  Nodes: {len(sub['nodes'])}, Edges: {len(sub['edges'])}")
        print(f"\nNodes:")
        for node in sub["nodes"]:
            name = node.properties.get("name", node.properties.get("experiment_id", node.id))
            print(f"  [{node.type}] {name}")
        print(f"\nEdges:")
        for edge in sub["edges"]:
            src = kg.nodes[edge.source] if edge.source in kg.nodes else None
            tgt = kg.nodes[edge.target] if edge.target in kg.nodes else None
            src_name = src.properties.get("name", edge.source) if src else edge.source
            tgt_name = tgt.properties.get("name", edge.target) if tgt else edge.target
            print(f"  ({src_name}) -[:{edge.relation}]-> ({tgt_name})")
        return

    # --question single Q&A
    if args.question:
        result = kg.ask(
            args.question,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            top_k=args.top_k,
            traversal_depth=args.depth,
            verbose=True
        )
        print(f"\n{'─'*60}")
        print(result["response"])
        print(f"{'─'*60}")
        print(f"Sources: {', '.join(result['sources'][:10])}")
        print(f"Subgraph: {result['subgraph_stats']['nodes']} nodes, {result['subgraph_stats']['edges']} edges")
        return

    # --interactive mode
    if args.interactive:
        run_interactive(kg, args.api_key, args.base_url, args.model)
        return

    # Default: show statistics
    parser.print_help()
    print()
    kg.print_stats()


if __name__ == "__main__":
    # argparse may not be imported yet, import in main()
    import argparse
    main()
