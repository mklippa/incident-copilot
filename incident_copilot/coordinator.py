"""Coordinator: hand-rolled agentic loop that classifies a ticket, decides
which specialists to send it to, dispatches them, and drafts a resolution.

Extends the same hand-rolled discipline as classify_loop.py (task 1.1) to a
multi-phase loop: inspect stop_reason, append tool results before the next
call, terminate only on end_turn, iteration cap as a safety net (not the
stopping condition - if it fires, that's a bug to investigate).

Demonstrates all three orchestration patterns from task 1.2 in one flow:
- Hub-and-spoke: the Coordinator decides which specialists run and dispatches
  them (specialists never talk to each other or decide this themselves).
- Parallel fan-out: selected specialists are mutually independent, so they
  run concurrently via asyncio.gather.
- Sequential pipeline: classify -> investigate -> draft-resolution.

Task decomposition (1.6): known ticket categories use a fixed, hardcoded
specialist list (no model call needed to decide). Categories that don't
match ("other", or a null/unrecognized category) fall through to a dynamic,
model-decided selection via the select_specialists tool.

Note on scope: draft_resolution below is a deliberately lightweight decision
schema (summary/root_cause/auto_resolve/confidence/reasoning) - it is NOT
the formal escalation payload from task 1.4 (Customer ID/Summary/Root
cause/Recommended action), which is built and enforced in the Safety rails
step alongside the PreToolUse/PostToolUse hooks. This step only needs the
Coordinator's loop to reach a terminal decision.

Usage: uv run python -m incident_copilot.coordinator
Requires ANTHROPIC_API_KEY in the environment (or a .env file).
"""

import asyncio
import json
import os

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from incident_copilot.classify_loop import (
    CLASSIFY_TICKET_TOOL,
    SYSTEM_PROMPT as CLASSIFY_SYSTEM_PROMPT,
    build_ticket_prompt,
    tool_result_message,
)
from incident_copilot.db import connect
from incident_copilot.paths import DATA_DIR
from incident_copilot.run_logging import configure_run_logging
from incident_copilot.specialists import run_specialist

load_dotenv()
log = configure_run_logging("coordinator")

MODEL = os.environ.get("MODEL") or "claude-haiku-4-5-20251001"
MAX_ITERATIONS = 5

RESULTS_PATH = DATA_DIR / "investigation_results.jsonl"

# Task 1.6: fixed decomposition for known categories. Anything else (e.g.
# "other", or a null/unrecognized category) falls through to the dynamic,
# model-decided path via SELECT_SPECIALISTS_TOOL.
FIXED_SPECIALIST_MAP: dict[str, list[str]] = {
    "billing": ["customer_history", "kb_searcher"],
    "production_incident": ["log_analyzer", "customer_history"],
    "performance": ["log_analyzer"],
    "bug_report": ["log_analyzer", "kb_searcher"],
    "account": ["customer_history", "kb_searcher"],
}

SELECT_SPECIALISTS_TOOL = {
    "name": "select_specialists",
    "description": (
        "Decide which specialist(s) should investigate this ticket. Only "
        "called when the ticket's category doesn't map to a fixed "
        "investigation plan - use your judgment about which specialists "
        "are relevant given the ticket text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "specialists": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["log_analyzer", "kb_searcher", "customer_history"],
                },
                "minItems": 1,
                "description": "One or more specialists to dispatch, in no particular order (they run in parallel).",
            },
            "reasoning": {
                "type": "string",
                "description": "1-2 sentences on why these specialists (and not the others) are relevant.",
            },
        },
        "required": ["specialists", "reasoning"],
    },
}

DRAFT_RESOLUTION_TOOL = {
    "name": "draft_resolution",
    "description": (
        "Record a draft resolution after reviewing the specialist findings. "
        "This is a preliminary decision, not a final auto-resolve action - "
        "no destructive or financial action is taken by calling this tool."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "1-3 sentences summarizing what was found and what should happen next.",
            },
            "root_cause": {
                "type": ["string", "null"],
                "description": "Best-guess root cause, or null if the specialist findings don't support one.",
            },
            "auto_resolve": {
                "type": "boolean",
                "description": (
                    "True only if findings are conclusive, confidence is high, and no "
                    "destructive/financial action is implied. False otherwise (needs "
                    "human review) - when in doubt, false."
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Confidence in this draft resolution given the specialist findings.",
            },
            "reasoning": {
                "type": "string",
                "description": "1-3 sentences of reasoning behind auto_resolve and confidence.",
            },
        },
        "required": ["summary", "root_cause", "auto_resolve", "confidence", "reasoning"],
    },
}

COORDINATOR_SYSTEM_PROMPT = (
    CLASSIFY_SYSTEM_PROMPT
    + """

## Orchestration rules

After classifying, you will sometimes (not always) be asked to call
select_specialists to choose which specialists should investigate - this
only happens when the ticket's category doesn't have a fixed investigation
plan. When asked, pick every specialist genuinely relevant; it's fine to
pick more than one, they run in parallel.

After specialists run, their findings will be injected as a user message
titled "## Specialist Findings". Base your draft_resolution strictly on
those findings plus the original ticket - do not invent facts the
specialists didn't report.

Call each tool exactly once, only when the system asks for it. After
draft_resolution, respond with one brief closing sentence and stop - do not
call any tool again.
"""
)


