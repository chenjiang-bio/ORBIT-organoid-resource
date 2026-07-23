#!/usr/bin/env python3
"""
chat_v2.py — Organoid Knowledge Graph LLM GraphRAG Interactive Chat Terminal (v2)

Two-phase architecture:
  Phase 1 (query_kg): LLM generates accurate Cypher from user question
                      → executes on Neo4j → returns ALL node details
  Phase 2 (synthesize): LLM takes question + intent + full results
                        → synthesizes natural language scientific answer

Key improvements over chat.py:
  - Complete property-level schema documentation in system prompt
  - Retry logic: Cypher errors fed back to LLM for correction (max 3 attempts)
  - ALL node details returned (not truncated/formatted)
  - No str.format() with user input (avoids { } crashes)
  - 15+ query pattern examples covering common question types
  - Direct question→answer flow (no interactive refinement step)

Usage:
  set LLM_API_KEY=sk-xxx
  set NEO4J_PASSWORD=xxx
  python scripts/chat_v2.py

  python scripts/chat_v2.py --base-url https://api.openai.com/v1 --model gpt-4o
"""

import os
import sys
import json
import argparse
import textwrap
from typing import Dict, List, Any, Optional, Tuple

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# =============================================================================
# Colors (ANSI)
# =============================================================================

C = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "cyan":    "\033[36m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "blue":    "\033[34m",
    "magenta": "\033[35m",
    "red":     "\033[31m",
}


def _p(color: str, text: str) -> str:
    return f"{C.get(color, '')}{text}{C['reset']}"


# =============================================================================

# =============================================================================
# Conversation History (multi-turn support with auto-compaction)
# =============================================================================

class ConversationHistory:
    """Manage multi-turn conversation with automatic compaction."""

    def __init__(self, max_recent_turns: int = 5, max_summary_chars: int = 2000):
        self.turns: List[dict] = []       # [{"q": ..., "a": ..., "cypher": ...}]
        self.max_recent_turns = max_recent_turns
        self.max_summary_chars = max_summary_chars
        self._summary = ""                # compacted summary of older turns

    def add(self, question: str, answer: str, cypher: str = ""):
        """Record a conversation turn."""
        self.turns.append({"q": question, "a": answer, "cypher": cypher})
        self._compact()

    def _compact(self):
        """Compress older turns into a brief summary when exceeding max_recent_turns."""
        if len(self.turns) <= self.max_recent_turns:
            return
        older = self.turns[:-self.max_recent_turns]
        parts = []
        total_chars = 0
        for t in older:
            q_short = t['q'][:120]
            parts.append(q_short)
            total_chars += len(q_short)
            if total_chars > self.max_summary_chars:
                parts.append("...")
                break
        self._summary = "; ".join(parts)

    def clear(self):
        """Reset all history."""
        self.turns.clear()
        self._summary = ""

    def format_context(self) -> str:
        """Format conversation history for inclusion in LLM prompts."""
        parts = []
        if self._summary:
            parts.append(f"[Earlier in this conversation, the user asked about: {self._summary}]")
            parts.append("")

        start_idx = max(0, len(self.turns) - self.max_recent_turns)
        for i in range(start_idx, len(self.turns)):
            t = self.turns[i]
            turn_num = i + 1
            parts.append(f"--- Conversation Turn {turn_num} ---")
            parts.append(f"User: {t['q']}")
            answer_preview = t['a']
            if len(answer_preview) > 400:
                answer_preview = answer_preview[:397] + "..."
            parts.append(f"Assistant: {answer_preview}")
            parts.append("")

        return "\n".join(parts)

    @property
    def is_empty(self) -> bool:
        return len(self.turns) == 0

    @property
    def turn_count(self) -> int:
        return len(self.turns)

# Banner
# =============================================================================

BANNER = r"""
   ██████╗  ██████╗  ██████╗  ██╗ ████████╗
  ██╔═══██╗ ██╔══██╗ ██╔══██╗ ██║ ╚══██╔══╝
  ██║   ██║ ██████╔╝ ██████╔╝ ██║    ██║
  ██║   ██║ ██╔══██╗ ██╔══██╗ ██║    ██║
  ╚██████╔╝ ██║  ██║ ██████╔╝ ██║    ██║
   ╚═════╝  ╚═╝  ╚═╝ ╚═════╝  ╚═╝    ╚═╝
       Organoid Knowledge Graph  GraphRAG Chat v2
"""

# =============================================================================
# Complete KG Schema for Phase 1 (Query Understanding + Cypher Generation)
# =============================================================================

KG_SCHEMA_FOR_CYPHER = """
## Organoid Knowledge Graph — Complete Schema for Cypher Generation

### CRITICAL: Neo4j Label Names
Node labels in Neo4j are PascalCase single words (NO prefixes) — 34 types total:

Core:     Sample
Entity:   Organism, Organ, Source, DiseaseModel, Application, Gene,
          ApplicationStrategy, Publication, System
JSON:     CellFactor, Technology, Drug, Infection, Biomarker, Phenotype,
          Test, Omics, Composition
Compound: CultureProtocol, CoCultureProtocol, CultureTechnique,
          CultureCondition, OrganoidProfile, Platform, CoCultureTechnique
Cross:    GroupInfo, GroupDEGs, IntraClusterDEGs, ClusterMarkers,
          GSVA, GSEA, GeneAnnotation
Material: MaterialInfo

The `id` property values use prefixes (e.g. "smp_KM-00001", "drg_492d36f2")
but the LABEL is just "Sample", "Drug", etc. — never use prefix as label!

### Node Types with ALL Properties
"""

