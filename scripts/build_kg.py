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
import ast
import os
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

# =============================================================================
# Configuration — loaded from kg_mapping.json (edit the JSON, not this file)
# =============================================================================

def _load_mapping_config(config_path: str = None):
    """Load KG mapping configuration from JSON file and set module-level globals.

    Called at module import time with the default JSON.  Can be re-called at
    runtime with a custom path (via --mapping) to override the defaults before
    building.

    The JSON uses descriptive object keys for readability; this function converts
    them to the tuple/list formats expected by the rest of the code.
    """
    global DEFAULT_TABLE_MAPPING, FOCUS_TABLES, MANUAL_TABLE_TYPES
    global WIDE_TABLE_ENTITY_MAPPING, COMPOUND_ENTITY_CONFIG
    global INFERRED_RELATIONS, JSON_ENTITY_NAME_KEYS, COCULTURE_COLUMNS
    global GENE_ANNOTATION_DRUG_LOOKUP
    global MATERIAL_INFO_CONFIG, MATERIAL_SIMILARITY_CONFIG

    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), 'kg_mapping.json')

    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    DEFAULT_TABLE_MAPPING = cfg["table_mapping"]
    FOCUS_TABLES = cfg["focus_tables"]
    MANUAL_TABLE_TYPES = {k: tuple(v) for k, v in cfg.get("manual_table_types", {}).items()}

    # wide_table_entity_mapping: descriptive objects → tuples (indexed access in build logic)
    wide_mapping = {}
    for col, entry in cfg["wide_table_entity_mapping"].items():
        parts = [entry["node_type"], entry["id_prefix"], entry["relation"], entry["edge_from"]]
        if entry.get("is_json"):
            parts.append("json")
        wide_mapping[col] = tuple(parts)
    WIDE_TABLE_ENTITY_MAPPING = wide_mapping

    COMPOUND_ENTITY_CONFIG = cfg["compound_entity_config"]

    # inferred_relations: array of objects → list of tuples
    INFERRED_RELATIONS = [
        (r["source_column"], r["target_column"], r["source_type"], r["target_type"], r["relation"])
        for r in cfg.get("inferred_relations", [])
    ]

    JSON_ENTITY_NAME_KEYS = cfg["json_entity_name_keys"]
    COCULTURE_COLUMNS = set(cfg["coculture_columns"])

    GENE_ANNOTATION_DRUG_LOOKUP = cfg.get("gene_annotation_drug_lookup", {})

    MATERIAL_INFO_CONFIG = cfg.get("material_info_config", {})
    MATERIAL_SIMILARITY_CONFIG = cfg.get("material_similarity_config", {})

    print(f"[INFO] KG mapping loaded from: {config_path}")

# Load defaults at module import time
_load_mapping_config()

# Truncation limit for GroupInfo sub-node queries (GroupDEGs, IntraClusterDEGs,
# ClusterMarkers, GSVA, GSEA). Max rows fetched per GSE_ID per sub-table.
# Set to None for unlimited. Default 50 — keeps the top rows per GSE_ID,
# drastically reducing KG build time while preserving the most relevant entries.
GROUPINFO_SUB_NODE_MAX_ROWS = 50


