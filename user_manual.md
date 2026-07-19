# Organoid Knowledge Graph — User Manual

> Data source: MySQL `public_general_2026` table (17,055 sample records)
> Build artifacts: 103,360 nodes / 258,284 relationships, JSON ~560 MB / SQLite ~520 MB

---

## 1. Graph Overview

This knowledge graph is built from the organoid culture database `public_general_2026`, extracting structured data from the wide table into **18 node types** and **19 relationship types**, supporting keyword search, graph traversal, inference queries, and LLM GraphRAG Q&A.

Internal mechanism: Each MySQL row → 1 Sample node + several entity nodes (via JSON column parsing + content hash deduplication). Chinese questions are auto-converted to English keywords for graph search, and the subgraph is injected into the LLM prompt to generate evidence-based answers.

### 1.1 Core Statistics

| Metric | Value |
|------|-----|
| Total nodes | 103,360 |
| Total relationships | 258,284 |
| Node types | 18 |
| Relationship types | 19 |
| Average degree | 5.00 |

### 1.2 Node Type Distribution

| Node Type | Description | Count |
|----------|----------|------|
| Sample | Sample (core fact entity) | 17,055 |
| Phenotype | Phenotype | 17,984 |
| Technology | Culture/analysis techniques | 15,869 |
| Publication | Reference sources | 12,473 |
| Composition | Cell composition profiles | 10,518 |
| Organoid | Organoid types | 9,095 |
| Drug | Screened drugs | 4,255 |
| Biomarker | Biomarkers | 4,193 |
| DiseaseModel | Disease models | 4,038 |
| CellFactor | Cytokines/growth factors/small molecules | 2,848 |
| Application | Application directions | 1,453 |
| Gene | Gene editing targets | 1,333 |
| Infection | Infection/microbial challenges | 959 |
| Organ | Organ/tissue sources | 601 |
| System | Physiological systems | 243 |
| Omics | Omics data | 226 |
| Source | Tissue/cell sources | 120 |
| Organism | Species | 97 |

### 1.3 Relationship Type Distribution

| Relationship Type | Description | Direction | Count |
|----------|----------|------|------|
| HAS_BIOMARKER | Expressed/detected biomarkers | Sample → Biomarker | 29,568 |
| USES_FACTOR | Cytokines used | Sample → CellFactor | 25,974 |
| HAS_COMPOSITION | Cell composition profiles | Sample → Composition | 25,233 |
| HAS_PHENOTYPE | Observed phenotypes | Sample → Phenotype | 18,859 |
| HAS_ORGANOID | Organoid cultured in sample | Sample → Organoid | 17,055 |
| FROM_ORGANISM | Species source of sample | Sample → Organism | 17,055 |
| CITES | Cited references | Sample → Publication | 17,055 |
| USES_TECHNOLOGY | Techniques used | Sample → Technology | 17,055 |
| SCREENS_DRUG | Drugs screened | Sample → Drug | 14,232 |
| INDICATES_DISEASE | Biomarker-disease association (inferred) | Biomarker → DiseaseModel | 13,471 |
| HAS_APPLICATION | Application directions of organoid | Organoid → Application | 12,787 |
| MODELS_DISEASE | Disease modeled | Organoid → DiseaseModel | 11,175 |
| DERIVED_FROM | Tissue source of organoid | Organoid → Source | 10,116 |
| FROM_ORGAN | Organoid derived from organ | Organoid → Organ | 9,611 |
| TREATS_DISEASE | Drug-disease association (inferred) | Drug → DiseaseModel | 8,648 |
| HAS_OMICS | Associated omics data | Sample → Omics | 5,868 |
| HAS_GENE_EDIT | Gene editing | Sample → Gene | 1,918 |
| HAS_INFECTION | Infection challenge experiments | Sample → Infection | 1,829 |
| BELONGS_TO_SYSTEM | Organ belongs to physiological system | Organ → System | 775 |