# Detailed node type definitions
NODE_TYPE_DETAILS = """
=== Sample ===
Label: Sample
id prefix: smp_
Key properties: sample_id, year, search_content, is_analyzed
Use sample_id for display; search_content contains full text of the source record.

=== Organ ===
Label: Organ
id prefix: orn_
Key properties: name
name examples: "Liver", "Small Intestine", "Colon", "Pancreas", "Brain", "Stomach"

=== System ===
Label: System
id prefix: sys_
Key properties: name, organs
name examples: "Digestive System", "Nervous System", "Respiratory System"

=== Organism ===
Label: Organism
id prefix: osm_
Key properties: name
name examples: "Homo sapiens", "Mus musculus", "Rattus norvegicus"

=== Source ===
Label: Source
id prefix: src_
Key properties: name

=== CellFactor ===
Label: CellFactor
id prefix: cf_
Key properties: name, category, concentration
name examples: "EGF", "FGF2", "Wnt3a", "R-spondin1", "Noggin"

=== Technology ===
Label: Technology
id prefix: tec_
Key properties: name, category
name examples: "CRISPR-Cas9", "scRNA-seq", "Organ-on-a-chip"

=== Drug ===
Label: Drug
id prefix: drg_
Key properties: name, category, target, concentration_range
name examples: "Cisplatin", "5-FU", "Gemcitabine", "Urolithin A"

=== Gene ===
Label: Gene
id prefix: gen_
Key properties: name, sgrna, editing_method
name examples: "TP53", "APC", "KRAS", "SMAD4"

=== DiseaseModel ===
Label: DiseaseModel
id prefix: dm_
Key properties: name, category, description
name examples: "Colorectal Cancer", "Pancreatic Cancer", "IBD", "Cystic Fibrosis"

=== Infection ===
Label: Infection
id prefix: inf_
Key properties: name, category, moi

=== Biomarker ===
Label: Biomarker
id prefix: bmk_
Key properties: name, category, detection_method
name examples: "Lgr5", "Ki67", "E-cadherin", "Vimentin"

=== Phenotype ===
Label: Phenotype
id prefix: phn_
Key properties: name, category, description, quantification

=== Test ===
Label: Test
id prefix: tst_
Key properties: name, category, target
name examples: "qPCR", "Western blot", "Immunofluorescence", "Flow cytometry"

=== Omics ===
Label: Omics
id prefix: omc_
Key properties: omics_id, omics_type, platform_name, accession
omics_type examples: "scRNA-seq", "RNA-seq", "ATAC-seq", "proteomics"

=== Composition ===
Label: Composition
id prefix: cmp_
Key properties: name, cell_types, category, role, organ, species, cell_type, cell_source, organoid_origin
role examples: "organoid_core"
organoid_origin examples: "ASCs", "PSCs", "iPSCs"

=== Application ===
Label: Application
id prefix: app_
Key properties: name, category, description
name examples: "Drug screening", "Disease modeling", "Regenerative medicine"

=== Publication ===
Label: Publication
id prefix: pub_
Key properties: reference, doi, title, year

=== CultureProtocol ===
Label: CultureProtocol
id prefix: cpr_
Key properties: stages (list of stage names), steps_text (list of step descriptions),
    media_used (list), supplement_names (list), growth_factor_names (list),
    small_molecule_names (list), protocol_text, summary, material_sources (JSON string),
    culture_days (string), endpoints (string)
Query media/growth factors via list properties: WHERE 'EGF' IN cp.growth_factor_names
culture_days examples: "7.0", "14.0", "28.0"

=== CultureTechnique ===
Label: CultureTechnique
id prefix: cte_
Key properties: category, subcategory, formation_strategy, full_description
full_description examples: "Matrigel embedding", "Scaffold-based 3D culture", "Suspension culture"

=== CultureCondition ===
Label: CultureCondition
id prefix: ccn_
Key properties: conditions (list of condition strings), description
conditions examples: ["growth media", "DMEM/F12", "37C, 5% CO2"]

=== ApplicationStrategy ===
Label: ApplicationStrategy
id prefix: ast_
Key properties: strategy

=== OrganoidProfile ===
Label: OrganoidProfile
id prefix: opr_
Key properties: characteristics, functions, maturity, complexity

=== Platform ===
Label: Platform
id prefix: pla_
Key properties: name, category
name examples: "Illumina NovaSeq 6000", "10x Genomics Chromium"

=== CoCultureProtocol ===
Label: CoCultureProtocol
id prefix: ccp_
Key properties: stages, steps_text, media_used, supplement_names, growth_factor_names,
    small_molecule_names, protocol_text, summary, material_sources,
    coculture_days (string), read_out (string), coculture_description (string)

=== MaterialInfo ===
Label: MaterialInfo
id prefix: mat_
Key properties: name (standard_name or material_name), material_name, material_type,
    source (vendor), cat_number, lot_number, source_type,
    standard_name, application, pathway_family, signaling_direction
name examples: "Matrigel", "B-27 Supplement", "Y-27632"
Edge: CultureProtocol -[:USES_MATERIAL]-> MaterialInfo
Edge: CoCultureProtocol -[:USES_MATERIAL]-> MaterialInfo

=== CoCultureTechnique ===
Label: CoCultureTechnique
id prefix: cct_
Key properties: category, subcategory, formation_strategy, full_description

=== GroupInfo ===
Label: GroupInfo
id prefix: gin_
Key properties: factor (comparison group name), GSE_ID, group, condition,
    Organism, Data_Type, category, cell_type, path
Sub-node types hang off GroupInfo via specific relations (see Relationship Details below):
  HAS_DEG → GroupDEGs, HAS_INTRACLUSTER_DEG → IntraClusterDEGs,
  HAS_CLUSTER_MARKER → ClusterMarkers, HAS_GSVA_PATHWAY → GSVA, HAS_GSEA_PATHWAY → GSEA

=== GroupDEGs ===
Label: GroupDEGs
id prefix: gde_
Key properties: symbol (gene symbol, e.g., "TP53", "EGFR"), regulation (up/down),
    group, cluster, pseudobulk_cell_type, organism
Source table: public_rna_seq_differ_genes (bulk RNA-seq differential genes)

=== IntraClusterDEGs ===
Label: IntraClusterDEGs
id prefix: icd_
Key properties: symbol (gene symbol), regulation (up/down), group, cluster,
    pseudobulk_cell_type, organism
Source table: public_scrna_seq_cluster_differ_genes (scRNA-seq intra-cluster DEGs)

=== ClusterMarkers ===
Label: ClusterMarkers
id prefix: clm_
Key properties: symbol (gene symbol), regulation (up/down), group, cluster,
    pseudobulk_cell_type, organism
Source table: public_scrna_seq_cluster_marker_genes (scRNA-seq cluster markers)

=== GSVA ===
Label: GSVA
id prefix: gsv_
Key properties: term (pathway name, e.g., "Wnt signaling pathway", "TNFα signaling via NF-κB"),
    regulation (up/down), group, pseudobulk_cell_type, organism
Source table: public_rna_seq_gsva_differ_pathways

=== GSEA ===
Label: GSEA
id prefix: gse_
Key properties: terms (pathway function description), regulation (up/down),
    pathway_id, group, organism
Source table: public_rna_seq_gsea_enriched_pathways

=== GeneAnnotation ===
Label: GeneAnnotation
id prefix: gan_
Key properties: name (gene symbol), organism_species (human/mouse),
    entrez_ids (list), gene_annotation_entrez_id, gene_annotation_gene_name,
    gene_annotation_pfam, gene_annotation_prosite, gene_annotation_drug_name,
    site_Entry, site_Site, site_Binding_site, site_Active_site,
    disease_Involvement_in_disease, disease_Mutagenesis,
    string_rows (JSON array), crispick_rows (JSON array)
Source: Gene_Annotation_*, site_*, disease_*, STRING_Combine_*, CRISPick_Combine_* tables
Index on id; query via HAS_GENE_ANNOTATION from GroupDEGs/IntraClusterDEGs/ClusterMarkers
  or via HAS_ANNOTATION from Gene nodes.

"""

