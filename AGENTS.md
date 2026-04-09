# AGENTS.md

Repo-specific guidance for coding agents working in this project.

## Scope

- `README.md` is the canonical human-facing document for setup, usage, debugging, and testing.
- `AGENTS.md` is only for architecture rules, editing constraints, and current repo facts that agents should not get wrong.

## Current Repo Facts

- Canonical project name: `Medical Wizard MCP`
- Python package: `Medical_Wizard_MCP`
- Source root: `src/Medical_Wizard_MCP/`
- Local runner: `./local-dev/run-server.sh`
- Local MCP endpoint: `http://127.0.0.1:8000/mcp`
- Preferred local debug loop:
  - `FASTMCP_LOG_LEVEL=DEBUG ./local-dev/run-server.sh`
  - `npx -y @modelcontextprotocol/inspector`
- Shared `FastMCP` instance lives in `src/Medical_Wizard_MCP/app.py`
- Audit/request-context middleware lives in `src/Medical_Wizard_MCP/server.py`
- Host, port, and transport are provided by the runtime environment and `mcp.run(...)`, not stored as constants in `server.py`

## Architecture Intent

- This project is LLM-first.
- MCP tools should expose atomic, well-filtered data.
- The LLM is responsible for orchestration, analysis, comparison, and synthesis.
- Do not move analytics or interpretation logic into the MCP server layer.

## Request Flow

`User question -> MCP tool -> SourceRegistry -> source adapters -> normalized Pydantic models -> LLM synthesis`

## Layer Boundaries

- `src/Medical_Wizard_MCP/sources/`
  Raw HTTP requests, parsing, normalization, source-specific quirks
- `src/Medical_Wizard_MCP/sources/registry.py`
  Source initialization, fan-out, merge behavior
- `src/Medical_Wizard_MCP/tools/`
  Thin MCP wrappers around registry calls
- `src/Medical_Wizard_MCP/models/`
  Shared normalized response models
- `src/Medical_Wizard_MCP/app.py`
  Shared `FastMCP` instance
- `src/Medical_Wizard_MCP/server.py`
  FastMCP middleware and server-side request context helpers

## Implementation Patterns

- `BaseSource` defines the shared source interface.
- Source capability methods intentionally default to `[]` or `None`; a source only overrides what it supports.
- New sources should normally be added by implementing `BaseSource` and registering them in `__main__.py`.
- Tool modules register via `@mcp.tool()` using the shared `mcp` from `app.py`.
- Tool registration happens at import time through `src/Medical_Wizard_MCP/tools/__init__.py`.

## Editing Guidance

- Keep tools thin and composable.
- Keep source-specific parsing out of tools.
- Reuse the registry instead of having tools talk to sources directly.
- Treat the code in `src/Medical_Wizard_MCP/tools/` as the source of truth for which MCP tools are actually implemented.
- If setup or debugging commands change, update `README.md`, not `AGENTS.md`, unless the change affects an agent-specific invariant.
