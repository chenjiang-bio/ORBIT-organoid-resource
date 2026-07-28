# Literature MCP Services

A multi-source search service built on FastMCP, providing query tools for Wikipedia, NCBI GEO, and NCBI Gene databases.

This module is part of [ORBIT-organoid-resource](https://github.com/chenjiang-bio/ORBIT-organoid-resource) and is used by [`../literature-agent/`](../literature-agent/).

## Overview

This project implements an MCP (Model Context Protocol) service with the following capabilities:

### Wikipedia search
- `get_wikipedia_summary` - get page summary
- `get_wikipedia_categories` - get page categories
- `get_wikipedia_text` - get full page text
- `get_wikipedia_links` - get outgoing links from a page
- `get_wikipedia_backlinks` - get incoming links to a page

### NCBI GEO database search
- `get_gse_summary` - get GSE dataset summary
- `get_gse_full_info` - get full GSE dataset information

### NCBI Gene database search
- `get_gene_summary` - get gene summary
- `get_gene_full_info` - get full gene information

All query results are cached locally to avoid repeated requests.

## Installation

### Requirements
- Python 3.8+
- pip

### Install dependencies

```bash
pip install fastmcp wikipediaapi requests
```

Or use requirements.txt:

```bash
pip install -r requirements.txt
```

## Starting the service

### 1. Start the MCP server

From the project root:

```bash
fastmcp run search_mcp.py:mcp --transport http --port 12400
```

The service listens at `http://localhost:12400/mcp` by default.

### 2. Service logs

After startup you will see:
- Registered tools
- Listen address
- Request handling logs

## MCP client tests

### 1. Run the test script

```bash
cd search_mcp
python search_mcpclient.py
```

### 2. What is tested

The script runs the following tests in order:

#### Wikipedia search tests
```python
# get summary
await client.call_tool("get_wikipedia_summary", {
    "keywords": ["Organoid", "Cancer"]
})

# get categories
await client.call_tool("get_wikipedia_categories", {
    "keywords": ["Cell"]
})

# get full text
await client.call_tool("get_wikipedia_text", {
    "keywords": ["Organoid"]
})

# get links
await client.call_tool("get_wikipedia_links", {
    "keywords": ["Homo sapiens", "Mus musculus"]
})

# get backlinks
await client.call_tool("get_wikipedia_backlinks", {
    "keywords": ["Model Context Protocol", "HTTP"]
})
```

#### GEO database tests
```python
# get GSE summary
await client.call_tool("get_gse_summary", {
    "gse_ids": ["GSE14594", "GSE28265"]
})

# get full GSE info
await client.call_tool("get_gse_full_info", {
    "gse_ids": ["GSE14594"]
})
```

#### Gene database tests
```python
# get gene summary
await client.call_tool("get_gene_summary", {
    "querys": [
        {"gene_name": "TP53", "organism": "Homo sapiens"},
        {"gene_name": "LGR5", "organism": "Homo sapiens"}
    ]
})

# get full gene info
await client.call_tool("get_gene_full_info", {
    "querys": [
        {"gene_name": "TP53", "organism": "Mus musculus"}
    ]
})
```

## Usage examples

### From Python

```python
import asyncio
from fastmcp import Client

client = Client("http://localhost:12400/mcp")

async def search_example():
    async with client:
        # query Wikipedia
        result = await client.call_tool("get_wikipedia_summary", {
            "keywords": ["Machine Learning"]
        })
        print(result.content)
        
        # query gene info
        result = await client.call_tool("get_gene_summary", {
            "querys": [
                {"gene_name": "BRCA1", "organism": "Homo sapiens"}
            ]
        })
        print(result.content)

asyncio.run(search_example())
```

### Cache

All query results are cached under `./cache`:
- Wikipedia: `wiki_{keyword}.json`
- GEO: `{gse_id}.json`
- Gene: `gene_{organism}_{gene_name}.json`

To clear the cache, delete the corresponding cache files.

## Response format

All tools return JSON:

### Wikipedia tools
```json
{
  "keyword1": "content...",
  "keyword2": "content...",
  "keyword3": "not found, need to check"
}
```

### GEO tools
```json
{
  "GSE12345": ["ID: GSE12345", "Title: ...", "Summary: ..."],
  "GSE67890": "not found, need to check"
}
```

### Gene tools
```json
[
  {
    "gene_name": "TP53",
    "organism": "Homo sapiens",
    "summary": ["Gene ID: 7157", "Symbol: TP53", ...]
  }
]
```

## Credentials

Do not commit real API keys. Copy the example files and fill in values:

```bash
cp calling/google.env.example calling/google.env
cp calling/wiki.env.example calling/wiki.env
```

## Project structure

```
literature-mcp/
├── search_mcp.py           # MCP service entry
├── search_mcpclient.py     # test client
├── requirements.txt
└── calling/
    ├── wiki_search.py
    ├── gse_search.py
    ├── gene_search.py
    ├── google_search.py
    ├── pubmed_search.py
    ├── wiki.env.example
    └── google.env.example
```

Local cache files are written under `./cache/` (gitignored).

## Notes

1. The first query for a given key is slower because data is fetched from the network
2. Cache files persist on disk; clean them periodically to free space
3. Ensure network access to Wikipedia and NCBI services
4. Gene queries require both gene name and organism
5. GSE IDs may be provided with or without the `GSE` prefix