RELATIONSHIP_DETAILS = """
### Relationship Types with Directions (35 unique types)

Direct Sample connections (from Sample -> X):
  FROM_ORGAN:          (s:Sample)-[:FROM_ORGAN]->(orn:Organ)
  FROM_ORGANISM:       (s:Sample)-[:FROM_ORGANISM]->(osm:Organism)
  DERIVED_FROM:        (s:Sample)-[:DERIVED_FROM]->(src:Source)
  USES_FACTOR:         (s:Sample)-[:USES_FACTOR]->(cf:CellFactor)
  USES_TECHNOLOGY:     (s:Sample)-[:USES_TECHNOLOGY]->(tec:Technology)
  SCREENS_DRUG:        (s:Sample)-[:SCREENS_DRUG]->(drg:Drug)
  TARGETS_GENE:        (s:Sample)-[:TARGETS_GENE]->(gen:Gene)
  HAS_INFECTION:       (s:Sample)-[:HAS_INFECTION]->(inf:Infection)
  HAS_BIOMARKER:       (s:Sample)-[:HAS_BIOMARKER]->(bmk:Biomarker)
  HAS_PHENOTYPE:       (s:Sample)-[:HAS_PHENOTYPE]->(phn:Phenotype)
  HAS_TEST:            (s:Sample)-[:HAS_TEST]->(tst:Test)
  HAS_OMICS:           (s:Sample)-[:HAS_OMICS]->(omc:Omics)
  HAS_COMPOSITION:     (s:Sample)-[:HAS_COMPOSITION]->(cmp:Composition)
  MODELS_DISEASE:      (s:Sample)-[:MODELS_DISEASE]->(dm:DiseaseModel)
  HAS_APPLICATION:     (s:Sample)-[:HAS_APPLICATION]->(app:Application)
  HAS_PROFILE:         (s:Sample)-[:HAS_PROFILE]->(opr:OrganoidProfile)
  REPORTED_IN:         (s:Sample)-[:REPORTED_IN]->(pub:Publication)
  USES_PROTOCOL:       (s:Sample)-[:USES_PROTOCOL]->(cpr:CultureProtocol)
  USES_TECHNIQUE:      (s:Sample)-[:USES_TECHNIQUE]->(cte:CultureTechnique)
  HAS_CONDITION:       (s:Sample)-[:HAS_CONDITION]->(ccn:CultureCondition)
  HAS_STRATEGY:        (s:Sample)-[:HAS_STRATEGY]->(ast:ApplicationStrategy)
  USES_COCULTURE_PROTOCOL:  (s:Sample)-[:USES_COCULTURE_PROTOCOL]->(ccp:CoCultureProtocol)
  USES_COCULTURE_TECHNIQUE: (s:Sample)-[:USES_COCULTURE_TECHNIQUE]->(cct:CoCultureTechnique)
  HAS_GROUP_INFO:      (s:Sample)-[:HAS_GROUP_INFO]->(gi:GroupInfo)

Organ connections:
  BELONGS_TO_SYSTEM:   (orn:Organ)-[:BELONGS_TO_SYSTEM]->(sys:System)

Cross-entity connections:
  USES_PLATFORM:       (omc:Omics)-[:USES_PLATFORM]->(pla:Platform)
  ASSOCIATED_WITH_DISEASE: (drg:Drug)-[:ASSOCIATED_WITH_DISEASE]->(dm:DiseaseModel)
  ASSOCIATED_WITH_DISEASE: (bmk:Biomarker)-[:ASSOCIATED_WITH_DISEASE]->(dm:DiseaseModel)

GroupInfo sub-node connections (Step F — specific relation per sub-type):
  HAS_DEG:                (gi:GroupInfo)-[:HAS_DEG]->(gde:GroupDEGs)
  HAS_INTRACLUSTER_DEG:   (gi:GroupInfo)-[:HAS_INTRACLUSTER_DEG]->(icd:IntraClusterDEGs)
  HAS_CLUSTER_MARKER:     (gi:GroupInfo)-[:HAS_CLUSTER_MARKER]->(clm:ClusterMarkers)
  HAS_GSVA_PATHWAY:       (gi:GroupInfo)-[:HAS_GSVA_PATHWAY]->(gsv:GSVA)
  HAS_GSEA_PATHWAY:       (gi:GroupInfo)-[:HAS_GSEA_PATHWAY]->(gse:GSEA)

GeneAnnotation connections (Step G):
  HAS_GENE_ANNOTATION:    (gde:GroupDEGs)-[:HAS_GENE_ANNOTATION]->(gan:GeneAnnotation)
  HAS_GENE_ANNOTATION:    (icd:IntraClusterDEGs)-[:HAS_GENE_ANNOTATION]->(gan:GeneAnnotation)
  HAS_GENE_ANNOTATION:    (clm:ClusterMarkers)-[:HAS_GENE_ANNOTATION]->(gan:GeneAnnotation)
  HAS_ANNOTATION:         (gen:Gene)-[:HAS_ANNOTATION]->(gan:GeneAnnotation)

Protocol component connections (Step B.6):
  USES_COMPONENT:         (cpr:CultureProtocol)-[:USES_COMPONENT]->(cf:CellFactor)
  USES_COMPONENT:         (ccp:CoCultureProtocol)-[:USES_COMPONENT]->(cf:CellFactor)

Note: CellFactor nodes from protocol parsing carry a component_type property
(growth_factor, small_molecule, supplement, or medium) to distinguish the source.
"""

CYPHER_RULES = """
### Cypher Best Practices (from Neo4j Cypher Skill)

**Schema-First Protocol**
1. All node labels are single PascalCase words from the schema above — verify label exists before writing.
2. All relationship types are UPPER_SNAKE_CASE — verify type + direction from the relationship table.
3. Property names must match the per-type property lists above exactly.
4. Every node has an `id` property (e.g. "smp_KM-00001", "drg_492d36f2") with a per-label index.

**Label & Index Rules**
5. ALWAYS use labeled MATCH: `MATCH (s:Sample)` NOT bare `MATCH (s)`.
6. FORBIDDEN: label-free MATCH — `MATCH (n) WHERE n.id = 'xxx'` never uses an index, scans all nodes.
7. Use per-label index on id: `MATCH (s:Sample {id: 'smp_KM-00001'})`
8. NEVER use label prefixes as label names — `smp_Sample` is not valid, use `Sample`.
9. `MERGE` only on the constrained key `id`; use `ON CREATE SET`/`ON MATCH SET` for other properties.
10. `SET n = {k:v}` replaces ALL properties → use `SET n += {k:v}` for partial updates.

**String Matching**
11. Case-insensitive regex: `WHERE orn.name =~ '(?i).*liver.*'`
12. Simple substring: `WHERE orn.name CONTAINS 'Liver'`
13. List membership: `WHERE 'EGF' IN cp.growth_factor_names`

**Aggregation & WITH Scope**
14. Non-aggregating expressions in RETURN/WITH are implicit grouping keys — no GROUP BY needed.
15. Every variable NOT listed in WITH is dropped from scope. `WITH *` carries all forward.
16. `count(n)` counts non-null rows; `count(*)` counts ALL rows including nulls.
17. Count after OPTIONAL MATCH: use `count(DISTINCT s)` for distinct sample counts.
18. Use `collect(DISTINCT ...)` to deduplicate grouped values; `count()` is faster than `size(collect())`.

**Query Structure & Performance**
19. Default LIMIT 50 on all queries; use LIMIT 25 for exploratory queries.
20. Push `WITH n LIMIT 50` BEFORE high-cardinality operations (fan-out MATCH, variable-length paths).
21. Return NAMED properties: `RETURN s.sample_id, drg.name` — NOT `RETURN s` (wastes tokens).
22. Chained OPTIONAL MATCH → replace with `COLLECT { MATCH ... RETURN ... }` subqueries.
23. `DETACH DELETE n` when node has relationships; plain `DELETE n` throws on connected nodes.

**Common Syntax Traps — NEVER WRITE THESE**
24. `-- comment` → use `// comment` (-- is SQL, invalid Cypher)
25. `WHERE n.x = null` → use `WHERE n.x IS NULL` (= null is always false)
26. `UNWIND list AS x WHERE x>5` → `UNWIND list AS x WITH x WHERE x>5` (WHERE after UNWIND needs WITH)
27. `count(r WHERE r.x=5)` → `sum(CASE WHEN r.x=5 THEN 1 ELSE 0 END)` (count doesn't take WHERE)
28. `ORDER BY n.prop AS x DESC` → `ORDER BY n.prop DESC` (no AS in ORDER BY)
29. `toInteger(null)` → `toIntegerOrNull(null)` (toInteger throws on null)
"""