async def investigate_ticket(ticket: dict, client: AsyncAnthropic) -> dict:
    messages = [{"role": "user", "content": build_ticket_prompt(ticket)}]

    classification: dict | None = None
    decomposition_mode: str | None = None
    specialists_to_run: list[str] = []
    specialists_used: list[str] = []
    draft: dict | None = None

    phase = "classify"

    for iteration in range(MAX_ITERATIONS):
        if phase == "classify":
            tools = [CLASSIFY_TICKET_TOOL]
            tool_choice = {"type": "tool", "name": "classify_ticket"}
        elif phase == "select_specialists":
            tools = [SELECT_SPECIALISTS_TOOL]
            tool_choice = {"type": "tool", "name": "select_specialists"}
        elif phase == "draft_resolution":
            tools = [DRAFT_RESOLUTION_TOOL]
            tool_choice = {"type": "tool", "name": "draft_resolution"}
        else:  # "closing" - no tools at all, guarantees a plain end_turn
            tools = []
            tool_choice = {"type": "auto"}

        response = await client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=COORDINATOR_SYSTEM_PROMPT,
            tools=tools,
            tool_choice=tool_choice,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            tool_block = next(b for b in response.content if b.type == "tool_use")
            result = tool_block.input

            if tool_block.name == "classify_ticket":
                classification = result
                messages.append(
                    tool_result_message(
                        tool_block.id,
                        f"Recorded: category={result.get('category')}, severity={result.get('severity')}.",
                    )
                )
                category = result.get("category")
                if category in FIXED_SPECIALIST_MAP:
                    decomposition_mode = "fixed"
                    specialists_to_run = FIXED_SPECIALIST_MAP[category]
                    log.info(
                        "ticket %s: fixed decomposition for category=%s -> %s",
                        ticket["ticket_id"],
                        category,
                        specialists_to_run,
                    )
                    phase = "dispatch"
                else:
                    decomposition_mode = "dynamic"
                    phase = "select_specialists"

            elif tool_block.name == "select_specialists":
                specialists_to_run = result.get("specialists", [])
                log.info(
                    "ticket %s: dynamic decomposition -> %s (%s)",
                    ticket["ticket_id"],
                    specialists_to_run,
                    result.get("reasoning"),
                )
                messages.append(
                    tool_result_message(tool_block.id, f"Selected specialists: {specialists_to_run}.")
                )
                phase = "dispatch"

            elif tool_block.name == "draft_resolution":
                draft = result
                messages.append(tool_result_message(tool_block.id, "Draft resolution recorded."))
                phase = "closing"

            if phase == "dispatch":
                log.info(
                    "ticket %s: dispatching %d specialist(s) in parallel: %s",
                    ticket["ticket_id"],
                    len(specialists_to_run),
                    specialists_to_run,
                )
                findings = await asyncio.gather(
                    *(run_specialist(name, ticket) for name in specialists_to_run)
                )
                specialists_used = list(specialists_to_run)
                findings_block = "\n\n".join(
                    f"### {name} findings\n{text}" for name, text in zip(specialists_to_run, findings)
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"## Specialist Findings\n\n{findings_block}\n\n"
                            "Call draft_resolution now based on these findings."
                        ),
                    }
                )
                phase = "draft_resolution"

            continue

        if response.stop_reason == "end_turn":
            if draft is None:
                log.warning(
                    "ticket %s: reached end_turn with no draft_resolution - unexpected",
                    ticket["ticket_id"],
                )
            return {
                "classification": classification,
                "decomposition_mode": decomposition_mode,
                "specialists_used": specialists_used,
                "draft": draft,
            }

        log.warning(
            "ticket %s: unexpected stop_reason=%s on iteration %d (phase=%s)",
            ticket["ticket_id"],
            response.stop_reason,
            iteration,
            phase,
        )

    log.error(
        "ticket %s: hit iteration cap (%d) without end_turn - 1.1 loop violation, investigate",
        ticket["ticket_id"],
        MAX_ITERATIONS,
    )
    return {
        "classification": classification,
        "decomposition_mode": decomposition_mode,
        "specialists_used": specialists_used,
        "draft": draft,
    }


async def main() -> None:
    client = AsyncAnthropic()
    conn = connect()
    tickets = [dict(row) for row in conn.execute("SELECT * FROM tickets ORDER BY ticket_id")]
    conn.close()

    # One representative ticket per seed category, to exercise every fixed
    # decomposition path plus the dynamic ("other") path at least once,
    # without running the full dataset through real specialist subprocesses.
    seen_categories: set[str] = set()
    demo_tickets = []
    for ticket in tickets:
        if ticket["seed_category"] not in seen_categories:
            seen_categories.add(ticket["seed_category"])
            demo_tickets.append(ticket)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as out:
        for ticket in demo_tickets:
            result = await investigate_ticket(ticket, client)
            draft = result["draft"] or {}
            print(
                f"{ticket['ticket_id']} [{ticket['seed_category']}]: "
                f"classified={result['classification'] and result['classification'].get('category')} "
                f"decomposition={result['decomposition_mode']} "
                f"specialists={result['specialists_used']} "
                f"auto_resolve={draft.get('auto_resolve')} "
                f"confidence={draft.get('confidence')}"
            )
            out.write(
                json.dumps({"ticket_id": ticket["ticket_id"], "seed_category": ticket["seed_category"], **result})
                + "\n"
            )


if __name__ == "__main__":
    asyncio.run(main())
