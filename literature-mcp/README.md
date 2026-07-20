# Literature MCP Services

MCP (Model Context Protocol) services that support the ORBIT literature extraction agent.

## Scope

This module will host the MCP servers and tools used by [`../literature-agent/`](../literature-agent/) for external lookups and tool calling during literature curation (for example DOI, catalog, or database validation tools).

## Status

Scaffold only. Implementation will be contributed by collaborators.

## Relationship to the literature agent

1. Start the MCP services defined in this directory.
2. Point the literature agent configuration at the local MCP endpoint(s).
3. Run the literature agent workflow.

## Planned contents

- MCP server implementations
- Tool definitions and configuration
- Local run / deployment notes
- Module-specific documentation

## Usage

Instructions will be added when the MCP service code is committed to this directory.
