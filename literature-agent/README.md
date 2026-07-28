# Literature Agent (OrganoidInfoExtract)

Multi-agent pipeline that extracts structured organoid culture information from scientific papers (Markdown). Built on [crewAI](https://crewai.com).

This module is part of [ORBIT-organoid-resource](https://github.com/chenjiang-bio/ORBIT-organoid-resource). Runtime search tools are provided by [`../literature-mcp/`](../literature-mcp/).

**Data flow:** PDF → MinerU → `pdf_output/<id>/content.md` → Crew extraction → `output*/<id>/final_output.json`

## Requirements

- Python `>=3.10,<3.14`
- [UV](https://docs.astral.sh/uv/) for dependency management

### Locked crewAI versions

- crewai: `0.203.2`
- crewai-tools: `0.76.0`

## Installation

Install UV if needed:

```bash
pip install uv
```

From the project root, install dependencies into `.venv`:

```bash
uv sync --frozen
```

On Windows, prefer the project venv CLI to avoid a different global `crewai` on `PATH`:

```powershell
.\.venv\Scripts\crewai.exe --help
```

## Environment variables (`.env`)

Create a `.env` in the project root. Models are configured **per pipeline stage**. Missing required values can crash LLM construction (e.g. `float(None)` / `int(None)`).

Model names usually use LiteLLM/crewAI style, e.g. `openai/gpt-4o` or `openai/gemini-2.5-flash`.

You may keep a local `.env` as a private template; **do not commit secrets**.

### Extract

| Variable | Description |
|----------|-------------|
| `EXTRACT_API_MODEL` | Model id |
| `EXTRACT_API_BASEURL` | API base URL |
| `EXTRACT_API_KEY` | API key |
| `EXTRACT_API_TEMPERATURE` | Temperature (float) |
| `EXTRACT_API_TIMEOUT` | Timeout seconds (int) |
| `EXTRACT_API_REASONING_EFFORT` | e.g. `low` / `medium` / `high` |
| `EXTRACT_NUM_CTX` | Context window size (int, default `262144`) |

### Search plan

| Variable | Description |
|----------|-------------|
| `SEARCH_PLAN_API_MODEL` | Model id |
| `SEARCH_PLAN_API_BASEURL` | API base URL |
| `SEARCH_PLAN_API_KEY` | API key |
| `SEARCH_PLAN_API_TEMPERATURE` | Temperature |
| `SEARCH_PLAN_API_TIMEOUT` | Timeout seconds |
| `SEARCH_PLAN_API_REASONING_EFFORT` | Reasoning effort |
| `SEARCH_PLAN_NUM_CTX` | Context window size |

### Search execute

| Variable | Description |
|----------|-------------|
| `SEARCH_EXECUTE_API_MODEL` | Model id |
| `SEARCH_EXECUTE_API_BASEURL` | API base URL |
| `SEARCH_EXECUTE_API_KEY` | API key |
| `SEARCH_EXECUTE_API_TEMPERATURE` | Temperature |
| `SEARCH_EXECUTE_API_TIMEOUT` | Timeout seconds |
| `SEARCH_EXECUTE_API_REASONING_EFFORT` | Reasoning effort |
| `SEARCH_EXECUTE_NUM_CTX` | Context window size |

### Check (up to 3 parallel checkers)

Shared:

| Variable | Description |
|----------|-------------|
| `CHECK_API_TEMPERATURE` | Shared temperature |
| `CHECK_API_TIMEOUT` | Shared timeout |
| `CHECK_API_REASONING_EFFORT` | Shared reasoning effort |
| `CHECK_NUM_CTX` | Shared context size |

Per checker (`N` = `1`, `2`, or `3`):

| Variable | Description |
|----------|-------------|
| `CHECK_API_MODEL{N}` | Model id |
| `CHECK_API_BASEURL{N}` | API base URL |
| `CHECK_API_KEY{N}` | API key |
| `CHECK_API_NAME{N}` | Task/crew name used for cache and parallel runs (must stay consistent with task naming) |

### Correct (up to 2 parallel correctors)

Shared: `CORRECT_API_TEMPERATURE`, `CORRECT_API_TIMEOUT`, `CORRECT_API_REASONING_EFFORT`, `CORRECT_NUM_CTX`

Per corrector (`N` = `1` or `2`): `CORRECT_API_MODEL{N}`, `CORRECT_API_BASEURL{N}`, `CORRECT_API_KEY{N}`, `CORRECT_API_NAME{N}`

### Judge

| Variable | Description |
|----------|-------------|
| `JUDGE_API_MODEL` | Model id |
| `JUDGE_API_BASEURL` | API base URL |
| `JUDGE_API_KEY` | API key |
| `JUDGE_API_TEMPERATURE` | Temperature |
| `JUDGE_API_TIMEOUT` | Timeout seconds |
| `JUDGE_API_REASONING_EFFORT` | Reasoning effort |
| `JUDGE_NUM_CTX` | Context window size |

### Shared / optional

| Variable | Required | Description |
|----------|----------|-------------|
| `STREAM_SWITCH` | No | `"True"` / `"False"` for LLM streaming (default `False`) |
| `AGENT_REQUEST_WAIT_SEC` | No | Min seconds between agent LLM requests (patch executor; default `45`) |
| `DIFF_EMBEDDING_MODEL` | No | Embedding model for JSON semantic diff |
| `DIFF_EMBEDDING_BASE_URL` | No | **Full embeddings endpoint URL** (used as-is; not base + `/embeddings`) |
| `DIFF_EMBEDDING_API_KEY` | No | Embedding API key |
| `CUSTOM_NOTIFY_URL` | No | Webhook URL for progress notifications |

Example skeleton (replace placeholders):

```dotenv
EXTRACT_API_MODEL="openai/your-model"
EXTRACT_API_BASEURL="https://your-api-host/v1"
EXTRACT_API_KEY="sk-..."
EXTRACT_API_TEMPERATURE="0.0"
EXTRACT_API_TIMEOUT="600"
EXTRACT_API_REASONING_EFFORT="medium"
EXTRACT_NUM_CTX="262144"

# ... same pattern for SEARCH_PLAN_*, SEARCH_EXECUTE_*, CHECK_*, CORRECT_*, JUDGE_*

STREAM_SWITCH="False"
AGENT_REQUEST_WAIT_SEC="45"
```

## Run config (`run.json` / `PAPER_CONFIG_DIR`)

`PAPER_CONFIG_DIR` is an environment variable whose value is the **path to a JSON config file** (despite the name, it is not a directory).

Required JSON fields:

| Field | Meaning |
|-------|---------|
| `EXTRACTION_DATA_DIR` | Root of paper folders. Each subfolder is a work name and must contain `content.md` |
| `OUTPUT_DATA_DIR` | Root for outputs (`tentative_output.json`, `check_output.json`, `search_*`, `final_output.json`, …) |
| `LOG_DIR` | Root for run logs |

Example (also shipped as `run.json`):

```json
{
  "EXTRACTION_DATA_DIR": "./pdf_output",
  "OUTPUT_DATA_DIR": "./output",
  "LOG_DIR": "./logs"
}
```

Notes:

- Input layout: `{EXTRACTION_DATA_DIR}/{work_name}/content.md`
- If `{OUTPUT_DATA_DIR}/{work_name}/final_output.json` already exists and validates, that paper is **skipped**

## PDF → Markdown (MinerU)

MinerU must run in a **separate** conda environment:

```bash
conda create -n mineru python=3.11
conda activate mineru
pip install -U "mineru[core]==2.6.4"
```

Convert PDFs with:

```bash
python ./src/organoid_info_extract/mineru/pdf_loader.py --input_dir ./pdf_dir/ --output_dir ./pdf_output
```

## CrewAI patch (required)

This project ships custom patches under `venv_patch/` that must be copied into `.venv` after install. Stock crewAI 0.203.x is not sufficient as-is.

Patches cover (among others):

| Path under `venv_patch/.../crewai/` | Purpose |
|-------------------------------------|---------|
| `utilities/converter.py` | BaseModel → prompt conversion (e.g. missing field descriptions) |
| `agents/parser.py` | `AgentAction` dataclass field order; multi-action parse |
| `agents/crew_agent_executor.py` | Multi-action list execution; request spacing |
| `utilities/agent_utils.py` | Helpers aligned with multi-action / max-iteration handling |
| `agents/constants.py` | Multi-action regex |
| `llm.py` | LLM-related fixes |

**Re-apply the patch after every `uv sync`, reinstall, or dependency refresh.** Without it you may hit errors such as:

- `TypeError: non-default argument 'text' follows default argument`
- `'list' object has no attribute 'text'`
- Broken converter / structured output behavior

### PowerShell / Windows

```powershell
robocopy ".\venv_patch\" ".\.venv\" "*.py" /S /R:1 /W:1
```

### Bash / Linux

```bash
cp -rf venv_patch/. .venv/
```

## MCP search service

Search (and related tool) stages connect to MCP servers listed in:

`src/organoid_info_extract/config/tools.json`

Default:

```json
[
  {
    "url": "http://localhost:12400/mcp",
    "transport": "streamable-http"
  }
]
```

1. Configure and start [`../literature-mcp/`](../literature-mcp/) (default expects port `12400`).
2. Change the URL/transport in `tools.json` if your service differs.

If MCP is down, search-related steps will fail.

## Running the project

### Checklist

1. `uv sync --frozen`
2. Configure `.env`
3. Apply `venv_patch` (see above)
4. Prepare `run.json` (or another config JSON) and input data (`*/content.md`)
5. Start the MCP search service
6. Run the crew from the **project root**

### PowerShell / Windows

```powershell
$Env:PAPER_CONFIG_DIR = 'run.json' ; crewai run
```

Or with the project venv explicitly:

```powershell
$Env:PAPER_CONFIG_DIR = 'run.json' ; .\.venv\Scripts\crewai.exe run
```

### Bash / Linux

```bash
export PAPER_CONFIG_DIR='run.json' && crewai run
```

## Customizing

- `src/organoid_info_extract/config/agents.yaml` — agent roles and protocols
- `src/organoid_info_extract/config/tasks.yaml` — task I/O and instructions
- `src/organoid_info_extract/config/tools.json` — MCP search servers
- `src/organoid_info_extract/process/*.py` — stage logic and LLM wiring
- `src/organoid_info_extract/main.py` — flow orchestration and batch runner
