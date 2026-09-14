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

## Installing

This repo doubles as a self-hosting Claude plugin marketplace
(`.claude-plugin/marketplace.json`) and as a plain Python package. Which
install path applies depends on which Claude surface you're using — they
don't all support the plugin system the same way.

### Claude Code

1. Add this repo as a marketplace, then install the plugin from it:
   ```
   /plugin marketplace add /path/to/ynab-mcp
   /plugin install ynab@ynab-mcp
   ```
   (`/plugin install` always resolves through a marketplace, hence the
   self-referencing one above. To try the plugin without installing it,
   `claude --plugin-dir /path/to/ynab-mcp` loads it for a single session.)
2. `uv` needs to be installed on the machine running Claude — `.mcp.json`
   uses `uv --directory ${CLAUDE_PLUGIN_ROOT} run ynab-mcp`, so `uv`
   resolves and runs the package on first use with no separate install
   step. `${CLAUDE_PLUGIN_ROOT}` is filled in automatically wherever the
   plugin ends up installed — no path to edit.
3. Set the environment variables below.

### Claude Cowork

Cowork shares Claude Code's plugin infrastructure, just through a GUI
instead of `/plugin`:

1. **Customize → Plugins → Add marketplace**, pointing at this repo on
   GitHub (`kearneylackas/ynab-mcp`).
2. Install the `ynab` plugin from that marketplace on the same screen.
3. Set the environment variables below on the machine running Cowork.
   `${CLAUDE_PLUGIN_ROOT}` support isn't explicitly documented for Cowork,
   but it shares Code's plugin loader so it's expected to resolve the same
   way — if the server fails to connect, that's the first thing to check.

### Claude Desktop

Desktop does **not** support the plugin/marketplace system at all — no
`.claude-plugin/`, no `/plugin` commands. It only reads a flat MCP server
list, and it does not reliably expand `${CLAUDE_PLUGIN_ROOT}` or
`${YNAB_ACCESS_TOKEN}`-style variables — those have to be literal values
here, unlike Code/Cowork.

1. Open `%APPDATA%\Claude\claude_desktop_config.json` (or Settings →
   Developer → Edit Config in the app).
2. Add:
   ```json
   {
     "mcpServers": {
       "ynab": {
         "command": "uv",
         "args": ["--directory", "C:\\path\\to\\ynab-mcp", "run", "ynab-mcp"],
         "env": {
           "YNAB_ACCESS_TOKEN": "your_actual_token_here",
           "YNAB_DEFAULT_BUDGET_ID": "your_actual_budget_id_here"
         }
       }
     }
   }
   ```
   Note the literal values, not `${...}` references — Desktop doesn't pull
   those from the system environment the way the plugin loader does.
3. Restart Desktop.

### Environment variables (Claude Code / Cowork)

`.mcp.json` reads these from the host machine's environment at connect
time via `${YNAB_ACCESS_TOKEN}` / `${YNAB_DEFAULT_BUDGET_ID}` — nothing
sensitive is baked into the plugin itself:

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
Restart Claude/your terminal after running these — `setx` doesn't affect
already-open processes.

### If you cloned this repo and see a `ynab` connection error

Opening this repository itself as a project in Claude Code will report the
`ynab` MCP server failing to connect, whether or not you installed the
plugin. That's expected. `.mcp.json` sits at the repo root, so Claude Code
also reads it as a *project*-scoped server and tries to launch it outside
the plugin loader — where `${CLAUDE_PLUGIN_ROOT}` is undefined and (unless
you've set it) there's no `YNAB_ACCESS_TOKEN` either, so the server exits
immediately. It says nothing about whether the installed plugin works. Set
the environment variables above if you want it to connect while you work on
the repo.

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

(For a manual, non-plugin MCP client config, see the Claude Desktop section
above — same shape applies to any client that reads a flat `mcpServers`
list.)

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
