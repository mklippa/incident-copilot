# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This repository currently contains only `incident-copilot-project-spec.md` — no code has been written yet. There is no build system, package manifest, test suite, or `.claude/` config to reference. **Read `incident-copilot-project-spec.md` in full before doing any work here** — it is the design doc and the source of truth for architecture, scope, and build order, not background reading to skim.

Do not invent commands, file layouts, or conventions not present in the spec or in code you've actually written in this session. When the spec is ambiguous or silent on an implementation detail, ask rather than assume.

## What this project is

Incident Copilot is a demo/practice project built to exercise all 30 task statements across the 5 domains of a Claude Certified Architect curriculum (agentic orchestration, tool/MCP design, Claude Code configuration, prompt engineering/structured output, context management/reliability). It simulates a SaaS support/incident queue: tickets come in, a Coordinator agent triages and delegates to specialist subagents that investigate via a custom MCP server, and the system either auto-resolves (logged/audited) or escalates via a structured handoff.

Everything is synthetic — SQLite for customers/tickets/resolutions, markdown files for a runbook knowledge base (including two deliberately contradictory articles, used to exercise provenance handling), and JSON/text log snippets. There are no real external integrations.

## Suggested stack (per spec, not yet implemented)

- **Language:** Python throughout — Anthropic SDK + Claude Agent SDK for agents, the `mcp` Python SDK for the custom MCP server.
- **Storage:** SQLite (`tickets`, `customers`, `resolutions`) + `runbooks/` (markdown KB) + `logs/` (synthetic log snippets).
- **Dev environment:** a real `.claude/` config (agents, skills, hooks, path-specific rules) is graded material for this project, not incidental scaffolding — build it deliberately, not minimally.
- **CI:** GitHub Actions running `claude -p` headlessly as a PR check.

## Architecture (target, per spec)

Coordinator agent (hand-rolled agentic loop against the Messages API — inspect `stop_reason`, append tool results, terminate on `end_turn` only, iteration cap as a safety net not a stopping condition) classifies and delegates to specialist subagents (Log Analyzer, KB Searcher, Customer History Lookup) via the Agent SDK, using hub-and-spoke as the default orchestration pattern with parallel fan-out (independent specialists) and sequential pipelines (classify → investigate → draft-resolution) where they actually fit. Specialists are capped at 4-5 tools each and receive ticket context explicitly through the task payload — no shared conversation history with the Coordinator.

All specialists talk to one custom MCP server (stdio) exposing the ticket DB, KB, and logs. The Coordinator then either auto-resolves (non-destructive, confidence above threshold) or produces a structured escalation (`Customer ID / Summary / Root cause / Recommended action`) — the same schema enforced everywhere, never a silent failure. `PreToolUse` hooks block destructive actions (e.g., large refunds, record deletion) regardless of model decision; `PostToolUse` hooks write an append-only audit log.

Nightly/offline: a Batch API job re-classifies the day's resolved tickets for trend reporting (not user-facing), and a QA Reviewer agent — a fresh session, never the one that resolved the ticket — audits a sample with stratified-by-category accuracy tracking.

See the "Skill map" table in the spec for exactly which task statement each piece of this architecture is meant to exercise, and the "Suggested build order" section for the intended build sequence (foundations → tools/MCP → orchestration → safety rails → reliability layer → ops layer).

## Working conventions for this repo

- Prefer building in the spec's suggested order rather than jumping ahead to later-stage pieces (e.g., don't build the QA Reviewer before the Coordinator and MCP server exist).
- Structured schemas mentioned in the spec (escalation payload, tool error shape `{errorCategory, isRetryable, retryAfterMs, partialResult, suggestion}`, provenance `{claim, source, url, date}`) should be defined once and reused everywhere they're mentioned — don't let each component invent its own variant.
- The two intentionally-contradictory runbook articles are a deliberate test fixture for provenance/synthesis handling (task 5.6) — don't "fix" the contradiction when you find it.