> TREATS_DISEASE and INDICATES_DISEASE are inferred relationships, auto-generated based on co-occurrence of Drug/DiseaseModel or Biomarker/DiseaseModel within the same sample, with a confidence attribute.

---

## 2. Quick Start

### 2.1 Environment Setup

**Requires Python 3.10+**. Using a virtual environment is recommended:

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS / Linux)
source venv/bin/activate

# Install dependencies
pip install -r scripts/requirements.txt
```
### 2.2 Build the Knowledge Graph

```bash
# Explore database structure (confirm tables and columns)
python scripts/build_kg.py --host 192.168.20.30 --port 33061 --database public --user xxx --password xxx --explore

# Build knowledge graph (output JSON + SQLite)
python scripts/build_kg.py --host 192.168.20.30 --port 33061 --database public --user xxx --password xxx --output-dir ./organoid-kg-output
```

Artifacts are stored by timestamp under `organoid-kg-output/YYYY-MM-DD-HHMM/`, with each build kept independently.

### 2.3 Interactive Chat (Recommended)

`chat.py` is a GraphRAG chat terminal preconfigured with DeepSeek that auto-detects the latest KG:

```bash
  Usage
  # DeepSeek (default, zero config)
  set DEEPSEEK_API_KEY=sk-xxx
  python scripts/chat.py

  # OpenAI
  set OPENAI_API_KEY=sk-xxx
  python scripts/chat.py --base-url https://api.openai.com/v1 --model gpt-4o

  # Ollama local model (no API key needed)
  python scripts/chat.py --base-url http://localhost:11434/v1 --model llama3 --api-key ollama

  # Other compatible services (Qwen / vLLM / etc.)
  set LLM_API_KEY=sk-xxx
  python scripts/chat.py --base-url https://your-api.com/v1 --model your-model

  # Pass key directly via command line
  python scripts/chat.py --api-key sk-xxx --base-url https://api.deepseek.com --model deepseek-chat

```

Supports natural language questions in both Chinese and English. Internal flow: Chinese question → LLM extracts English keywords → graph search for subgraph → subgraph injected into prompt → LLM generates answer.

Session commands:

| Command | Function |
|------|------|
| `/help` | Show help |
| `/stats` | View graph statistics (node/relationship distribution) |
| `/search EGF` | Keyword search, no LLM token consumption |
| `/subgraph smp_KM-00001` | View 1-hop neighbors of a node |
| `/history` | View current session chat history |
| `/clear` | Clear screen |
| `/exit` | Exit |

### 2.4 Command-Line Queries

You can also use `query_tool.py` for non-interactive operations:

```bash
# Graph statistics
python scripts/query_tool.py --graph kg.json --stats

# Keyword search
python scripts/query_tool.py --graph kg.json --search "intestinal organoid"

# View node subgraph
python scripts/query_tool.py --graph kg.json --subgraph smp_KM-00001

# Single LLM Q&A
python scripts/query_tool.py --graph kg.json --base-url https://api.deepseek.com --api-key sk-xxx --model deepseek-chat --question "Which culture conditions support intestinal organoid differentiation?"

# Interactive Q&A (query_tool built-in)
python scripts/query_tool.py --graph kg.json --base-url https://api.deepseek.com --api-key sk-xxx --model deepseek-chat --interactive
```

### 2.5 Python API

```python
from query_tool import KnowledgeGraphQuery

kg = KnowledgeGraphQuery.load("organoid_kg.json")

# Keyword search
results = kg.search("intestinal organoid", top_k=10)
for node, score in results:
    print(f"[{node.type}] {node.properties.get('name', node.id)}")

# Type-restricted search
results = kg.search("Cisplatin", node_type="Drug", top_k=10)

# Graph traversal
subgraph = kg.traverse("smp_KM-00001", depth=2)

