#!/usr/bin/env python3
"""
export_for_gephi.py — Export knowledge graph to formats supported by Gephi visualization software

Supported formats:
  - GEXF (.gexf) — Gephi native format, supports node/edge attributes, colors, labels (recommended)
  - GML  (.gml)  — Simple text format, good compatibility
  - CSV  (.csv)  — Dual-file export (nodes.csv + edges.csv), most universal

Usage:
  # Export to GEXF (recommended)
  python export_for_gephi.py organoid-kg-output/2026-07-19-1138/organoid_kg.json

  # Specify output format and path
  python export_for_gephi.py kg.json --format gexf --output my_graph.gexf

  # Sampled export (for large graph preview, randomly select N Sample nodes and their 1-2 hop neighbors)
  python export_for_gephi.py kg.json --sample 500

  # Export only specified node types and their associated edges
  python export_for_gephi.py kg.json --node-types Sample,Organ,Drug

  # Export as CSV dual files
  python export_for_gephi.py kg.json --format csv --output-dir ./gephi_export
"""

import json
import os
import sys
import random
import argparse
import xml.sax.saxutils as saxutils
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

# Import query_tool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from query_tool import KnowledgeGraphQuery

# =============================================================================
# Node type → Gephi visualization color (RGB)
# =============================================================================

NODE_TYPE_COLORS = {
    "Sample":        (74, 144, 226),   # Blue — core entity
    "Organ":         (126, 211, 33),   # Green — organ
    "System":        (0, 128, 0),      # Dark green — physiological system
    "Organism":      (208, 2, 27),     # Red — species
    "Source":        (184, 233, 134),  # Light green — source
    "CellFactor":    (144, 19, 254),   # Purple — cell factor
    "Technology":    (74, 144, 226),   # Light blue — technology
    "Drug":          (245, 166, 35),   # Orange-yellow — drug
    "Gene":          (208, 2, 27),     # Red — gene
    "DiseaseModel":  (255, 77, 77),    # Light red — disease model
    "Infection":     (139, 87, 42),    # Brown — infection
    "Biomarker":     (80, 227, 194),   # Cyan — biomarker
    "Phenotype":     (248, 231, 28),   # Yellow — phenotype
    "Omics":         (189, 16, 224),   # Magenta — omics
    "Composition":   (255, 153, 204),  # Pink — cell composition
    "Application":   (0, 168, 168),    # Teal — application
    "Publication":   (155, 155, 155),  # Gray — publication
}

# Relationship type → edge color
EDGE_TYPE_COLORS = {
    "FROM_ORGAN":          (126, 211, 33),
    "BELONGS_TO_SYSTEM":   (0, 128, 0),
    "FROM_ORGANISM":       (208, 2, 27),
    "DERIVED_FROM":        (184, 233, 134),
    "USES_FACTOR":         (144, 19, 254),
    "USES_TECHNOLOGY":     (74, 144, 226),
    "SCREENS_DRUG":        (245, 166, 35),
    "HAS_GENE_EDIT":       (208, 2, 27),
    "MODELS_DISEASE":      (255, 77, 77),
    "HAS_INFECTION":       (139, 87, 42),
    "HAS_BIOMARKER":       (80, 227, 194),
    "HAS_PHENOTYPE":       (248, 231, 28),
    "HAS_OMICS":           (189, 16, 224),
    "HAS_COMPOSITION":     (255, 153, 204),
    "HAS_APPLICATION":     (0, 168, 168),
    "CITES":               (155, 155, 155),
    "TREATS_DISEASE":      (255, 77, 77),
    "INDICATES_DISEASE":   (80, 227, 194),
}


def _node_label(node) -> str:
    """Generate a readable node label"""
    props = node.properties
    name = props.get("name") or props.get("sample_id") or props.get("canonical_name") or node.id
    name = str(name)
    # Truncate overly long labels
    return name[:60] + "…" if len(name) > 60 else name


def _clean_xml_text(text: str) -> str:
    """Clean text: remove XML-invalid characters, escape special symbols"""
    if not isinstance(text, str):
        text = str(text)
    # Remove control characters disallowed in XML 1.0 (except \t \n \r)
    import re
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', text)
    # Escape XML special characters (including double quotes, to avoid breaking attribute values)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    # Single quotes are safe in double-quoted attributes, but escaping them uniformly is safer
    text = text.replace("'", "&apos;")
    return text