QUERY_PATTERNS = """
### Query Pattern Examples

--- Pattern 1: Find samples by organ ---
User: "Show me liver organoid samples"
Cypher:
MATCH (s:Sample)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*liver.*'
OPTIONAL MATCH (s)-[:HAS_PROFILE]->(op:OrganoidProfile)
RETURN s.sample_id, op.organoid, orn.name
LIMIT 50

--- Pattern 2: Find samples by organ AND disease ---
User: "Pancreatic cancer organoid samples"
Cypher:
MATCH (s:Sample)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*pancrea.*'
OPTIONAL MATCH (s)-[:MODELS_DISEASE]->(dm:DiseaseModel)
WHERE dm.name =~ '(?i).*cancer.*'
RETURN s, orn, dm
LIMIT 50

--- Pattern 3: Drug screening by organ ---
User: "Which drugs were tested on intestinal organoids?"
Cypher:
MATCH (s:Sample)-[:SCREENS_DRUG]->(drg:Drug)
MATCH (s)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*intestin.*'
RETURN DISTINCT drg.name AS drug, count(DISTINCT s) AS sample_count
ORDER BY sample_count DESC
LIMIT 30

--- Pattern 4: Culture protocols with growth factors ---
User: "Culture protocols using EGF for colon organoids"
Cypher:
MATCH (s:Sample)-[:USES_PROTOCOL]->(cp:CultureProtocol)
MATCH (s)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*colon.*' AND 'EGF' IN cp.growth_factor_names
OPTIONAL MATCH (s)-[:HAS_PROFILE]->(op:OrganoidProfile)
RETURN s.sample_id, op.organoid, cp.stages, cp.media_used, cp.growth_factor_names
LIMIT 20

--- Pattern 5: Gene edits in organoids ---
User: "APC gene knockout in colorectal organoids"
Cypher:
MATCH (s:Sample)-[:TARGETS_GENE]->(g:Gene)
WHERE g.name =~ '(?i).*APC.*'
MATCH (s)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*(colon|colorectal|intestin).*'
RETURN s, g, orn
LIMIT 20

--- Pattern 6: Biomarker expression ---
User: "Samples expressing Lgr5 biomarker"
Cypher:
MATCH (s:Sample)-[:HAS_BIOMARKER]->(bmk:Biomarker)
WHERE bmk.name =~ '(?i).*Lgr5.*'
RETURN s, bmk
LIMIT 30

--- Pattern 7: Disease models by organ ---
User: "What disease models are studied in liver organoids?"
Cypher:
MATCH (s:Sample)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*liver.*'
MATCH (s)-[:MODELS_DISEASE]->(dm:DiseaseModel)
RETURN DISTINCT dm.name AS disease, orn.name AS organ, count(s) AS sample_count
LIMIT 30

--- Pattern 8: Find full sample context (all connected nodes) ---
User: "Show me everything about sample smp_KM-00001"
Cypher:
MATCH (s:Sample {sample_id: 'KM-00001'})
OPTIONAL MATCH (s)-[:FROM_ORGAN]->(orn:Organ)
OPTIONAL MATCH (orn)-[:BELONGS_TO_SYSTEM]->(sys:System)
OPTIONAL MATCH (s)-[:FROM_ORGANISM]->(osm:Organism)
OPTIONAL MATCH (s)-[:SCREENS_DRUG]->(drg:Drug)
OPTIONAL MATCH (s)-[:TARGETS_GENE]->(g:Gene)
OPTIONAL MATCH (s)-[:MODELS_DISEASE]->(dm:DiseaseModel)
OPTIONAL MATCH (s)-[:USES_PROTOCOL]->(cp:CultureProtocol)
OPTIONAL MATCH (s)-[:USES_TECHNIQUE]->(cte:CultureTechnique)
OPTIONAL MATCH (s)-[:HAS_CONDITION]->(ccn:CultureCondition)
OPTIONAL MATCH (s)-[:USES_FACTOR]->(cf:CellFactor)
OPTIONAL MATCH (s)-[:HAS_BIOMARKER]->(bmk:Biomarker)
OPTIONAL MATCH (s)-[:HAS_PHENOTYPE]->(phn:Phenotype)
OPTIONAL MATCH (s)-[:HAS_PROFILE]->(op:OrganoidProfile)
RETURN s, orn, sys, osm, drg, g, dm, cp, cte, ccn, cf, bmk, phn, op
LIMIT 1

--- Pattern 9: Compare across species ---
User: "Compare human vs mouse intestinal organoid protocols"
Cypher:
MATCH (s:Sample)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*intestin.*'
MATCH (s)-[:FROM_ORGANISM]->(osm:Organism)
MATCH (s)-[:USES_PROTOCOL]->(cp:CultureProtocol)
OPTIONAL MATCH (s)-[:HAS_PROFILE]->(op:OrganoidProfile)
RETURN osm.name AS species, op.organoid, cp.media_used, cp.growth_factor_names, count(DISTINCT s) AS sample_count
ORDER BY species, sample_count DESC
LIMIT 20

--- Pattern 10: Technology used with specific organoids ---
User: "Single-cell sequencing on brain organoids"
Cypher:
MATCH (s:Sample)-[:USES_TECHNOLOGY]->(tec:Technology)
WHERE tec.name =~ '(?i).*single.cell.*' OR tec.name =~ '(?i).*scrna.*'
MATCH (s)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*brain.*'
RETURN s, orn, tec
LIMIT 20

--- Pattern 11: Omics datasets ---
User: "RNA-seq datasets from pancreatic organoids"
Cypher:
MATCH (s:Sample)-[:HAS_OMICS]->(omc:Omics)
WHERE omc.omics_type =~ '(?i).*rna.seq.*'
MATCH (s)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*pancrea.*'
OPTIONAL MATCH (omc)-[:USES_PLATFORM]->(pla:Platform)
RETURN s, orn, omc, pla
LIMIT 20

--- Pattern 12: Co-culture information ---
User: "Co-culture protocols for immune organoids"
Cypher:
MATCH (s:Sample)-[:USES_COCULTURE_PROTOCOL]->(ccp:CoCultureProtocol)
OPTIONAL MATCH (s)-[:HAS_PROFILE]->(op:OrganoidProfile)
RETURN s.sample_id, op.organoid, ccp.stages, ccp.media_used
LIMIT 15

--- Pattern 13: Organoid profile / characteristics ---
User: "Mature intestinal organoids with complex architecture"
Cypher:
MATCH (s:Sample)-[:HAS_PROFILE]->(opr:OrganoidProfile)
MATCH (s)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*intestin.*'
  AND (opr.maturity =~ '(?i).*mature.*' OR opr.complexity =~ '(?i).*complex.*')
RETURN s, orn, opr
LIMIT 20

--- Pattern 14: Publications by year ---
User: "Recent publications on organoids (2023+)"
Cypher:
MATCH (s:Sample)-[:REPORTED_IN]->(pub:Publication)
WHERE toInteger(pub.year) >= 2023
OPTIONAL MATCH (s)-[:HAS_PROFILE]->(op:OrganoidProfile)
RETURN pub.title, pub.year, pub.doi, op.organoid, s.sample_id
ORDER BY pub.year DESC
LIMIT 30

--- Pattern 15: Multi-faceted search ---
User: "Human pancreatic cancer organoids tested with gemcitabine using EGF"
Cypher:
MATCH (s:Sample)-[:FROM_ORGAN]->(orn:Organ)
WHERE orn.name =~ '(?i).*pancrea.*'
MATCH (s)-[:MODELS_DISEASE]->(dm:DiseaseModel)
WHERE dm.name =~ '(?i).*cancer.*'
MATCH (s)-[:SCREENS_DRUG]->(drg:Drug)
WHERE drg.name =~ '(?i).*gemcitabine.*'
MATCH (s)-[:USES_FACTOR]->(cf:CellFactor)
WHERE cf.name =~ '(?i).*EGF.*'
MATCH (s)-[:FROM_ORGANISM]->(osm:Organism)
WHERE osm.name =~ '(?i).*sapiens.*'
RETURN s, orn, dm, drg, cf, osm
LIMIT 10
"""


