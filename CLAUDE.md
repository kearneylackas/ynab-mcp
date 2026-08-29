# ynab-mcp

A Claude plugin: a local stdio MCP server for YNAB, talking directly to
YNAB's REST API (`api.ynab.com/v1`) — no third-party MCP wrapper. See
[README.md](README.md) for install/usage instructions aimed at humans.

## Layout

This repo is both the plugin source and the Python package it launches:

- `.claude-plugin/plugin.json` — plugin manifest (name, version, description).
- `.claude-plugin/marketplace.json` — lets this repo self-host as its own
  single-plugin marketplace (`source: "./"`). Claude Code has no
  install-a-bare-plugin path — every install goes through a marketplace,
  even a self-referencing one — so this file is required, not optional:
  `/plugin marketplace add <this-repo>` then `/plugin install ynab@ynab-mcp`.
- `.mcp.json` — MCP server definition. Uses `${CLAUDE_PLUGIN_ROOT}` for the
  server directory (never a hardcoded path) and `${YNAB_ACCESS_TOKEN}` /
  `${YNAB_DEFAULT_BUDGET_ID}` for credentials, pulled from the host
  machine's environment at connect time — nothing sensitive is baked in.
- `src/ynab_mcp/server.py` — the whole server: `YnabClient` (thin async
  HTTP wrapper over `httpx`) plus one `@mcp.tool()` function per tool,
  registered via `fastmcp`. This is the only file that matters for
  behavior changes.
- `src/ynab_mcp/__init__.py` — re-exports `main` for the
  `ynab-mcp` console script.
- `pyproject.toml` — package metadata. `packages = ["src/ynab_mcp"]` and
  the entry point `ynab_mcp.server:main` depend on this exact `src/`
  layout; don't move the source back to repo root or the build breaks.

Bump `.claude-plugin/plugin.json`'s `version` when shipping a change meant
for distribution (e.g. rebuilding a `.plugin` zip) — nothing does this
automatically.

## Conventions specific to this server

- **Dollars at the edges, milliunits nowhere else.** Every tool takes/
  returns plain dollar floats (`12.34`); conversion to/from YNAB's
  milliunits happens only in `_to_milliunits` / `_from_milliunits`. Don't
  let a raw milliunit value leak into a tool's public signature or return
  value.
- **`budget_id` defaults to `YNAB_DEFAULT_BUDGET_ID` env var (or YNAB's
  `"last-used"`)** on every tool, set once via closure over `default_budget`
  in `create_server()` — not re-read per call.
- **`delete_transaction` is intentionally commented out**, not missing.
  Don't silently re-add it; if asked to restore it, treat it as a
  deliberate, security-relevant decision to confirm first (it's a
  permanent, no-undo financial data delete).
- Logging goes to `stderr` only (`logging.basicConfig(..., stream=sys.stderr)`)
  — stdout is the MCP protocol channel under stdio transport. Never
  `print()` or log to stdout.
- Dependencies in `pyproject.toml` are deliberately pinned
  (`fastmcp==2.5.1`, `pydantic==2.11.5`, `mcp==1.9.1`) — see the comment
  there. Don't casually bump these without checking tool registration
  still works.

## Testing a change

No test suite exists yet. To verify a change by hand:

```bash
uv run ynab-mcp
```

This needs `YNAB_ACCESS_TOKEN` set in the environment (real token — there's
no sandbox/mock YNAB API), and will sit waiting for stdio input; drive it
via an actual MCP client (e.g. point a local Claude Code/Desktop config at
this directory) rather than typing into it directly.

## Known gaps / open items

- No automated tests.
- No CI.
- `update_transaction`'s support for converting a transaction to a split
  via `subtransactions` is implemented but explicitly noted in its own
  docstring as unverified against YNAB's actual API behavior.