def _xml_escape(text: str) -> str:
    """XML escape (backwards-compatible interface)"""
    return _clean_xml_text(str(text))


def _sample_subgraph(kg: KnowledgeGraphQuery, n_samples: int = 500) -> Set[str]:
    """Randomly sample from Sample nodes and take their k-hop neighbor subgraph"""
    sample_ids = [nid for nid, n in kg.nodes.items() if n.type == "Sample"]
    if len(sample_ids) <= n_samples:
        seeds = sample_ids
    else:
        seeds = random.sample(sample_ids, n_samples)

    selected: Set[str] = set()
    for seed in seeds:
        sub = kg.traverse(seed, depth=1)
        selected.add(seed)
        for n in sub["nodes"]:
            selected.add(n.id)

    print(f"[INFO] Sampled {len(seeds)} seeds → {len(selected)} nodes in subgraph")
    return selected


def _filter_by_types(kg: KnowledgeGraphQuery,
                     node_types: List[str]) -> Set[str]:
    """Keep only nodes of the specified types, and the edges between them"""
    allowed_nodes = {nid for nid, n in kg.nodes.items() if n.type in node_types}
    return allowed_nodes


# =============================================================================
# GEXF export (recommended)
# =============================================================================

def export_gexf(kg: KnowledgeGraphQuery, path: str,
                allowed_nodes: Optional[Set[str]] = None):
    """Export as GEXF 1.3 format"""
    # Collect nodes and edges to export
    if allowed_nodes is not None:
        nodes_to_export = {nid: kg.nodes[nid] for nid in allowed_nodes if nid in kg.nodes}
        edges_to_export = [e for e in kg.edges
                           if e.source in allowed_nodes and e.target in allowed_nodes]
    else:
        nodes_to_export = kg.nodes
        edges_to_export = kg.edges

    # ID mapping: ensure GEXF ids contain no special characters
    node_id_map = {nid: f"n_{i}" for i, nid in enumerate(nodes_to_export.keys())}

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<gexf xmlns="http://www.gexf.net/1.3" '
                 'xmlns:viz="http://www.gexf.net/1.3/viz" version="1.3">')

    # Graph metadata
    lines.append(f'  <meta lastmodifieddate="{_xml_escape(str(kg.meta.get("created", "")))}">')
    lines.append(f'    <creator>export_for_gephi.py</creator>')
    lines.append(f'    <description>Organoid Culture Knowledge Graph</description>')
    lines.append(f'  </meta>')

    lines.append('  <graph mode="static" defaultedgetype="directed">')

    # Node attribute definitions
    lines.append('    <attributes class="node" mode="static">')
    lines.append('      <attribute id="0" title="type" type="string"/>')
    lines.append('      <attribute id="1" title="name" type="string"/>')
    lines.append('      <attribute id="2" title="node_count" type="integer"/>')
    lines.append('    </attributes>')

    # Edge attribute definitions
    lines.append('    <attributes class="edge" mode="static">')
    lines.append('      <attribute id="0" title="relation" type="string"/>')
    lines.append('      <attribute id="1" title="confidence" type="double"/>')
    lines.append('    </attributes>')

    # Nodes
    lines.append('    <nodes>')
    for orig_id, node in nodes_to_export.items():
        gexf_id = node_id_map[orig_id]
        label = _xml_escape(_node_label(node))
        node_type = _xml_escape(node.type)
        r, g, b = NODE_TYPE_COLORS.get(node.type, (180, 180, 180))

        lines.append(f'      <node id="{gexf_id}" label="{label}">')
        lines.append(f'        <attvalues>')
        lines.append(f'          <attvalue for="0" value="{node_type}"/>')
        lines.append(f'          <attvalue for="1" value="{label}"/>')
        lines.append(f'          <attvalue for="2" value="1"/>')
        lines.append(f'        </attvalues>')
        lines.append(f'        <viz:color r="{r}" g="{g}" b="{b}"/>')
        # Use node degree to determine size (Gephi will use viz:size)
        degree = len(kg._adjacency.get(orig_id, []))
        size = max(3.0, min(20.0, 3.0 + degree * 0.5))
        lines.append(f'        <viz:size value="{size:.1f}"/>')
        lines.append(f'      </node>')
    lines.append('    </nodes>')

    # Edges
    lines.append('    <edges>')
    for i, edge in enumerate(edges_to_export):
        src_gexf = node_id_map.get(edge.source)
        tgt_gexf = node_id_map.get(edge.target)
        if src_gexf is None or tgt_gexf is None:
            continue
        relation = _xml_escape(edge.relation)
        confidence = edge.properties.get("confidence", 0.0)
        r, g, b = EDGE_TYPE_COLORS.get(edge.relation, (128, 128, 128))

        lines.append(f'      <edge id="e_{i}" source="{src_gexf}" target="{tgt_gexf}" '
                     f'label="{relation}" weight="{confidence or 1.0}">')
        lines.append(f'        <attvalues>')
        lines.append(f'          <attvalue for="0" value="{relation}"/>')
        lines.append(f'          <attvalue for="1" value="{confidence}"/>')
        lines.append(f'        </attvalues>')
        lines.append(f'        <viz:color r="{r}" g="{g}" b="{b}"/>')
        lines.append(f'      </edge>')
    lines.append('    </edges>')

    lines.append('  </graph>')
    lines.append('</gexf>')

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[OK] GEXF exported: {path}")
    print(f"     {len(nodes_to_export):,} nodes, {len(edges_to_export):,} edges")


