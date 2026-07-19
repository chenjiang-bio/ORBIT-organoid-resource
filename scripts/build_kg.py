#!/usr/bin/env python3
"""
build_kg.py — Build an organoid culture knowledge graph from a MySQL database

Reference: Knowledge graph construction methodology from MOF-ChemUnity (JACS 2025)

Features:
  1. Connect to MySQL database and automatically explore table structure
  2. Map structured data to knowledge graph nodes and edges
  3. Output JSON format graph file (universal format, downloadable for anyone)
  4. Output SQLite format graph file (supports local SQL queries)

Usage:
  # Explore database structure
  python build_kg.py --host localhost --database organoid_db --user root --password xxx --explore

  # Build knowledge graph (JSON + SQLite)
  python build_kg.py --host localhost --database organoid_db --user root --password xxx \\
      --output-dir ./output --format json sqlite
"""

import json
import sqlite3
import argparse
import sys
import os
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

# =============================================================================
# Configuration — modify here to adapt to your database structure
# =============================================================================

# Default mapping from table to node type (fallback)
DEFAULT_TABLE_MAPPING = {
    "public_general_2026":  {"node_type": "Sample",    "id_prefix": "smp"},
}

# Focus table list — after configuration, explore/build only processes these tables
# Leave empty = iterate all tables
FOCUS_TABLES = ['public_general_2026']

# Manually specify table → node type mapping (priority higher than auto-inference)
# Format: {"table_name": ("node_type", "id_prefix")}
# Especially useful for single wide tables, e.g.: {"public_general_2026": ("Sample", "smp")}
MANUAL_TABLE_TYPES = {
    "public_general_2026": ("Sample", "smp"),
}

# Wide-table column to entity node mapping (for single-table data sources like public_general_2026)
# Format: "column_name": ("node_type", "id_prefix", "relation_name", "edge_origin", "is_json_column")
# Edge origin: "sample" = Sample→Entity, "organoid" = Organoid→Entity
WIDE_TABLE_ENTITY_MAPPING = {
    # === Regular columns → entity nodes (edges from Sample) ===
    "organoid":         ("Organoid",     "org", "HAS_ORGANOID",     "sample"),
    "organism":         ("Organism",     "osm", "FROM_ORGANISM",    "sample"),
    # === Regular columns → entity nodes (edges from Organoid) ===
    "organ":            ("Organ",        "orn", "FROM_ORGAN",       "organoid"),
    "source":           ("Source",       "src", "DERIVED_FROM",     "organoid"),
    "disease_modeling": ("DiseaseModel", "dm",  "MODELS_DISEASE",   "organoid"),
    "application":      ("Application",  "app", "HAS_APPLICATION",  "organoid"),
    "gene_name":        ("Gene",         "gen", "HAS_GENE_EDIT",    "sample"),
    # === Publications ===
    "reference":        ("Publication",  "pub", "CITES",            "sample"),
    # === JSON columns → entity nodes (edges from Sample) ===
    "system":                ("System",      "sys", "BELONGS_TO_SYSTEM", "organ"),
    "cell_factors":          ("CellFactor",  "cf",  "USES_FACTOR",      "sample",    "json"),
    "coculture_cell_factors":("CellFactor",  "cf",  "USES_FACTOR",      "sample",    "json"),
    "techologies":           ("Technology",  "tec", "USES_TECHNOLOGY",  "sample",    "json"),
    "drug_screening":        ("Drug",        "drg", "SCREENS_DRUG",     "sample",    "json"),
    "infection_list":        ("Infection",   "inf", "HAS_INFECTION",    "sample",    "json"),
    "biomarker":             ("Biomarker",   "bmk", "HAS_BIOMARKER",    "sample",    "json"),
    "biomarker_coculture":   ("Biomarker",   "bmk", "HAS_BIOMARKER",    "sample",    "json"),
    "phenotype_identification":("Phenotype", "phn", "HAS_PHENOTYPE",    "sample",    "json"),
    # "test" column abandoned — no node creation, no property storage
    "omics_id":              ("Omics",       "omc", "HAS_OMICS",        "sample",    "json"),
    "composition":           ("Composition", "cmp", "HAS_COMPOSITION",  "sample",    "json"),
}

# Inferred relationship config: (source_entity_col, target_entity_col, source_node_type, target_node_type, relation_name)
INFERRED_RELATIONS = [
    ("drug_screening",      "disease_modeling", "Drug",         "DiseaseModel", "TREATS_DISEASE"),
    ("biomarker",           "disease_modeling", "Biomarker",    "DiseaseModel", "INDICATES_DISEASE"),
    ("biomarker_coculture", "disease_modeling", "Biomarker",    "DiseaseModel", "INDICATES_DISEASE"),
]

# Entity name keys in JSON columns (for extracting names and deduplication from JSON objects)
# If JSON element is a string, use it directly; if it's an object, look up keys in this list
JSON_ENTITY_NAME_KEYS = ["name", "Name", "drug_name", "factor_name", "gene_name",
                          "marker_name", "technology_name", "disease_name",
                          "pathogen_name", "phenotype_name", "cell_type"]
# Co-culture context columns (edge context property set to "coculture")
COCULTURE_COLUMNS = {"coculture_cell_factors", "biomarker_coculture"}


