#!/usr/bin/env python3
"""
import_to_neo4j.py — Batch import knowledge graph to Neo4j database

Uses the official neo4j Python driver to efficiently import nodes and edges
with batch processing and progress tracking.

Requirements:
  pip install neo4j tqdm

Usage:
  # Import from JSON
  python import_to_neo4j.py --graph organoid_kg.json --uri bolt://localhost:7687 --user neo4j --password your_password

  # Clear existing data first
  python import_to_neo4j.py --graph organoid_kg.json --uri bolt://localhost:7687 --user neo4j --password your_password --clear

  # Use environment variable for password
  set NEO4J_PASSWORD=your_password
  python import_to_neo4j.py --graph organoid_kg.json --uri bolt://localhost:7687 --user neo4j
"""

import json
import argparse
import os
import sys
from typing import Dict, List
from tqdm import tqdm

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _scalarize(value):
    """Collapse one nested dict/list level into a Neo4j-safe scalar.

    Neo4j node properties must be primitives or arrays of primitives — the
    KG JSON has compound values (e.g. {"src": ..., "std": ...} src/std pairs,
    {"id": ..., "name": ...} time-anchor references) that violate this.
    Prefers a 'std'/'name'/'id' field if present, else falls back to a
    compact JSON string so no information is silently dropped.
    """
    if isinstance(value, dict):
        for key in ("std", "name", "id"):
            if key in value and not isinstance(value[key], (dict, list)):
                return value[key]
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, list):
        return [_scalarize(v) for v in value]
    return value


def _sanitize_properties(properties: dict) -> dict:
    """Make a node's properties dict safe for Neo4j (`SET n += properties`)."""
    return {k: _scalarize(v) for k, v in properties.items()}


def _run_batch_tx(tx, query, batch):
    """Execute a single batch query within a managed transaction."""
    tx.run(query, batch=batch)