# =============================================================================
# GML export
# =============================================================================

def export_gml(kg: KnowledgeGraphQuery, path: str,
               allowed_nodes: Optional[Set[str]] = None):
    """Export as GML format"""
    if allowed_nodes is not None:
        nodes_to_export = {nid: kg.nodes[nid] for nid in allowed_nodes if nid in kg.nodes}
        edges_to_export = [e for e in kg.edges
                           if e.source in allowed_nodes and e.target in allowed_nodes]
    else:
        nodes_to_export = kg.nodes
        edges_to_export = kg.edges

    lines = []
    lines.append("graph [")
    lines.append("  directed 1")
    lines.append("  multigraph 1")
    lines.append("")

    # Nodes
    for orig_id, node in nodes_to_export.items():
        label = _node_label(node).replace('"', "'")
        r, g, b = NODE_TYPE_COLORS.get(node.type, (180, 180, 180))
        lines.append("  node [")
        lines.append(f'    id "{orig_id}"')
        lines.append(f'    label "{label}"')
        lines.append(f'    type "{node.type}"')
        lines.append(f'    red {r}')
        lines.append(f'    green {g}')
        lines.append(f'    blue {b}')
        degree = len(kg._adjacency.get(orig_id, []))
        lines.append(f'    degree {degree}')
        lines.append("  ]")

    # Edges
    for edge in edges_to_export:
        confidence = edge.properties.get("confidence", 0.0)
        lines.append("  edge [")
        lines.append(f'    source "{edge.source}"')
        lines.append(f'    target "{edge.target}"')
        lines.append(f'    label "{edge.relation}"')
        lines.append(f'    relation "{edge.relation}"')
        lines.append(f'    confidence {confidence}')
        lines.append("  ]")

    lines.append("]")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[OK] GML exported: {path}")
    print(f"     {len(nodes_to_export):,} nodes, {len(edges_to_export):,} edges")


# =============================================================================
# CSV export (dual files)
# =============================================================================