def build_phase1_system_prompt() -> str:
    """Build the complete Phase 1 system prompt for Cypher generation."""
    return f"""You are an expert Cypher query generator for a Neo4j organoid culture knowledge graph.

Your ONLY job: convert a natural language question into a SINGLE valid Cypher query.

{KG_SCHEMA_FOR_CYPHER}
{NODE_TYPE_DETAILS}
{RELATIONSHIP_DETAILS}
{CYPHER_RULES}
{QUERY_PATTERNS}

## CRITICAL OUTPUT FORMAT
Return ONLY the Cypher query. No markdown code blocks, no explanation.
Start directly with MATCH or CYPHER.

## Before responding, verify:
1. ALL node labels are single PascalCase words (Sample, Organ, Drug, etc.)
2. ALL relationship types are UPPER_SNAKE_CASE (FROM_ORGAN, SCREENS_DRUG, etc.)
3. Property names match the schema exactly (sample_id not sampleId)
4. Use =~ with (?i) for case-insensitive text matching
5. LIMIT is included (default 50)
6. No label-free MATCH (n) — always specify label
"""


# =============================================================================
# Phase 2: Synthesis Prompt
# =============================================================================

PHASE2_SYSTEM_PROMPT = """You are a scientific assistant specializing in organoid culture and research.

Your job: synthesize the knowledge graph query results into a clear, accurate, natural-language answer.

## Input
You will receive:
1. The user's original question
2. An intent summary (what the system understood the user wanted)
3. Knowledge graph query results as structured JSON (node labels, IDs, and ALL properties)

## Instructions
1. Carefully review the query results — these are the GROUND TRUTH
2. Organize findings logically by theme (e.g., by organ type, by drug, by protocol)
3. Cite specific sample IDs, organoid names, drug names, and protocol details when present
4. If results are empty/insufficient, clearly state that and provide context from general knowledge
5. Use bullet points and clear section headers for readability
6. When listing samples, include: sample_id, organoid name, organ, and any distinguishing details
7. If the results contain many records, summarize patterns and highlight representative examples
8. Do NOT fabricate sample IDs, data points, or references not in the results
9. Keep the answer scientifically rigorous and well-structured

## Output Format
- Start with a brief summary answering the question directly
- Follow with structured details (bullets, sections)
- End with a note on data completeness (e.g., "Found 15 matching records in the knowledge graph")
"""


# =============================================================================
# LLM Client
# =============================================================================

