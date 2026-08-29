# ynab-mcp

A Claude plugin that connects Claude to a self-built local MCP server for
YNAB, built directly against YNAB's REST API (`api.ynab.com/v1`) — no
third-party MCP project, no SDK dependency beyond `fastmcp` and `httpx`.
The server runs over stdio: your MCP client (Claude Desktop, Claude Code,
Cowork) launches it directly as a local process. No server to host, no
Docker, no networking.

This repo is both things at once: the plugin manifest (`.claude-plugin/`,
`.mcp.json`) and the Python package source (`src/ynab_mcp/`) that manifest
launches.

## Installing as a Claude plugin (recommended)

1. Point Claude at this repo as a plugin source (e.g. via a marketplace
   entry, or a local path during development).
2. `uv` needs to be installed on the machine running Claude — `.mcp.json`
   uses `uv --directory ${CLAUDE_PLUGIN_ROOT} run ynab-mcp`, so `uv`
   resolves and runs the package on first use with no separate install
   step. `${CLAUDE_PLUGIN_ROOT}` is filled in automatically wherever the
   plugin ends up installed — no path to edit.
3. Set two **system environment variables** on that machine (not in the
   plugin — `.mcp.json` reads them via `${YNAB_ACCESS_TOKEN}` /
   `${YNAB_DEFAULT_BUDGET_ID}` at connect time):
   - `YNAB_ACCESS_TOKEN` — from https://app.ynab.com/settings/developer
   - `YNAB_DEFAULT_BUDGET_ID` — optional, pins a specific budget (ask
     Claude to run `list_budgets` to get the id). Without it, tools
     default to YNAB's "last-used" budget, which can silently point at a
     different budget if another one was opened more recently in the app.

   On Windows (Command Prompt, one-time):
   ```
   setx YNAB_ACCESS_TOKEN "your_token_here"
   setx YNAB_DEFAULT_BUDGET_ID "your_budget_id_here"
   ```
   Restart Claude/your terminal after running these — `setx` doesn't
   affect already-open processes.

No credentials are stored in the plugin itself — the `${...}` syntax pulls
from your own machine's environment at connect time, not from any value
baked into `.mcp.json`.

## Running/installing the server standalone (for development or testing)

```bash
# From this directory
uv run ynab-mcp

# From anywhere
uv --directory /path/to/ynab-mcp run ynab-mcp
```

It'll sit waiting for stdio input — that's normal, it's meant to be driven
by an MCP client, not run interactively. Ctrl+C to stop.

To install the package directly instead:

```bash
cd ynab-mcp
uv sync
# or: pip install -e .
```

Then a manual (non-plugin) MCP client config would look like:

```json
{
  "mcpServers": {
    "ynab": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\ynab-mcp", "run", "ynab-mcp"],
      "env": {
        "YNAB_ACCESS_TOKEN": "your_token_here",
        "YNAB_DEFAULT_BUDGET_ID": "your_budget_id_here"
      }
    }
  }
}
```

## Tools

10 tools, read and write:

- `list_budgets`, `list_accounts`, `list_categories`, `get_month`
- `get_unapproved_transactions`, `list_transactions`
- `create_transaction` (supports splits via `subtransactions`, and
  `import_id` for safe retries)
- `approve_transaction`
- `update_transaction` (can also convert an existing transaction into a
  split via `subtransactions`)
- `assign_to_category`

`delete_transaction` is intentionally disabled (commented out in
`src/ynab_mcp/server.py`).

All amounts are plain dollars in and out (e.g. `12.34`), converted to
YNAB's internal milliunits automatically.

**Heads up:** this server has real write access to your budget —
`create_transaction`, `approve_transaction`, `update_transaction`, and
`assign_to_category` all make real changes. Treat any tool call that
touches a transaction or category budget the same as you would a real
financial edit, because it is one.
