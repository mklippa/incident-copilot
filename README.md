# Incident Copilot

A demo/practice project simulating a SaaS support/incident queue, built to exercise the full Claude Certified Architect curriculum. See [`incident-copilot-project-spec.md`](./incident-copilot-project-spec.md) for the full design doc and [`CLAUDE.md`](./CLAUDE.md) for repo conventions.

Everything is synthetic: SQLite for customers/tickets/resolutions, markdown files for a runbook knowledge base (including two deliberately contradictory articles), and text files for log snippets. No real external integrations.

## Setup

```bash
uv sync
```

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.

## Generate synthetic data

```bash
uv run python -m incident_copilot.generate_data
```

Deterministic and idempotent — populates `data/incident_copilot.db` (customers, tickets, resolutions) and (re)writes `runbooks/*.md` and `logs/*.log`. Safe to rerun any time.

## Run the classify-ticket loop

```bash
uv run python -m incident_copilot.classify_loop
```

A hand-rolled agentic loop (not the Agent SDK) that classifies every ticket in the DB via a forced tool call against the live Anthropic Messages API. Results are printed and appended to `data/classification_results.jsonl`.

## MCP server

`mcp-server/server.py` is a custom MCP server (stdio transport) exposing the ticket DB, runbook KB, and logs as four tools. It's wired into this project via `.mcp.json`.

- `search_knowledge_base` — keyword search across runbook KB articles
- `get_customer_history` — customer profile plus their ticket and resolution history
- `get_recent_logs` — filter synthetic log lines by keyword and/or level
- `create_refund` — issue a refund and record it as a resolution against a ticket

It also exposes each runbook article as an individually readable MCP resource (`runbook://<filename>`), complementing `search_knowledge_base`: list resources to see every article's title and URI, then read one directly to get its full markdown body.

Run the smoke test to exercise all four tools end-to-end, including the deliberate edge cases (empty KB search result vs. simulated DB outage, the two contradictory refund-policy articles surfacing together):

```bash
uv run python mcp-server/smoke_test.py
```

For interactive, by-hand testing, use the official [MCP Inspector](https://github.com/modelcontextprotocol/inspector) instead — it launches a local web UI to call each tool through a form and inspect raw request/response JSON:

```bash
npx @modelcontextprotocol/inspector uv run python mcp-server/server.py
```

### Why a custom server, and why also a community one

`.mcp.json` also wires in the official `@modelcontextprotocol/server-filesystem`, scoped to `runbooks/` and `logs/`, purely as a comparison exercise. We didn't build our own "list/read files in a directory" tool because that's exactly what the filesystem server already does safely (scoped path access, traversal protection) — there's no reason to reimplement it.

What *did* need a custom server is the domain logic layered on top of raw file/DB access: `search_knowledge_base` and `get_recent_logs` do keyword filtering and structured parsing specific to this project's KB/log formats, `get_customer_history` performs SQL joins across the ticket DB, and `create_refund` performs a validated, audited write. None of that exists in a generic filesystem server — that's the part worth building ourselves.