class MySQLKnowledgeGraphBuilder:
    """Build a knowledge graph from a MySQL database"""

    def __init__(self, host: str, port: int, user: str, password: str,
                 database: str, focus_tables: List[str] = None):
        self.connection_params = {
            "host": host, "port": port, "user": user,
            "password": password, "database": database
        }
        self.focus_tables = focus_tables if focus_tables is not None else (FOCUS_TABLES or None)
        self.table_mapping = DEFAULT_TABLE_MAPPING

        # Apply table filtering (focused tables)
        if self.focus_tables:
            filtered = {}
            for table, cfg in self.table_mapping.items():
                for focus in self.focus_tables:
                    if focus.lower() in table.lower():
                        filtered[table] = cfg
                        break
            if filtered:
                self.table_mapping = filtered

        self.conn = None

    # -------------------------------------------------------------------------
    # Database connection and exploration
    # -------------------------------------------------------------------------

    def connect(self):
        """Establish MySQL connection"""
        try:
            import pymysql
            self.conn = pymysql.connect(
                **self.connection_params,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            print(f"[OK] Connected to MySQL: {self.connection_params['host']}/{self.connection_params['database']}")
        except ImportError:
            print("[ERROR] pymysql not installed. Run: pip install pymysql")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Failed to connect to MySQL: {e}")
            sys.exit(1)

    def _filter_tables(self, all_tables: List[str]) -> List[str]:
        """Filter table names based on self.focus_tables (substring match)"""
        if not self.focus_tables:
            return all_tables
        filtered = []
        for table in all_tables:
            for focus in self.focus_tables:
                if focus.lower() in table.lower():
                    filtered.append(table)
                    break
        skipped = set(all_tables) - set(filtered)
        if skipped:
            print(f"[INFO] Focus mode: processing {len(filtered)}/{len(all_tables)} tables "
                  f"(skipped: {', '.join(sorted(skipped))})")
        return filtered

    def explore(self) -> dict:
        """Explore database table structure, return table list and field info (with annotations)"""
        self.connect()
        schema_info = {"tables": {}, "foreign_keys": []}

        with self.conn.cursor() as cursor:
            # Get all tables
            cursor.execute("SHOW TABLES")
            all_tables = [row[list(row.keys())[0]] for row in cursor.fetchall()]
            tables = self._filter_tables(all_tables)

            for table in tables:
                # Get table comment
                table_comment = ""
                try:
                    cursor.execute(f"SHOW TABLE STATUS WHERE Name = '{table}'")
                    status = cursor.fetchone()
                    if status and status.get("Comment"):
                        table_comment = status["Comment"]
                except Exception:
                    pass

                # Get column info (with comments)
                cursor.execute(f"SHOW FULL COLUMNS FROM `{table}`")
                columns = cursor.fetchall()

                # Get row count
                cursor.execute(f"SELECT COUNT(*) as cnt FROM `{table}`")
                row_count = cursor.fetchone()["cnt"]

                schema_info["tables"][table] = {
                    "comment": table_comment,
                    "columns": [
                        {
                            "name": col["Field"],
                            "type": col["Type"],
                            "null": col["Null"],
                            "key": col["Key"],
                            "default": col["Default"],
                            "comment": col.get("Comment", ""),
                        }
                        for col in columns
                    ],
                    "row_count": row_count
                }

            # Get foreign key relationships
            for table in tables:
                cursor.execute(f"""
                    SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                    FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = '{self.connection_params['database']}'
                      AND TABLE_NAME = '{table}'
                      AND REFERENCED_TABLE_NAME IS NOT NULL
                """)
                for row in cursor.fetchall():
                    schema_info["foreign_keys"].append({
                        "source_table": table,
                        "source_column": row["COLUMN_NAME"],
                        "target_table": row["REFERENCED_TABLE_NAME"],
                        "target_column": row["REFERENCED_COLUMN_NAME"]
                    })

        self.conn.close()
        return schema_info

    def print_explore(self, schema_info: dict):
        """Print database structure (with annotations); add column grouping for single wide table"""
        print("\n" + "=" * 70)
        print(f"Database: {self.connection_params['database']}")
        print("=" * 70)

        is_wide_table = len(schema_info["tables"]) == 1 and len(schema_info["foreign_keys"]) == 0

        for table, info in schema_info["tables"].items():
            pk_cols = [c["name"] for c in info["columns"] if c["key"] == "PRI"]
            comment_str = f"  -- {info['comment']}" if info.get("comment") else ""
            print(f"\n┌─ {table} ({len(info['columns'])} columns, {info['row_count']} rows){comment_str}")

            if is_wide_table:
                # Single wide table mode: display columns grouped by semantics
                columns = info["columns"]
                groups = self._group_columns(columns)
                for group_name, group_cols in groups.items():
                    print(f"│")
                    print(f"│   ┌─ [{group_name}] ({len(group_cols)} columns)")
                    for col in group_cols:
                        markers = []
                        if col["key"] == "PRI": markers.append("PK")
                        if col["key"] == "MUL": markers.append("FK")
                        marker_str = f" ({', '.join(markers)})" if markers else ""
                        col_comment = f"  // {col['comment']}" if col.get("comment") else ""
                        print(f"│   │   ├── {col['name']:28s} {col['type']:18s}{marker_str}{col_comment}")
                print(f"│")
                print(f"│   Tip: This is a single wide table. Edit WIDE_TABLE_ENTITY_MAPPING")
                print(f"│        in the script config to customize entity extraction from columns.")
            else:
                # Multi-table mode: simple listing
                for col in info["columns"]:
                    markers = []
                    if col["key"] == "PRI": markers.append("PK")
                    if col["key"] == "MUL": markers.append("FK")
                    marker_str = f" ({', '.join(markers)})" if markers else ""
                    col_comment = f"  // {col['comment']}" if col.get("comment") else ""
                    print(f"│   ├── {col['name']:30s} {col['type']:20s}{marker_str}{col_comment}")

        if schema_info["foreign_keys"]:
            print(f"\nForeign Keys:")
            for fk in schema_info["foreign_keys"]:
                print(f"  {fk['source_table']}.{fk['source_column']} → {fk['target_table']}.{fk['target_column']}")

    @staticmethod
    def _group_columns(columns: List[dict]) -> Dict[str, List[dict]]:
        """Group wide-table columns by semantics for easier understanding of table structure"""
        groups = {
            "Identity & Key": [],
            "Organoid Identity": [],
            "Culture & Protocol": [],
            "Co-culture": [],
            "Biomarkers & Characterization": [],
            "Drug & Phenotype": [],
            "Application & Disease": [],
            "Genomics & Omics": [],
            "Reference & Source": [],
            "Metadata & System": [],
            "Other": [],
        }

        # Keyword → group mapping
        keyword_groups = {
            "Identity & Key": ["sample_id", "accession", "is_analyzed", "is_organoid", "deleted_at"],
            "Organoid Identity": ["organoid", "organ", "source", "organism", "canonical_name",
                                   "maturity", "characteristics", "functions", "complexity"],
            "Culture & Protocol": ["culture_technique", "cultivation_protocol", "cultivation_material",
                                    "culture_days", "culture_condition", "cell_factors", "techologies",
                                    "time_anchors", "composition"],
            "Co-culture": ["coculture", "coculture_cultivation", "coculture_condition",
                            "coculture_days", "coculture_cell_factors", "coculture_technique",
                            "read_out"],
            "Biomarkers & Characterization": ["biomarker", "endpoints"],
            "Drug & Phenotype": ["drug_screening", "phenotype_identification", "test",
                                  "infection_list"],
            "Application & Disease": ["application", "application_strategy", "disease_modeling"],
            "Genomics & Omics": ["omics_id", "gene_name", "sgrna", "platform"],
            "Reference & Source": ["reference", "doi", "search_content"],
            "Metadata & System": ["system"],
        }

        for col in columns:
            col_name = col["name"].lower()
            placed = False
            for group, keywords in keyword_groups.items():
                if any(kw in col_name for kw in keywords):
                    groups[group].append(col)
                    placed = True
                    break
            if not placed:
                groups["Other"].append(col)

        # Remove empty groups
        return {k: v for k, v in groups.items() if v}

    @staticmethod
    @staticmethod
    def _table_name_to_node_type(table_name: str) -> str:
        """Convert table name to CamelCase node type name"""
        cleaned = table_name.replace("_table", "").replace("_tbl", "")
        parts = cleaned.split("_")
        return "".join(p.capitalize() for p in parts)

    # -------------------------------------------------------------------------
    # Knowledge graph construction
    # -------------------------------------------------------------------------

    def build(self) -> Tuple[List[dict], List[dict]]:
        """Extract data from MySQL wide table and build knowledge graph nodes and edges

        From the public_general_2026 single table: Sample core node + JSON column entity extraction + inferred relations.
        See WIDE_TABLE_ENTITY_MAPPING, INFERRED_RELATIONS for configuration.
        """
        self.connect()
        print(f"[INFO] Using WIDE_TABLE_ENTITY_MAPPING to extract entities from columns")
        result = self._build_from_wide_table()
        self.conn.close()
        return result

    # -------------------------------------------------------------------------
    # Wide table mode construction
    # -------------------------------------------------------------------------

    def _build_from_wide_table(self) -> Tuple[List[dict], List[dict]]:
        """Build knowledge graph from single wide table (public_general_2026)"""
        nodes = []
        edges = []
        # Entity registry: (node_type, entity_name) -> node_id
        entity_registry = {}
        # For inferred relations: sample_id -> set of entity node IDs
        sample_entities = defaultdict(lambda: defaultdict(set))
        # Organoid registry: organoid_name -> organoid_node_id
        organoid_registry = {}
        # Organ registry: organ_name -> organ_node_id
        organ_registry = {}

        # Determine the wide table name
        table_name = list(self.table_mapping.keys())[0]
        mapping = self.table_mapping[table_name]
        core_type = mapping["node_type"]  # "Sample"
        core_prefix = mapping["id_prefix"]  # "smp"

        with self.conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM `{table_name}`")
            all_rows = cursor.fetchall()
            print(f"[INFO] Processing {len(all_rows)} rows from {table_name}")

            # ---- DEBUG: techologies column data exploration ----
            tech_debug = {"total_nonnull": 0, "col_missing_or_null": 0,
                          "parsed_ok": 0, "parsed_empty": 0,
                          "entity_extracted": 0, "samples": [],
                          "col_in_first_row": False, "first_row_cols": []}

            # Global edge dedup: shared entities across rows (Organoid, Organ, etc.) produce duplicate edges
            global_edge_keys = set()

            # ---- Preload public_general_extraction_raw table (for infection_list / cell_factors use) ----
            infection_raw_lookup = {}
            infection_debug = {"loaded": 0, "matched": 0, "found_infection": 0,
                               "extracted_items": 0,
                               "sample_keys": [], "no_match_samples": []}
            cf_debug = {"primary": 0, "coculture": 0,
                        "primary_items": 0, "coculture_items": 0,
                        "samples_checked": 0, "sample_keys": []}
            try:
                cursor.execute("SELECT sample_id, raw_json FROM public_general_extraction_raw")
                for ext_row in cursor.fetchall():
                    sid = ext_row.get("sample_id")
                    if sid:
                        infection_raw_lookup[str(sid)] = ext_row.get("raw_json")
                infection_debug["loaded"] = len(infection_raw_lookup)
                print(f"[INFO] Pre-loaded infection raw data for {len(infection_raw_lookup)} samples "
                      f"from public_general_extraction_raw")
            except Exception as e:
                print(f"[WARN] Could not load public_general_extraction_raw: {e}")

            for row_idx, row in enumerate(all_rows):
                # ---- Step A: Create Sample core node ----
                sample_node = self._row_to_node_wide(row, table_name, core_type, core_prefix)
                if not sample_node:
                    continue
                nodes.append(sample_node)
                sample_id = sample_node["id"]

                # ---- Step B: Extract entities from regular columns ----
                for col, entry in WIDE_TABLE_ENTITY_MAPPING.items():
                    entity_type, prefix, relation, edge_from = entry[0], entry[1], entry[2], entry[3]
                    is_json = len(entry) > 4 and entry[4] == "json"
                    if is_json:
                        continue  # JSON columns handled in Step C

                    if col not in row or row[col] is None or row[col] == '':
                        continue

                    raw_value = row[col]
                    entity_name = str(raw_value).strip()

                    # Special handling: reference → use doi as ID
                    if entity_type == "Publication":
                        doi = row.get("doi", "")
                        entity_name = str(doi).strip() if doi else entity_name

                    # Create or retrieve entity node
                    entity_node, is_new = self._get_or_create_entity(
                        entity_registry, entity_type, prefix, entity_name,
                        extra_props={"source_column": col}
                    )
                    if is_new:
                        nodes.append(entity_node)

                    # Create edge
                    edge_context = "coculture" if col in COCULTURE_COLUMNS else "primary"
                    if edge_from == "sample":
                        edge = self._make_edge(sample_id, entity_node["id"], relation,
                                               {"source_column": col, "context": edge_context})
                    elif edge_from == "organoid":
                        edge = self._make_edge(None, entity_node["id"], relation,
                                               {"source_column": col})
                        # Defer; connect after Organoid node is created
                        self._defer_organoid_edge = getattr(self, '_defer_organoid_edge', [])
                        self._defer_organoid_edge.append((col, entity_node["id"], relation))
                    elif edge_from == "organ":
                        edge = self._make_edge(None, entity_node["id"], relation,
                                               {"source_column": col})
                        self._defer_organ_edge = getattr(self, '_defer_organ_edge', [])
                        self._defer_organ_edge.append((col, entity_node["id"], relation))
                    else:
                        edge = self._make_edge(sample_id, entity_node["id"], relation,
                                               {"source_column": col})

                    if edge_from == "sample" and edge:
                        ek = (edge["source"], edge["target"], edge["relation"])
                        if ek not in global_edge_keys:
                            global_edge_keys.add(ek)
                            edges.append(edge)

                    # Record entity ownership
                    sample_entities[sample_id][entity_type].add(entity_node["id"])
                    if entity_type == "Organoid":
                        organoid_registry[entity_name] = entity_node["id"]
                    if entity_type == "Organ":
                        organ_registry[entity_name] = entity_node["id"]

                # ---- Step C: Extract entities from JSON columns ----
                RAW_JSON_COLUMNS = {"infection_list", "cell_factors", "coculture_cell_factors"}
                # cell_factors extraction cache: sample_id_raw -> (primary_list, coculture_list)
                cell_factors_cache = {}

                for col, (entity_type, prefix, relation, edge_from, *rest) in WIDE_TABLE_ENTITY_MAPPING.items():
                    is_json = len(rest) > 0 and rest[0] == "json"
                    if not is_json:
                        continue
                    if col not in row or row[col] is None:
                        # For the following columns, the data source is in raw_json, not in the current row
                        if col in RAW_JSON_COLUMNS:
                            pass
                        else:
                            # DEBUG: techologies column missing or NULL
                            if col == "techologies":
                                tech_debug["col_missing_or_null"] += 1
                                if row_idx == 0:
                                    tech_debug["first_row_cols"] = sorted(row.keys())
                                    tech_debug["col_in_first_row"] = col in row
                            continue

                    # infection_list gets data from public_general_extraction_raw table
                    if col == "infection_list":
                        sample_id_raw = str(row.get("sample_id", ""))
                        raw_json_val = infection_raw_lookup.get(sample_id_raw)
                        infection_debug["matched"] += 1

                        if raw_json_val is None:
                            if len(infection_debug["no_match_samples"]) < 5:
                                infection_debug["no_match_samples"].append(sample_id_raw)
                            continue
                        if isinstance(raw_json_val, str):
                            try:
                                raw_json_val = json.loads(raw_json_val)
                            except json.JSONDecodeError:
                                continue

                        # Traverse cultures[].story.infection_list, aggregate infection data from all cultures
                        json_data = self._extract_infection_data(raw_json_val, max_depth=4)
                        if json_data is None:
                            continue

                        infection_debug["found_infection"] += 1
                        infection_debug["extracted_items"] += len(json_data)
                        if len(infection_debug["sample_keys"]) < 3:
                            top_keys = (list(raw_json_val.keys()) if isinstance(raw_json_val, dict)
                                        else f"type={type(raw_json_val).__name__}")
                            infection_debug["sample_keys"].append({
                                "sample_id": sample_id_raw,
                                "raw_json_type": type(raw_json_val).__name__,
                                "top_keys": str(top_keys)[:300],
                                "infection_data_type": type(json_data).__name__,
                                "infection_data_len": len(json_data),
                                "infection_data_preview": str(json_data)[:500],
                            })

                    # cell_factors / coculture_cell_factors extracted from raw_json, split by if_co_culture
                    elif col in ("cell_factors", "coculture_cell_factors"):
                        sample_id_raw = str(row.get("sample_id", ""))
                        if sample_id_raw not in cell_factors_cache:
                            raw_json_val = infection_raw_lookup.get(sample_id_raw)
                            if raw_json_val is None:
                                cell_factors_cache[sample_id_raw] = ([], [])
                            else:
                                if isinstance(raw_json_val, str):
                                    try:
                                        raw_json_val = json.loads(raw_json_val)
                                    except json.JSONDecodeError:
                                        cell_factors_cache[sample_id_raw] = ([], [])
                                        continue
                                # Collect diagnostic info for first 3 samples
                                extract_debug = {} if len(cf_debug["sample_keys"]) < 3 else None
                                cell_factors_cache[sample_id_raw] = \
                                    self._extract_cell_factors_from_raw(raw_json_val, max_depth=4,
                                                                        debug_info=extract_debug)
                                if extract_debug:
                                    extract_debug["sample_id"] = sample_id_raw
                                    extract_debug["top_keys"] = (list(raw_json_val.keys())[:200]
                                        if isinstance(raw_json_val, dict)
                                        else f"type={type(raw_json_val).__name__}")
                                    cf_debug["sample_keys"].append(extract_debug)

                        primary_list, coculture_list = cell_factors_cache[sample_id_raw]

                        if col == "cell_factors":
                            json_data = primary_list
                            cf_debug["samples_checked"] += 1
                            if primary_list:
                                cf_debug["primary"] += 1
                                cf_debug["primary_items"] += len(primary_list)
                        else:  # coculture_cell_factors
                            json_data = coculture_list
                            if coculture_list:
                                cf_debug["coculture"] += 1
                                cf_debug["coculture_items"] += len(coculture_list)

                        if not json_data:
                            continue

                    else:
                        json_data = row[col]

                    items = self._parse_json_column(json_data)
                    if not items:
                        # DEBUG: record techologies empty parse
                        if col == "techologies":
                            tech_debug["total_nonnull"] += 1
                            tech_debug["parsed_empty"] += 1
                        continue

                    # DEBUG: record techologies parse status
                    if col == "techologies":
                        tech_debug["total_nonnull"] += 1
                        tech_debug["parsed_ok"] += 1
                        if len(tech_debug["samples"]) < 3:
                            tech_debug["samples"].append({
                                "row_idx": row_idx,
                                "raw_type": type(json_data).__name__,
                                "raw_preview": str(json_data)[:200],
                                "items_count": len(items),
                                "item_preview": [str(it)[:120] for it in items[:3]],
                            })
                        # techologies has nested objects; use recursive flatten to extract leaf strings
                        items = self._flatten_json_values(json_data)

                    edge_context = "coculture" if col in COCULTURE_COLUMNS else "primary"

                    for item in items:
                        entity_name = self._extract_entity_name(item, col)
                        if not entity_name:
                            # DEBUG: techologies entity name extraction failed
                            if col == "techologies" and len(tech_debug["samples"]) < 5:
                                tech_debug["samples"].append({
                                    "row_idx": row_idx, "fail_reason": "entity_name is None",
                                    "item_type": type(item).__name__,
                                    "item_preview": str(item)[:200],
                                })
                            continue
                        if col == "techologies":
                            tech_debug["entity_extracted"] += 1

                        # Create or retrieve entity node
                        entity_node, is_new = self._get_or_create_entity(
                            entity_registry, entity_type, prefix, entity_name,
                            extra_props={"source_column": col}
                        )
                        if is_new:
                            # Extract additional properties from JSON entry
                            if isinstance(item, dict):
                                for k, v in item.items():
                                    if k not in ("name", "Name") and v is not None:
                                        entity_node["properties"][k] = v
                            nodes.append(entity_node)

                        # Create edge
                        if edge_from == "sample":
                            edge = self._make_edge(sample_id, entity_node["id"], relation,
                                                   {"source_column": col, "context": edge_context})
                            if edge:
                                ek = (edge["source"], edge["target"], edge["relation"])
                                if ek not in global_edge_keys:
                                    global_edge_keys.add(ek)
                                    edges.append(edge)
                        elif edge_from == "organoid":
                            self._defer_organoid_edge = getattr(self, '_defer_organoid_edge', [])
                            self._defer_organoid_edge.append((col, entity_node["id"], relation,
                                                               {"source_column": col}))
                        elif edge_from == "organ":
                            self._defer_organ_edge = getattr(self, '_defer_organ_edge', [])
                            self._defer_organ_edge.append((col, entity_node["id"], relation,
                                                            {"source_column": col}))

                        sample_entities[sample_id][entity_type].add(entity_node["id"])

                # ---- Step D: Resolve deferred Organoid→X edges ----
                deferred = getattr(self, '_defer_organoid_edge', [])
                organoid_id = organoid_registry.get(
                    str(row.get("organoid", "")).strip(), sample_id)
                for item in deferred:
                    if len(item) == 4:
                        col, tgt_id, rel, props = item
                    else:
                        col, tgt_id, rel = item
                        props = {"source_column": col}
                    edge = self._make_edge(organoid_id, tgt_id, rel, props)
                    if edge:
                        ek = (edge["source"], edge["target"], edge["relation"])
                        if ek not in global_edge_keys:
                            global_edge_keys.add(ek)
                            edges.append(edge)
                self._defer_organoid_edge = []

                # Resolve deferred Organ→System edges
                deferred_organ = getattr(self, '_defer_organ_edge', [])
                organ_id = organ_registry.get(
                    str(row.get("organ", "")).strip(), None)
                if organ_id:
                    for item in deferred_organ:
                        if len(item) == 4:
                            col, tgt_id, rel, props = item
                        else:
                            col, tgt_id, rel = item
                            props = {"source_column": col}
                        edge = self._make_edge(organ_id, tgt_id, rel, props)
                        if edge:
                            ek = (edge["source"], edge["target"], edge["relation"])
                            if ek not in global_edge_keys:
                                global_edge_keys.add(ek)
                                edges.append(edge)
                self._defer_organ_edge = []

                if (row_idx + 1) % 1000 == 0:
                    print(f"  ... processed {row_idx + 1}/{len(all_rows)} rows, "
                          f"{len(nodes)} nodes, {len(edges)} edges")

            # ---- DEBUG: print techologies exploration results ----
            print(f"\n[DEBUG] techologies column analysis:")
            print(f"  column in row[0] keys:   {tech_debug['col_in_first_row']}")
            if tech_debug['first_row_cols']:
                # Filter column names containing 'tech' for location assistance
                tech_like = [c for c in tech_debug['first_row_cols'] if 'tech' in c.lower()]
                print(f"  columns matching 'tech':  {tech_like}")
            print(f"  col missing or NULL:     {tech_debug['col_missing_or_null']}")
            print(f"  non-null & parsed OK:    {tech_debug['parsed_ok']}")
            print(f"  non-null & parsed empty: {tech_debug['parsed_empty']}")
            print(f"  entity names extracted:  {tech_debug['entity_extracted']}")
            if tech_debug["samples"]:
                print(f"  sample raw values (first {len(tech_debug['samples'])}):")
                for s in tech_debug["samples"]:
                    for k, v in s.items():
                        print(f"    {k}: {v}")
            print()

            # ---- DEBUG: infection_list exploration results ----
            print(f"[DEBUG] infection_list column analysis:")
            print(f"  raw samples loaded:      {infection_debug['loaded']}")
            print(f"  samples checked:         {infection_debug['matched']}")
            print(f"  infection data found:    {infection_debug['found_infection']} "
                  f"(total items extracted: {infection_debug['extracted_items']})")
            if infection_debug["no_match_samples"]:
                print(f"  no-match sample_ids (first 5): {infection_debug['no_match_samples'][:5]}")
            if infection_debug["sample_keys"]:
                print(f"  sample raw_json structure (first {len(infection_debug['sample_keys'])}):")
                for s in infection_debug["sample_keys"]:
                    for k, v in s.items():
                        print(f"    {k}: {v}")
            print()

            # ---- DEBUG: cell_factors exploration results ----
            print(f"[DEBUG] cell_factors / coculture_cell_factors analysis (from raw_json):")
            print(f"  samples checked:           {cf_debug['samples_checked']}")
            print(f"  samples with primary CF:   {cf_debug['primary']} "
                  f"(total items: {cf_debug['primary_items']})")
            print(f"  samples with coculture CF: {cf_debug['coculture']} "
                  f"(total items: {cf_debug['coculture_items']})")
            if cf_debug["sample_keys"]:
                print(f"  diagnostic info (first {len(cf_debug['sample_keys'])} samples):")
                for s in cf_debug["sample_keys"]:
                    for k, v in s.items():
                        print(f"    {k}: {v}")
            print()

            # ---- Step E: Generate inferred relationships ----
            print(f"[INFO] Generating inferred relationships...")
            inferred_edges = self._infer_relationships(
                sample_entities, entity_registry, nodes, edges)
            edges.extend(inferred_edges)
            print(f"[INFO] Added {len(inferred_edges)} inferred edges")

        print(f"[OK] Wide-table build complete: {len(nodes)} nodes, {len(edges)} edges")
        return nodes, edges

    def _row_to_node_wide(self, row: dict, table: str, node_type: str,
                           id_prefix: str) -> Optional[dict]:
        """Wide table row → core node (excluding columns already extracted as entity nodes)"""
        props = {}
        extracted_cols = set(WIDE_TABLE_ENTITY_MAPPING.keys())
        # Also exclude doi (already handled via reference column)
        extracted_cols.add("doi")
        # test column abandoned, not saved to Sample properties
        extracted_cols.add("test")

        for col, val in row.items():
            if col in extracted_cols:
                continue
            if val is None:
                continue
            if isinstance(val, datetime):
                props[col] = val.isoformat()
            elif isinstance(val, (str, int, float, bool, list, dict)):
                props[col] = val
            elif isinstance(val, bytes):
                try:
                    props[col] = val.decode('utf-8')
                except UnicodeDecodeError:
                    props[col] = val.hex()
            else:
                props[col] = str(val)

        pk_val = row.get("sample_id", list(row.values())[0])
        node_id = f"{id_prefix}_{pk_val}"

        return {
            "id": node_id,
            "type": node_type,
            "properties": props,
            "_provenance": {
                "source_type": "mysql",
                "source_database": self.connection_params["database"],
                "source_table": table,
                "source_row_id": str(pk_val),
                "extracted_at": datetime.now().isoformat()
            }
        }

    def _get_or_create_entity(self, registry: dict, entity_type: str, prefix: str,
                               name: str, extra_props: dict = None) -> Tuple[dict, bool]:
        """Get or create entity node (dedup by name)"""
        key = (entity_type, name.lower().strip())
        if key in registry:
            return registry[key], False

        # Use first 8 chars of MD5 as hash
        name_hash = hashlib.md5(name.lower().strip().encode()).hexdigest()[:8]
        node_id = f"{prefix}_{name_hash}"

        props = {"name": name}
        if extra_props:
            props.update(extra_props)

        node = {
            "id": node_id,
            "type": entity_type,
            "properties": props,
            "_provenance": {
                "source_type": "json_extraction" if extra_props and "source_column" in extra_props else "column_extraction",
                "source_column": extra_props.get("source_column", "") if extra_props else "",
                "extracted_at": datetime.now().isoformat()
            }
        }
        registry[key] = node
        return node, True

    def _parse_json_column(self, value) -> Optional[list]:
        """Parse JSON column, return list; if already a list, return directly"""
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                return [value]
        if isinstance(value, dict):
            return [value]
        return [str(value)]

    def _extract_entity_name(self, item, col: str) -> Optional[str]:
        """Extract entity name from JSON entry"""
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for key in JSON_ENTITY_NAME_KEYS:
                if key in item and item[key]:
                    return str(item[key]).strip()
            # If no standard key, take the first string value
            for k, v in item.items():
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return None

    def _flatten_json_values(self, data, max_depth: int = 5) -> List[str]:
        """Recursively flatten nested JSON, collecting all leaf-node string values

        For deeply nested structures like techologies:
        {'cellular_imaging': {'microscopies': [{'method': 'Bright-field', ...}]}}
        → ['Bright-field', 'Leica DM6 microscope', ...]
        """
        results = []
        if isinstance(data, str):
            s = data.strip()
            if s:
                results.append(s)
        elif isinstance(data, list):
            for item in data:
                if max_depth > 0:
                    results.extend(self._flatten_json_values(item, max_depth - 1))
        elif isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, str) and val.strip():
                    results.append(val.strip())
                elif max_depth > 0:
                    results.extend(self._flatten_json_values(val, max_depth - 1))
        return results

    @staticmethod
    def _find_cultures_array(data, max_depth: int = 4):
        """Find cultures[] array in nested JSON, return list or None

        General-purpose helper method shared by _extract_infection_data and _extract_cell_factors_from_raw.
        """
        if max_depth <= 0 or data is None:
            return None
        if isinstance(data, dict):
            if "cultures" in data and isinstance(data["cultures"], list):
                return data["cultures"]
            for val in data.values():
                if isinstance(val, (dict, list)):
                    result = MySQLKnowledgeGraphBuilder._find_cultures_array(val, max_depth - 1)
                    if result is not None:
                        return result
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    result = MySQLKnowledgeGraphBuilder._find_cultures_array(item, max_depth - 1)
                    if result is not None:
                        return result
        return None

    def _extract_infection_data(self, data, max_depth: int = 4):
        """Extract all infection data from raw_json, supporting cultures[].story.infection_list path

        A single record may contain multiple cultures, each with its own
        story.infection_list. This method traverses all cultures[] entries and aggregates all infections.

        Args:
            data: raw_json parsed dict/list
            max_depth: Maximum nesting depth for searching the cultures array

        Returns:
            list of infection dicts, or None if no data
        """
        if max_depth <= 0 or data is None:
            return None

        cultures = self._find_cultures_array(data, max_depth)
        if cultures:
            all_infections = []
            for culture in cultures:
                if not isinstance(culture, dict):
                    continue
                story = culture.get("story")
                if isinstance(story, dict):
                    inf_list = story.get("infection_list")
                    if inf_list and isinstance(inf_list, list):
                        all_infections.extend(inf_list)
            if all_infections:
                return all_infections

        # Fallback: legacy format without cultures[] structure → recursively search for single infection_list
        return self._find_infection_key_fallback(data, max_depth)

    def _extract_cell_factors_from_raw(self, data, max_depth: int = 4,
                                        debug_info: dict = None):
        """Extract cell_factors from raw_json, split by if_co_culture

        Supports two JSON structures:
        1. With cultures[] wrapper (multi-culture):
           cultures[].base_info.if_co_culture + cultures[].story.protocol[].growth_factors
        2. Without cultures[] wrapper (single culture, current actual data format):
           top-level base_info.if_co_culture + top-level story.protocol[].growth_factors

        Splitting rule: if_co_culture == True  → coculture_cell_factors
                         otherwise              → cell_factors
        """
        cell_factors = []
        coculture_factors = []

        if data is None:
            if debug_info is not None:
                debug_info["error"] = "data is None"
            return cell_factors, coculture_factors

        # Collect (base_info_dict, story_dict) pairs
        culture_units = []

        cultures = self._find_cultures_array(data, max_depth)
        if cultures:
            # Structure 1: cultures[] wrapper
            if debug_info is not None:
                debug_info["structure"] = "cultures[]"
                debug_info["culture_count"] = len(cultures)
            for c in cultures:
                if isinstance(c, dict):
                    culture_units.append((c.get("base_info", {}), c.get("story", {})))
        else:
            # Structure 2: no cultures[] — find story/base_info from top level or recursively
            if debug_info is not None:
                debug_info["structure"] = "flat (no cultures)"
            # Try to find story and base_info in data
            base_info = data.get("base_info", {}) if isinstance(data, dict) else {}
            story = data.get("story", {}) if isinstance(data, dict) else {}
            if isinstance(story, dict) and story:
                culture_units.append((base_info, story))
            else:
                # Deep search: find first story containing protocol[]
                found_story, found_base_info = self._find_story_and_base_info(data, max_depth)
                if found_story:
                    culture_units.append((found_base_info or {}, found_story))

        if debug_info is not None:
            debug_info["culture_units_found"] = len(culture_units)

        for ui, (base_info, story) in enumerate(culture_units):
            # Determine if co-culture
            is_coculture = False
            if isinstance(base_info, dict):
                val = base_info.get("if_co_culture", False)
                if val is True or str(val).lower() in ("true", "1", "yes"):
                    is_coculture = True

            if debug_info is not None and ui < 2:
                unit_debug = {
                    "unit_idx": ui,
                    "base_info_keys": str(list(base_info.keys()))[:200] if isinstance(base_info, dict) else f"type={type(base_info).__name__}",
                    "if_co_culture_raw": repr(base_info.get("if_co_culture")) if isinstance(base_info, dict) else "N/A",
                    "is_coculture": is_coculture,
                }

            # Collect growth_factors from story.protocol[]
            if not isinstance(story, dict):
                continue
            protocols = story.get("protocol", [])
            if not isinstance(protocols, list):
                if debug_info is not None and ui < 2:
                    unit_debug["protocol_type"] = type(protocols).__name__
                    unit_debug["story_keys"] = str(list(story.keys()))[:200]
                    debug_info.setdefault("culture_units_debug", []).append(unit_debug)
                continue

            if debug_info is not None and ui < 2:
                unit_debug["protocol_count"] = len(protocols)
                if protocols:
                    unit_debug["protocol_0_keys"] = str(list(protocols[0].keys()))[:300] if isinstance(protocols[0], dict) else f"type={type(protocols[0]).__name__}"

            for pi, protocol in enumerate(protocols):
                if not isinstance(protocol, dict):
                    continue
                growth_factors = protocol.get("growth_factors")
                if not growth_factors:
                    if debug_info is not None and ui < 2 and pi == 0:
                        unit_debug["protocol_0_has_growth_factors"] = False
                        unit_debug["protocol_0_keys_full"] = str(list(protocol.keys()))[:300]
                    continue
                if isinstance(growth_factors, list):
                    items = growth_factors
                else:
                    items = [growth_factors]

                if is_coculture:
                    coculture_factors.extend(items)
                else:
                    cell_factors.extend(items)

                if debug_info is not None and ui < 2 and pi == 0:
                    unit_debug["growth_factors_found"] = True
                    unit_debug["growth_factors_type"] = type(growth_factors).__name__
                    unit_debug["growth_factors_len"] = len(items) if isinstance(items, list) else 1
                    unit_debug["growth_factors_preview"] = str(items)[:300]

            if debug_info is not None and ui < 2:
                debug_info.setdefault("culture_units_debug", []).append(unit_debug)

        return cell_factors, coculture_factors

    @staticmethod
    def _find_story_and_base_info(data, max_depth: int = 4):
        """In a structure without cultures[], search for story (containing protocol[]) and its sibling base_info

        Returns: (story_dict, base_info_dict) or (None, None)
        """
        if max_depth <= 0 or data is None:
            return None, None
        if isinstance(data, dict):
            # Sibling story and base_info
            story = data.get("story")
            base_info = data.get("base_info")
            if isinstance(story, dict) and isinstance(story.get("protocol"), list):
                return story, base_info if isinstance(base_info, dict) else None
            # Recursive search
            for val in data.values():
                if isinstance(val, (dict, list)):
                    s, bi = MySQLKnowledgeGraphBuilder._find_story_and_base_info(val, max_depth - 1)
                    if s is not None:
                        return s, bi
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    s, bi = MySQLKnowledgeGraphBuilder._find_story_and_base_info(item, max_depth - 1)
                    if s is not None:
                        return s, bi
        return None, None

    def _find_infection_key_fallback(self, data, max_depth: int = 4):
        """Fallback: recursively search raw_json for infection-related keys, return their values

        Only used when _extract_infection_data cannot find a cultures[] structure.
        """
        if max_depth <= 0:
            return None
        if isinstance(data, dict):
            if "infection_list" in data and data["infection_list"] is not None:
                return data["infection_list"]
            if "infection" in data and data["infection"] is not None:
                return data["infection"]
            for key in data:
                if "infection" in key.lower() and data[key] is not None:
                    return data[key]
            for key, val in data.items():
                if isinstance(val, (dict, list)):
                    result = self._find_infection_key_fallback(val, max_depth - 1)
                    if result is not None:
                        return result
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    result = self._find_infection_key_fallback(item, max_depth - 1)
                    if result is not None:
                        return result
        return None

    def _make_edge(self, source_id: str, target_id: str, relation: str,
                   props: dict = None) -> Optional[dict]:
        """Create edge"""
        if not source_id or not target_id:
            return None
        edge = {
            "id": f"e_{source_id}_{relation}_{target_id}",
            "source": source_id,
            "target": target_id,
            "relation": relation,
            "properties": props or {},
            "_provenance": {
                "derived_from": props.get("source_column", "") if props else "",
                "confidence": 1.0
            }
        }
        return edge

    def _infer_relationships(self, sample_entities: dict, entity_registry: dict,
                              nodes: list, edges: list) -> List[dict]:
        """Infer relationships from co-occurrence data (TREATS_DISEASE, INDICATES_DISEASE)"""
        inferred = []
        seen_pairs = set()

        for src_col, tgt_col, src_type, tgt_type, relation in INFERRED_RELATIONS:
            for sample_id, type_sets in sample_entities.items():
                src_ids = type_sets.get(src_type, set())
                tgt_ids = type_sets.get(tgt_type, set())
                if not src_ids or not tgt_ids:
                    continue

                for src_id in src_ids:
                    for tgt_id in tgt_ids:
                        pair_key = (src_id, tgt_id, relation)
                        if pair_key in seen_pairs:
                            continue
                        seen_pairs.add(pair_key)

                        edge = {
                            "id": f"e_infer_{src_id}_{relation}_{tgt_id}",
                            "source": src_id,
                            "target": tgt_id,
                            "relation": relation,
                            "properties": {
                                "confidence": 0.5,  # Initial confidence level
                                "derived_from": "co_occurrence_inference"
                            },
                            "_provenance": {
                                "derived_from": "co_occurrence_inference",
                                "source_columns": [src_col, tgt_col],
                                "confidence": 0.5
                            }
                        }
                        inferred.append(edge)

        return inferred

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Output
    # -------------------------------------------------------------------------

    def save_json(self, nodes: List[dict], edges: List[dict], output_path: str):
        """Save as JSON format knowledge graph"""
        node_types = sorted(set(n["type"] for n in nodes))
        relation_types = sorted(set(e["relation"] for e in edges))

        kg = {
            "meta": {
                "name": f"Organoid Culture Knowledge Graph",
                "version": "1.0",
                "created": datetime.now().isoformat(),
                "source_database": self.connection_params["database"],
                "description": "Knowledge graph of organoid culture experiments built from MySQL database",
                "node_types": node_types,
                "relationship_types": relation_types,
                "statistics": {
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "nodes_by_type": self._count_by_key(nodes, "type"),
                    "edges_by_relation": self._count_by_key(edges, "relation")
                }
            },
            "nodes": nodes,
            "edges": edges
        }

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(kg, f, ensure_ascii=False, indent=2)

        print(f"[OK] JSON knowledge graph saved to: {output_path}")
        print(f"     Nodes: {len(nodes)}, Edges: {len(edges)}")
        self._print_statistics(nodes, edges)

    def save_sqlite(self, nodes: List[dict], edges: List[dict], output_path: str):
        """Save as SQLite format knowledge graph"""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        conn = sqlite3.connect(output_path)
        cursor = conn.cursor()

        # Create nodes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                properties TEXT NOT NULL
            )
        """)

        # Create edges table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edge_id TEXT,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                relation TEXT NOT NULL,
                properties TEXT,
                FOREIGN KEY (source) REFERENCES nodes(id),
                FOREIGN KEY (target) REFERENCES nodes(id)
            )
        """)

        # Create metadata table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation)")

        # Insert nodes
        for node in nodes:
            cursor.execute(
                "INSERT OR REPLACE INTO nodes (id, type, properties) VALUES (?, ?, ?)",
                (node["id"], node["type"], json.dumps(node.get("properties", {}), ensure_ascii=False))
            )

        # Insert edges
        for i, edge in enumerate(edges):
            cursor.execute(
                "INSERT INTO edges (edge_id, source, target, relation, properties) VALUES (?, ?, ?, ?, ?)",
                (
                    edge.get("id", f"edge_{i}"),
                    edge["source"],
                    edge["target"],
                    edge["relation"],
                    json.dumps(edge.get("properties", {}), ensure_ascii=False)
                )
            )

        # Insert metadata
        meta = {
            "name": "Organoid Culture Knowledge Graph",
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "source_database": self.connection_params["database"],
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        }
        for key, val in meta.items():
            cursor.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(val)))

        conn.commit()
        conn.close()

        print(f"[OK] SQLite knowledge graph saved to: {output_path}")
        print(f"     Nodes: {len(nodes)}, Edges: {len(edges)}")

    @staticmethod
    def _count_by_key(items: List[dict], key: str) -> dict:
        counts = defaultdict(int)
        for item in items:
            counts[item.get(key, "unknown")] += 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    @staticmethod
    def _print_statistics(nodes: List[dict], edges: List[dict]):
        print(f"\n{'='*50}")
        print(f"  Knowledge Graph Statistics")
        print(f"{'='*50}")
        print(f"  Total nodes: {len(nodes)}")
        print(f"  Total edges: {len(edges)}")
        print(f"\n  Nodes by type:")
        for ntype, count in MySQLKnowledgeGraphBuilder._count_by_key(nodes, "type").items():
            print(f"    {ntype:20s}: {count:>6d}")
        print(f"\n  Edges by relation:")
        for rel, count in MySQLKnowledgeGraphBuilder._count_by_key(edges, "relation").items():
            print(f"    {rel:25s}: {count:>6d}")


