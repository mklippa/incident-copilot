"""Hand-rolled agentic loop for ticket classification (task 1.1).

Deliberately built directly against the Messages API rather than the Agent
SDK: inspects stop_reason explicitly, appends tool results before the next
call, and terminates only on end_turn. The iteration cap is a safety net,
not the stopping condition - if it fires, that's a bug to investigate, not
normal operation.

Usage: uv run python -m incident_copilot.classify_loop
Requires ANTHROPIC_API_KEY in the environment (or a .env file).
"""

import json
import logging
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from incident_copilot.db import connect

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("classify_loop")

MODEL = os.environ.get("MODEL") or "claude-haiku-4-5-20251001"
MAX_ITERATIONS = 3

RESULTS_PATH = Path(__file__).resolve().parent.parent / "data" / "classification_results.jsonl"

CLASSIFY_TICKET_TOOL = {
    "name": "classify_ticket",
    "description": (
        "Record the classification of a support ticket: its category, severity, "
        "and confidence. Call this once you have read the ticket subject and body."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": ["string", "null"],
                "enum": [
                    "billing",
                    "bug_report",
                    "production_incident",
                    "performance",
                    "account",
                    "other",
                    None,
                ],
                "description": "Best-fit category. Use null only if genuinely undeterminable from the ticket text.",
            },
            "severity": {
                "type": ["string", "null"],
                "enum": ["P1", "P2", "P3", None],
                "description": (
                    "P1 = production down / critical / affects many customers. "
                    "P2 = degraded but functioning / significant impact to one customer. "
                    "P3 = minor, cosmetic, or a question. Use null if undeterminable."
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Your confidence in this classification.",
            },
            "reasoning": {
                "type": "string",
                "description": "1-3 sentences of reasoning behind the classification.",
            },
            "needs_human_review": {
                "type": "boolean",
                "description": "True if this ticket is ambiguous, high-stakes, or confidence is not high.",
            },
        },
        "required": ["category", "severity", "confidence", "reasoning", "needs_human_review"],
    },
}

SYSTEM_PROMPT = """\
You are the triage classifier for Incident Copilot, a support/incident queue \
for a SaaS product. Your only job right now is to classify one ticket at a \
time by calling the classify_ticket tool.

## Categories
- billing: payments, invoices, refunds, plan charges
- bug_report: something in the product behaves incorrectly
- production_incident: a service outage, widespread errors, or a security- \
or data-integrity-adjacent failure affecting more than one customer
- performance: the product is slow or laggy but still functioning
- account: login, password, 2FA, ownership/access management
- other: feature requests, general feedback, anything that doesn't fit above

## Severity
- P1: production down, authentication broken for anyone, cross-customer data \
leakage, or any issue affecting many customers at once. Escalate-worthy.
- P2: a real problem affecting the reporting customer's ability to work, but \
not a full outage and not affecting many other customers.
- P3: minor, cosmetic, a question, or a feature request. Nothing is broken.

## Calibration: P1 vs P3
- "Our whole team gets a 500 error on every page starting 10 minutes ago" -> \
P1. Full outage, multiple users, ongoing right now.
- "How do I change the email my invoices go to" -> P3. Nothing is broken; \
it's a how-do-I question.
- "My CSV export today included rows with names and emails I don't \
recognize" -> P1 even though only one customer reported it, because \
cross-customer data leakage is a data-integrity/security issue, not a \
routine bug.

## Rules
- Call classify_ticket exactly once with your best classification.
- If the ticket text genuinely does not give you enough to determine \
category or severity, use null for that field rather than guessing - do not \
fabricate a confident answer to a genuinely ambiguous ticket.
- Set needs_human_review to true whenever confidence is not "high", or the \
ticket describes a destructive/financial/security-adjacent situation even if \
you are fairly confident.
- Base your classification only on the ticket subject and body provided. Do \
not assume facts not stated in the ticket.

## Worked examples

Ticket: "Payment failed on renewal - my card should be valid, will I be \
downgraded?"
Reasoning: Billing/payment issue; the customer is not yet downgraded and \
nothing else is broken, so this is a real but non-urgent billing problem.
Classification: category=billing, severity=P2, confidence=high, \
needs_human_review=false

Ticket: "API returning 503 for all requests, started 15 minutes ago, please \
escalate immediately"
Reasoning: Full outage, explicitly affecting all requests, ongoing right \
now - textbook P1 production incident.
Classification: category=production_incident, severity=P1, \
confidence=high, needs_human_review=true

Ticket: "Dark mode toggle resets on page refresh, minor annoyance"
Reasoning: Cosmetic UI bug the customer themselves describes as minor; \
nothing is blocked.
Classification: category=bug_report, severity=P3, confidence=high, \
needs_human_review=false

Ticket (ambiguous): "Since about an hour ago, literally every page takes \
15+ seconds to load for everyone on our team, no exceptions. It's \
technically still loading, but at this point it's unusable and it's \
affecting our entire org."
Reasoning: This reads like a performance complaint (nothing is fully down, \
pages do load) but the scope (entire org, every page, sudden onset) matches \
the production-incident pattern more than an isolated slowness report. \
Because the impact is org-wide and severe even though technically \
"degraded" rather than "down", classify as production_incident at P1 rather \
than a routine performance ticket, and flag for human review given the \
genuine ambiguity between the two categories.
Classification: category=production_incident, severity=P1, \
confidence=medium, needs_human_review=true
"""