class MySQLKnowledgeGraphBuilder:
    """Build a knowledge graph from a MySQL database"""

    def __init__(self, host: str, port: int, user: str, password: str,
                 database: str, focus_tables: List[str] = None,
                 mapping_path: str = None):
        self.connection_params = {
            "host": host, "port": port, "user": user,
            "password": password, "database": database
        }
        self.mapping_path = mapping_path
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
        # Reload mapping if a custom config path was provided
        if self.mapping_path:
            _load_mapping_config(self.mapping_path)

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

            # ---- DEBUG: json_structured columns (CultureCondition, CoCultureTechnique) ----
            js_debug = {}
            for js_col in ["culture_condition", "coculture_technique"]:
                js_debug[js_col] = {"null_or_missing": 0, "parse_failed": 0,
                                    "non_dict_data": 0, "empty_data": 0,
                                    "extracted_ok": 0, "samples": []}
            # ---- DEBUG: test column ----
            test_debug = {"null_or_missing": 0, "parse_empty": 0,
                          "entity_extracted": 0, "samples": []}
            # ---- DEBUG: coculture technique from raw_json ----
            cct_debug = {"lookup_attempts": 0, "raw_found": 0, "raw_not_found": 0,
                         "key_found": 0, "key_not_found": 0,
                         "node_created": 0, "node_dedup": 0,
                         "extraction_failed": 0, "samples": []}

            # Global edge dedup: shared entities across rows (Organ, etc.) produce duplicate edges
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
                # Print sample raw_json keys for first 3 entries to verify structure
                sample_count = 0
                for sid, rj in infection_raw_lookup.items():
                    if sample_count >= 3:
                        break
                    try:
                        if isinstance(rj, str):
                            rj_parsed = json.loads(rj)
                        else:
                            rj_parsed = rj
                        if isinstance(rj_parsed, dict):
                            top_keys = sorted(rj_parsed.keys())
                            # Also check for culture_technique_coculture at any level
                            ctc_found = MySQLKnowledgeGraphBuilder._find_key_recursive(rj_parsed, "culture_technique_coculture", 4)
                            print(f"[INFO] raw_json sample {sid}: top_keys={top_keys}, "
                                  f"culture_technique_coculture={'FOUND' if ctc_found is not None else 'NOT FOUND'}")
                        else:
                            print(f"[INFO] raw_json sample {sid}: type={type(rj_parsed).__name__} (not a dict)")
                    except Exception:
                        print(f"[INFO] raw_json sample {sid}: failed to parse")
                    sample_count += 1
            except Exception as e:
                print(f"[WARN] Could not load public_general_extraction_raw: {e}")

            # ---- Preload Material_name_similarity_candidates_enhanced (for MaterialInfo enrichment) ----
            material_similarity_rows = []
            if MATERIAL_SIMILARITY_CONFIG.get("enabled", False):
                sim_table = MATERIAL_SIMILARITY_CONFIG["table"]
                try:
                    cursor.execute(f"SELECT * FROM `{sim_table}`")
                    for sim_row in cursor.fetchall():
                        row_dict = {}
                        for k, v in sim_row.items():
                            if v is not None:
                                row_dict[k] = v
                        if row_dict.get("similar_names", "").strip():
                            material_similarity_rows.append(row_dict)
                    print(f"[INFO] Pre-loaded {len(material_similarity_rows)} rows from {sim_table}")
                except Exception as e:
                    print(f"[WARN] Could not load {sim_table}: {e}")

            # ---- Preload public_GDS_omics → GSE_ID lookup ----
            # sample_id column is comma-separated: "id1,id2,id3"
            gds_lookup = {}     # {sample_id → [GSE_ID, ...]}
            pathway_lookup = {}  # {GSE_ID → [row_dict, ...]}
            gds_debug = {"rows": 0, "parsed_sample_ids": 0, "unique_gse_ids": 0}
            pw_debug = {"rows": 0, "with_factor": 0, "unique_gse_ids": 0}
            try:
                cursor.execute(
                    "SELECT sample_id, GSE_ID FROM public_GDS_omics "
                    "WHERE sample_id IS NOT NULL AND sample_id != ''"
                )
                for gds_row in cursor.fetchall():
                    gds_debug["rows"] += 1
                    raw_ids = str(gds_row.get("sample_id", ""))
                    gse_id = str(gds_row.get("GSE_ID", "")).strip()
                    if raw_ids and gse_id:
                        for sid in raw_ids.split(","):
                            sid = sid.strip()
                            if sid:
                                gds_debug["parsed_sample_ids"] += 1
                                if sid not in gds_lookup:
                                    gds_lookup[sid] = []
                                if gse_id not in gds_lookup[sid]:
                                    gds_lookup[sid].append(gse_id)
                gds_debug["unique_gse_ids"] = len(set(
                    gse for gse_list in gds_lookup.values() for gse in gse_list
                ))
                print(f"[INFO] Pre-loaded GDS_omics: {gds_debug['rows']} rows → "
                      f"{len(gds_lookup)} unique sample_ids → {gds_debug['unique_gse_ids']} unique GSE_IDs")

                # ---- Preload public_search_pathway → GroupInfo data ----
                cursor.execute(
                    "SELECT * FROM public_search_pathway "
                    "WHERE GSE_ID IS NOT NULL AND GSE_ID != '' AND factor IS NOT NULL AND factor != ''"
                )
                for pw_row in cursor.fetchall():
                    pw_debug["rows"] += 1
                    gse_id = str(pw_row.get("GSE_ID", "")).strip()
                    factor_val = str(pw_row.get("factor", "")).strip() if pw_row.get("factor") else ""
                    if gse_id:
                        pw_debug["with_factor"] += 1
                        if gse_id not in pathway_lookup:
                            pathway_lookup[gse_id] = []
                        pathway_lookup[gse_id].append(pw_row)
                pw_debug["unique_gse_ids"] = len(pathway_lookup)
                print(f"[INFO] Pre-loaded search_pathway: {pw_debug['rows']} rows "
                      f"(with factor: {pw_debug['with_factor']}) → {pw_debug['unique_gse_ids']} unique GSE_IDs")
            except Exception as e:
                print(f"[WARN] Could not load GDS_omics or search_pathway: {e}")
                gds_lookup = {}
                pathway_lookup = {}

            # ---- Sub-node config for GroupInfo enrichment (queried on-demand in Step F) ----
            # Use module-level GROUPINFO_SUB_NODE_MAX_ROWS (override via --groupinfo-max-rows CLI arg)

            GROUPINFO_SUB_NODE_CONFIG = [
                {
                    "node_type": "GroupDEGs", "id_prefix": "gde",
                    "table": "public_rna_seq_differ_genes",
                    "fields": ["data", "group", "symbol", "regulation", "pseudobulk_cell_type"],
                    "name_field": "symbol",
                },
                {
                    "node_type": "IntraClusterDEGs", "id_prefix": "icd",
                    "table": "public_scrna_seq_cluster_differ_genes",
                    "fields": ["data", "group", "symbol", "cluster"],
                    "name_field": "symbol",
                },
                {
                    "node_type": "ClusterMarkers", "id_prefix": "clm",
                    "table": "public_scrna_seq_cluster_marker_genes",
                    "fields": ["data", "group", "symbol", "cluster"],
                    "name_field": "symbol",
                },
                {
                    "node_type": "GSVA", "id_prefix": "gsv",
                    "table": "public_rna_seq_gsva_differ_pathways",
                    "fields": ["data", "group", "term", "regulation", "pseudobulk_cell_type"],
                    "name_field": "term",
                },
                {
                    "node_type": "GSEA", "id_prefix": "gse",
                    "table": "public_rna_seq_gsea_enriched_pathways",
                    "fields": ["data", "group", "terms", "pathway_id"],
                    "name_field": "terms",
                },
            ]

            # ---- Gene Annotation table groups for Step G ----
            # Each group maps to human/mouse tables queried by gene symbol.
            # multi_row=True means results are stored as JSON arrays.
            GENE_ANNOTATION_TABLE_GROUPS = [
                {
                    "group_name": "gene_annotation",
                    "human_table": "Gene_Annotation_Human",
                    "mouse_table": "Gene_Annotation_Mouse",
                    "match_column": "symbol",
                    "fields": ["entrez_id", "gene_name", "pfam", "prosite", "drug_id"],
                },
                {
                    "group_name": "site",
                    "human_table": "site_human",
                    "mouse_table": "site_mouse",
                    "match_column": "Gene_Names",
                    "fields": ["Entry", "Site", "Binding_site", "Active_site"],
                },
                {
                    "group_name": "disease",
                    "human_table": "disease_human",
                    "mouse_table": "disease_mouse",
                    "match_column": "Gene_Names",
                    "fields": ["Involvement_in_disease", "Mutagenesis"],
                },
                {
                    "group_name": "string",
                    "human_table": "STRING_Combine_Human",
                    "mouse_table": "STRING_Combine_Mouse",
                    "match_column": "GeneSymbol_x",
                    "match_column_alt": "GeneSymbol_y",
                    "fields": ["GeneSymbol_x", "GeneSymbol_y", "combined_score"],
                },
                {
                    "group_name": "crispick",
                    "human_table": "CRISPick_Combine_Human",
                    "mouse_table": "CRISPick_Combine_Mouse",
                    "match_column": "Input",
                    "fields": ["CRISPR Mechanism", "PAM Policy", "sgRNA Sequence",
                               "sgRNA Context Sequence", "Combined Rank"],
                },
            ]

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
                        entity_registry, entity_type, prefix, entity_name
                    )
                    if is_new:
                        nodes.append(entity_node)

                    # Create edge
                    edge_context = "coculture" if col in COCULTURE_COLUMNS else "primary"
                    if edge_from == "sample":
                        edge = self._make_edge(sample_id, entity_node["id"], relation,
                                               {"source_column": col, "context": edge_context})
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
                    if entity_type == "Organ":
                        organ_registry[entity_name] = entity_node["id"]

                # ---- Step B.6: Extract compound entity nodes (merged, profile) ----
                for primary_col, config in COMPOUND_ENTITY_CONFIG.items():
                    extraction_type = config["extraction_type"]

                    if extraction_type == "merged":
                        merged_node = self._extract_merged_node(row, config)
                        if merged_node is None:
                            continue

                        # Dedup by content hash via (node_type, node_id) registry key
                        node_id = merged_node["id"]
                        registry_key = (config["node_type"], node_id)
                        if registry_key in entity_registry:
                            entity_node = entity_registry[registry_key]
                        else:
                            entity_registry[registry_key] = merged_node
                            entity_node = merged_node
                            nodes.append(merged_node)

                        # Enrich CoCultureProtocol material_sources from raw_json
                        if config["node_type"] == "CoCultureProtocol":
                            sample_id_raw = str(row.get("sample_id", ""))
                            raw_json_val = infection_raw_lookup.get(sample_id_raw)
                            ms_list = self._extract_coculture_material_sources_from_raw(raw_json_val)
                            if ms_list:
                                existing = entity_node["properties"].get("material_sources")
                                if existing:
                                    # Merge: append unique new sources
                                    existing_list = ([existing] if isinstance(existing, str)
                                                     else (existing if isinstance(existing, list) else [str(existing)]))
                                    for ms in ms_list:
                                        if ms not in existing_list:
                                            existing_list.append(ms)
                                    entity_node["properties"]["material_sources"] = existing_list
                                else:
                                    entity_node["properties"]["material_sources"] = ms_list

                        # For CultureProtocol/CoCultureProtocol: extract components as CellFactor nodes
                        if config["node_type"] in ("CultureProtocol", "CoCultureProtocol"):
                            component_fields = [
                                ("growth_factor_names", "growth_factor"),
                                ("small_molecule_names", "small_molecule"),
                                ("supplement_names", "supplement"),
                                ("media_used", "medium"),
                            ]
                            for prop_key, component_type in component_fields:
                                items = entity_node["properties"].get(prop_key, [])
                                if not items:
                                    continue
                                for item_name in items:
                                    if not item_name or not str(item_name).strip():
                                        continue
                                    cf_node, cf_is_new = self._get_or_create_entity(
                                        entity_registry, "CellFactor", "cf", str(item_name).strip()
                                    )
                                    if cf_is_new:
                                        cf_node["properties"]["component_type"] = component_type
                                        nodes.append(cf_node)
                                    # Edge: Protocol -[:USES_COMPONENT]-> CellFactor
                                    cf_edge = self._make_edge(entity_node["id"], cf_node["id"],
                                                              "USES_COMPONENT",
                                                              {"component_type": component_type,
                                                               "source": "protocol_parsing"})
                                    if cf_edge:
                                        ek = (cf_edge["source"], cf_edge["target"], cf_edge["relation"])
                                        if ek not in global_edge_keys:
                                            global_edge_keys.add(ek)
                                            edges.append(cf_edge)

                        # ---- Extract MaterialInfo nodes from material_sources ----
                        if (MATERIAL_INFO_CONFIG
                                and config["node_type"] in MATERIAL_INFO_CONFIG.get("parent_node_types", [])):
                            src_prop = MATERIAL_INFO_CONFIG.get("source_property", "material_sources")
                            ms_value = entity_node["properties"].get(src_prop)
                            if ms_value:
                                material_items = self._parse_material_sources(ms_value)
                                json_props = MATERIAL_INFO_CONFIG.get("json_properties", [])
                                enrich_fields = MATERIAL_INFO_CONFIG.get("enrichment_fields", [])
                                name_fallback = MATERIAL_INFO_CONFIG.get("name_fallback_field", "material_name")

                                for item in material_items:
                                    if not isinstance(item, dict):
                                        continue
                                    mat_name_raw = str(item.get("material_name", "")).strip()
                                    if not mat_name_raw:
                                        continue

                                    # Enrich from similarity table
                                    enriched = self._match_material_similarity(
                                        mat_name_raw, material_similarity_rows
                                    ) or {}

                                    # Build dedup dict for content-hash
                                    dedup_dict = {}
                                    for p in json_props:
                                        dedup_dict[p] = (str(item.get(p, "")).strip()
                                                         if item.get(p) is not None else "")
                                    for f in enrich_fields:
                                        dedup_dict[f] = enriched.get(f, "")

                                    content_hash = self._content_hash(dedup_dict)
                                    mat_node_id = f"{MATERIAL_INFO_CONFIG['id_prefix']}_{content_hash}"

                                    # Dedup MaterialInfo node by content hash
                                    mat_registry_key = ("MaterialInfo", mat_node_id)
                                    if mat_registry_key in entity_registry:
                                        mat_node = entity_registry[mat_registry_key]
                                    else:
                                        mat_node = {
                                            "id": mat_node_id,
                                            "type": "MaterialInfo",
                                            "properties": {
                                                "name": enriched.get("standard_name")
                                                        or item.get(name_fallback, ""),
                                            },
                                            "_provenance": {
                                                "source_type": "material_extraction",
                                                "parent_node_type": config["node_type"],
                                                "extracted_at": datetime.now().isoformat()
                                            }
                                        }
                                        # Populate json_properties
                                        for p in json_props:
                                            val = item.get(p)
                                            if val is not None and str(val).strip():
                                                mat_node["properties"][p] = str(val).strip()
                                        # Populate enrichment fields
                                        for f in enrich_fields:
                                            if f in enriched and enriched[f]:
                                                mat_node["properties"][f] = enriched[f]

                                        entity_registry[mat_registry_key] = mat_node
                                        nodes.append(mat_node)

                                    # Edge: Protocol -[:USES_MATERIAL]-> MaterialInfo
                                    mat_edge = self._make_edge(
                                        entity_node["id"], mat_node_id,
                                        MATERIAL_INFO_CONFIG["relation"],
                                        {"source": "material_sources_parsing",
                                         "protocol_type": config["node_type"]}
                                    )
                                    if mat_edge:
                                        ek = (mat_edge["source"], mat_edge["target"], mat_edge["relation"])
                                        if ek not in global_edge_keys:
                                            global_edge_keys.add(ek)
                                            edges.append(mat_edge)

                        # Create edge from Sample
                        if config["edge_from"] == "sample":
                            edge = self._make_edge(sample_id, entity_node["id"], config["relation"],
                                                   {"source_columns": config["source_columns"]})
                            if edge:
                                ek = (edge["source"], edge["target"], edge["relation"])
                                if ek not in global_edge_keys:
                                    global_edge_keys.add(ek)
                                    edges.append(edge)
                            sample_entities[sample_id][config["node_type"]].add(entity_node["id"])

                    elif extraction_type == "profile":
                        merged_node = self._extract_merged_node(row, config)
                        if merged_node is None:
                            continue

                        node_id = merged_node["id"]
                        registry_key = (config["node_type"], node_id)
                        if registry_key in entity_registry:
                            entity_node = entity_registry[registry_key]
                        else:
                            entity_registry[registry_key] = merged_node
                            entity_node = merged_node
                            nodes.append(merged_node)

                        # Create edge based on config.edge_from
                        if config["edge_from"] == "sample":
                            edge = self._make_edge(sample_id, entity_node["id"], config["relation"],
                                                   {"source_columns": config["source_columns"]})
                            if edge:
                                ek = (edge["source"], edge["target"], edge["relation"])
                                if ek not in global_edge_keys:
                                    global_edge_keys.add(ek)
                                    edges.append(edge)
                        sample_entities[sample_id][config["node_type"]].add(entity_node["id"])

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
                            # DEBUG: test column missing or NULL
                            if col == "test":
                                test_debug["null_or_missing"] += 1
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
                        # DEBUG: record test empty parse
                        if col == "test":
                            test_debug["parse_empty"] += 1
                            if len(test_debug["samples"]) < 3:
                                test_debug["samples"].append({
                                    "reason": "parse returned empty",
                                    "raw_type": type(json_data).__name__,
                                    "raw_preview": str(json_data)[:200],
                                })
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

                    # test column may have nested structures; flatten to leaf strings
                    if col == "test":
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
                        if col == "test":
                            test_debug["entity_extracted"] += 1

                        # Create or retrieve entity node
                        entity_node, is_new = self._get_or_create_entity(
                            entity_registry, entity_type, prefix, entity_name
                        )
                        if is_new:
                            # Extract additional properties from JSON entry
                            if isinstance(item, dict):
                                for k, v in item.items():
                                    if k not in ("name", "Name", "phenotype") and v is not None:
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
                        elif edge_from == "organ":
                            self._defer_organ_edge = getattr(self, '_defer_organ_edge', [])
                            self._defer_organ_edge.append((col, entity_node["id"], relation,
                                                            {"source_column": col}))

                        sample_entities[sample_id][entity_type].add(entity_node["id"])

                # ---- Step C.5: Extract JSON-structured entity nodes ----
                for col, config in COMPOUND_ENTITY_CONFIG.items():
                    if config["extraction_type"] != "json_structured":
                        continue
                    if col not in row or row[col] is None or row[col] == '':
                        if col in js_debug:
                            js_debug[col]["null_or_missing"] += 1
                        continue

                    config_with_source = dict(config)
                    config_with_source["_source_column"] = col
                    structured_node = self._extract_json_structured_node(row[col], config_with_source)
                    if structured_node is None:
                        if col in js_debug:
                            # Try to determine WHY extraction failed
                            val = row[col]
                            if isinstance(val, str):
                                try:
                                    parsed = json.loads(val)
                                except json.JSONDecodeError:
                                    js_debug[col]["parse_failed"] += 1
                                    if len(js_debug[col]["samples"]) < 3:
                                        js_debug[col]["samples"].append({
                                            "reason": "JSON decode error",
                                            "raw_preview": val[:200],
                                        })
                                    continue
                            elif isinstance(val, (dict, list)):
                                parsed = val
                            else:
                                js_debug[col]["parse_failed"] += 1
                                if len(js_debug[col]["samples"]) < 3:
                                    js_debug[col]["samples"].append({
                                        "reason": f"unexpected type: {type(val).__name__}",
                                        "raw_preview": str(val)[:200],
                                    })
                                continue

                            if not parsed:
                                js_debug[col]["empty_data"] += 1
                                if len(js_debug[col]["samples"]) < 3:
                                    js_debug[col]["samples"].append({
                                        "reason": "empty data (after parse)",
                                        "parsed_type": type(parsed).__name__,
                                        "raw_preview": str(row[col])[:200],
                                    })
                            elif not isinstance(parsed, dict):
                                js_debug[col]["non_dict_data"] += 1
                                if len(js_debug[col]["samples"]) < 3:
                                    js_debug[col]["samples"].append({
                                        "reason": f"non-dict type: {type(parsed).__name__}",
                                        "parsed_type": type(parsed).__name__,
                                        "raw_preview": str(row[col])[:200],
                                        "parsed_preview": str(parsed)[:200],
                                    })
                            else:
                                js_debug[col]["empty_data"] += 1  # dict but empty
                        continue

                    if col in js_debug:
                        js_debug[col]["extracted_ok"] += 1

                    node_id = structured_node["id"]
                    registry_key = (config["node_type"], node_id)
                    if registry_key in entity_registry:
                        entity_node = entity_registry[registry_key]
                    else:
                        entity_registry[registry_key] = structured_node
                        entity_node = structured_node
                        nodes.append(structured_node)

                    if config["edge_from"] == "sample":
                        edge = self._make_edge(sample_id, entity_node["id"], config["relation"],
                                               {"source_column": col})
                        if edge:
                            ek = (edge["source"], edge["target"], edge["relation"])
                            if ek not in global_edge_keys:
                                global_edge_keys.add(ek)
                                edges.append(edge)
                        sample_entities[sample_id][config["node_type"]].add(entity_node["id"])

                # ---- Step C.5.5: Extract CoCultureTechnique from raw_json ----
                # Data lives at 'culture_technique_coculture' key in raw_json, not in main table column
                sample_id_raw = str(row.get("sample_id", ""))
                cct_debug["lookup_attempts"] += 1
                raw_json_val = infection_raw_lookup.get(sample_id_raw)
                if raw_json_val is not None:
                    cct_debug["raw_found"] += 1
                    cct_data = self._extract_coculture_technique_from_raw(raw_json_val)
                    if cct_data is not None:
                        cct_debug["key_found"] += 1
                        if len(cct_debug["samples"]) < 3:
                            cct_debug["samples"].append({
                                "sample_id": sample_id_raw,
                                "cct_data_type": type(cct_data).__name__,
                                "cct_data_len": len(cct_data) if isinstance(cct_data, list) else 1,
                                "cct_data_preview": str(cct_data)[:300],
                            })
                        # cct_data is a list of technique strings from cultures[] entries
                        if not isinstance(cct_data, list):
                            cct_data = [cct_data]
                        cct_config = {
                            "node_type": "CoCultureTechnique", "id_prefix": "cct",
                            "_source_column": "culture_technique_coculture",
                        }
                        for technique_val in cct_data:
                            if not technique_val or not str(technique_val).strip():
                                continue
                            cct_node = self._extract_json_structured_node(technique_val, cct_config)
                            if cct_node is not None:
                                node_id = cct_node["id"]
                                registry_key = ("CoCultureTechnique", node_id)
                                if registry_key in entity_registry:
                                    cct_entity = entity_registry[registry_key]
                                    cct_debug["node_dedup"] += 1
                                else:
                                    entity_registry[registry_key] = cct_node
                                    cct_entity = cct_node
                                    nodes.append(cct_node)
                                    cct_debug["node_created"] += 1
                                edge = self._make_edge(sample_id, cct_entity["id"],
                                                       "USES_COCULTURE_TECHNIQUE",
                                                       {"source_column": "culture_technique_coculture"})
                                if edge:
                                    ek = (edge["source"], edge["target"], edge["relation"])
                                    if ek not in global_edge_keys:
                                        global_edge_keys.add(ek)
                                        edges.append(edge)
                                sample_entities[sample_id]["CoCultureTechnique"].add(cct_entity["id"])
                            else:
                                cct_debug["extraction_failed"] += 1
                                if len(cct_debug["samples"]) < 5:
                                    cct_debug["samples"].append({
                                        "sample_id": sample_id_raw,
                                        "fail_reason": "_extract_json_structured_node returned None",
                                        "technique_val_type": type(technique_val).__name__,
                                        "technique_val_preview": str(technique_val)[:200],
                                    })
                    else:
                        cct_debug["key_not_found"] += 1
                else:
                    cct_debug["raw_not_found"] += 1
                    if len(cct_debug["samples"]) < 3 and cct_debug["raw_not_found"] <= 3:
                        cct_debug["samples"].append({
                            "sample_id": sample_id_raw,
                            "fail_reason": "raw_json not found in infection_raw_lookup",
                        })

                # ---- Step C.6: Extract Platform node (Omics → Platform two-level edge) ----
                platform_config = COMPOUND_ENTITY_CONFIG.get("platform")
                if platform_config:
                    platform_val = row.get("platform")
                    if platform_val is not None and str(platform_val).strip():
                        platform_node = self._extract_platform_node(str(platform_val))
                        if platform_node:
                            node_id = platform_node["id"]
                            registry_key = ("Platform", node_id)
                            if registry_key in entity_registry:
                                entity_node = entity_registry[registry_key]
                            else:
                                entity_registry[registry_key] = platform_node
                                entity_node = platform_node
                                nodes.append(platform_node)

                            # Defer: Omics → Platform edge (resolve after Omics is created)
                            self._defer_omics_edge = getattr(self, '_defer_omics_edge', [])
                            self._defer_omics_edge.append(
                                ("platform", entity_node["id"], "USES_PLATFORM",
                                 {"source_column": "platform"})
                            )
                            sample_entities[sample_id]["Platform"].add(entity_node["id"])

                # ---- Step D: Resolve deferred Organ→System edges ----
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

                # ---- Step D.5: Resolve deferred Omics → Platform edges & enrich properties ----
                deferred_omics = getattr(self, '_defer_omics_edge', [])
                if deferred_omics:
                    # Find Omics node for this sample
                    omics_node_id = None
                    for etype, ids in sample_entities[sample_id].items():
                        if etype == "Omics" and ids:
                            omics_node_id = list(ids)[0]
                            break

                    if omics_node_id:
                        for item in deferred_omics:
                            col, tgt_id, rel, props = item
                            # Enrich platform name onto Omics node
                            for node in nodes:
                                if node["id"] == omics_node_id:
                                    node["properties"]["platform"] = str(row.get("platform", ""))
                                    break
                            edge = self._make_edge(omics_node_id, tgt_id, rel, props)
                            if edge:
                                ek = (edge["source"], edge["target"], edge["relation"])
                                if ek not in global_edge_keys:
                                    global_edge_keys.add(ek)
                                    edges.append(edge)
                self._defer_omics_edge = []

                # ---- Enrich sgrna onto Gene node ----
                sgrna_val = row.get("sgrna")
                if sgrna_val is not None and str(sgrna_val).strip():
                    gene_name = str(row.get("gene_name", "")).strip() if row.get("gene_name") else None
                    if gene_name:
                        gene_key = ("Gene", gene_name.lower())
                        if gene_key in entity_registry:
                            gene_node = entity_registry[gene_key]
                            gene_node["properties"]["sgrna"] = str(sgrna_val).strip()
                            gene_node["properties"]["editing_method"] = gene_node["properties"].get(
                                "editing_method", "CRISPR-Cas9")

                # ---- Enrich organism/species onto Gene node ----
                gene_name_val = str(row.get("gene_name", "")).strip() if row.get("gene_name") else None
                organism_val = str(row.get("organism", "")).strip() if row.get("organism") else None
                if gene_name_val and organism_val:
                    gene_key = ("Gene", gene_name_val.lower())
                    if gene_key in entity_registry:
                        gene_node = entity_registry[gene_key]
                        organisms = gene_node["properties"].get("organisms", [])
                        if organism_val not in organisms:
                            organisms.append(organism_val)
                            gene_node["properties"]["organisms"] = organisms
                        species = MySQLKnowledgeGraphBuilder._detect_species(organism_val)
                        if species:
                            species_list = gene_node["properties"].get("species", [])
                            if species not in species_list:
                                species_list.append(species)
                                gene_node["properties"]["species"] = sorted(species_list)

                # ---- Enrich accession onto Omics node ----
                accession_val = row.get("accession")
                if accession_val is not None and str(accession_val).strip():
                    for etype, ids in sample_entities[sample_id].items():
                        if etype == "Omics" and ids:
                            omics_nid = list(ids)[0]
                            for node in nodes:
                                if node["id"] == omics_nid:
                                    node["properties"]["accession"] = str(accession_val).strip()
                                    break
                            break

                # ---- Extract GroupInfo from GDS_omics → search_pathway lookup chain ----
                sample_id_raw = str(row.get("sample_id", ""))
                gse_ids = gds_lookup.get(sample_id_raw, [])
                for gse_id in gse_ids:
                    pw_rows = pathway_lookup.get(gse_id, [])
                    for pw_row in pw_rows:
                        factor_val = str(pw_row.get("factor", "")).strip() if pw_row.get("factor") else None
                        if not factor_val:
                            continue

                        # Collect all relevant fields for content-hash dedup
                        groupinfo_fields = [
                            "Data_Type", "Organism", "group", "condition", "additional_condition",
                            "factor", "organ_control", "organ_condition",
                            "organ_system_control", "organ_system_condition",
                            "comparison_control", "comparison_condition",
                            "model_control", "model_condition",
                            "time_control", "time_condition",
                            "source_control", "source_condition",
                            "category", "path", "GSE_ID", "cell_type"
                        ]
                        merged_data = {}
                        for field in groupinfo_fields:
                            val = pw_row.get(field)
                            if val is not None and str(val).strip():
                                merged_data[field] = str(val).strip()

                        if not merged_data.get("factor"):
                            continue

                        content_hash = self._content_hash(merged_data)
                        node_id = f"gin_{content_hash}"
                        registry_key = ("GroupInfo", node_id)

                        if registry_key in entity_registry:
                            entity_node = entity_registry[registry_key]
                        else:
                            entity_node = {
                                "id": node_id,
                                "type": "GroupInfo",
                                "properties": {
                                    "name": merged_data.get("factor", ""),
                                    **merged_data
                                },
                                "_provenance": {
                                    "source_type": "cross_table_lookup",
                                    "source_tables": ["public_GDS_omics", "public_search_pathway"],
                                    "gse_id": gse_id,
                                    "lookup_key": sample_id_raw,
                                    "extracted_at": datetime.now().isoformat()
                                }
                            }
                            entity_registry[registry_key] = entity_node
                            nodes.append(entity_node)

                        # Create edge: Sample -[:HAS_GROUP_INFO]-> GroupInfo
                        edge = self._make_edge(sample_id, entity_node["id"], "HAS_GROUP_INFO",
                                               {"source": "public_GDS_omics→public_search_pathway",
                                                "gse_id": gse_id,
                                                "factor": merged_data.get("factor", "")})
                        if edge:
                            ek = (edge["source"], edge["target"], edge["relation"])
                            if ek not in global_edge_keys:
                                global_edge_keys.add(ek)
                                edges.append(edge)

                        sample_entities[sample_id]["GroupInfo"].add(entity_node["id"])

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

            # ---- DEBUG: json_structured columns analysis ----
            print(f"[DEBUG] json_structured column analysis (CultureCondition, CoCultureTechnique):")
            for js_col in ["culture_condition", "coculture_technique"]:
                dbg = js_debug.get(js_col, {})
                print(f"  [{js_col}]:")
                print(f"    null_or_missing:   {dbg.get('null_or_missing', 0)}")
                print(f"    parse_failed:      {dbg.get('parse_failed', 0)}")
                print(f"    non_dict_data:     {dbg.get('non_dict_data', 0)}")
                print(f"    empty_data:        {dbg.get('empty_data', 0)}")
                print(f"    extracted_ok:      {dbg.get('extracted_ok', 0)}")
                if dbg.get("samples"):
                    print(f"    sample failures (first {len(dbg['samples'])}):")
                    for s in dbg["samples"]:
                        print(f"      reason={s.get('reason')}, parsed_type={s.get('parsed_type', '?')}")
                        print(f"      raw: {s.get('raw_preview', '?')[:150]}")
            print()

            # ---- DEBUG: coculture technique from raw_json ----
            print(f"[DEBUG] CoCultureTechnique extraction from raw_json:")
            print(f"  lookup_attempts:     {cct_debug.get('lookup_attempts', 0)}")
            print(f"  raw_found:           {cct_debug.get('raw_found', 0)}")
            print(f"  raw_not_found:       {cct_debug.get('raw_not_found', 0)}")
            print(f"  key_found:           {cct_debug.get('key_found', 0)}")
            print(f"  key_not_found:       {cct_debug.get('key_not_found', 0)}")
            print(f"  node_created:        {cct_debug.get('node_created', 0)}")
            print(f"  node_dedup:          {cct_debug.get('node_dedup', 0)}")
            print(f"  extraction_failed:   {cct_debug.get('extraction_failed', 0)}")
            if cct_debug.get("samples"):
                print(f"  sample details (first {len(cct_debug['samples'])}):")
                for s in cct_debug["samples"]:
                    for k, v in s.items():
                        print(f"    {k}: {v}")
            print()

            # ---- DEBUG: test column analysis ----
            print(f"[DEBUG] test column analysis:")
            print(f"  null_or_missing:     {test_debug.get('null_or_missing', 0)}")
            print(f"  parse_empty:         {test_debug.get('parse_empty', 0)}")
            print(f"  entity_extracted:    {test_debug.get('entity_extracted', 0)}")
            if test_debug.get("samples"):
                print(f"  sample failures (first {len(test_debug['samples'])}):")
                for s in test_debug["samples"]:
                    for k, v in s.items():
                        print(f"    {k}: {v}")
            print()

            # ---- Step E: Generate inferred relationships ----
            print(f"[INFO] Generating inferred relationships...")
            inferred_edges = self._infer_relationships(
                sample_entities, entity_registry, nodes, edges)
            edges.extend(inferred_edges)
            print(f"[INFO] Added {len(inferred_edges)} inferred edges")

            # ---- Step F: Create sub-nodes from GroupInfo (DEGs, markers, pathways) ----
            # Collect unique GSE_IDs + organisms from GroupInfo, then query each
            # sub-table on-demand with only the needed columns.
            print(f"[INFO] Creating sub-nodes from GroupInfo via GSE_ID cross-reference...")
            sub_node_counts = {}
            sub_edge_counts = {}

            # {gse_id: {"ginodes": [(node_id, organism), ...], "organisms": set()}}
            gse_info = {}
            for (etype, node_id), ginode in entity_registry.items():
                if etype != "GroupInfo":
                    continue
                gse_id = str(ginode["properties"].get("GSE_ID", "")).strip()
                if not gse_id:
                    continue
                organism = str(ginode["properties"].get("Organism", "")).strip()
                if gse_id not in gse_info:
                    gse_info[gse_id] = {"ginodes": [], "organisms": set()}
                gse_info[gse_id]["ginodes"].append((node_id, organism))
                if organism:
                    gse_info[gse_id]["organisms"].add(organism)

            if not gse_info:
                print(f"  No GroupInfo nodes with GSE_ID found, skipping sub-node creation.")
            else:
                all_gse_ids = sorted(gse_info.keys())
                total_ginodes = sum(len(v["ginodes"]) for v in gse_info.values())
                print(f"  Collected {len(all_gse_ids)} unique GSE_IDs from {total_ginodes} GroupInfo nodes")

                BATCH_SIZE = 256

                # Relation name per sub-node type (Step F edges: GroupInfo → sub-node)
                _SUB_RELATION_MAP = {
                    "GroupDEGs": "HAS_DEG",
                    "IntraClusterDEGs": "HAS_INTRACLUSTER_DEG",
                    "ClusterMarkers": "HAS_CLUSTER_MARKER",
                    "GSVA": "HAS_GSVA_PATHWAY",
                    "GSEA": "HAS_GSEA_PATHWAY",
                }

                for cfg in GROUPINFO_SUB_NODE_CONFIG:
                    nt = cfg["node_type"]
                    table = cfg["table"]
                    fields = cfg["fields"]
                    name_field = cfg["name_field"]
                    nt_new_nodes = 0
                    nt_new_edges = 0

                    # ---- DEBUG for specific node types ----
                    is_debug = (nt == "GSEA")
                    if is_debug:
                        print(f"  [{datetime.now().strftime('%H:%M:%S')}] [DEBUG:{nt}] "
                              f"table={table}, fields={fields}, name_field={name_field}, "
                              f"total GSE_IDs={len(all_gse_ids)}, max_rows={GROUPINFO_SUB_NODE_MAX_ROWS}")

                    # Only SELECT needed columns (not SELECT *)
                    needed_cols = list(dict.fromkeys(fields + ["data"]))  # order-preserving dedup
                    col_list = ", ".join(f"`{c}`" for c in needed_cols)

                    # Query rows, group by data (=GSE_ID).
                    # When GROUPINFO_SUB_NODE_MAX_ROWS is set, query each GSE_ID
                    # individually with LIMIT to avoid fetching unnecessary rows.
                    temp_lookup = {}  # {gse_id: [row_dict, ...]}
                    total_rows = 0
                    total_gse = len(all_gse_ids)
                    try:
                        if GROUPINFO_SUB_NODE_MAX_ROWS is not None:
                            # Per-GSE_ID query with LIMIT (compatible with MySQL 5.x / 8.x)
                            base_sql = f"SELECT DISTINCT {col_list} FROM `{table}` WHERE data = %s LIMIT {GROUPINFO_SUB_NODE_MAX_ROWS}"
                            for gse_idx, gse_id in enumerate(all_gse_ids):
                                cursor.execute(base_sql, (gse_id,))
                                batch_rows = 0
                                for sub_row in cursor.fetchall():
                                    if gse_id in gse_info:
                                        temp_lookup.setdefault(gse_id, []).append(sub_row)
                                        batch_rows += 1
                                total_rows += batch_rows
                                if (gse_idx + 1) % BATCH_SIZE == 0 or (gse_idx + 1) == total_gse:
                                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] [{nt}] "
                                          f"GSE_IDs {gse_idx + 1}/{total_gse}: "
                                          f"{total_rows} rows cumul., {len(temp_lookup)} keys")
                        else:
                            # Original batch query (no per-GSE_ID limit)
                            total_batches = (total_gse + BATCH_SIZE - 1) // BATCH_SIZE
                            for batch_idx in range(total_batches):
                                i = batch_idx * BATCH_SIZE
                                batch = all_gse_ids[i:i + BATCH_SIZE]
                                placeholders = ",".join(["%s"] * len(batch))
                                sql = f"SELECT DISTINCT {col_list} FROM `{table}` WHERE data IN ({placeholders})"
                                cursor.execute(sql, batch)
                                batch_rows = 0
                                for sub_row in cursor.fetchall():
                                    key = str(sub_row.get("data", "")).strip()
                                    if key and key in gse_info:
                                        temp_lookup.setdefault(key, []).append(sub_row)
                                        batch_rows += 1
                                total_rows += batch_rows
                                print(f"  [{datetime.now().strftime('%H:%M:%S')}] [{nt}] "
                                      f"batch {batch_idx + 1}/{total_batches} "
                                      f"({len(batch)} GSE_IDs): {batch_rows} rows "
                                      f"(cumulative: {total_rows} rows, {len(temp_lookup)} keys)")
                    except Exception as e:
                        print(f"  [WARN] Could not query {table}: {e}")
                        if is_debug:
                            import traceback
                            print(f"  [DEBUG:{nt}] Full traceback:\n{traceback.format_exc()}")
                        continue

                    if is_debug:
                        sample_keys = list(temp_lookup.keys())[:3]
                        sample_info = []
                        for k in sample_keys:
                            rows = temp_lookup[k]
                            sample_info.append(f"{k}: {len(rows)} rows, "
                                               f"first_row_cols={list(rows[0].keys()) if rows else 'N/A'}, "
                                               f"first_row_preview={ {c: rows[0].get(c) for c in (fields + ['data'])} if rows else 'N/A'}")
                        print(f"  [DEBUG:{nt}] query done: {total_rows} total rows, "
                              f"{len(temp_lookup)} keys; sample: {' | '.join(sample_info)}")

                    # Pre-resolve sub-node IDs per (gse_id, organism) for each row
                    # to avoid redundant _content_hash calls in the edge-creation loop.
                    # gse_row_nodes: {gse_id: [(sub_node_id, nt), ...]}
                    gse_row_nodes = {}
                    total_keys = len(temp_lookup)
                    processed_keys = 0
                    for gse_id, rows in temp_lookup.items():
                        info = gse_info.get(gse_id)
                        if not info:
                            continue
                        node_ids_for_gse = []
                        seen_in_gse = set()  # dedup within this gse

                        for row in rows:
                            # Build base data from table fields
                            base_data = {}
                            for f in fields:
                                val = row.get(f)
                                if val is not None and str(val).strip():
                                    base_data[f] = str(val).strip()

                            name_val = base_data.get(name_field)
                            if not name_val:
                                continue

                            # One sub-node per unique (base_data + organism) combo
                            organisms = info["organisms"] if info["organisms"] else {""}
                            for organism in organisms:
                                merged_data = dict(base_data)
                                if organism:
                                    merged_data["organism"] = organism

                                content_hash = self._content_hash(merged_data)
                                sub_node_id = f"{cfg['id_prefix']}_{content_hash}"
                                sub_registry_key = (nt, sub_node_id)

                                if sub_registry_key not in entity_registry:
                                    sub_node = {
                                        "id": sub_node_id,
                                        "type": nt,
                                        "properties": {
                                            "name": name_val,
                                            **merged_data
                                        },
                                        "_provenance": {
                                            "source_type": "cross_table_lookup",
                                            "source_tables": [table],
                                            "gse_id": gse_id,
                                            "extracted_at": datetime.now().isoformat()
                                        }
                                    }
                                    entity_registry[sub_registry_key] = sub_node
                                    nodes.append(sub_node)
                                    nt_new_nodes += 1

                                if sub_node_id not in seen_in_gse:
                                    seen_in_gse.add(sub_node_id)
                                    node_ids_for_gse.append(sub_node_id)

                        gse_row_nodes[gse_id] = node_ids_for_gse
                        processed_keys += 1
                        if processed_keys % 100 == 0 or processed_keys == total_keys:
                            print(f"  [{datetime.now().strftime('%H:%M:%S')}] [{nt}] nodes: {processed_keys}/{total_keys} keys done, "
                                  f"{nt_new_nodes} new nodes so far")

                    # Create edges: each GroupInfo → all sub-nodes of its GSE_ID
                    total_gses = len(gse_row_nodes)
                    processed_gses = 0
                    for gse_id, node_ids in gse_row_nodes.items():
                        info = gse_info.get(gse_id)
                        if not info or not node_ids:
                            continue
                        for ginode_id, organism in info["ginodes"]:
                            for sub_node_id in node_ids:
                                edge = self._make_edge(ginode_id, sub_node_id, _SUB_RELATION_MAP.get(nt, "HAS"),
                                                       {"source_table": table, "gse_id": gse_id})
                                if edge:
                                    ek = (edge["source"], edge["target"], edge["relation"])
                                    if ek not in global_edge_keys:
                                        global_edge_keys.add(ek)
                                        edges.append(edge)
                                        nt_new_edges += 1
                        processed_gses += 1
                        if processed_gses % 100 == 0 or processed_gses == total_gses:
                            print(f"  [{datetime.now().strftime('%H:%M:%S')}] [{nt}] edges: {processed_gses}/{total_gses} GSE_IDs done, "
                                  f"{nt_new_edges} new edges so far")

                    sub_node_counts[nt] = nt_new_nodes
                    sub_edge_counts[nt] = nt_new_edges
                    print(f"  [{nt}] {nt_new_nodes} new nodes, {nt_new_edges} new edges "
                          f"(from {table})")
                    if is_debug:
                        print(f"  [DEBUG:{nt}] summary: queried {total_rows} rows from {len(temp_lookup)} GSE_IDs, "
                              f"created {nt_new_nodes} nodes + {nt_new_edges} edges; "
                              f"temp_lookup_keys={sorted(temp_lookup.keys())[:5]}{'...' if len(temp_lookup) > 5 else ''}")

            # ---- Step G: Create GeneAnnotation nodes for GroupDEGs/IntraClusterDEGs/ClusterMarkers ----
            print(f"[INFO] Creating GeneAnnotation nodes from gene symbols...")
            TARGET_TYPES = {"GroupDEGs", "IntraClusterDEGs", "ClusterMarkers"}

            # Phase 1: Collect unique (symbol, species) pairs from target sub-nodes
            # symbol_map: {(symbol_lower, species): {"symbol": orig, "species": species, "source_nodes": [(nt, node_id), ...]}}
            symbol_map = {}
            unknown_organisms = set()
            for (etype, node_id), node in entity_registry.items():
                if etype not in TARGET_TYPES:
                    continue
                symbol = str(node["properties"].get("symbol", "")).strip()
                organism = str(node["properties"].get("organism", "")).strip()
                if not symbol:
                    continue
                species = MySQLKnowledgeGraphBuilder._detect_species(organism)
                if not species:
                    if organism:
                        unknown_organisms.add(organism)
                    continue
                key = (symbol.lower(), species)
                if key not in symbol_map:
                    symbol_map[key] = {"symbol": symbol, "species": species, "source_nodes": []}
                symbol_map[key]["source_nodes"].append((etype, node_id))

            if unknown_organisms:
                print(f"  [INFO] Skipped {len(unknown_organisms)} unrecognized organism(s): "
                      f"{sorted(unknown_organisms)[:10]}")

            if not symbol_map:
                print(f"  No gene symbols with recognized organism found, skipping GeneAnnotation creation.")
            else:
                print(f"  Collected {len(symbol_map)} unique (symbol, species) pairs "
                      f"from {sum(len(v['source_nodes']) for v in symbol_map.values())} source nodes")

                GA_BATCH = 256
                gene_annotation_data = {}  # {(symbol_lower, species): {group_name: {...}}}
                # entrez_id lookup cache for crispick: {(symbol_lower, species): [entrez_id, ...]}
                symbol_entrez = {}

                # Pre-build reverse lookup index: species → symbol_lower → [(key, info), ...]
                # This avoids O(n_symbols) linear scan per database row (the main bottleneck).
                _symbol_lookup = {"human": {}, "mouse": {}}
                for _mk, _info in symbol_map.items():
                    _sp = _info["species"]
                    _sym_lower = _info["symbol"].lower()
                    _bucket = _symbol_lookup[_sp]
                    if _sym_lower not in _bucket:
                        _bucket[_sym_lower] = []
                    _bucket[_sym_lower].append(_mk)

                def _build_entrez_lookup():
                    """Rebuild entrez_id → [(sk, sp)] index (called after gene_annotation populates symbol_entrez)."""
                    _el = {"human": {}, "mouse": {}}
                    for (_sk, _sp), _eids in symbol_entrez.items():
                        for _eid in _eids:
                            if _eid not in _el[_sp]:
                                _el[_sp][_eid] = []
                            _el[_sp][_eid].append((_sk, _sp))
                    return _el

                _entrez_lookup_built = False  # lazy-init after gene_annotation populates symbol_entrez

                for group_cfg in GENE_ANNOTATION_TABLE_GROUPS:
                    group_name = group_cfg["group_name"]
                    match_col = group_cfg["match_column"]
                    match_col_alt = group_cfg.get("match_column_alt")
                    fields = group_cfg["fields"]
                    is_crispick = (group_name == "crispick")

                    for species in ("human", "mouse"):
                        table_name = group_cfg[f"{species}_table"]
                        symbols_for_species = [
                            info["symbol"] for key, info in symbol_map.items()
                            if info["species"] == species
                        ]
                        if not symbols_for_species:
                            continue

                        try:
                            # Check table exists
                            cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
                            if not cursor.fetchone():
                                print(f"  [WARN] Table '{table_name}' does not exist, "
                                      f"skipping {group_name}/{species}")
                                continue

                            if is_crispick:
                                # crispick uses entrez_id (from gene_annotation lookup) → Input column.
                                # Collect entrez_ids for all symbols of this species.
                                entrez_ids = []
                                for (sym_lower, sp), info in symbol_map.items():
                                    if sp != species:
                                        continue
                                    eids = symbol_entrez.get((sym_lower, sp), [])
                                    entrez_ids.extend(eids)
                                # Dedup
                                entrez_ids = sorted(set(eids for eids in entrez_ids if eids))
                                lookup_values = entrez_ids
                                lookup_label = f"{len(entrez_ids)} entrez_ids"
                            else:
                                lookup_values = symbols_for_species
                                lookup_label = f"{len(symbols_for_species)} symbols"

                            if not lookup_values:
                                if is_crispick:
                                    print(f"  [{group_name}/{species}] no entrez_ids resolved, skipping")
                                continue

                            # Build select columns: always include match column(s) so
                            # row.get(match_col) can read them (they may differ from
                            # the stored fields). Dedup with set to preserve DISTINCT
                            # semantics.
                            _select_cols = list(fields)
                            if match_col not in _select_cols:
                                _select_cols.append(match_col)
                            if match_col_alt and match_col_alt not in _select_cols:
                                _select_cols.append(match_col_alt)
                            col_list = ", ".join(f"`{c}`" for c in _select_cols)
                            match_col_q = f"`{match_col}`"
                            total_fetched = 0

                            # STRING tables can be huge (11M+ rows); use smaller batches
                            # and split OR into two queries to avoid MySQL lock-table overflow.
                            _is_string = bool(match_col_alt)
                            _batch_size = 64 if _is_string else GA_BATCH

                            for i in range(0, len(lookup_values), _batch_size):
                                batch = lookup_values[i:i + _batch_size]
                                placeholders = ",".join(["%s"] * len(batch))

                                if match_col_alt:
                                    # STRING: query each column separately to reduce lock pressure,
                                    # then union results in Python via row-level dedup.
                                    alt_col_q = f"`{match_col_alt}`"
                                    sql_x = (f"SELECT DISTINCT {col_list} FROM `{table_name}` "
                                             f"WHERE {match_col_q} IN ({placeholders})")
                                    sql_y = (f"SELECT DISTINCT {col_list} FROM `{table_name}` "
                                             f"WHERE {alt_col_q} IN ({placeholders})")
                                    cursor.execute(sql_x, batch)
                                    rows_x = cursor.fetchall()
                                    cursor.execute(sql_y, batch)
                                    rows_y = cursor.fetchall()
                                    # Dedup by row values (tuples), preserving order
                                    seen = set()
                                    all_rows = []
                                    for r in rows_x + rows_y:
                                        rt = tuple(r.items())
                                        if rt not in seen:
                                            seen.add(rt)
                                            all_rows.append(r)
                                else:
                                    sql = (f"SELECT DISTINCT {col_list} FROM `{table_name}` "
                                           f"WHERE {match_col_q} IN ({placeholders})")
                                    params = batch
                                    cursor.execute(sql, params)
                                    all_rows = cursor.fetchall()

                                batch_rows = 0
                                # Build entrez reverse lookup on first crispick use (after gene_annotation populated symbol_entrez)
                                if is_crispick and not _entrez_lookup_built:
                                    _entrez_lookup = _build_entrez_lookup()
                                    _entrez_lookup_built = True

                                for row in all_rows:
                                    # Determine which symbols this row matches (O(1) via reverse index)
                                    matched_keys = []
                                    raw_match = str(row.get(match_col, "")).strip()

                                    if is_crispick:
                                        # Match by entrez_id → Input column (O(1) lookup)
                                        matched_keys.extend(_entrez_lookup[species].get(raw_match, []))
                                    elif match_col_alt:
                                        # STRING: check both columns (O(1) per column)
                                        raw_alt = str(row.get(match_col_alt, "")).strip()
                                        seen = set()
                                        for sym in _symbol_lookup[species].get(raw_match.lower(), []):
                                            if sym not in seen:
                                                seen.add(sym)
                                                matched_keys.append(sym)
                                        if raw_match.lower() != raw_alt.lower():
                                            for sym in _symbol_lookup[species].get(raw_alt.lower(), []):
                                                if sym not in seen:
                                                    seen.add(sym)
                                                    matched_keys.append(sym)
                                    else:
                                        # Simple single-column match (O(1) lookup)
                                        matched_keys.extend(_symbol_lookup[species].get(raw_match.lower(), []))

                                    for mk in matched_keys:
                                        if mk not in gene_annotation_data:
                                            gene_annotation_data[mk] = {}
                                        if group_name not in gene_annotation_data[mk]:
                                            gene_annotation_data[mk][group_name] = []

                                        row_data = {}
                                        for f in fields:
                                            val = row.get(f)
                                            if val is not None and str(val).strip():
                                                row_data[f] = str(val).strip()
                                        if row_data:
                                            gene_annotation_data[mk][group_name].append(row_data)
                                    batch_rows += 1
                                total_fetched += batch_rows

                            print(f"  [{datetime.now().strftime('%H:%M:%S')}] [{group_name}/{species}] "
                                  f"queried {lookup_label} → {total_fetched} rows from {table_name}")

                            # For gene_annotation, cache entrez_id for crispick lookup
                            if group_name == "gene_annotation":
                                for mk, groups in gene_annotation_data.items():
                                    if mk[1] != species:
                                        continue
                                    ga_rows = groups.get("gene_annotation", [])
                                    for ga_row in ga_rows:
                                        eid = ga_row.get("entrez_id", "").strip()
                                        if eid:
                                            if mk not in symbol_entrez:
                                                symbol_entrez[mk] = []
                                            if eid not in symbol_entrez[mk]:
                                                symbol_entrez[mk].append(eid)

                        except Exception as e:
                            print(f"  [WARN] Error querying {table_name}: {e}")
                            continue

                # Phase 2.5: Build drug lookup from public_drug table
                # Config driven by kg_mapping.json → gene_annotation_drug_lookup
                drug_lookup = {}
                if GENE_ANNOTATION_DRUG_LOOKUP:
                    drug_table = GENE_ANNOTATION_DRUG_LOOKUP["table"]
                    drug_match_col = GENE_ANNOTATION_DRUG_LOOKUP["match_column"]
                    drug_target_field = GENE_ANNOTATION_DRUG_LOOKUP["target_field"]
                    drug_source_field = GENE_ANNOTATION_DRUG_LOOKUP.get("source_field", "drug_id")

                    # Collect all unique drug_id values from gene_annotation data
                    all_drug_ids = set()
                    for (sym_key, species), groups in gene_annotation_data.items():
                        ga_rows = groups.get("gene_annotation", [])
                        for row in ga_rows:
                            drug_id_val = str(row.get(drug_source_field, "")).strip()
                            if drug_id_val:
                                all_drug_ids.add(drug_id_val)

                    if all_drug_ids:
                        drug_ids_list = sorted(all_drug_ids)
                        DRUG_BATCH = 500
                        try:
                            with self.conn.cursor() as cursor:
                                for i in range(0, len(drug_ids_list), DRUG_BATCH):
                                    batch = drug_ids_list[i:i + DRUG_BATCH]
                                    placeholders = ",".join(["%s"] * len(batch))
                                    sql = (f"SELECT {drug_match_col}, {drug_target_field} "
                                           f"FROM {drug_table} "
                                           f"WHERE {drug_match_col} IN ({placeholders})")
                                    cursor.execute(sql, batch)
                                    for row in cursor.fetchall():
                                        db_id = str(row.get(drug_match_col, "")).strip()
                                        target_val = str(row.get(drug_target_field, "")).strip()
                                        if db_id and target_val:
                                            drug_lookup[db_id] = target_val
                            print(f"  [{drug_table}] Loaded {len(drug_lookup)} drug names "
                                  f"from {len(all_drug_ids)} unique {drug_source_field}s")
                        except Exception as e:
                            print(f"  [WARN] Could not query {drug_table} table: {e}")

                # Phase 3: Build GeneAnnotation nodes
                ga_new_nodes = 0
                ga_new_edges = 0

                for (sym_key, species), info in symbol_map.items():
                    merged_props = {
                        "name": info["symbol"],
                        "organism_species": species,
                    }

                    ga_data = gene_annotation_data.get((sym_key, species), {})

                    for group_cfg in GENE_ANNOTATION_TABLE_GROUPS:
                        group_name = group_cfg["group_name"]
                        rows = ga_data.get(group_name, [])
                        if not rows:
                            continue
                        if len(rows) == 1:
                            # Single row: merge flat with group prefix
                            for k, v in rows[0].items():
                                merged_props[f"{group_name}_{k}"] = v
                        else:
                            # Multi-row: store as JSON array
                            merged_props[f"{group_name}_rows"] = rows

                    # Resolve drug_id → preferred_name via public_drug lookup (config-driven)
                    if GENE_ANNOTATION_DRUG_LOOKUP:
                        drug_source_field = GENE_ANNOTATION_DRUG_LOOKUP.get("source_field", "drug_id")
                        drug_output_prop = GENE_ANNOTATION_DRUG_LOOKUP["output_property"]
                        # Single-row case: replace gene_annotation_{source_field} with output_property
                        old_prop_key = f"gene_annotation_{drug_source_field}"
                        if old_prop_key in merged_props:
                            drug_id_val = merged_props.pop(old_prop_key)
                            drug_name = drug_lookup.get(drug_id_val)
                            if drug_name:
                                merged_props[drug_output_prop] = drug_name
                        # Multi-row case: enrich each row in gene_annotation_rows
                        if "gene_annotation_rows" in merged_props:
                            for row in merged_props["gene_annotation_rows"]:
                                if drug_source_field in row:
                                    drug_id_val = row.pop(drug_source_field)
                                    drug_name = drug_lookup.get(drug_id_val)
                                    if drug_name:
                                        row["drug_name"] = drug_name

                    # Also store entrez_ids at top level for convenience
                    eids = symbol_entrez.get((sym_key, species), [])
                    if eids:
                        merged_props["entrez_ids"] = eids

                    # Dedup by content hash
                    content_hash = self._content_hash(merged_props)
                    ga_node_id = f"gan_{content_hash}"
                    ga_registry_key = ("GeneAnnotation", ga_node_id)

                    if ga_registry_key in entity_registry:
                        ga_node = entity_registry[ga_registry_key]
                    else:
                        ga_node = {
                            "id": ga_node_id,
                            "type": "GeneAnnotation",
                            "properties": merged_props,
                            "_provenance": {
                                "source_type": "cross_table_lookup",
                                "source_tables": [
                                    f"{cfg['human_table']}/{cfg['mouse_table']}"
                                    for cfg in GENE_ANNOTATION_TABLE_GROUPS
                                ],
                                "extracted_at": datetime.now().isoformat()
                            }
                        }
                        entity_registry[ga_registry_key] = ga_node
                        nodes.append(ga_node)
                        ga_new_nodes += 1

                    # Phase 4: Create edges from source sub-nodes → GeneAnnotation
                    for (st, sn_id) in info["source_nodes"]:
                        edge = self._make_edge(sn_id, ga_node_id, "HAS_GENE_ANNOTATION",
                                               {"source": "gene_annotation_lookup", "species": species})
                        if edge:
                            ek = (edge["source"], edge["target"], edge["relation"])
                            if ek not in global_edge_keys:
                                global_edge_keys.add(ek)
                                edges.append(edge)
                                ga_new_edges += 1

                sub_node_counts["GeneAnnotation"] = ga_new_nodes
                sub_edge_counts["GeneAnnotation"] = ga_new_edges
                print(f"  [GeneAnnotation] {ga_new_nodes} new nodes, {ga_new_edges} new edges "
                      f"(from {len(symbol_map)} unique symbols)")

                # Phase 5: Create Gene → GeneAnnotation edges
                # Build lookup: (symbol_lower, species) → ga_node_id
                ga_lookup = {}
                for (etype, node_id), node in entity_registry.items():
                    if etype == "GeneAnnotation":
                        sym = str(node["properties"].get("name", "")).strip().lower()
                        sp = str(node["properties"].get("organism_species", "")).strip()
                        if sym and sp:
                            ga_lookup[(sym, sp)] = node_id

                gene_ga_edges = 0
                for (etype, node_id), node in entity_registry.items():
                    if etype != "Gene":
                        continue
                    gene_name = str(node["properties"].get("name", "")).strip().lower()
                    species_list = node["properties"].get("species", [])
                    for sp in species_list:
                        ga_key = (gene_name, sp)
                        ga_node_id = ga_lookup.get(ga_key)
                        if ga_node_id:
                            edge = self._make_edge(node_id, ga_node_id, "HAS_ANNOTATION",
                                                   {"source": "gene_to_annotation_lookup",
                                                    "species": sp})
                            if edge:
                                ek = (edge["source"], edge["target"], edge["relation"])
                                if ek not in global_edge_keys:
                                    global_edge_keys.add(ek)
                                    edges.append(edge)
                                    gene_ga_edges += 1

                if gene_ga_edges:
                    sub_node_counts["GeneToAnnotation"] = gene_ga_edges
                    print(f"  [Gene→GeneAnnotation] {gene_ga_edges} new HAS_ANNOTATION edges")

        print(f"[OK] Wide-table build complete: {len(nodes)} nodes, {len(edges)} edges")
        return nodes, edges

    def _row_to_node_wide(self, row: dict, table: str, node_type: str,
                           id_prefix: str) -> Optional[dict]:
        """Wide table row → core node (excluding columns already extracted as entity nodes)"""
        props = {}
        extracted_cols = set(WIDE_TABLE_ENTITY_MAPPING.keys())
        # Also exclude doi (already handled via reference column)
        extracted_cols.add("doi")
        # v3.0: exclude compound entity columns (extracted as independent nodes)
        for config_key, config in COMPOUND_ENTITY_CONFIG.items():
            extracted_cols.add(config_key)
            for sc in config.get("source_columns", []):
                extracted_cols.add(sc)
        # v3.0: exclude enrichment columns (enriched onto other nodes, not Sample props)
        extracted_cols.update({"sgrna", "accession", "deleted_at", "is_organoid"})

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

        node = {
            "id": node_id,
            "type": entity_type,
            "properties": props,
            "_provenance": {
                "source_type": "column_extraction",
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
                    val = item[key]
                    if isinstance(val, dict):
                        # e.g. biomarker_name: {src: "TLR2", std: "Tlr2"} → "TLR2"
                        return str(val.get("name", val.get("src", list(val.values())[0] if val else ""))).strip()
                    return str(val).strip()
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

    @staticmethod
    def _find_key_recursive(data, target_key: str, max_depth: int = 4):
        """Recursively search for a key in nested dicts/lists and return its value.

        Args:
            data: dict, list, or other parsed JSON data
            target_key: key name to search for (exact match)
            max_depth: Maximum nesting depth

        Returns:
            The value associated with the key, or None if not found
        """
        if max_depth <= 0 or data is None:
            return None
        if isinstance(data, dict):
            if target_key in data and data[target_key] is not None:
                return data[target_key]
            for val in data.values():
                if isinstance(val, (dict, list)):
                    result = MySQLKnowledgeGraphBuilder._find_key_recursive(val, target_key, max_depth - 1)
                    if result is not None:
                        return result
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    result = MySQLKnowledgeGraphBuilder._find_key_recursive(item, target_key, max_depth - 1)
                    if result is not None:
                        return result
        return None

    def _extract_coculture_technique_from_raw(self, data, max_depth: int = 4):
        """Extract CoCultureTechnique data from raw_json at cultures[].story.culture_technique_coculture.

        Iterates all culture entries and collects their technique descriptions.
        Follows the same cultures[] pattern as _extract_infection_data.

        Args:
            data: raw_json parsed dict/list or JSON string
            max_depth: Maximum nesting depth for searching

        Returns:
            List of technique values (strings from each culture entry), or None if no data
        """
        if data is None:
            return None
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return None

        techniques = []

        cultures = self._find_cultures_array(data, max_depth)
        if cultures:
            for culture in cultures:
                if not isinstance(culture, dict):
                    continue
                story = culture.get("story")
                if isinstance(story, dict):
                    val = story.get("culture_technique_coculture")
                    if val is not None and str(val).strip():
                        techniques.append(str(val).strip())
        else:
            # Fallback: no cultures[] wrapper — search recursively for the key
            val = self._find_key_recursive(data, "culture_technique_coculture", max_depth)
            if val is not None and str(val).strip():
                techniques.append(str(val).strip())

        return techniques if techniques else None

    def _extract_coculture_material_sources_from_raw(self, data, max_depth: int = 4):
        """Extract material_sources from raw_json for co-culture entries.

        Iterates cultures[], checks base_info.if_co_culture.
        For coculture entries, collects story.material_source values.

        Args:
            data: raw_json parsed dict/list or JSON string
            max_depth: Maximum nesting depth for searching

        Returns:
            Aggregated material_source string (comma-joined), or None if no data
        """
        if data is None:
            return None
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return None

        material_sources = []

        # Collect (base_info_dict, story_dict) pairs from cultures[] or top-level
        cultures = self._find_cultures_array(data, max_depth)
        if cultures:
            for c in cultures:
                if isinstance(c, dict):
                    base_info = c.get("base_info", {})
                    story = c.get("story", {})
                    if isinstance(base_info, dict):
                        is_coculture = base_info.get("if_co_culture", False)
                        if is_coculture is True or str(is_coculture).lower() in ("true", "1", "yes"):
                            if isinstance(story, dict):
                                ms = story.get("material_source")
                                if ms is not None:
                                    material_sources.append(str(ms))
        else:
            # Structure 2: no cultures[] — check top-level
            base_info = data.get("base_info", {}) if isinstance(data, dict) else {}
            story = data.get("story", {}) if isinstance(data, dict) else {}
            if isinstance(base_info, dict):
                is_coculture = base_info.get("if_co_culture", False)
                if is_coculture is True or str(is_coculture).lower() in ("true", "1", "yes"):
                    if isinstance(story, dict):
                        ms = story.get("material_source")
                        if ms is not None:
                            material_sources.append(str(ms))

        if material_sources:
            return "; ".join(material_sources)
        return None

    @staticmethod
    def _parse_material_sources(material_sources_value) -> List[dict]:
        """Parse material_sources into a list of dicts with material properties.

        Handles multiple formats:
          1. CultureProtocol: JSON string of list-of-dicts
             e.g. '[{"source":"Corning","cat_number":"356231","material_name":"Matrigel","material_type":"Matrix"}]'
          2. CoCultureProtocol: semicolon-joined string or Python-literal list string
             e.g. "Matrigel; Collagen I" or "['Matrigel', 'Collagen I']"

        Returns:
            List of dicts, each with optional keys: source, cat_number, lot_number,
            source_type, material_name, material_type.
            Returns empty list if material_sources_value is None/empty/unparseable.
        """
        if material_sources_value is None:
            return []

        items = []

        # ---- Format 1: JSON array (CultureProtocol) ----
        if isinstance(material_sources_value, str):
            try:
                parsed = json.loads(material_sources_value)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            items.append(item)
                        elif isinstance(item, str) and item.strip():
                            items.append({"material_name": item.strip()})
                    if items:
                        return items
            except (json.JSONDecodeError, TypeError):
                pass

        # ---- Format 2: semicolon-joined or Python-literal (CoCultureProtocol) ----
        raw_str = (str(material_sources_value) if not isinstance(material_sources_value, str)
                   else material_sources_value)

        # Try Python literal_eval on the whole string first
        try:
            parsed = ast.literal_eval(raw_str)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        items.append(item)
                    elif isinstance(item, str) and item.strip():
                        items.append({"material_name": item.strip()})
                if items:
                    return items
        except (ValueError, SyntaxError):
            pass

        # Split by semicolon and try each part
        parts = [p.strip() for p in raw_str.split(";") if p.strip()]
        for part in parts:
            # Try JSON on individual part
            try:
                sub = json.loads(part)
                if isinstance(sub, dict):
                    items.append(sub)
                    continue
                elif isinstance(sub, str) and sub.strip():
                    items.append({"material_name": sub.strip()})
                    continue
            except (json.JSONDecodeError, TypeError):
                pass

            # Try ast.literal_eval on individual part
            try:
                sub = ast.literal_eval(part)
                if isinstance(sub, dict):
                    items.append(sub)
                    continue
                elif isinstance(sub, str) and sub.strip():
                    items.append({"material_name": sub.strip()})
                    continue
            except (ValueError, SyntaxError):
                pass

            # Fallback: plain material name
            items.append({"material_name": part})

        return items

    @staticmethod
    def _match_material_similarity(material_name: str, similarity_rows: List[dict]) -> Optional[dict]:
        """Match a material_name against Material_name_similarity_candidates_enhanced.

        Uses Python 'in' operator for substring matching: iterates all preloaded rows,
        checks whether material_name (lowercased) is found within the row's similar_names text.

        Args:
            material_name: The raw material name from a protocol's material_sources entry.
            similarity_rows: Preloaded list of dicts from the similarity table.

        Returns:
            Dict with keys matching MATERIAL_SIMILARITY_CONFIG.output_fields if a match
            is found, or None if no match.
        """
        if not material_name or not similarity_rows:
            return None

        mat_lower = material_name.lower().strip()
        output_fields = MATERIAL_SIMILARITY_CONFIG.get("output_fields", [])

        for row in similarity_rows:
            similar = row.get("similar_names", "")
            if similar and mat_lower in similar.lower():
                result = {}
                for field in output_fields:
                    val = row.get(field)
                    if val is not None and str(val).strip():
                        result[field] = str(val).strip()
                if result:
                    return result
                # Even if output_fields are all null, return at least standard_name
                std_name = row.get("standard_name")
                if std_name:
                    return {"standard_name": str(std_name).strip()}
        return None

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
        """Infer relationships from co-occurrence data (ASSOCIATED_WITH_DISEASE)"""
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
    # Compound entity extraction (v3.0 new node types)
    # -------------------------------------------------------------------------

    @staticmethod
    def _content_hash(data: dict) -> str:
        """Generate content hash from a normalized dict (sorted keys, stable JSON serialization)"""
        normalized = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()[:8]

    @staticmethod
    def _detect_species(organism_str: str):
        """Return 'human', 'mouse', or None from an Organism scientific name.

        Handles 'Homo sapiens', 'Mus musculus', and common variants.
        Case-insensitive substring match.
        """
        if not organism_str:
            return None
        org_lower = organism_str.strip().lower()
        if "homo sapiens" in org_lower:
            return "human"
        if "mus musculus" in org_lower:
            return "mouse"
        return None

    @staticmethod
    def _parse_protocol_json(raw_value) -> dict:
        """Parse a cultivation_protocol JSON value and extract structured fields.

        Handles both primary protocol (protocol[].stage/steps/medium/...) and
        co-culture protocol (time_axis[]/time_anchors[]) structures.

        Returns a dict with keys:
            stages, steps_text, media_used, supplement_names,
            growth_factor_names, small_molecule_names,
            protocol_text (flattened for full-text search),
            summary (human-readable one-liner),
            dedup_key (normalized data for content-hash dedup)
        """
        result = {
            "stages": [], "steps_text": [], "media_used": [],
            "supplement_names": [], "growth_factor_names": [],
            "small_molecule_names": [], "protocol_text": "",
            "summary": "", "dedup_key": {},
        }
        if not raw_value:
            return result

        # Parse JSON if string
        if isinstance(raw_value, str):
            try:
                data = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                return result
        elif isinstance(raw_value, dict):
            data = raw_value
        else:
            return result

        if not isinstance(data, dict):
            return result

        stages = []
        all_steps = []
        media_set = set()
        supplement_set = set()
        gf_set = set()
        sm_set = set()

        # -- Primary protocol structure: {"protocol": [{stage, steps, medium, ...}, ...]} --
        protocol_list = data.get("protocol")
        if isinstance(protocol_list, list):
            for stage_obj in protocol_list:
                if not isinstance(stage_obj, dict):
                    continue
                stage_name = stage_obj.get("stage", "")
                if stage_name:
                    stages.append(str(stage_name).strip())

                steps = stage_obj.get("steps")
                if isinstance(steps, list):
                    for s in steps:
                        if s and str(s).strip():
                            all_steps.append(str(s).strip())

                medium = stage_obj.get("medium")
                if medium and str(medium).strip():
                    media_set.add(str(medium).strip().lower())

                for field, target_set in [
                    ("supplements", supplement_set),
                    ("growth_factors", gf_set),
                    ("small_molecules", sm_set),
                ]:
                    items = stage_obj.get(field)
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                name = item.get("name")
                                if name and str(name).strip():
                                    target_set.add(str(name).strip().lower())
                            elif isinstance(item, str) and item.strip():
                                target_set.add(item.strip().lower())

        # -- Co-culture structure: {"time_axis": [...], "time_anchors": [...]} --
        time_axis = data.get("time_axis")
        if isinstance(time_axis, list):
            for axis in time_axis:
                if isinstance(axis, dict):
                    branch = axis.get("branch_name", "")
                    if branch:
                        stages.append(str(branch).strip())
                    axes = axis.get("axes")
                    if isinstance(axes, list):
                        for a in axes:
                            if isinstance(a, dict):
                                for anchor_key in ("start_anchor", "end_anchor"):
                                    anchor = a.get(anchor_key, {})
                                    if isinstance(anchor, dict):
                                        name = anchor.get("name", "")
                                        if name:
                                            stages.append(str(name).strip())

        time_anchors_list = data.get("time_anchors", [])
        if isinstance(time_anchors_list, list):
            for anchor in time_anchors_list:
                if isinstance(anchor, dict):
                    desc = anchor.get("desc", "")
                    if desc and str(desc).strip():
                        all_steps.append(str(desc).strip())
                    name_action = anchor.get("name_action", "")
                    if name_action and str(name_action).strip():
                        all_steps.append(str(name_action).strip())

        # Deduplicate while preserving order
        seen = set()
        unique_stages = []
        for s in stages:
            if s.lower() not in seen:
                seen.add(s.lower())
                unique_stages.append(s)

        # Build protocol_text (flattened for full-text search)
        text_parts = []
        if unique_stages:
            text_parts.append("Stages: " + " → ".join(unique_stages))
        if all_steps:
            text_parts.append("Steps: " + "; ".join(all_steps))
        if media_set:
            text_parts.append("Media: " + ", ".join(sorted(media_set)))
        if supplement_set:
            text_parts.append("Supplements: " + ", ".join(sorted(supplement_set)))
        if gf_set:
            text_parts.append("Growth factors: " + ", ".join(sorted(gf_set)))
        if sm_set:
            text_parts.append("Small molecules: " + ", ".join(sorted(sm_set)))

        protocol_text = ". ".join(text_parts)

        # Build human-readable summary
        summary_parts = []
        if unique_stages:
            summary_parts.append(" → ".join(unique_stages[:6]))
            if len(unique_stages) > 6:
                summary_parts[-1] += f" (+{len(unique_stages) - 6} more)"
        media_str = ", ".join(sorted(media_set)[:5])
        if media_str:
            summary_parts.append(f"[{media_str}]")
        supp_str = ", ".join(sorted(supplement_set)[:5])
        if supp_str:
            summary_parts.append(f"supp: {supp_str}")

        summary = "; ".join(summary_parts) if summary_parts else "(empty protocol)"
        if len(summary) > 200:
            summary = summary[:197] + "..."

        # Build dedup key from structured fields (excludes sample-specific metadata)
        dedup_key = {
            "stages": sorted(unique_stages),
            "steps_count": len(all_steps),
            "steps_hash": hashlib.md5(
                "||".join(sorted(all_steps)[:50]).encode()
            ).hexdigest()[:8] if all_steps else "",
            "media": sorted(media_set),
            "supplements": sorted(supplement_set),
            "growth_factors": sorted(gf_set),
            "small_molecules": sorted(sm_set),
        }

        result.update({
            "stages": unique_stages,
            "steps_text": all_steps,
            "media_used": sorted(media_set),
            "supplement_names": sorted(supplement_set),
            "growth_factor_names": sorted(gf_set),
            "small_molecule_names": sorted(sm_set),
            "protocol_text": protocol_text,
            "summary": summary,
            "dedup_key": dedup_key,
        })
        return result

    @staticmethod
    def _make_display_name(props: dict, node_type: str) -> str:
        """Generate a concise human-readable display name for nodes without a 'name' property."""
        # Use existing human-readable fields first
        for key in ("summary", "full_description", "description"):
            val = props.get(key)
            if val and isinstance(val, str) and len(val.strip()) > 0 and not val.strip().startswith("{"):
                return val.strip()[:120]

        if node_type == "OrganoidProfile":
            for k in ("name", "characteristics", "functions", "maturity", "complexity"):
                v = props.get(k)
                if v and str(v).strip():
                    return str(v).strip()[:120]

        return ""

    def _extract_merged_node(self, row: dict, config: dict) -> Optional[dict]:
        """Build a merged entity node from multiple source columns.

        Merges the configured source_columns into a dict, generates a content hash,
        returns node dict. Returns None if all source columns are null/empty.
        """
        merged_data = {}
        all_empty = True
        for col in config["source_columns"]:
            val = row.get(col)
            if val is None or val == '':
                continue
            all_empty = False
            merged_data[col] = val

        if all_empty:
            return None

        node_type = config["node_type"]

        # Build properties based on node type.
        # For CultureProtocol / CoCultureProtocol, extract structured fields FIRST,
        # then use those for dedup hashing (so structurally identical protocols
        # share the same node regardless of sample-specific JSON noise).
        if node_type == "CultureProtocol":
            protocol_raw = merged_data.get("cultivation_protocol")
            time_anchors_raw = merged_data.get("time_anchors")
            material_raw = merged_data.get("cultivation_material_sources")
            structured = self._parse_protocol_json(protocol_raw)

            # Use structured dedup_key for content hash → better dedup
            content_hash = self._content_hash(structured["dedup_key"])
            node_id = f"{config['id_prefix']}_{content_hash}"

            props = {
                "stages": structured["stages"],
                "steps_text": structured["steps_text"],
                "media_used": structured["media_used"],
                "supplement_names": structured["supplement_names"],
                "growth_factor_names": structured["growth_factor_names"],
                "small_molecule_names": structured["small_molecule_names"],
                "protocol_text": structured["protocol_text"],
                "summary": structured["summary"],
                # Keep raw data for provenance / downstream consumers
                "protocol": protocol_raw,
                "time_axes": time_anchors_raw,
                "time_anchors": time_anchors_raw,
                "material_sources": material_raw,
                # culture_days and endpoints merged from former CultureMetrics node
                "culture_days": str(merged_data.get("culture_days", "")).strip() if merged_data.get("culture_days") else None,
                "endpoints": str(merged_data.get("endpoints", "")).strip() if merged_data.get("endpoints") else None,
            }
        elif node_type == "CoCultureProtocol":
            protocol_raw = merged_data.get("coculture_cultivation_protocol")
            structured = self._parse_protocol_json(protocol_raw)

            content_hash = self._content_hash(structured["dedup_key"])
            node_id = f"{config['id_prefix']}_{content_hash}"

            props = {
                "stages": structured["stages"],
                "steps_text": structured["steps_text"],
                "media_used": structured["media_used"],
                "supplement_names": structured["supplement_names"],
                "growth_factor_names": structured["growth_factor_names"],
                "small_molecule_names": structured["small_molecule_names"],
                "protocol_text": structured["protocol_text"],
                "summary": structured["summary"],
                "protocol": protocol_raw,
                "time_axes": merged_data.get("coculture_time_anchors"),
                "time_anchors": merged_data.get("coculture_time_anchors"),
                # material_sources enriched from raw_json in Step B.6
                "material_sources": None,
                # coculture_days, read_out, coculture merged from former CoCultureMetrics node
                "coculture_days": str(merged_data.get("coculture_days", "")).strip() if merged_data.get("coculture_days") else None,
                "read_out": str(merged_data.get("read_out", "")).strip() if merged_data.get("read_out") else None,
                "coculture_description": str(merged_data.get("coculture", "")).strip() if merged_data.get("coculture") else None,
            }
        else:
            # Non-protocol node types: use raw merged_data for content hash (existing behavior)
            content_hash = self._content_hash(merged_data)
            node_id = f"{config['id_prefix']}_{content_hash}"

            if config["extraction_type"] == "profile":
                props = {}
                for col in config["source_columns"]:
                    val = row.get(col)
                    if val is not None and str(val).strip():
                        s = str(val).strip()
                        if col == "organoid":
                            props["name"] = s
                        else:
                            props[col] = s
                props["display_name"] = self._make_display_name(props, node_type)
            else:
                # Generic fallback: store all merged data as properties
                props = {k: v for k, v in merged_data.items()}

        return {
            "id": node_id,
            "type": node_type,
            "properties": props,
            "_provenance": {
                "source_type": "merged_extraction",
                "source_columns": config["source_columns"],
                "extracted_at": datetime.now().isoformat()
            }
        }

    @staticmethod
    def _make_summary(data: dict, max_chars: int = 200) -> str:
        """Generate a human-readable summary from merged data dict"""
        parts = []
        for k, v in data.items():
            if v is None:
                continue
            if isinstance(v, str):
                s = v.strip()
            elif isinstance(v, (dict, list)):
                s = str(v)
            else:
                s = str(v)
            if s:
                parts.append(s)
        summary = "; ".join(parts)
        if len(summary) > max_chars:
            summary = summary[:max_chars - 3] + "..."
        return summary

    def _extract_json_structured_node(self, row_value, config: dict) -> Optional[dict]:
        """Parse a JSON object column and extract structured fields.

        Handles both JSON objects (dict) and JSON arrays (list).
        Dedup is based on content hash of the entire parsed JSON.
        """
        if row_value is None:
            return None

        # Handle empty string / bytes edge case
        if isinstance(row_value, str) and row_value.strip() == '':
            return None

        node_type = config["node_type"]

        # Parse if string or bytes (MySQL may return JSON as bytes in some configurations)
        if isinstance(row_value, bytes):
            try:
                row_value = row_value.decode('utf-8')
            except UnicodeDecodeError:
                return None
        if isinstance(row_value, str):
            try:
                data = json.loads(row_value)
            except json.JSONDecodeError:
                # Not valid JSON — treat as a plain string value.
                # For technique/condition types, wrap into the expected dict shape.
                s = row_value.strip()
                if not s:
                    return None
                if node_type in ("CultureTechnique", "CoCultureTechnique"):
                    data = {"category": None, "subcategory": None,
                            "formation_strategy": None, "full_description": s}
                elif node_type in ("CultureCondition", "CoCultureCondition"):
                    data = {"conditions": [s], "description": s}
                else:
                    return None
            # json.loads may return a list — wrap it into dict
            if isinstance(data, list):
                data = self._wrap_json_array_as_dict(data, node_type)
        elif isinstance(row_value, dict):
            data = row_value
        elif isinstance(row_value, list):
            # JSON array — wrap into dict depending on node type
            data = self._wrap_json_array_as_dict(row_value, node_type)
        else:
            return None

        # Reject empty data or non-dict (after wrapping)
        if not data:
            return None
        if not isinstance(data, dict):
            return None

        content_hash = self._content_hash(data)
        node_id = f"{config['id_prefix']}_{content_hash}"

        # Extract structured fields
        if node_type in ("CultureTechnique", "CoCultureTechnique"):
            full_desc = ", ".join(
                str(v) for v in data.values()
                if v and isinstance(v, str)
            )
            # CultureTechnique: name = subcategory (e.g. "Matrigel embedding")
            # CoCultureTechnique: name = full_description (e.g. "Direct co-culture")
            tech_name = (data.get("subcategory") or full_desc or "").strip() if node_type == "CultureTechnique" else (full_desc or "").strip()
            props = {
                "name": tech_name,
                "category": data.get("category"),
                "subcategory": data.get("subcategory"),
                "formation_strategy": data.get("formation_strategy"),
                "full_description": full_desc,
            }
        elif node_type in ("CultureCondition", "CoCultureCondition"):
            conditions = data.get("conditions", [])
            if isinstance(conditions, list):
                conditions = sorted([str(c) for c in conditions])
            props = {
                "name": ", ".join(conditions) if conditions else "",
                "conditions": conditions if conditions else [],
            }
        else:
            props = {k: v for k, v in data.items()}

        return {
            "id": node_id,
            "type": node_type,
            "properties": props,
            "_provenance": {
                "source_type": "json_structured_extraction",
                "source_column": config.get("_source_column", ""),
                "extracted_at": datetime.now().isoformat()
            }
        }

    @staticmethod
    def _wrap_json_array_as_dict(data: list, node_type: str) -> dict:
        """Wrap a JSON array into a dict suitable for structured extraction.

        Args:
            data: The parsed JSON array (list)
            node_type: The target node type (CultureCondition, CoCultureTechnique, etc.)

        Returns:
            A dict with appropriate keys for the node type
        """
        if not data:
            return {}

        # For condition-like types: wrap as {"conditions": [...]}
        if node_type in ("CultureCondition", "CoCultureCondition"):
            return {"conditions": data, "description": ", ".join(str(v) for v in data if v)}

        # For technique-like types: extract strings into a flat description
        if node_type in ("CultureTechnique", "CoCultureTechnique"):
            # Flatten nested structures and collect string values
            flat_values = []
            for item in data:
                if isinstance(item, str):
                    flat_values.append(item)
                elif isinstance(item, dict):
                    flat_values.extend(
                        str(v) for v in item.values() if v and isinstance(v, str)
                    )
            return {
                "category": None,
                "subcategory": None,
                "formation_strategy": None,
                "full_description": ", ".join(flat_values) if flat_values else str(data),
            }

        # Generic fallback
        return {"items": data}

    def _extract_platform_node(self, platform_value: str) -> Optional[dict]:
        """Create a Platform node from the normalized platform name."""
        if not platform_value or not str(platform_value).strip():
            return None

        name = str(platform_value).strip()
        name_hash = hashlib.md5(name.lower().encode('utf-8')).hexdigest()[:8]
        node_id = f"pla_{name_hash}"

        return {
            "id": node_id,
            "type": "Platform",
            "properties": {"name": name},
            "_provenance": {
                "source_type": "column_extraction",
                "source_column": "platform",
                "extracted_at": datetime.now().isoformat()
            }
        }

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
                "version": "3.0",
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
            "version": "3.0",
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
    global GROUPINFO_SUB_NODE_MAX_ROWS

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
    parser.add_argument("--mapping", default=None,
                        help="Path to custom KG mapping JSON file. "
                             "Default: scripts/kg_mapping.json")
    parser.add_argument("--groupinfo-max-rows", type=int, default=GROUPINFO_SUB_NODE_MAX_ROWS,
                        help=f"Max rows per GSE_ID for GroupInfo sub-nodes "
                             f"(GroupDEGs/IntraClusterDEGs/ClusterMarkers/GSVA/GSEA). "
                             f"Default: {GROUPINFO_SUB_NODE_MAX_ROWS}. "
                             f"Set to 0 for unlimited.")

    args = parser.parse_args()

    # Focus tables: CLI argument > script config
    focus_tables = args.tables if args.tables is not None else None

    # Override module-level truncation limit
    if args.groupinfo_max_rows == 0:
        GROUPINFO_SUB_NODE_MAX_ROWS = None  # 0 means unlimited
    else:
        GROUPINFO_SUB_NODE_MAX_ROWS = args.groupinfo_max_rows

    # --explore mode
    if args.explore:
        builder = MySQLKnowledgeGraphBuilder(
            host=args.host, port=args.port, user=args.user,
            password=args.password, database=args.database,
            focus_tables=focus_tables,
            mapping_path=args.mapping,
        )
        schema = builder.explore()
        builder.print_explore(schema)
        return

    builder = MySQLKnowledgeGraphBuilder(
        host=args.host, port=args.port, user=args.user,
        password=args.password, database=args.database,
        focus_tables=focus_tables,
        mapping_path=args.mapping,
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