class LLMClient:
    """Thin wrapper around OpenAI-compatible API."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def chat(self, system_prompt: str, user_message: str,
             temperature: float = 0.1, max_tokens: int = 2000,
             timeout: int = 60) -> str:
        """Send a chat completion request."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")

        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        client = OpenAI(**client_kwargs)

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        # Handle both ChatCompletion objects and raw strings (API compat)
        if isinstance(response, str):
            # Some API versions return raw JSON string
            try:
                import json as _json
                data = _json.loads(response)
                return data["choices"][0]["message"]["content"]
            except (_json.JSONDecodeError, KeyError, IndexError, TypeError):
                # Likely an error message from the API — surface it clearly
                raise RuntimeError(
                    f"LLM API returned unexpected text response "
                    f"(status may indicate auth or endpoint error):\n{response[:500]}"
                )
        return response.choices[0].message.content

    def chat_stream(self, system_prompt: str, user_message: str,
                    temperature: float = 0.1, max_tokens: int = 2000,
                    timeout: int = 120):
        """Stream chat completion, yielding text tokens one at a time.

        Yields each content delta as a string. Callers should iterate over
        the generator to receive tokens as they arrive.
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")

        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        client = OpenAI(**client_kwargs)

        stream = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            stream=True,
        )

        # stream should be an iterable of ChatCompletionChunk objects.
        # If it's a plain string (API compat edge case), yield it and return.
        if isinstance(stream, str):
            yield stream
            return

        for chunk in stream:
            # chunk may be a ChatCompletionChunk or a plain dict/str
            if isinstance(chunk, str):
                yield chunk
                continue
            if isinstance(chunk, dict):
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {}) if isinstance(choices[0], dict) else getattr(choices[0], "delta", None)
                    if delta:
                        content = delta.get("content", "") if isinstance(delta, dict) else getattr(delta, "content", "")
                        if content:
                            yield content
                continue
            # Normal ChatCompletionChunk
            if chunk.choices and chunk.choices[0].delta:
                content = chunk.choices[0].delta.content
                if content:
                    yield content


# =============================================================================
# Phase 1: Query Understanding + Cypher Generation + Execution
# =============================================================================

class KnowledgeGraphQuery:
    """Phase 1: Understand user intent, generate Cypher, execute on Neo4j."""

    def __init__(self, uri: str, user: str, password: str,
                 llm: LLMClient):
        try:
            from neo4j import GraphDatabase
        except ImportError:
            raise ImportError("neo4j package not installed. Run: pip install neo4j")

        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.llm = llm
        self._system_prompt = build_phase1_system_prompt()

        # Verify connection
        try:
            self.driver.verify_connectivity()
            print(f"{_p('green', chr(0x2713))} Connected to Neo4j at {uri}")
        except Exception as e:
            raise ConnectionError(f"Cannot connect to Neo4j: {e}")

    def close(self):
        self.driver.close()

    def _clean_cypher(self, raw: str) -> str:
        """Clean LLM output to extract pure Cypher query."""
        if not raw or not raw.strip():
            return ""

        cypher = raw.strip()

        # Strip DeepSeek/Claude thinking tags if present
        for tag_prefix in ("<｜end▁of▁thinking｜>", "用户"):
            if cypher.startswith(tag_prefix):
                # Remove everything up to the actual content after newlines
                rest = cypher[len(tag_prefix):].strip()
                if rest:
                    cypher = rest

        # Remove markdown code blocks
        if cypher.startswith("```"):
            lines = cypher.split("\n")
            # Find the closing ```
            end_idx = None
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip() == "```":
                    end_idx = i
                    break
            if end_idx is not None:
                lines = lines[1:end_idx]
            else:
                lines = lines[1:]
            cypher = "\n".join(lines).strip()

        # Remove "cypher" language tag if present on first line
        if cypher.lower().startswith("cypher"):
            cypher = cypher[6:].strip()

        # Remove trailing semicolons
        cypher = cypher.rstrip().rstrip(";")

        return cypher

    def _execute_cypher(self, cypher: str) -> Tuple[List[Dict], Optional[str]]:
        """Execute Cypher query. Returns (records, error_message)."""
        # Guard: reject empty Cypher before hitting Neo4j
        if not cypher or not cypher.strip():
            return [], "EMPTY_CYPHER: The LLM generated an empty query. Ensure the response starts with MATCH or CYPHER."

        # Add LIMIT guardrail
        if "limit" not in cypher.lower():
            cypher = cypher + "\nLIMIT 50"

        try:
            with self.driver.session() as session:
                result = session.run(cypher)
                records = []
                for record in result:
                    records.append(dict(record))
                return records, None
        except Exception as e:
            return [], str(e)

    @staticmethod
    def _serialize_node(node) -> Dict[str, Any]:
        """Convert a Neo4j Node to a serializable dict with all properties."""
        props = dict(node)
        label = list(node.labels)[0] if node.labels else "Unknown"
        return {
            "label": label,
            "id": props.get("id", "N/A"),
            "properties": props,
        }

    @staticmethod
    def _serialize_relationship(rel) -> Dict[str, Any]:
        """Convert a Neo4j Relationship to a serializable dict."""
        return {
            "type": rel.type,
            "properties": dict(rel),
        }

    def _serialize_results(self, records: List[Dict]) -> List[Dict]:
        """Serialize all Neo4j objects in records to JSON-safe dicts."""
        serialized = []
        for i, record in enumerate(records):
            rec_data = {"_record_index": i + 1}
            for key, value in record.items():
                if hasattr(value, 'labels'):  # Neo4j Node
                    rec_data[key] = self._serialize_node(value)
                elif hasattr(value, 'type') and hasattr(value, 'nodes'):  # Relationship
                    rec_data[key] = self._serialize_relationship(value)
                elif isinstance(value, list):
                    # Handle lists of nodes/rels
                    serialized_list = []
                    for item in value:
                        if hasattr(item, 'labels'):
                            serialized_list.append(self._serialize_node(item))
                        elif hasattr(item, 'type') and hasattr(item, 'nodes'):
                            serialized_list.append(self._serialize_relationship(item))
                        else:
                            serialized_list.append(str(item))
                    rec_data[key] = serialized_list
                else:
                    rec_data[key] = str(value) if value is not None else None
            serialized.append(rec_data)
        return serialized

    def query(self, question: str, verbose: bool = False,
              max_retries: int = 3,
              conversation_context: str = "") -> Dict[str, Any]:
        """
        Phase 1: Convert question → Cypher → execute → return ALL node details.

        Returns:
            {
                "question": str,
                "cypher": str,
                "results": list of serialized records,
                "node_count": int,
                "error": str or None,
                "retries": int,
            }
        """
        # Build the user message — no str.format() with user input!
        user_message = f"Generate a Cypher query for this question:\n\n{question}"

        last_cypher = None
        last_error = None

        for attempt in range(1, max_retries + 1):
            if verbose and attempt > 1:
                print(f"  {_p('yellow', f'Retry {attempt}/{max_retries}...')}")

            # Build message (include error feedback on retry)
            if attempt == 1:
                msg = user_message
            else:
                msg = (
                    f"Your previous Cypher query had this error:\n"
                    f"```\n{last_error}\n```\n\n"
                    f"Please fix the error and generate a corrected Cypher query for:\n\n"
                    f"{question}"
                )

            # Call LLM
            raw_response = self.llm.chat(
                system_prompt=self._system_prompt,
                user_message=msg,
                temperature=0.1,
                max_tokens=1000,
            )

            cypher = self._clean_cypher(raw_response)
            last_cypher = cypher

            if verbose:
                raw_preview = raw_response[:200].replace('\n', '\\n') if raw_response else '(empty)'
                print(f"  {_p('dim', f'Generated Cypher ({len(cypher)} chars cleaned, {len(raw_response)} chars raw):')}")
                if cypher:
                    preview = cypher[:300] + "..." if len(cypher) > 300 else cypher
                    for line in preview.split("\n")[:8]:
                        print(f"    {_p('dim', line)}")
                    if len(cypher.split("\n")) > 8:
                        print(f"    {_p('dim', '... (truncated)')}")
                else:
                    print(f"    {_p('yellow', f'LLM returned empty/whitespace-only response. Raw: [{raw_preview}]')}")

            # Execute
            records, error = self._execute_cypher(cypher)

            if error is None:
                # Success!
                serialized = self._serialize_results(records)
                # Count distinct nodes
                node_count = sum(
                    1 for rec in serialized
                    for v in rec.values()
                    if isinstance(v, dict) and "label" in v
                )
                return {
                    "question": question,
                    "cypher": cypher,
                    "results": serialized,
                    "node_count": node_count,
                    "error": None,
                    "retries": attempt - 1,
                }
            else:
                if verbose:
                    print(f"  {_p('red', f'Cypher error: {error[:200]}')}")

                # If LLM generated nothing, fix error feedback for retry
                if not cypher or not cypher.strip():
                    last_error = (
                        f"EMPTY_RESPONSE: You returned an empty/whitespace-only response. "
                        f"You MUST output a valid Cypher query starting with MATCH or CYPHER. "
                        f"Use the query patterns in the system prompt as templates."
                    )
                    last_cypher = None  # don't carry empty cypher to next retry
                else:
                    last_error = error

        # All retries exhausted
        return {
            "question": question,
            "cypher": last_cypher,
            "results": [],
            "node_count": 0,
            "error": last_error,
            "retries": max_retries,
        }


# =============================================================================
# Phase 2: Synthesis
# =============================================================================

class ResultSynthesizer:
    """Phase 2: Synthesize KG results into natural language answer."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def synthesize(self, question: str, phase1_result: Dict[str, Any],
                   conversation_context: str = "") -> str:
        """
        Synthesize Phase 1 results into a natural language answer.

        Args:
            question: Original user question
            phase1_result: Output from KnowledgeGraphQuery.query()

        Returns:
            Synthesized answer string
        """
        results = phase1_result.get("results", [])
        cypher = phase1_result.get("cypher") or ""
        error = phase1_result.get("error")
        node_count = phase1_result.get("node_count", 0)

        # Build intent summary from the generated Cypher
        intent_summary = f"The system interpreted the question as a graph query. Generated Cypher:\n{cypher[:500]}"

        # If error, return error message
        if error and not results:
            return (
                f"I was unable to query the knowledge graph for your question.\n\n"
                f"**Cypher generated:**\n```\n{cypher}\n```\n\n"
                f"**Error:** {error}\n\n"
                f"The query may need manual adjustment. You can try rephrasing your question "
                f"or using /search to explore the graph directly."
            )

        if not results:
            return (
                f"The knowledge graph query returned no matching records.\n\n"
                f"**What was searched:** The system looked for information related to "
                f"organoid culture data matching your question.\n\n"
                f"**Suggestion:** Try broadening your search terms, or use /search to "
                f"explore available data. You can also ask about general organoid biology "
                f"and I'll answer from scientific knowledge."
            )

        # Format results as compact JSON for the LLM
        # Truncate if too large (max ~4000 chars for results)
        results_json = json.dumps(results, ensure_ascii=False, indent=2)
        if len(results_json) > 6000:
            results_json = results_json[:6000] + "\n... (truncated, showing first 6000 chars)"

        # Build the user message for synthesis
        conv_section = ""
        if conversation_context:
            conv_section = f"## Previous Conversation\\n{conversation_context}\\n\\n"
        user_message = f"""{conv_section}## User Question
{question}

## Intent Understanding
{intent_summary}

## Knowledge Graph Query Results
Retrieved {node_count} nodes across {len(results)} records.

### Raw Results (JSON):
```json
{results_json}
```

## Task
Synthesize the above results into a clear, comprehensive answer to the user's question.
Cite specific sample IDs, organoid names, drug names, protocol details, etc. from the results.
"""

        answer = self.llm.chat(
            system_prompt=PHASE2_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.3,
            max_tokens=2000,
        )

        return answer


# =============================================================================
# Chat Session
# =============================================================================