# =============================================================================
# Main CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Build knowledge graph from MySQL organoid culture database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Explore database structure
  python build_kg.py --host localhost --database organoid_db --user root --password xxx --explore

  # Build knowledge graph (JSON + SQLite)
  python build_kg.py --host localhost --database organoid_db --user root --password xxx --output-dir ./output

  # Build JSON only
  python build_kg.py --host localhost --database organoid_db --user root --password xxx --format json
        """
    )

    # MySQL connection
    parser.add_argument("--host", default="192.168.20.30", help="MySQL host (default:)")
    parser.add_argument("--port", type=int, default=33061, help="MySQL port (default: 33061)")
    parser.add_argument("--user", default="wangchenglong", help="MySQL user")
    parser.add_argument("--password", default="", help="MySQL password")
    parser.add_argument("--database", default='public', help="MySQL database name (default: public)")

    # Operation mode
    parser.add_argument("--explore", action="store_true", help="Explore database schema and exit")

    # Build options
    parser.add_argument("--output-dir", default="./organoid-kg-output", help="Output directory")
    parser.add_argument("--format", nargs="+", default=["json", "sqlite"],
                        choices=["json", "sqlite"], help="Output formats (default: json sqlite)")
    parser.add_argument("--tables", nargs="*", default=None,
                        help="Only process tables whose names contain these strings (substring match). "
                             "e.g. --tables organoid culture. If not set, uses FOCUS_TABLES from script config.")

    args = parser.parse_args()

    # Focus tables: CLI argument > script config
    focus_tables = args.tables if args.tables is not None else None

    # --explore mode
    if args.explore:
        builder = MySQLKnowledgeGraphBuilder(
            host=args.host, port=args.port, user=args.user,
            password=args.password, database=args.database,
            focus_tables=focus_tables
        )
        schema = builder.explore()
        builder.print_explore(schema)
        return

    builder = MySQLKnowledgeGraphBuilder(
        host=args.host, port=args.port, user=args.user,
        password=args.password, database=args.database,
        focus_tables=focus_tables
    )

    # Build mode
    print(f"\nBuilding knowledge graph from {args.database}...")
    nodes, edges = builder.build()

    if not nodes:
        print("[WARNING] No nodes were extracted. Check your database connection and data.")
        return

    # Output — write to timestamped subdirectory
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    output_subdir = os.path.join(args.output_dir, timestamp)
    os.makedirs(output_subdir, exist_ok=True)

    if "json" in args.format:
        json_path = os.path.join(output_subdir, "organoid_kg.json")
        builder.save_json(nodes, edges, json_path)

    if "sqlite" in args.format:
        sqlite_path = os.path.join(output_subdir, "organoid_kg.sqlite")
        builder.save_sqlite(nodes, edges, sqlite_path)

    # Build report
    report = {
        "build_time": datetime.now().isoformat(),
        "source_database": args.database,
        "output_dir": output_subdir,
        "statistics": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "nodes_by_type": builder._count_by_key(nodes, "type"),
            "edges_by_relation": builder._count_by_key(edges, "relation")
        }
    }
    report_path = os.path.join(output_subdir, "build_report.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[OK] Build report saved to: {report_path}")

    print(f"\n{'='*50}")
    print(f"  Build complete!")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
