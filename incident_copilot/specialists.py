"""Specialist subagents, built as real Agent SDK AgentDefinitions (task 1.3).

Each specialist is capped at a single custom MCP tool - the minimum needed
for its job - and is invoked as a fresh, independent Agent SDK session with
no shared conversation history with the Coordinator or with each other.
Ticket context is passed explicitly through the task payload (the query()
prompt), not accumulated turn-by-turn like the Coordinator's own loop.
"""

import asyncio
import os

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage

from incident_copilot.paths import REPO_ROOT

MCP_CONNECT_TIMEOUT_S = 10
MCP_CONNECT_POLL_INTERVAL_S = 0.5

MCP_SERVERS_CONFIG = {
    "incident-copilot": {
        "type": "stdio",
        "command": "uv",
        "args": ["run", "python", str(REPO_ROOT / "mcp-server" / "server.py")],
    }
}

SPECIALIST_DEFINITIONS: dict[str, AgentDefinition] = {
    "log_analyzer": AgentDefinition(
        description="Investigates synthetic log snippets relevant to a ticket.",
        prompt=(
            "You are the Log Analyzer specialist for Incident Copilot. You "
            "are given a single support ticket's details and nothing else - "
            "you have no memory of any other ticket or conversation.\n\n"
            "Use get_recent_logs to search for log lines relevant to this "
            "ticket (by keyword, and by level if the ticket suggests errors "
            "vs. warnings). Summarize in 2-4 sentences what the logs show: "
            "is there evidence of an actual incident, and if so what, when, "
            "and how severe does it look from the log evidence alone. If "
            "nothing relevant turns up, say so plainly rather than "
            "speculating."
        ),
        tools=["mcp__incident-copilot__get_recent_logs"],
        maxTurns=6,
    ),
    "kb_searcher": AgentDefinition(
        description="Searches the runbook knowledge base for relevant policy/procedure articles.",
        prompt=(
            "You are the KB Searcher specialist for Incident Copilot. You "
            "are given a single support ticket's details and nothing else - "
            "you have no memory of any other ticket or conversation.\n\n"
            "Use search_knowledge_base to find runbook articles relevant to "
            "this ticket. If your search surfaces multiple articles that "
            "disagree with each other, report all of them with their "
            "filenames and last-updated dates - do not pick one or average "
            "them, and do not resolve the disagreement yourself. Summarize "
            "in 2-4 sentences what the KB says, citing article filenames."
        ),
        tools=["mcp__incident-copilot__search_knowledge_base"],
        maxTurns=6,
    ),
    "customer_history": AgentDefinition(
        description="Looks up a customer's profile, ticket, and resolution history.",
        prompt=(
            "You are the Customer History Lookup specialist for Incident "
            "Copilot. You are given a single support ticket's details and "
            "nothing else - you have no memory of any other ticket or "
            "conversation.\n\n"
            "Use get_customer_history to look up the customer named in this "
            "ticket. Summarize in 2-4 sentences anything relevant to the "
            "current complaint: their plan, prior tickets in the same area, "
            "and any prior resolutions (e.g. past refunds) that bear on how "
            "this ticket should be handled."
        ),
        tools=["mcp__incident-copilot__get_customer_history"],
        maxTurns=6,
    ),
}


def build_specialist_prompt(ticket: dict) -> str:
    return (
        f"Ticket ID: {ticket['ticket_id']}\n"
        f"Customer ID: {ticket['customer_id']}\n"
        f"Subject: {ticket['subject']}\n\n"
        f"{ticket['body']}"
    )


async def run_specialist(name: str, ticket: dict) -> str:
    """Run one specialist as a fresh, independent Agent SDK session.

    No conversation history is shared with the Coordinator or with any
    other specialist - this opens a brand-new client/session per call, and
    the only context the specialist receives is the ticket payload below.

    Uses ClaudeSDKClient (not the one-shot query() function) because query()
    does not wait for MCP server connection before sending the first turn -
    verified empirically: the custom MCP server's status is still "pending"
    at the init system message, and the model gets tools=[] and hallucinates
    tool calls in plain text instead of making real tool_use calls. Polling
    get_mcp_status() until "connected" before querying avoids that race.
    """
    agent_def = SPECIALIST_DEFINITIONS[name]

    options = ClaudeAgentOptions(
        system_prompt=agent_def.prompt,
        tools=agent_def.tools,
        allowed_tools=agent_def.tools,
        mcp_servers=MCP_SERVERS_CONFIG,
        max_turns=agent_def.maxTurns,
        cwd=str(REPO_ROOT),
        env={"ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"]},
    )

    async with ClaudeSDKClient(options=options) as client:
        elapsed = 0.0
        while elapsed < MCP_CONNECT_TIMEOUT_S:
            status = await client.get_mcp_status()
            servers = status.get("mcpServers", [])
            if servers and all(s.get("status") == "connected" for s in servers):
                break
            await asyncio.sleep(MCP_CONNECT_POLL_INTERVAL_S)
            elapsed += MCP_CONNECT_POLL_INTERVAL_S
        else:
            return f"({name} specialist: MCP server never connected within {MCP_CONNECT_TIMEOUT_S}s)"

        await client.query(build_specialist_prompt(ticket))

        result_text = None
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                result_text = message.result

    return result_text or f"({name} specialist produced no result)"
