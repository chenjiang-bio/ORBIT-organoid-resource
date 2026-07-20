# ORBIT Organoid Resource

Code and reproducible workflows for **ORBIT**, an organoid knowledge and analysis resource. This repository is organized as a set of independent tools and pipelines. Each top-level subdirectory is a self-contained module that collaborators can develop and release on its own schedule.

The default branch is `main`.

## Repository layout

| Directory | Description |
|-----------|-------------|
| [`omics-pipeline/`](omics-pipeline/) | Multi-omics analysis pipeline for organoid transcriptomic and related datasets |
| [`literature-agent/`](literature-agent/) | Multi-agent system for structured extraction from organoid literature |
| [`knowledge-graph/`](knowledge-graph/) | Knowledge-graph construction, schema, and query utilities |
| [`literature-mcp/`](literature-mcp/) | MCP (Model Context Protocol) services used by the literature extraction agent |

## Getting started

1. Clone this repository:

   ```bash
   git clone https://github.com/chenjiang-bio/ORBIT-organoid-resource.git
   cd ORBIT-organoid-resource
   ```

2. Open the subdirectory for the module you need and follow its `README.md` for install and usage instructions.

## Collaboration notes

- Keep module code, configs, and docs **inside the corresponding subdirectory**.
- Prefer English for all public documentation, comments intended for external readers, and commit messages in this repository.
- Do not commit secrets (API keys, credentials, `.env` files with private tokens).
- Large raw data and model weights should stay out of git; document download or access steps in the module README instead.

## License

This project is released under the [MIT License](LICENSE).