# GraphRAG Q&A (DeepSeek)
answer = kg.ask(
    "Which culture conditions support intestinal organoid differentiation?",
    api_key="sk-xxx",
    base_url="https://api.deepseek.com",
    model="deepseek-chat",
)
print(answer["response"])
```

### 2.6 Validate Graph Quality

```bash
python scripts/validate_kg.py   # Auto-detect latest build, run structure checks + query tests
```

---

## 3. Gephi Visualization

```bash
# Sampled export (recommended for preview)
python scripts/export_for_gephi.py kg.json --sample 200 -o preview.gexf

# Filter by type
python scripts/export_for_gephi.py kg.json -t Sample,Organoid,Organ,Drug -o drug_subgraph.gexf

# Full export
python scripts/export_for_gephi.py kg.json -o full.gexf
```

After importing into Gephi: Appearance → Nodes → Color → Partition → `type` → Apply; Layout → ForceAtlas 2 → Run.

---

## 4. Common Query Scenarios

### Query by Organoid/Organ

**Q: Which organoids are intestinal?**
```python
results = kg.search("intestine intestinal colon", top_k=10)
for node, score in results:
    if node.type == "Organoid":
        print(node.properties.get("name"))
```

**Q: What tissues are liver organoids derived from?**
```python
results = kg.search("Liver hepatic", top_k=5)
for node, score in results:
    if node.type in ("Organoid", "Organ"):
        sub = kg.traverse(node.id, depth=3)
        for n in sub["nodes"]:
            if n.type == "Source":
                print(f"Source: {n.properties.get('name')}")
```

### Query by Cytokine

**Q: Which samples used EGF?**
```python
results = kg.search("EGF", top_k=10)
for node, score in results:
    if node.type == "CellFactor":
        sub = kg.traverse(node.id, depth=1)
        samples = [n for n in sub["nodes"] if n.type == "Sample"]
        print(f"EGF used in {len(samples)} samples")
```

**Q: How many samples use EGF + Wnt + R-spondin together?**
```python
def find_samples(kg, keyword):
    results = kg.search(keyword, top_k=20)
    sample_ids = set()
    for node, _ in results:
        if node.type == "CellFactor":
            sub = kg.traverse(node.id, depth=1)
            for n in sub["nodes"]:
                if n.type == "Sample":
                    sample_ids.add(n.id)
    return sample_ids

common = find_samples(kg, "EGF") & find_samples(kg, "Wnt") & find_samples(kg, "R-spondin")
print(f"Samples using all three factors: {len(common)}")
```

### Query by Drug/Disease

**Q: Which drugs treat colorectal cancer?** (inferred relation TREATS_DISEASE)
```python
results = kg.search("Colorectal Cancer", top_k=5)
for node, score in results:
    if node.type == "DiseaseModel":
        sub = kg.traverse(node.id, depth=1)
        for e in sub["edges"]:
            if e.relation == "TREATS_DISEASE":
                src = kg.nodes[e.source]
                print(f"{src.properties.get('name')} (conf={e.properties.get('confidence')})")
```

### Query by Gene/Technology

**Q: Which samples involve APC gene?**
```python
results = kg.search("APC", top_k=10)
for node, score in results:
    if node.type == "Gene":
        print(f"{node.properties.get('name')} - {node.properties.get('editing_method', 'N/A')}")
```

### Query by Biomarker

**Q: Which biomarkers are associated with inflammatory bowel disease?** (inferred relation INDICATES_DISEASE)
```python
results = kg.search("inflammatory bowel disease", top_k=5)
for node, score in results:
    if node.type == "DiseaseModel":
        sub = kg.traverse(node.id, depth=1)
        for n in sub["nodes"]:
            if n.type == "Biomarker":
                print(n.properties.get("name"))