def import_to_neo4j(kg_path: str, uri: str, user: str, password: str,
                    database: str = "neo4j", batch_size: int = 200, clear_db: bool = False):
    """Import knowledge graph to Neo4j with batch processing

    Each batch runs inside its own managed transaction (execute_write) so
    memory is released between batches — avoids MemoryPoolOutOfMemoryError
    when importing large graphs.
    """

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Error: neo4j package not installed. Run: pip install neo4j")
        return 1

    print(f"Loading knowledge graph from {kg_path}...")

    # Load graph
    with open(kg_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    print(f"Loaded {len(nodes):,} nodes, {len(edges):,} edges")

    # Connect to Neo4j
    print(f"\nConnecting to Neo4j at {uri}...")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    try:
        # Verify connection
        driver.verify_connectivity()
        print("✓ Connected to Neo4j")
    except Exception as e:
        print(f"Error: Cannot connect to Neo4j: {e}")
        print("\nMake sure Neo4j is running:")
        print("  - Download: https://neo4j.com/download/")
        print("  - Start: neo4j start")
        print("  - Default URI: bolt://localhost:7687")
        driver.close()
        return 1

    with driver.session(database=database) as session:
        # Clear database if requested
        if clear_db:
            print("\n⚠ Clearing existing database...")
            confirm = input("This will delete all nodes and relationships. Continue? (yes/no): ")
            if confirm.lower() == 'yes':
                session.run("MATCH (n) DETACH DELETE n")
                print("✓ Database cleared")
            else:
                print("Aborted")
                driver.close()
                return 0

        # Import nodes in batches, grouped by label (Cypher can't parameterize
        # labels, but the label set is small and fixed, so group-by-label +
        # UNWIND/MERGE stays fast without needing APOC).
        nodes_by_type: Dict[str, List[dict]] = {}
        for node in nodes:
            nodes_by_type.setdefault(node['type'], []).append(node)

        print(f"\nImporting {len(nodes):,} nodes across {len(nodes_by_type)} labels "
              f"(batch size: {batch_size})...")

        for node_type, type_nodes in tqdm(nodes_by_type.items(), desc="Labels"):
            query = f"""
            UNWIND $batch AS node
            MERGE (n:`{node_type}` {{id: node.id}})
            SET n += node.properties
            """
            for i in range(0, len(type_nodes), batch_size):
                batch = type_nodes[i:i + batch_size]
                session.execute_write(_run_batch_tx, query, [
                    {"id": n["id"], "properties": _sanitize_properties(n.get("properties", {}))}
                    for n in batch
                ])

        print(f"✓ Imported {len(nodes):,} nodes")

        # Create index on node.id for faster edge import
        print("\nCreating index on node.id...")
        node_types = set(n['type'] for n in nodes)
        for node_type in tqdm(node_types, desc="Indexes"):
            index_query = f"CREATE INDEX IF NOT EXISTS FOR (n:{node_type}) ON (n.id)"
            session.run(index_query)

        print(f"✓ Created {len(node_types)} indexes")

        # Full-text index over common text properties, used by chat.py's
        # /search command (falls back to CONTAINS if this isn't present).
        # NOTE: CREATE FULLTEXT INDEX does not support IF NOT EXISTS in Neo4j 5.x,
        # so we drop first (ignoring "index does not exist" errors) and then create.
        print("\nCreating full-text search index...")
        try:
            labels = ", ".join(f"`{t}`" for t in node_types)
            # Drop existing index if it's there (e.g. from a previous import)
            try:
                session.run("DROP INDEX kg_fulltext IF EXISTS")
            except Exception:
                pass  # index didn't exist — fine
            session.run(
                f"CREATE FULLTEXT INDEX kg_fulltext "
                f"FOR (n:{labels}) ON EACH [n.name, n.sample_id, n.search_content, "
                f"n.summary, n.description, n.full_description]"
            )
            print("✓ Created full-text index 'kg_fulltext'")
        except Exception as e:
            print(f"⚠ Could not create full-text index (search will fall back to CONTAINS): {e}")

        # Build an id → type lookup so we can use labeled MATCH (which lets
        # Neo4j use the per-label indexes created above — without a label,
        # MATCH {id: ...} must scan every node in the database).
        id_to_type: Dict[str, str] = {}
        for node in nodes:
            id_to_type[node["id"]] = node["type"]

        # Group edges by (relation, source_type, target_type) so the Cypher
        # query can include both labels and use the per-label indexes.
        edges_by_key: Dict[tuple, List[dict]] = {}
        missing_types = set()
        for edge in edges:
            src_type = id_to_type.get(edge["source"])
            tgt_type = id_to_type.get(edge["target"])
            if src_type is None:
                missing_types.add(edge["source"])
            if tgt_type is None:
                missing_types.add(edge["target"])
            key = (edge["relation"], src_type or "Unknown", tgt_type or "Unknown")
            edges_by_key.setdefault(key, []).append(edge)

        if missing_types:
            print(f"⚠ {len(missing_types)} edge endpoints have no matching node id "
                  f"(will use unlabeled MATCH fallback)")

        print(f"\nImporting {len(edges):,} edges across {len(edges_by_key)} (relation×src×tgt) groups "
              f"(batch size: {batch_size})...")

        for (relation, src_type, tgt_type), rel_edges in tqdm(edges_by_key.items(), desc="Relations"):
            # Build labeled MATCH when we know the node types, falling back to
            # unlabeled MATCH only for edges whose endpoints weren't found.
            if src_type != "Unknown" and tgt_type != "Unknown":
                match_start = f"MATCH (start:`{src_type}` {{id: edge.source}})"
                match_end = f"MATCH (end:`{tgt_type}` {{id: edge.target}})"
            else:
                match_start = "MATCH (start {id: edge.source})"
                match_end = "MATCH (end {id: edge.target})"

            query = f"""
            UNWIND $batch AS edge
            {match_start}
            {match_end}
            CREATE (start)-[r:`{relation}`]->(end)
            SET r += edge.properties
            """
            for i in range(0, len(rel_edges), batch_size):
                batch = rel_edges[i:i + batch_size]
                session.execute_write(_run_batch_tx, query, [
                    {"source": e["source"], "target": e["target"],
                     "properties": _sanitize_properties(e.get("properties", {}))}
                    for e in batch
                ])

        print(f"✓ Imported {len(edges):,} edges")

        # Verify import
        print("\nVerifying import...")
        result = session.run("MATCH (n) RETURN count(n) as node_count").single()
        node_count = result['node_count']
        result = session.run("MATCH ()-[r]->() RETURN count(r) as edge_count").single()
        edge_count = result['edge_count']

        print(f"✓ Neo4j database contains:")
        print(f"  - Nodes: {node_count:,}")
        print(f"  - Edges: {edge_count:,}")

        if node_count != len(nodes):
            print(f"⚠ Warning: Expected {len(nodes):,} nodes, found {node_count:,}")
        if edge_count != len(edges):
            print(f"⚠ Warning: Expected {len(edges):,} edges, found {edge_count:,}")

    driver.close()

    print("\n✓ Import complete!")
    print("\nNext steps:")
    print("  1. Open Neo4j Browser: http://localhost:7474")
    print("  2. Run test query: MATCH (n) RETURN n LIMIT 25")
    print("  3. Use scripts/neo4j_graphrag.py for GraphRAG queries")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Import knowledge graph to Neo4j database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic import
  python import_to_neo4j.py --graph organoid_kg.json

  # Custom Neo4j connection
  python import_to_neo4j.py --graph organoid_kg.json \\
      --uri bolt://localhost:7687 --user neo4j --password your_password

  # Clear database before import
  python import_to_neo4j.py --graph organoid_kg.json --clear

  # Use environment variable for password
  set NEO4J_PASSWORD=your_password
  python import_to_neo4j.py --graph organoid_kg.json
        """)

    parser.add_argument("--graph", required=True,
                        help="Path to organoid_kg.json")
    parser.add_argument("--uri", default="bolt://192.168.24.42:7687",
                        help="Neo4j URI (default: bolt://localhost:7687)")
    parser.add_argument("--user", default="neo4j",
                        help="Neo4j username (default: neo4j)")
    parser.add_argument("--password", default=None,
                        help="Neo4j password (or set NEO4J_PASSWORD env var)")
    parser.add_argument("--batch-size", type=int, default=1000,
                        help="Batch size for import (default: 200)")
    parser.add_argument("--database", default="neo4j",
                        help="Neo4j database name (default: neo4j)")
    parser.add_argument("--clear", action="store_true",
                        help="Clear database before import")

    args = parser.parse_args()

    # Get password from env var if not provided
    password = args.password or os.environ.get("NEO4J_PASSWORD")
    if not password:
        print("Error: Neo4j password required.")
        print("  Use --password or set NEO4J_PASSWORD environment variable")
        return 1

    if not os.path.exists(args.graph):
        print(f"Error: File not found: {args.graph}")
        return 1

    return import_to_neo4j(
        args.graph,
        args.uri,
        args.user,
        password,
        args.database,
        args.batch_size,
        args.clear
    )


if __name__ == "__main__":
    sys.exit(main())