class ChatSession:
    """Interactive GraphRAG chat session (v2 two-phase architecture)."""

    def __init__(self, kg_query: KnowledgeGraphQuery,
                 synthesizer: ResultSynthesizer,
                 model: str):
        self.kg_query = kg_query
        self.synthesizer = synthesizer
        self.model = model
        self.history: List[Tuple[str, str, str]] = []  # (question, cypher, answer)
        self.conversation = ConversationHistory()

    @property
    def _driver(self):
        """Reuse the existing Neo4j driver from kg_query."""
        return self.kg_query.driver

    # -------------------------------------------------------------------------
    # Special commands
    # -------------------------------------------------------------------------

    def cmd_stats(self):
        """Show graph statistics."""
        try:
            with self._driver.session() as session:
                node_rows = list(session.run(
                    "MATCH (n) RETURN labels(n)[0] AS type, count(*) AS c ORDER BY c DESC"))
                edge_rows = list(session.run(
                    "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS c ORDER BY c DESC"))

            total_nodes = sum(r["c"] for r in node_rows)
            total_edges = sum(r["c"] for r in edge_rows)

            print(f"\n{_p('bold', 'Knowledge Graph Statistics')}")
            print(f"  Nodes: {_p('cyan', f'{total_nodes:,}')}  |  "
                  f"Edges: {_p('cyan', f'{total_edges:,}')}  |  "
                  f"Node types: {len(node_rows)}  |  Edge types: {len(edge_rows)}")
            print(f"\n  {_p('bold', 'Top Node Types:')}")
            for r in node_rows[:10]:
                bar = "#" * min(40, r["c"] // 500)
                print(f"    {r['type']:<22} {r['c']:>7,}  {_p('dim', bar)}")
            print(f"\n  {_p('bold', 'Top Edge Types:')}")
            for r in edge_rows[:10]:
                bar = "#" * min(40, r["c"] // 800)
                print(f"    {r['type']:<28} {r['c']:>7,}  {_p('dim', bar)}")
            print()
        except Exception as e:
            print(f"  {_p('red', f'Error fetching stats: {e}')}\n")

    def cmd_search(self, query: str):
        """Keyword search via full-text index."""
        try:
            rows = None
            with self._driver.session() as session:
                try:
                    rows = list(session.run(
                        "CALL db.index.fulltext.queryNodes('kg_fulltext', $q) "
                        "YIELD node, score RETURN node, score ORDER BY score DESC LIMIT 15",
                        q=query))
                except Exception:
                    rows = None

            if not rows:
                with self._driver.session() as session:
                    rows = list(session.run(
                        "MATCH (n) WHERE toLower(toString(n.name)) CONTAINS toLower($q) "
                        "   OR toLower(toString(n.sample_id)) CONTAINS toLower($q) "
                        "   OR toLower(toString(n.search_content)) CONTAINS toLower($q) "
                        "RETURN n AS node, 1.0 AS score LIMIT 15",
                        q=query))

            if not rows:
                print(f"  {_p('yellow', 'No results found.')}\n")
                return

            print(f"  {_p('green', f'Found {len(rows)} results:')}")
            for row in rows:
                node = row["node"]
                label = list(node.labels)[0] if node.labels else "Node"
                props = dict(node)
                # Display name
                name = props.get('name') or props.get('sample_id') or props.get('summary', '')
                if name and len(str(name)) > 80:
                    name = str(name)[:77] + "..."
                score = row["score"]
                print(f"    [{_p('cyan', label):<22}] {str(name)[:60]}  "
                      f"{_p('dim', f'({score:.2f})')}")
            print()
        except Exception as e:
            print(f"  {_p('red', f'Search error: {e}')}\n")

    def cmd_subgraph(self, node_id: str):
        """View a node and its 1-hop neighbors."""
        try:
            with self._driver.session() as session:
                # Find node
                node_row = session.run(
                    "MATCH (n {id: $id}) RETURN n LIMIT 1", id=node_id
                ).single()
                if node_row is None:
                    # Try sample_id for Sample nodes
                    node_row = session.run(
                        "MATCH (n:Sample {sample_id: $id}) RETURN n LIMIT 1", id=node_id
                    ).single()
                if node_row is None:
                    print(f"  {_p('yellow', f'Node {node_id} not found.')}\n")
                    return

                node = node_row["n"]
                label = list(node.labels)[0] if node.labels else "Node"
                props = dict(node)
                name = props.get('name') or props.get('sample_id') or props.get('id', '')

                print(f"\n  {_p('bold', 'Node:')} [{_p('cyan', label)}] {name}")
                # Show key properties
                for k, v in props.items():
                    if k in ('id', 'name', 'sample_id'):
                        continue
                    v_str = str(v)
                    if len(v_str) > 100:
                        v_str = v_str[:97] + "..."
                    print(f"    {k}: {v_str}")

                # 1-hop neighbors
                rows = list(session.run(
                    "MATCH (n {id: $id})-[r]-(m) "
                    "RETURN type(r) AS rel, labels(m) AS labels, m.id AS neighbor_id, "
                    "m.name AS neighbor_name LIMIT 100",
                    id=props.get('id', node_id)))

            if not rows:
                print(f"  {_p('dim', 'No relationships found.')}\n")
                return

            from collections import Counter
            ntc = Counter(
                tuple(r["labels"])[0] if r["labels"] else "Node" for r in rows
            )
            etc = Counter(r["rel"] for r in rows)

            print(f"\n  {_p('bold', f'1-hop subgraph:')} {len(rows)} edges")
            print(f"  Neighbor types: {dict(ntc)}")
            print(f"  Edge types: {dict(etc)}")

            # Show sample neighbors
            print(f"\n  {_p('bold', 'Neighbors:')}")
            for r in rows[:15]:
                nlabel = r["labels"][0] if r["labels"] else "?"
                nname = r["neighbor_name"] or r["neighbor_id"]
                rel = r["rel"]
                print(f"    -[{rel}]-> [{_p('cyan', nlabel)}] {nname}")
            if len(rows) > 15:
                print(f"    {_p('dim', f'... and {len(rows) - 15} more')}")
            print()
        except Exception as e:
            print(f"  {_p('red', f'Subgraph error: {e}')}\n")

    # -------------------------------------------------------------------------
    # Main Q&A flow
    # -------------------------------------------------------------------------

    def ask(self, question: str, verbose: bool = True):
        """Two-phase GraphRAG Q&A with conversation context."""
        # Get conversation context for multi-turn support
        conv_context = self.conversation.format_context() if not self.conversation.is_empty else ""

        # Phase 1: Query KG
        if verbose:
            ctx_indicator = f" {_p('dim', f'(turn {self.conversation.turn_count + 1})')}" if not self.conversation.is_empty else ""
            print(f"\n{_p('bold', 'Phase 1')}{ctx_indicator} {_p('dim', '— Understanding question & querying knowledge graph...')}")

        phase1_result = self.kg_query.query(question, verbose=verbose,
                                            conversation_context=conv_context)

        cypher = phase1_result.get("cypher") or ""
        node_count = phase1_result.get("node_count", 0)
        error = phase1_result.get("error")
        retries = phase1_result.get("retries", 0)

        if verbose:
            if error:
                print(f"  {_p('red', f'Query failed after {retries} retries: {error[:150]}')}")
            else:
                status = f"{node_count} nodes, {len(phase1_result['results'])} records"
                if retries > 0:
                    status += f" (fixed after {retries} retries)"
                print(f"  {_p('green', f'Query OK: {status}')}")

        # Phase 2: Synthesize
        if verbose:
            print(f"\n{_p('bold', 'Phase 2')} {_p('dim', '— Synthesizing answer...')}")

        answer = self.synthesizer.synthesize(question, phase1_result,
                                               conversation_context=conv_context)

        # Display answer
        print(f"\n{_p('bold', chr(0x250C) + ' Answer ' + chr(0x2500) * 55)}")
        wrapper = textwrap.TextWrapper(
            width=70, initial_indent="| ", subsequent_indent="| "
        )
        for line in answer.split("\n"):
            if not line.strip():
                print("|")
            elif len(line) <= 70:
                print(f"| {line}")
            else:
                for wrapped in wrapper.wrap(line):
                    print(wrapped)
        print(_p("bold", chr(0x2514) + chr(0x2500) * 65))

        # Show Cypher
        if verbose and cypher:
            cypher_preview = cypher.strip()[:300] if cypher else "(empty)"
            print(f"\n{_p('dim', f'Cypher: {cypher_preview}')}")
        print()

        # Save history
        self.history.append((question, cypher, answer))
        self.conversation.add(question, answer, cypher)

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    def run(self):
        """Start interactive main loop."""
        os.system("cls" if os.name == "nt" else "clear")
        print(_p("cyan", BANNER))

        # Get graph stats
        try:
            with self._driver.session() as session:
                n_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                e_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            print(_p("dim", f"  Model: {self.model}  |  "
                    f"Nodes: {n_count:,}  |  "
                    f"Edges: {e_count:,}"))
        except Exception:
            pass

        print(_p("dim", "  Type /help for commands, /exit to quit, /new to start fresh."))
        print(_p("dim", "  Two-phase: Phase 1 (query KG) → Phase 2 (synthesize answer)"))
        print(_p("dim", "  Multi-turn: follow-up questions carry conversation context (auto-compact)"))
        print()

        while True:
            try:
                conv_indicator = f" [{self.conversation.turn_count}]" if not self.conversation.is_empty else ""
                question = input(_p("bold", f"You{conv_indicator} > ")).strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{_p('dim', 'Goodbye!')}")
                break

            if not question:
                continue

            # Special commands
            if question.startswith("/"):
                parts = question[1:].split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if cmd in ("exit", "quit", "q"):
                    print(f"{_p('dim', 'Goodbye!')}")
                    break
                elif cmd == "help":
                    self._print_help()
                elif cmd == "stats":
                    self.cmd_stats()
                elif cmd == "search":
                    if not arg:
                        print(f"  {_p('yellow', 'Usage: /search <keyword>')}\n")
                    else:
                        self.cmd_search(arg)
                elif cmd == "subgraph":
                    if not arg:
                        print(f"  {_p('yellow', 'Usage: /subgraph <node_id>')}\n")
                    else:
                        self.cmd_subgraph(arg)
                elif cmd == "clear":
                    os.system("cls" if os.name == "nt" else "clear")
                elif cmd in ("new", "fresh"):
                    # Start a new conversation session
                    turn_count = self.conversation.turn_count
                    self.conversation.clear()
                    self.history.clear()
                    print(f"\n{_p('green', chr(0x2500) * 60)}")
                    if turn_count > 0:
                        print(_p('green', f"  New session started. Previous {turn_count} turns archived."))
                    else:
                        print(_p('green', "  New session started."))
                    print(_p('green', chr(0x2500) * 60))
                    if arg:
                        # /new <question> — immediately ask the new question
                        self.ask(arg)
                    print()
                elif cmd == "history":
                    if not self.history:
                        print(f"  {_p('dim', 'No history yet.')}\n")
                    else:
                        for i, (q, c, a) in enumerate(self.history, 1):
                            a_preview = a[:80].replace('\n', ' ')
                            print(f"  {_p('dim', f'[{i}]')} {q[:60]}")
                            print(f"      {_p('dim', a_preview + '...')}")
                        print()
                elif cmd == "cypher":
                    # Show last Cypher
                    if self.history:
                        print(f"\n{_p('dim', 'Last Cypher:')}")
                        print(f"{_p('dim', self.history[-1][1][:500])}\n")
                    else:
                        print(f"  {_p('dim', 'No query yet.')}\n")
                else:
                    print(f"  {_p('yellow', f'Unknown command: /{cmd}')}  "
                          f"Type /help for available commands.\n")
                continue

            # GraphRAG Q&A
            self.ask(question)

    def _print_help(self):
        print(f"""
{_p('bold', 'Available Commands:')}
  {_p('cyan', '/help')}        Show this help
  {_p('cyan', '/stats')}       Show knowledge graph statistics
  {_p('cyan', '/search')} kw   Search nodes by keyword (e.g. {_p('dim', '/search EGF')})
  {_p('cyan', '/subgraph')} id View a node and its 1-hop neighbors
  {_p('cyan', '/cypher')}      Show the last generated Cypher query
  {_p('cyan', '/history')}     Show conversation history
  {_p('cyan', '/new')} [q]     Start a new conversation session (optional: with new question)
  {_p('cyan', '/clear')}       Clear screen
  {_p('cyan', '/exit')}        Quit

{_p('bold', 'Architecture:')}
  Phase 1: LLM understands question → generates Cypher → queries Neo4j
           (retries up to 3 times on Cypher syntax errors)
  Phase 2: LLM synthesizes all retrieved node details into answer
  Multi-turn: follow-up questions carry previous conversation context
           (auto-compacts when >5 turns, keeps last 5 turns in full)

{_p('bold', 'Tips:')}
  - Ask questions in Chinese or English
  - Be specific: mention organ names, drug names, disease models, etc.
  - The system returns ALL node properties for accurate answers
  - Use {_p('dim', '/search')} to explore the graph without consuming LLM tokens
  - Use {_p('dim', '/cypher')} to inspect the generated Cypher query
  - Use {_p('dim', '/new')} to start fresh when switching topics
""")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Organoid KG GraphRAG Interactive Chat v2 (Two-Phase Architecture)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # DeepSeek default
  set LLM_API_KEY=sk-xxx
  set NEO4J_PASSWORD=xxx
  python scripts/chat_v2.py

  # OpenAI
  python scripts/chat_v2.py --base-url https://api.openai.com/v1 --model gpt-4o

  # Ollama local model
  python scripts/chat_v2.py --base-url http://localhost:11434/v1 --model llama3
        """)

    parser.add_argument("--uri", default="bolt://192.168.24.42:7687",
                        help="Neo4j URI (default: bolt://localhost:7687)")
    parser.add_argument("--user", default="neo4j",
                        help="Neo4j username (default: neo4j)")
    parser.add_argument("--password", default=None,
                        help="Neo4j password (or set F env var)")
    parser.add_argument("--api-key", default=None,
                        help="LLM API Key (or set LLM_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY)")
    parser.add_argument("--base-url", default="https://api.deepseek.com",
                        help="API base URL (default: https://api.deepseek.com)")
    parser.add_argument("--model", default="deepseek-v4-pro",
                        help="Model name (default: deepseek-v4-pro)")
    parser.add_argument("--single", "-s", default=None,
                        help="Single question mode (non-interactive)")
    args = parser.parse_args()

    # API Key
    api_key = (args.api_key
               or os.environ.get("LLM_API_KEY")
               or os.environ.get("DEEPSEEK_API_KEY")
               or os.environ.get("OPENAI_API_KEY"))
    if not api_key:
        print("Error: No API key provided. Use one of:")
        print("  --api-key sk-xxx")
        print("  set LLM_API_KEY=sk-xxx       (generic)")
        print("  set DEEPSEEK_API_KEY=sk-xxx   (DeepSeek)")
        print("  set OPENAI_API_KEY=sk-xxx     (OpenAI)")
        sys.exit(1)

    # Neo4j password
    password = args.password or os.environ.get("NEO4J_PASSWORD")
    if not password:
        print("Error: Neo4j password required.")
        print("  Use --password or set NEO4J_PASSWORD environment variable")
        sys.exit(1)

    # Provider name
    provider = ("DeepSeek" if "deepseek" in args.base_url else
                "OpenAI" if "openai" in args.base_url else
                "Ollama" if "localhost" in args.base_url or "ollama" in args.base_url else
                "Custom")
    print(f"LLM: {args.model} @ {provider} ({args.base_url})")

    # Initialize LLM client
    llm = LLMClient(api_key=api_key, base_url=args.base_url, model=args.model)

    # Initialize KG query engine
    try:
        kg_query = KnowledgeGraphQuery(
            uri=args.uri,
            user=args.user,
            password=password,
            llm=llm,
        )
    except Exception as e:
        print(f"Error connecting to Neo4j: {e}")
        print("\nMake sure Neo4j is running and the KG has been imported:")
        print("  python scripts/import_to_neo4j.py --graph <path>")
        sys.exit(1)

    # Initialize synthesizer
    synthesizer = ResultSynthesizer(llm=llm)

    # Start session
    session = ChatSession(
        kg_query=kg_query,
        synthesizer=synthesizer,
        model=args.model,
    )

    try:
        if args.single:
            # Single question mode
            session.ask(args.single, verbose=True)
        else:
            session.run()
    finally:
        kg_query.close()


if __name__ == "__main__":
    main()
