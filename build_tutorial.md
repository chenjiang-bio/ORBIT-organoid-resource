# Building an Organoid Knowledge Graph from a MySQL Database — Complete Tutorial

> Reference paper: **MOF-ChemUnity: Literature-Informed Large Language Models for Metal−Organic Framework Research**
> *J. Am. Chem. Soc. 2025, 147, 43474–43486*

---

## Table of Contents

1. [Methodology Overview](#1-methodology-overview)
2. [Knowledge Graph Schema Design](#2-knowledge-graph-schema-design)
3. [Extracting Data from MySQL](#3-extracting-data-from-mysql)
4. [Building the Knowledge Graph Files](#4-building-the-knowledge-graph-files)
5. [Query Tool: Graph Querying and LLM RAG](#5-query-tool-graph-querying-and-llm-rag)
6. [Validation, Testing, and Feedback](#6-validation-testing-and-feedback)
7. [Packaging and Distribution](#7-packaging-and-distribution)
8. [Appendix: FAQ and Tuning](#8-appendix-faq-and-tuning)

---

## 1. Methodology Overview

### 1.1 Core Method of the MOF-ChemUnity Paper

The MOF-ChemUnity paper proposes a **complete framework for building a knowledge graph from unstructured text and then enhancing LLM Q&A with the graph**, consisting of four core steps:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  1. Entity    │───▶│  2. Info      │───▶│  3. Knowledge │───▶│  4. GraphRAG │
│  Resolution  │    │  Extraction  │    │  Graph Build  │    │  Q&A System  │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

1. **Entity Resolution**: Uses LLM + RAG framework to map MOF names in literature (which may have multiple aliases) to standard identifiers in the CSD crystal structure database. This solves the problem of "the same thing called different names in different places."
2. **Information Extraction**: Uses LLM workflow to extract properties, synthesis steps, and applications from full-text literature.
3. **Knowledge Graph Construction**: Builds a graph in Neo4j containing node types such as MOF, Name, Publication, Property, Synthesis, and Application, connected by relationships like Has Property, Has Synthesis, and Has Source. The final graph contains 40,000+ nodes and 3,200,000+ relationships.
4. **Graph-enhanced RAG**: User natural language question → LLM translates to Cypher query → retrieves relevant subgraph → subgraph information injected as context into LLM prompt → generates evidence-based answer.

### 1.2 Our Adaptation

Your scenario has a key difference from the paper: **your data is already structured MySQL data**, so you don't need entity resolution and information extraction from unstructured literature PDFs. This greatly simplifies the process.

Our adaptation:

| Paper Step | Corresponding Step in This Tutorial | Description |
|---------|-------------|------|
| Entity Resolution (LLM RAG) | JSON column parsing + content hash deduplication | Fields with the same name are automatically deduplicated and merged across multiple samples |
| Information Extraction (LLM workflow) | JSON parsing + entity extraction | Extract independent entity nodes from JSON columns |
| Graph Construction (Neo4j) | Generate JSON file + SQLite file | File-based, no server needed |
| GraphRAG (Cypher queries) | Python Query Tool + subgraph retrieval | Load JSON file, keyword + graph traversal search |
| LLM Q&A | OpenAI API / any LLM API | Generate answers after context injection |
| (No paper equivalent) Quality Validation | `validate_kg.py` structural checks + query simulation | Automatically detect graph correctness, generate health scores and feedback reports |

Final deliverables:
```
build_graphRAG/
├── scripts/
│   ├── build_kg.py               # Graph construction script (MySQL → KG, repeatable)
│   ├── query_tool.py             # Graph query engine (CLI + Python library, with GraphRAG)
│   ├── chat.py                   # Interactive chat terminal (DeepSeek pre-configured, recommended for daily use)
│   ├── validate_kg.py            # Graph validation and feedback tool (structure checks + query tests + reports)
│   ├── export_for_gephi.py       # Gephi visualization export (GEXF / GML / CSV)
│   ├── test_kg.py                # Functional test script (12 search tests + LLM Q&A)
│   ├── diagnose_samples.py       # Database diagnostic tool
│   └── requirements.txt          # Python dependencies
├── organoid-kg-output/           # Build artifacts (timestamped subdirectories)
│   └── YYYY-MM-DD-HHMM/
│       ├── organoid_kg.json      # Knowledge graph (universal JSON format, ~560 MB)
│       ├── organoid_kg.sqlite    # Knowledge graph (SQLite, ~520 MB)
│       └── build_report.json     # Build statistics report
├── kg_test_output/               # Validation artifacts (timestamped subdirectories)
│   ├── YYYY-MM-DD-HHMM/
│   │   ├── test_report.json      # Structured test results
│   │   └── test_report.md        # Human-readable test report
│   └── user_manual.md            # User manual
├── gephi_export/                 # Gephi visualization export files
└── docs/
    └── schema_design.md          # Schema design document
```

---

## 2. Knowledge Graph Schema Design

### 2.1 Design Principles

Three principles from the MOF-ChemUnity paper:

- **Scalability**: Adding new data rows will not break the graph structure; simply append.
- **Linkability**: The same organoid type, drug, or gene appearing across different sample records will be correctly linked (via content hash deduplication).
- **Queryability**: Supports both precise queries ("Which drugs were screened for sample ABC123?") and broad queries ("Which liver organoids are sensitive to Cisplatin?").

### 2.2 Node Types

Based on the paper's six node categories and the 49 actual fields of `public_general_2026`, **18 node types** are defined:

| Layer | Node Type | ID Prefix | Source Column | Description |
|------|---------|--------|--------|------|
| **Core** | Sample | `smp` | `sample_id` (PK) | Single sample record, graph hub |
| **Biological Identity** | Organoid | `org` | `organoid`, `canonical_name` | Organoid type |
| | Organ | `orn` | `organ` | Organ/tissue (Liver, Intestine, etc.) |
| | System | `sys` | `system` (json) | Physiological system (Digestive, Nervous, etc.) |
| | Organism | `osm` | `organism` | Species (Human, Mouse, etc.) |
| | Source | `src` | `source` | Tissue/cell source |
| **Culture Components** | CellFactor | `cf` | `cell_factors`, `coculture_cell_factors` (json) | Cytokines/small molecules |
| | Technology | `tec` | `techologies` (json) | Culture/analysis techniques |
| **Experimental Variables** | Drug | `drg` | `drug_screening` (json) | Screened drugs |
| | Gene | `gen` | `gene_name`, `sgrna` | Gene editing targets |
| | DiseaseModel | `dm` | `disease_modeling` | Disease models |
| | Infection | `inf` | `infection_list` (json) | Infection challenges |
| **Measurement & Characterization** | Biomarker | `bmk` | `biomarker`, `biomarker_coculture` (json) | Biomarkers |
| | Phenotype | `phn` | `phenotype_identification` (json) | Phenotype information |
| | Composition | `cmp` | `composition` (json) | Cell composition profiles |
| **Downstream** | Omics | `omc` | `omics_id` (json) | Omics data |
| | Application | `app` | `application` | Application directions |
| | Publication | `pub` | `reference`, `doi` | References |

> Detailed definitions in [`schema_design.md`](docs/schema_design.md). Culture conditions, steps, materials, and other JSON columns are retained as Sample properties, not independent nodes.
>
> ⚠️ **The `test` column has been dropped**: The early design included Test nodes (detection methods) and `HAS_TEST` relationships, but due to poor data quality in the `test` column, they have been removed from the build script — neither nodes nor properties are created (see comments in `build_kg.py` under `WIDE_TABLE_ENTITY_MAPPING`). Thus the actual node count is 18 types and 19 relationship types.

### 2.3 Relationship Types

A total of **19 relationship types** (including 2 inferred relationships):

| Relationship Name | Direction | Semantics |
|--------|------|------|
| HAS_ORGANOID | Sample → Organoid | What organoid the sample cultured |
| FROM_ORGAN | Organoid → Organ | What organ the organoid is derived from |
| BELONGS_TO_SYSTEM | Organ → System | What physiological system the organ belongs to |
| FROM_ORGANISM | Sample → Organism | What species the sample comes from |
| DERIVED_FROM | Organoid → Source | Tissue/cell source of the organoid |
| USES_FACTOR | Sample → CellFactor | What cytokines the sample used |
| USES_TECHNOLOGY | Sample → Technology | What techniques the sample used |
| SCREENS_DRUG | Sample → Drug | What drugs the sample screened |
| HAS_GENE_EDIT | Sample → Gene | What gene editing the sample performed |
| MODELS_DISEASE | Organoid → DiseaseModel | What disease the organoid models |
| HAS_INFECTION | Sample → Infection | What infection experiment the sample conducted |
| HAS_BIOMARKER | Sample → Biomarker | What biomarkers the sample expressed |
| HAS_PHENOTYPE | Sample → Phenotype | What phenotype the sample exhibited |
| HAS_OMICS | Sample → Omics | What omics data the sample is linked to |
| HAS_COMPOSITION | Sample → Composition | What cell composition the sample contains |
| HAS_APPLICATION | Organoid → Application | What applications the organoid can be used for |
| CITES | Sample → Publication | What publication the sample references |
| TREATS_DISEASE ⚡ | Drug → DiseaseModel | Drug used for what disease (co-occurrence inference) |
| INDICATES_DISEASE ⚡ | Biomarker → DiseaseModel | Biomarker associated with what disease (co-occurrence inference) |

> ⚡ = Inferred relationships, not direct data extraction, based on co-occurrence within the same sample. See [`schema_design.md`](docs/schema_design.md) for details.
> The `HAS_TEST` relationship has been removed along with the `test` column.

### 2.4 JSON Graph File Format

```json
{
  "meta": {
    "name": "Organoid Culture Knowledge Graph",
    "version": "1.0",
    "created": "2026-07-18T15:52:02",
    "source_database": "public",
    "description": "Knowledge graph of organoid culture experiments built from MySQL database",
    "node_types": [
      "Application", "Biomarker", "Composition", "DiseaseModel", "Drug",
      "Gene", "Omics", "Organ", "Organism", "Organoid", "Phenotype",
      "Publication", "Sample", "Source", "System", "Technology"
    ],
    "relationship_types": [
      "BELONGS_TO_SYSTEM", "CITES", "DERIVED_FROM", "FROM_ORGAN", "FROM_ORGANISM",
      "HAS_APPLICATION", "HAS_BIOMARKER", "HAS_COMPOSITION", "HAS_GENE_EDIT",
      "HAS_OMICS", "HAS_ORGANOID", "HAS_PHENOTYPE", "INDICATES_DISEASE",
      "MODELS_DISEASE", "SCREENS_DRUG", "TREATS_DISEASE", "USES_TECHNOLOGY"
    ]
  },
  "nodes": [
    {
      "id": "smp_ABC123",
      "type": "Sample",
      "properties": {
        "sample_id": "ABC123",
        "culture_days": "7",
        "culture_condition": {"temperature": "37°C", "co2": "5%"},
        "endpoints": "Organoid formation efficiency > 80%"
      }
    },
    {
      "id": "org_a1b2c3d4",
      "type": "Organoid",
      "properties": {
        "name": "Intestinal Organoid",
        "canonical_name": "Small Intestinal Organoid"
      }
    },
    {
      "id": "orn_small_intestine",
      "type": "Organ",
      "properties": { "name": "Small Intestine" }
    },
    {
      "id": "drg_e5f6g7h8",
      "type": "Drug",
      "properties": {
        "name": "Cisplatin",
        "category": "Chemotherapy"
      }
    }
  ],
  "edges": [
    {
      "source": "smp_ABC123",
      "target": "org_a1b2c3d4",
      "relation": "HAS_ORGANOID"
    },
    {
      "source": "org_a1b2c3d4",
      "target": "orn_small_intestine",
      "relation": "FROM_ORGAN"
    },
    {
      "source": "smp_ABC123",
      "target": "drg_e5f6g7h8",
      "relation": "SCREENS_DRUG",
      "properties": { "concentration": "10 µM" }
    }
  ]
}
```

### 2.5 SQLite Graph Storage Format

The SQLite version uses three tables to store graph data, supporting standard SQL queries:

```sql
-- Nodes table
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    properties TEXT NOT NULL  -- JSON string
);

-- Edges table
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation TEXT NOT NULL,
    properties TEXT,  -- JSON string
    FOREIGN KEY (source) REFERENCES nodes(id),
    FOREIGN KEY (target) REFERENCES nodes(id)
);

-- Indexes for faster queries
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_edges_relation ON edges(relation);
```

---

## 3. Extracting Data from MySQL

### 3.1 Exploring Database Table Structure

First, use the `build_kg.py` script to auto-explore your MySQL database structure. The script lists all tables, fields, and foreign key relationships:

```bash
python build_kg.py \
    --host localhost \
    --port 3306 \
    --user root \
    --password your_password \
    --database organoid_db \
    --explore
```

Example output:
```
Tables found in public:
  └── public_general_2026 (49 columns, 17,546 rows)
      │   Single wide table — no foreign keys detected
      │
      ├── [Organoid Identity] (13 columns)
      │   ├── sample_id                varchar(250)      (PK)
      │   ├── organoid                 varchar(512)
      │   ├── organ                    varchar(255)
      │   ├── source                   varchar(250)
      │   ├── organism                 varchar(250)
      │   ├── system                   json
      │   └── ...
      ├── [Culture & Protocol] (10 columns)
      │   ├── culture_technique        json
      │   ├── cell_factors             json
      │   ├── cultivation_protocol     json
      │   └── ...
      ├── [Biomarkers & Characterization] (6 columns)
      │   ├── biomarker                json
      │   ├── biomarker_coculture      json
      │   └── ...
      └── [Drug & Phenotype] (5 columns)
          ├── drug_screening           json
          ├── phenotype_identification json
          └── ...
```

### 3.2 Field Mapping Strategy

Map `public_general_2026` (49-column single wide table) to 18 node types and 19 relationship types. Core principles:

1. **Reusable JSON columns → Independent nodes**: List entities stored in JSON columns like `cell_factors`, `drug_screening`, `biomarker` are deduplicated by content hash and extracted as shared nodes
2. **Non-reusable columns → Sample properties**: Columns like `culture_condition`, `cultivation_protocol`, `endpoints` that vary greatly between samples are retained as Sample node properties
3. **Foreign keys → Edges in the graph**: Association fields like the `organism` column generate `FROM_ORGANISM` edges
4. **Co-culture columns → Same-type nodes + edge markers**: `coculture_cell_factors` → CellFactor nodes, edges marked with `context: "coculture"` attribute to distinguish
5. **Inferred relationships**: Drug/DiseaseModel co-occurrence within the same sample → `TREATS_DISEASE`; Biomarker/DiseaseModel co-occurrence → `INDICATES_DISEASE`

The complete mapping table is in [`schema_design.md` Section 7](docs/schema_design.md).

### 3.3 Data Extraction Strategy

`build_kg.py` uses the following strategy to extract data from the `public_general_2026` wide table:

```python
# Pseudocode: Extract from single wide table and build graph
def extract_from_wide_table(connection):
    nodes = []
    edges = []

    # Step 1: Extract each row's sample → Sample node
    rows = query("SELECT * FROM public_general_2026")
    for row in rows:
        sample = SampleNode(id=f"smp_{row.sample_id}", properties=row)
        nodes.append(sample)

        # Step 2: Extract entity nodes from regular columns
        # organoid → Organoid, organ → Organ, organism → Organism, etc.
        organoid = get_or_create_Organoid(row.organoid)
        organ = get_or_create_Organ(row.organ)
        edges.append(Edge(sample.id, organoid.id, "HAS_ORGANOID"))
        edges.append(Edge(organoid.id, organ.id, "FROM_ORGAN"))

        # Step 3: Extract entity nodes from JSON columns (with deduplication)
        # cell_factors → CellFactor nodes
        for factor in parse_json(row.cell_factors):
            cf = get_or_create_CellFactor(factor.name)
            edges.append(Edge(sample.id, cf.id, "USES_FACTOR",
                          properties={"context": "primary"}))

        # drug_screening → Drug nodes
        for drug in parse_json(row.drug_screening):
            d = get_or_create_Drug(drug.name)
            edges.append(Edge(sample.id, d.id, "SCREENS_DRUG",
                          properties={"concentration": drug.concentration}))

        # biomarker, technology, omics, infection, phenotype...
        # Similar pattern: parse JSON → hash dedup → create node → create edge
        # Note: test column dropped; no Test nodes are created

        # Step 4: Co-culture columns → same-type nodes + edge marking context="coculture"
        for factor in parse_json(row.coculture_cell_factors):
            cf = get_or_create_CellFactor(factor.name)
            edges.append(Edge(sample.id, cf.id, "USES_FACTOR",
                          properties={"context": "coculture"}))

    # Step 5: Inferred relationships (post-processing)
    for sample in samples:
        if sample.has_drug and sample.has_disease:
            edges.append(Edge(drug.id, disease.id, "TREATS_DISEASE",
                          properties={"confidence": compute_confidence()}))

    return nodes, edges
```

> See [`scripts/build_kg.py`](../scripts/build_kg.py) for detailed implementation.

---

## 4. Building the Knowledge Graph Files

### 4.1 Running the Build Script

```bash
python build_kg.py --host localhost --port 3306 \
    --user root --password your_password --database organoid_db \
    --output-dir ./organoid-kg-output --format json sqlite
```

The script will **create a timestamped subdirectory** `YYYY-MM-DD-HHMM/` under `--output-dir` (e.g., `organoid-kg-output/2026-07-18-1552/`), with each run producing an independent copy for easy comparison between builds. Output inside the subdirectory:
- `organoid_kg.json` — JSON format knowledge graph
- `organoid_kg.sqlite` — SQLite format knowledge graph
- `build_report.json` — Build report (node count, edge count, type distribution, etc.)

> Tip: `build_kg.py`'s connection parameters have project defaults (`--host 192.168.20.30 --port 33061 --user wangchenglong --database public`). For your own database, explicitly override these parameters.

### 4.2 Build Report Example

Below is a `build_report.json` summary from an actual build (`public_general_2026`, 17,055 rows):

```json
{
  "statistics": {
    "total_nodes": 103360,
    "total_edges": 258284,
    "nodes_by_type": {
      "Phenotype": 17984,
      "Sample": 17055,
      "Technology": 15869,
      "Publication": 12473,
      "Composition": 10518,
      "Organoid": 9095,
      "Drug": 4255,
      "Biomarker": 4193,
      "DiseaseModel": 4038,
      "CellFactor": 2848,
      "Application": 1453,
      "Gene": 1333,
      "Infection": 959,
      "Organ": 601,
      "System": 243,
      "Omics": 226,
      "Source": 120,
      "Organism": 97
    },
    "edges_by_relation": {
      "HAS_BIOMARKER": 29568,
      "USES_FACTOR": 25974,
      "HAS_COMPOSITION": 25233,
      "HAS_PHENOTYPE": 18859,
      "HAS_ORGANOID": 17055,
      "FROM_ORGANISM": 17055,
      "CITES": 17055,
      "USES_TECHNOLOGY": 17055,
      "SCREENS_DRUG": 14232,
      "INDICATES_DISEASE": 13471,
      "HAS_APPLICATION": 12787,
      "MODELS_DISEASE": 11175,
      "DERIVED_FROM": 10116,
      "FROM_ORGAN": 9611,
      "TREATS_DISEASE": 8648,
      "HAS_OMICS": 5868,
      "HAS_GENE_EDIT": 1918,
      "HAS_INFECTION": 1829,
      "BELONGS_TO_SYSTEM": 775
    }
  }
}
```

> Improvements compared to earlier builds:
> - **CellFactor (2,848) / Infection (959) nodes restored from 0 to normal**: Entity extraction was fixed by preloading the `public_general_extraction_raw` table and parsing the `cultures[].story.protocol[].growth_factors` and `cultures[].story.infection_list` paths within the JSON.
> - **cell_factors / coculture_cell_factors auto-routed**: Growth factors are assigned to primary culture (USES_FACTOR, context=primary) or co-culture (USES_FACTOR, context=coculture) based on the `base_info.if_co_culture` field.
> - The generated `organoid_kg.json` is about **560 MB** and `organoid_kg.sqlite` about **520 MB** — these are large files; be mindful of disk and memory.

### 4.3 Data Quality and Deduplication

Referencing the paper's approach to MOF structure deduplication. In our single wide table scenario:

```python
# Deduplication strategy: content hash → same entity shared across multiple samples as one node
#
# 1. Same organoid name → shares one Organoid node (org_{name_hash})
# 2. Same drug name (e.g., "Cisplatin") → shares one Drug node (drg_{name_hash})
# 3. Same gene name (e.g., "APC") → shares one Gene node (gen_{name_hash})
# 4. cell_factor, biomarker, etc. extracted from JSON columns are deduplicated similarly

# Deduplication is implemented via the _get_or_create_entity() method:
# registry key = (entity_type, name.lower().strip())
# First 8 characters of MD5(name) as node ID suffix
# e.g., "drg_a1b2c3d4" corresponds to Cisplatin — all samples screening Cisplatin share this node
```

---

## 5. Query Tool: Graph Querying and LLM RAG

This is the core part of this tutorial. The project provides two interaction modes: `chat.py` (recommended chat terminal) and `query_tool.py` (CLI tool + Python library), both sharing the same `KnowledgeGraphQuery` engine.

### 5.1 Recommended: chat.py Interactive Chat

`chat.py` is a preconfigured DeepSeek chat terminal that auto-detects the latest KG, ready to use out of the box:

```bash
set DEEPSEEK_API_KEY=sk-xxx
python scripts/chat.py
```

Supports natural language questions in both Chinese and English; internally auto-converts Chinese questions to English keyword searches. Session commands available: `/stats`, `/search`, `/subgraph`, `/help`, etc.

### 5.2 Architecture Design

```
User natural language question
       │
       ▼
┌─────────────────────────────────────────────────────┐
│                  Query Tool                          │
│                                                      │
│  ┌──────────────┐    ┌──────────────┐               │
│  │ 1. Keyword    │    │ 2. Subgraph  │               │
│  │  Extraction   │───▶│  Retrieval   │               │
│  │  (rule/LLM)   │    │  (graph trav)│               │
│  └──────────────┘    └──────┬───────┘               │
│                              │                       │
│                    ┌─────────▼─────────┐            │
│                    │ 3. Context Build  │            │
│                    │  (format subgraph)│            │
│                    └─────────┬─────────┘            │
│                              │                       │
│                    ┌─────────▼─────────┐            │
│                    │ 4. LLM Generate   │            │
│                    │  Answer           │            │
│                    │  (GPT-4o / other) │            │
│                    └─────────┬─────────┘            │
│                              │                       │
│                    Return: Answer + Source citations │
└─────────────────────────────────────────────────────┘
```

### 5.3 Usage

#### As a Python Library

```python
from query_tool import KnowledgeGraphQuery

# Load the graph
kg = KnowledgeGraphQuery.load("organoid_kg.json")

# Method 1: Direct retrieval (no LLM needed)
results = kg.search("intestinal organoid Wnt3a")
for node, score in results:
    print(f"[{node['type']}] {node['properties'].get('name')} (score: {score:.2f})")

# Method 2: Type-filtered retrieval
drugs = kg.search("Cisplatin", node_type="Drug", top_k=5)
markers = kg.search("Lgr5", node_type="Biomarker", top_k=5)

# Method 3: Graph traversal — view all information linked to a sample
subgraph = kg.traverse("smp_ABC123", depth=2)
print(f"Subgraph: {len(subgraph['nodes'])} nodes, {len(subgraph['edges'])} edges")

# Method 4: GraphRAG Q&A (requires LLM API)
answer = kg.ask(
    question="Which organoid culture experiments used EGF factor and observed increased proliferation?",
    llm_api_key="sk-...",           # OpenAI API key
    llm_model="gpt-4o",             # or other models
    top_k=20                        # Number of relevant nodes to retrieve
)
print(answer['response'])           # LLM-generated answer
print(answer['sources'])            # Source citations (node IDs and evidence in the graph)
```

#### As a CLI Tool

```bash
# Interactive Q&A mode
python query_tool.py --graph organoid_kg.json --api-key sk-xxx --interactive

# Single query
python query_tool.py --graph organoid_kg.json --api-key sk-xxx \
    --question "Which cytokines support intestinal organoid differentiation?"

# Pure graph search (no LLM dependency)
python query_tool.py --graph organoid_kg.json --search "EGF R-spondin intestinal"

# View a sample's subgraph
python query_tool.py --graph organoid_kg.json --subgraph smp_ABC123

# View graph statistics
python query_tool.py --graph organoid_kg.json --stats
```

### 5.4 Subgraph Retrieval Strategy

Referencing the GraphRAG method in the paper, we use a two-layer retrieval:

```python
def retrieve_subgraph(kg, question, top_k=20):
    """
    Two-layer retrieval strategy:
    1. Keyword matching: Find seed nodes most relevant to the question
    2. Graph traversal: Starting from seed nodes, expand to neighbor nodes along edges
    """
    # Layer 1: Keyword matching to find seed nodes
    keywords = extract_keywords(question)  # Extract keywords from the question
    seed_nodes = []
    for node in kg.nodes:
        score = compute_keyword_score(node, keywords)
        if score > 0:
            seed_nodes.append((node, score))
    seed_nodes.sort(key=lambda x: x[1], reverse=True)
    seed_nodes = seed_nodes[:top_k]

    # Layer 2: 2-hop graph traversal from seed nodes
    visited_nodes = set()
    visited_edges = set()
    for seed, _ in seed_nodes:
        visited_nodes.add(seed['id'])
        # BFS traverse neighbors
        for edge in kg.edges:
            if edge['source'] == seed['id'] or edge['target'] == seed['id']:
                visited_edges.add(edge['id'])
                neighbor = edge['target'] if edge['source'] == seed['id'] else edge['source']
                visited_nodes.add(neighbor)

    # Build subgraph
    subgraph = {
        'nodes': [n for n in kg.nodes if n['id'] in visited_nodes],
        'edges': [e for e in kg.edges if e['id'] in visited_edges]
    }
    return subgraph
```

### 5.5 LLM Prompt Template

Referencing the Graph-enhanced RAG method from Figure 6 of the paper, the retrieved subgraph information is injected as context into the LLM prompt:

```python
PROMPT_TEMPLATE = """You are a scientific assistant specialized in organoid culture,
3D cell biology, and organ-on-a-chip research. Answer the user's question based ONLY
on the knowledge graph context provided below. If the context does not contain enough
information to answer, say so explicitly. Always cite the source sample IDs or node
IDs when making claims.

## Knowledge Graph Context
The graph contains 18 node types (Sample, Organoid, Organ, System, Organism, Source,
CellFactor, Technology, Drug, Gene, DiseaseModel, Infection, Biomarker, Phenotype,
Omics, Composition, Application, Publication) and 19 relationship types.

{context}

## User Question
{question}

## Instructions
- Answer based on the context above
- Cite specific sample IDs, organoid names, drug names, or gene names
- If the answer involves numbers or measurements, include them verbatim with units
- Format your answer clearly with bullet points when listing multiple items
- End with a "Sources:" section listing the node IDs you used
- If context is insufficient, state what is missing explicitly

## Answer"""
```

### 5.6 Custom LLM Backend

The `ask()` method of `query_tool.py` supports any OpenAI-compatible API service via the `--base-url` and `--model` parameters:

```bash
# OpenAI (default)
python query_tool.py --graph organoid_kg.json --api-key sk-xxx --interactive

# Ollama local model
python query_tool.py --graph organoid_kg.json \
    --base-url http://localhost:11434/v1 --model llama3 --interactive

# DeepSeek
python query_tool.py --graph organoid_kg.json \
    --base-url https://api.deepseek.com/v1 --api-key sk-xxx --model deepseek-chat --interactive
```

Code invocation:

```python
kg = KnowledgeGraphQuery.load("organoid_kg.json")
answer = kg.ask(
    "EGFR inhibitor effects?",
    api_key="sk-xxx",
    base_url="http://localhost:11434/v1",  # Ollama
    model="llama3"
)
# Pure retrieval mode (no LLM needed)
results = kg.search("EGFR inhibitor")
```

---

## 6. Validation, Testing, and Feedback

After the graph is built, how do you confirm it was "built correctly"? `scripts/validate_kg.py` provides an **automated detection and feedback** workflow: it loads the build artifacts, runs a batch of structural checks and query simulations, outputs a health score and actionable fix suggestions, and incidentally generates a user manual. This step addresses the quality assurance gap in the paper's methodology and is a supplement to the paper's approach.

### 6.1 How to Run

```bash
cd scripts

# Most common: auto-locate organoid_kg.json in the latest timestamped directory under organoid-kg-output, run all checks
python validate_kg.py

# Specify a specific graph file
python validate_kg.py ../organoid-kg-output/2026-07-18-1552/organoid_kg.json

# Run only structural checks (fast, no query simulation)
python validate_kg.py --structure-only

# Run only query tests
python validate_kg.py --query-only

# Generate user manual only (no tests)
python validate_kg.py --gen-manual
```

Parameter descriptions:

| Parameter | Default | Description |
|------|--------|------|
| `kg_file` (positional) | Auto-detect | Graph JSON path; if omitted, scans the latest timestamped directory under `--kg-dir` |
| `--kg-dir` | `./organoid-kg-output` | Build directory scanned during auto-detection (subdirectory names `YYYY-MM-DD-HHMM`, latest by lexicographic order) |
| `--output-dir` | `./kg_test_output` | Report output directory |
| `--structure-only` | — | Structural checks only |
| `--query-only` | — | Query tests only |
| `--gen-manual` | — | Generate user manual only |

### 6.2 Two Types of Checks

Validation is divided into two phases, both implemented using `query_tool.py` capabilities (`validate_kg.py` directly imports `KnowledgeGraphQuery`).

**Phase 1 — Structural Checks (`StructureValidator`, 10 items)**: Directly checks whether the graph itself conforms to the expected schema.

| # | Check Item | Pass Condition | Feedback on Failure |
|---|--------|----------|-------------|
| 1 | `node_types_complete` | All 18 expected node types present | List missing/extra types |
| 2 | `relation_types_complete` | All 19 expected relationship types present | List missing relationships |
| 3 | `node_counts_positive` | Each type (except Sample) has count > 0 | ⚠️ List types with zero count, suggest checking MySQL columns or JSON parsing |
| 4 | `entity_dedup` | Only one node per same type + same name | List duplicate entity groups, suggest checking `_get_or_create_entity()` |
| 5 | `edge_direction` | Each edge's `source_type→target_type` matches `EXPECTED_EDGE_DIRECTION` | List edges with incorrect direction |
| 6 | `coculture_context` | Edges with `context=coculture` exist | ⚠️ Suggest checking `COCULTURE_COLUMNS` |
| 7 | `inferred_relations_exist` | `TREATS_DISEASE`, `INDICATES_DISEASE` both > 0 | ⚠️ Suggest checking `INFERRED_RELATIONS` |
| 8 | `no_orphan_types` | Each type has at least one node with an edge | List orphan types |
| 9 | `no_duplicate_edges` | No duplicate `(source, target, relation)` edges | ⚠️ Report duplicate edge count |
| 10 | `edge_id_uniqueness` | Edge IDs are unique | Report duplicate ID count |

**Phase 2 — Query Simulation Tests (`QueryTester`, 20 questions)**: Simulates real user queries to verify "searchable, traversable, hitting expected node/relationship types." Tests cover single-hop, multi-hop, inferred relationships, co-culture, cross-query, and literature query six categories. Flow for each question:

```
Keyword search() → take top 5 hits → traverse() → check if expected node types and relationship types are hit → determine PASS/WARN/FAIL
```

> Note: The validation script's expected schema (`EXPECTED_NODE_TYPES` / `EXPECTED_RELATION_TYPES`) has also been synced to remove `Test` / `HAS_TEST`; the original question #10 (Immunofluorescence → HAS_TEST) has been deleted and replaced with scRNA-seq → HAS_OMICS. The two inferred relationship questions (TREATS_DISEASE, INDICATES_DISEASE) use `min_results=0`, allowing empty results and marking as WARN rather than FAIL.

### 6.3 Three Output Files

```
kg_test_output/
├── 2026-07-18-1552/
│   ├── test_report.json      # Structured results: status, detail, suggestion for each check/query
│   └── test_report.md        # Human-readable report: summary table + failure details + fix suggestions
└── user_manual.md            # Auto-generated user manual based on 20 test questions
```

The core of `test_report.md` is an **executive summary + health score**:

```
| Metric | Value |
|------|-----|
| Total checks | 30 |
| Passed | 26 |
| Failed | 4 |
| Pass rate | 86.7% |
| Health score | 87/100 |
```

**Health score** algorithm: structure check pass rate accounts for 50 points, query test pass rate accounts for 50 points, summed and rounded (see `ReportGenerator.health_score`). The "Fix Suggestions" table at the end of the report maps each failed item to a specific code configuration location (e.g., `WIDE_TABLE_ENTITY_MAPPING`, `INFERRED_RELATIONS`), forming a **detect → locate → fix** closed-loop feedback.

### 6.4 Typical Feedback Loop

Taking the actual build in Section 4.2 as an example, where `CellFactor` / `Infection` node counts were 0, validation would provide this feedback:

1. `node_counts_positive` marked as **⚠️ WARN**, `detail` lists `zero-count types: ['CellFactor', 'Infection']`;
2. Corresponding query questions (e.g., #3 "Samples using EGF factor") hit `expected_types_missing` for `CellFactor` in Phase 2, marked **FAIL**;
3. Fix suggestions point to: *"Type ['CellFactor'] not hit: check if the corresponding MySQL column has data"* and *"Check `WIDE_TABLE_ENTITY_MAPPING` config / `JSON_ENTITY_NAME_KEYS` key name matching"*.

Based on this, you can go back to `build_kg.py` to investigate the JSON structure and name keys of the `cell_factors` column, rebuild, and re-validate until the health score meets standards.

### 6.5 Auto-Generated User Manual

`user_manual.md` is generated by `ReportGenerator.save_manual()` based on 20 test questions without requiring an LLM. Contents include: graph overview, quick start commands, query guide grouped by node type, 20 Q&A items (each with `kg.search()` / `kg.traverse()` code and CLI commands), query tips, and known limitations. It serves as a ready-to-use onboarding document for graph users — regenerate after each build to stay in sync with the graph.

---

## 7. Packaging and Distribution

### 7.1 Distribution File Structure

When publishing the graph, it is recommended to package the scripts, a specific build artifact, and the validation-generated manual together:

```
organoid-kg-release/
├── README.md                       # Project description, quick start
├── organoid_kg.json                # Knowledge graph file (universal JSON, from a specific build)
├── organoid_kg.sqlite              # Knowledge graph file (SQLite)
├── build_report.json               # Build statistics report
├── user_manual.md                  # Auto-generated user manual by validate_kg.py
├── test_report.md                  # Validation test report (optional, reflects graph quality)
├── query_tool.py                   # Graph query tool
├── build_kg.py                     # Graph build script
├── validate_kg.py                  # Graph validation tool
├── example_queries.py              # Example query script
├── schema_design.md                # Schema design document
└── requirements.txt                # Python dependencies
```

> The build script by default writes artifacts to `organoid-kg-output/<timestamp>/` and reports to `kg_test_output/<timestamp>/`. When packaging for distribution, pick the desired version from the corresponding timestamped directory.

### 7.2 requirements.txt

```
pymysql>=1.1.0
openai>=1.0.0
```

> `validate_kg.py` only depends on the standard library + `query_tool.py`, no additional installation needed.

### 7.3 How Others Can Use Your Published Graph

Those who download the graph only need the following steps:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Read the auto-generated user manual first
#    user_manual.md — contains query examples for 20 common questions

# 3. Interactive Q&A
python query_tool.py --graph organoid_kg.json --api-key YOUR_KEY --interactive

# 4. Or use in code
python -c "
from query_tool import KnowledgeGraphQuery
kg = KnowledgeGraphQuery.load('organoid_kg.json')
print(kg.ask('List all drug screening samples related to intestinal organoids')['response'])
"

# 5. (Optional) Validate graph quality yourself
python validate_kg.py organoid_kg.json
```

---

## 8. Appendix: FAQ and Tuning

### 8.1 What if My MySQL Table Structure is Different?

Edit the configuration area at the top of the `build_kg.py` script:

```python
# 1. Modify connection info and table name
FOCUS_TABLES = ['your_table_name']

# 2. Modify core node type
MANUAL_TABLE_TYPES = {
    "your_table_name": ("YourCoreNode", "prefix"),
}

# 3. Modify column-to-entity-node mapping
# Example: your table has a "treatment" column → map to Treatment node
WIDE_TABLE_ENTITY_MAPPING = {
    "your_column":   ("YourNodeType", "prefix", "RELATION_NAME", "sample"),
    "your_json_col": ("YourNodeType", "prefix", "RELATION_NAME", "sample", "json"),
}
```

For multi-table relational databases, rewrite the entity extraction logic in the `build()` method. For single wide tables, modifying the above configuration is sufficient for adaptation.

> After changing the Schema, remember to synchronize the `EXPECTED_NODE_TYPES`, `EXPECTED_RELATION_TYPES`, `EXPECTED_EDGE_DIRECTION`, and `TEST_CASES` at the top of `validate_kg.py`, otherwise validation will report false positives. (When removing the `test` column in this project, both locations were synchronized.)

### 8.2 What if the Data Volume is Very Large?

- JSON files support streaming reads; `query_tool.py` defaults to iterator-based loading
- SQLite format natively supports large data volumes with index acceleration
- Actual build JSON has reached ~560 MB (100K+ nodes); if the graph exceeds 1 million nodes, consider generating only the SQLite format or splitting into multiple JSON files

### 8.3 How to Keep the Graph in Sync with the MySQL Database?

Re-run `build_kg.py` for a full rebuild (artifacts land in a new timestamped directory, never overwriting the old version). Since the wide-table architecture always does a full scan + hash deduplication, for incremental update scenarios, filter via SQL WHERE conditions before building, or modify the FOCUS_TABLES in the script to limit the data scope. After rebuilding, run `python validate_kg.py` once to compare health scores and quickly detect data regressions.

### 8.4 How to Troubleshoot When a Node Type Count is Zero?

This is the most common issue (e.g., `CellFactor` / `Infection` in the actual build from this tutorial). Troubleshooting order:

1. Run `python validate_kg.py --structure-only` to see the zero-count list in `node_counts_positive`;
2. Go back to MySQL to confirm whether the corresponding column (e.g., `cell_factors`) actually has data and whether it is valid JSON;
3. Check whether the name key of JSON elements falls within `build_kg.py`'s `JSON_ENTITY_NAME_KEYS` — if the JSON uses a different key name, entity name extraction will fail and no node will be created;
4. After correction, rebuild and re-validate.

### 8.5 Comparison Summary with the Paper's Method

| Dimension | MOF-ChemUnity Paper | This Tutorial's Approach |
|------|-------------------|-----------|
| Data Source | Unstructured literature PDF → Markdown | Structured MySQL database |
| Entity Resolution | LLM RAG (98% match rate, 94% accuracy) | Content hash deduplication (MD5 first 8 chars) |
| Information Extraction | LLM workflow (89% precision, 94% yield) | JSON column parsing + entity extraction |
| Graph Storage | Neo4j (Cypher queries) | JSON + SQLite |
| Query Method | LLM → Cypher → Neo4j | Keyword matching + graph traversal + LLM |
| Deduplication Strategy | CSD reference codes + name synonyms | Entity name + content hash deduplication |
| Quality Validation | Manual sample evaluation of precision/yield | `validate_kg.py` automation: structure checks + query simulation + health score |
| Portability | Requires Neo4j server | Single file, usable on any device |
| Data Provenance | Stores original text sentences as evidence | Stores source table and row ID as evidence |

---

## References

1. Pruyn, T. M. et al. MOF-ChemUnity: Literature-Informed Large Language Models for Metal−Organic Framework Research. *J. Am. Chem. Soc.* **2025**, *147*, 43474−43486.
2. MOF-ChemUnity open-source code: https://github.com/AI4ChemS/MOF_ChemUnity
3. Edge, D. et al. From Local to Global: A Graph RAG Approach to Query-Focused Summarization. *arXiv* **2024**, arXiv:2404.16130.
