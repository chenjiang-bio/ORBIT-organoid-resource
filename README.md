# Organoid Knowledge Graph & GraphRAG

A knowledge graph built from a MySQL organoid culture database (17,055 records), supporting keyword search, graph traversal, and LLM GraphRAG Q&A. Methodology adapted from [MOF-ChemUnity](https://github.com/AI4ChemS/MOF_ChemUnity) (JACS 2025).

**Scale**: 103,360 nodes / 258,284 relationships across 18 node types and 19 relationship types.

## Quick Start

**Recommended**: Open [`orbit_kg_notebook.ipynb`](orbit_kg_notebook.ipynb) in Jupyter — it walks through loading the KG, search, traversal, and GraphRAG Q&A step by step.

```bash
# 1. Install dependencies (Python 3.10+)
pip install -r scripts/requirements.txt

# 2. Open the notebook (primary entry point)
jupyter notebook orbit_kg_notebook.ipynb

# 3. Build the knowledge graph from MySQL (if you need to rebuild)
python scripts/build_kg.py \
    --host 192.168.20.30 --port 33061 --database public \
    --user your_user --password your_password \
    --output-dir ./organoid-kg-output

# 4. Start interactive GraphRAG chat (DeepSeek pre-configured)
set DEEPSEEK_API_KEY=sk-xxx
python scripts/chat.py

# 5. Validate graph quality
python scripts/validate_kg.py
```

## What You Can Do

| Task | Command / Tool |
|------|---------------|
| Interactive GraphRAG chat | `python scripts/chat.py` |
| CLI queries & stats | `python scripts/query_tool.py --graph kg.json --stats` |
| Keyword search | `python scripts/query_tool.py --graph kg.json --search "EGF intestinal"` |
| Export for Gephi visualization | `python scripts/export_for_gephi.py kg.json --sample 200 -o preview.gexf` |
| Run functional tests | `python scripts/test_kg.py` |
| Validate graph quality | `python scripts/validate_kg.py` |

### As a Python Library

```python
from query_tool import KnowledgeGraphQuery

kg = KnowledgeGraphQuery.load("organoid_kg.json")

# Keyword search
results = kg.search("intestinal organoid EGF", top_k=10)

# Graph traversal
subgraph = kg.traverse("smp_KM-00001", depth=2)

# GraphRAG Q&A
answer = kg.ask(
    "Which culture conditions support intestinal organoid differentiation?",
    api_key="sk-xxx",
    base_url="https://api.deepseek.com",
    model="deepseek-chat",
)
print(answer["response"])
```

### Multiple LLM Backends(Recommended)

`chat.py` and `query_tool.py` support any OpenAI-compatible API:

```bash
# DeepSeek (default)
python scripts/chat.py

# OpenAI
python scripts/chat.py --base-url https://api.openai.com/v1 --model gpt-4o

# Ollama (local)
python scripts/chat.py --base-url http://localhost:11434/v1 --model llama3
```

## Repository Structure

```
├── scripts/
│   ├── build_kg.py            # MySQL → KG builder
│   ├── query_tool.py           # Core query engine (shared library)
│   ├── chat.py                 # Interactive GraphRAG terminal
│   ├── validate_kg.py          # Automated validation + report generation
│   ├── test_kg.py              # Functional test suite
│   ├── export_for_gephi.py     # Gephi visualization export
│   ├── diagnose_samples.py     # Database diagnostic tool
│   ├── example_queries.py      # Python API usage examples
│   └── requirements.txt        # pymysql, openai
├── organoid-kg-output/         # Build artifacts (timestamped)
│   └── YYYY-MM-DD-HHMM/
│       ├── organoid_kg.json
│       ├── organoid_kg.sqlite
│       └── build_report.json
├── docs/
│   └── schema_design.md        # Full schema specification
├── build_tutorial.md           # Complete methodology tutorial
├── user_manual.md              # Auto-generated user manual
└── orbit_kg_notebook.ipynb     # Jupyter notebook
```

## Documentation

| Document | Contents |
|----------|----------|
| [`user_manual.md`](user_manual.md) | Quick start, query scenarios, node ID system, API reference |
| [`build_tutorial.md`](build_tutorial.md) | Full methodology: schema design, data extraction, build process, GraphRAG, validation feedback loop |
| [`docs/schema_design.md`](docs/schema_design.md) | Detailed node/relationship type definitions, ID generation rules, MySQL column mapping |
| [`orbit_kg_notebook.ipynb`](orbit_kg_notebook.ipynb) | Interactive notebook for exploring the KG |

## Graph Schema at a Glance

**18 node types** across 6 layers:

| Layer | Node Types |
|-------|-----------|
| Core | Sample |
| Biological Identity | Organoid, Organ, System, Organism, Source |
| Culture Components | CellFactor, Technology |
| Experimental Variables | Drug, Gene, DiseaseModel, Infection |
| Characterization | Biomarker, Phenotype, Composition, Omics |
| Downstream | Application, Publication |

**19 relationship types**, including 2 inferred (co-occurrence-based): `TREATS_DISEASE` and `INDICATES_DISEASE`. See [`docs/schema_design.md`](docs/schema_design.md) for the complete entity-relationship diagram and MySQL column mapping.

## Dependencies

- Python 3.10+
- `pymysql>=1.1.0` — MySQL connection
- `openai>=1.0.0` — LLM API client (OpenAI-compatible)
- DeepSeek / OpenAI / Ollama API key (for GraphRAG Q&A)