def build_ticket_prompt(ticket: dict) -> str:
    return f"Subject: {ticket['subject']}\n\n{ticket['body']}"


def classify_ticket(ticket: dict, client: Anthropic) -> dict:
    messages = [{"role": "user", "content": build_ticket_prompt(ticket)}]
    result = None

    for iteration in range(MAX_ITERATIONS):
        tool_choice = (
            {"type": "tool", "name": "classify_ticket"} if iteration == 0 else {"type": "auto"}
        )
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[CLASSIFY_TICKET_TOOL],
            tool_choice=tool_choice,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            tool_block = next(b for b in response.content if b.type == "tool_use")
            result = tool_block.input
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": (
                                f"Recorded: category={result.get('category')}, "
                                f"severity={result.get('severity')}."
                            ),
                        }
                    ],
                }
            )
            continue

        if response.stop_reason == "end_turn":
            if result is None:
                log.warning(
                    "ticket %s: reached end_turn with no prior tool_use - unexpected",
                    ticket["ticket_id"],
                )
            return result

        log.warning(
            "ticket %s: unexpected stop_reason=%s on iteration %d",
            ticket["ticket_id"],
            response.stop_reason,
            iteration,
        )

    log.error(
        "ticket %s: hit iteration cap (%d) without end_turn - 1.1 loop violation, investigate",
        ticket["ticket_id"],
        MAX_ITERATIONS,
    )
    return result


def main() -> None:
    client = Anthropic()
    conn = connect()
    tickets = [dict(row) for row in conn.execute("SELECT * FROM tickets ORDER BY ticket_id")]
    conn.close()

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as out:
        for ticket in tickets:
            result = classify_ticket(ticket, client)
            if result is None:
                log.error("ticket %s: no classification produced, skipping", ticket["ticket_id"])
                continue

            match = "match" if result.get("category") == ticket["seed_category"] else "differs"
            print(
                f"{ticket['ticket_id']}: seed={ticket['seed_category']}/{ticket['seed_severity']} "
                f"predicted={result.get('category')}/{result.get('severity')} "
                f"confidence={result.get('confidence')} review={result.get('needs_human_review')} "
                f"[{match}]"
            )

            out.write(
                json.dumps(
                    {
                        "ticket_id": ticket["ticket_id"],
                        "seed_category": ticket["seed_category"],
                        "seed_severity": ticket["seed_severity"],
                        **result,
                    }
                )
                + "\n"
            )


if __name__ == "__main__":
    main()