def export_csv(kg: KnowledgeGraphQuery, output_dir: str,
               allowed_nodes: Optional[Set[str]] = None):
    """Export as nodes.csv + edges.csv"""
    if allowed_nodes is not None:
        nodes_to_export = {nid: kg.nodes[nid] for nid in allowed_nodes if nid in kg.nodes}
        edges_to_export = [e for e in kg.edges
                           if e.source in allowed_nodes and e.target in allowed_nodes]
    else:
        nodes_to_export = kg.nodes
        edges_to_export = kg.edges

    os.makedirs(output_dir, exist_ok=True)

    # nodes.csv
    nodes_path = os.path.join(output_dir, "nodes.csv")
    with open(nodes_path, "w", encoding="utf-8") as f:
        f.write("id,label,type,name,degree\n")
        for orig_id, node in nodes_to_export.items():
            label = _node_label(node).replace('"', "'")
            name = str(node.properties.get("name", "")).replace('"', "'")
            degree = len(kg._adjacency.get(orig_id, []))
            f.write(f'"{orig_id}","{label}","{node.type}","{name}",{degree}\n')
    print(f"[OK] Nodes CSV: {nodes_path} ({len(nodes_to_export):,} rows)")

    # edges.csv
    edges_path = os.path.join(output_dir, "edges.csv")
    with open(edges_path, "w", encoding="utf-8") as f:
        f.write("source,target,relation,confidence\n")
        for edge in edges_to_export:
            conf = edge.properties.get("confidence", "")
            f.write(f'"{edge.source}","{edge.target}","{edge.relation}",{conf}\n')
    print(f"[OK] Edges CSV: {edges_path} ({len(edges_to_export):,} rows)")

    print(f"\n[INFO] Import steps in Gephi:")
    print(f"       1. File → Import Spreadsheet")
    print(f"       2. Import {nodes_path} first (As table: Nodes)")
    print(f"       3. Then import {edges_path} (As table: Edges)")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Export knowledge graph to Gephi visualization formats")
    parser.add_argument("kg_file", help="Path to KG JSON file")
    parser.add_argument("--format", "-f", choices=["gexf", "gml", "csv"],
                        default="gexf", help="Output format (default: gexf)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output file path (CSV mode requires --output-dir)")
    parser.add_argument("--output-dir", "-d", default="./gephi_export",
                        help="Output directory for CSV mode (default: ./gephi_export)")
    parser.add_argument("--sample", "-s", type=int, default=0,
                        help="Randomly sample N Sample nodes and their neighbors (0=full export)")
    parser.add_argument("--node-types", "-t", default=None,
                        help="Export only specified node types, comma-separated (e.g.: Sample,Organ,Drug)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    args = parser.parse_args()

    # Load the KG
    print(f"[INFO] Loading KG: {args.kg_file}")
    kg = KnowledgeGraphQuery.load(args.kg_file)
    print(f"       {len(kg.nodes):,} nodes, {len(kg.edges):,} edges")

    # Determine export scope
    allowed_nodes: Optional[Set[str]] = None

    if args.node_types:
        types = [t.strip() for t in args.node_types.split(",")]
        allowed_nodes = _filter_by_types(kg, types)
        print(f"[INFO] Filtered to types {types}: {len(allowed_nodes):,} nodes")

    if args.sample > 0:
        random.seed(args.seed)
        allowed_nodes = _sample_subgraph(kg, args.sample)

    if allowed_nodes is not None:
        # Count filtered edges
        edge_count = sum(1 for e in kg.edges
                         if e.source in allowed_nodes and e.target in allowed_nodes)
        print(f"[INFO] Export scope: {len(allowed_nodes):,} nodes, ~{edge_count:,} edges")
    else:
        print(f"[INFO] Export scope: FULL ({len(kg.nodes):,} nodes, {len(kg.edges):,} edges)")

    # Export
    if args.format == "gexf":
        output = args.output or "organoid_kg.gexf"
        export_gexf(kg, output, allowed_nodes)
    elif args.format == "gml":
        output = args.output or "organoid_kg.gml"
        export_gml(kg, output, allowed_nodes)
    elif args.format == "csv":
        output_dir = args.output or args.output_dir
        export_csv(kg, output_dir, allowed_nodes)

    # Print usage tips
    print(f"\n[Gephi] Recommended actions after import:")
    print(f"  1. Top-left Appearance → Nodes → Color → Partition → select 'type' → Apply")
    print(f"  2. Appearance → Nodes → Size → Ranking → select 'degree' → Apply")
    print(f"  3. Layout → select ForceAtlas 2 or Yifan Hu → Run")
    print(f"  4. Preview → Refresh to check the result, adjust edge transparency")


if __name__ == "__main__":
    main()