```

### Query by Omics/Composition

**Q: Which samples have scRNA-seq data?**
```python
results = kg.search("scRNA-seq", top_k=10)
```

**Q: Which samples contain Matrigel?**
```python
results = kg.search("Matrigel", top_k=10)
```

### Sample Similarity

```python
sub1 = kg.traverse("smp_KM-00001", depth=1)
sub2 = kg.traverse("smp_KM-00002", depth=1)
neighbors1 = {n.id for n in sub1["nodes"]}
neighbors2 = {n.id for n in sub2["nodes"]}
shared = neighbors1 & neighbors2
jaccard = len(shared) / len(neighbors1 | neighbors2)
print(f"Jaccard similarity: {jaccard:.4f}")
```

---

## 5. Node ID System

| Prefix | Node Type | Example |
|------|---------|------|
| `smp_` | Sample | `smp_KM-00001` |
| `org_` | Organoid | `org_2bfd0138` |
| `orn_` | Organ | `orn_cd474d96` |
| `sys_` | System | `sys_be6d4487` |
| `osm_` | Organism | `osm_ecaa62bb` |
| `src_` | Source | `src_6889e48b` |
| `cf_` | CellFactor | `cf_966b6949` |
| `tec_` | Technology | `tec_3ae24970` |
| `drg_` | Drug | `drg_e42f481c` |
| `gen_` | Gene | `gen_58da8a20` |
| `dm_` | DiseaseModel | `dm_ebe2d81e` |
| `inf_` | Infection | `inf_7c56acf7` |
| `bmk_` | Biomarker | `bmk_4f15c3e2` |
| `phn_` | Phenotype | `phn_364e91a5` |
| `omc_` | Omics | `omc_b6f6c91f` |
| `cmp_` | Composition | `cmp_c8ee2661` |
| `app_` | Application | `app_83178013` |
| `pub_` | Publication | `pub_303b4ddd` |

---

## 6. Tool Scripts Overview

| Script | Purpose |
|------|------|
| `scripts/chat.py` | **Recommended** Interactive GraphRAG chat terminal (DeepSeek pre-configured) |
| `scripts/build_kg.py` | Build knowledge graph from MySQL |
| `scripts/query_tool.py` | Graph query engine (CLI + Python library) |
| `scripts/validate_kg.py` | Graph validation (structure checks + query tests + reports) |
| `scripts/export_for_gephi.py` | Export to Gephi visualization format |
| `scripts/test_kg.py` | Functional test script (12 search tests + LLM Q&A) |
| `scripts/diagnose_samples.py` | Database diagnostic tool |

---

## 7. Query Tips

- **Precise type restriction**: `kg.search("Cisplatin", node_type="Drug")` searches only drug nodes
- **Deep traversal**: Increase the `depth` parameter to expand subgraph; higher depths may result in overly large subgraphs
- **Path finding**: `kg.find_paths("smp_A", "drg_B")` discovers relationship paths between two nodes
- **Composite queries**: Use `search()` first to find seed nodes, then `traverse()` to expand the subgraph
- **Inferred relationships**: TREATS_DISEASE / INDICATES_DISEASE are based on co-occurrence inference; confidence is in edge properties
- **Co-culture distinction**: Distinguish via edge attribute `context` (`"primary"` vs `"coculture"`)
- **Global statistics**: LLM prompt includes complete graph statistics; count-based questions won't hallucinate

---

## 8. Known Limitations

1. Culture conditions/steps/materials are retained as Sample JSON properties; fine-grained filtering by temperature, CO2 concentration, etc. is not supported
2. Co-culture data shares CellFactor/Biomarker node types, distinguished via edge attribute `context`
3. Inferred relationships (TREATS_DISEASE / INDICATES_DISEASE) are based on co-occurrence statistics and do not imply causality
4. JSON column entity extraction depends on key name matching; uncovered key names may miss entities
5. Currently only processes the `public_general_2026` single table; other related tables require extending `build_kg.py`
6. Uses JSON + SQLite file storage, no graph database needed, suitable for single-machine distribution

---

## References

- Complete tutorial: `build_tutorial.md`
- Schema design document: `docs/schema_design.md`
- Database table description: `docs/public_general_2026_info.md`
