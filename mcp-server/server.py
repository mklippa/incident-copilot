"""Incident Copilot's custom MCP server (stdio transport).

Exposes the ticket DB, the runbook knowledge base, and synthetic logs to
Coordinator/specialist agents. Run directly (not via `-m`, since this
directory's hyphenated name isn't a valid Python package path):

    uv run python mcp-server/server.py

Wired into Claude Code via the project's .mcp.json.
"""

import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from mcp.server import MCPServer

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from incident_copilot.db import connect  # noqa: E402
from incident_copilot.schemas import tool_error  # noqa: E402

RUNBOOKS_DIR = REPO_ROOT / "runbooks"
LOGS_DIR = REPO_ROOT / "logs"

TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
LAST_UPDATED_RE = re.compile(r"Last updated:\s*(\d{4}-\d{2}-\d{2})")
LOG_LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(.*)$")

server = MCPServer(
    "incident-copilot",
    description="Ticket DB, runbook knowledge base, and log access for Incident Copilot agents.",
)


@server.tool()
def search_knowledge_base(
    query: Annotated[
        str,
        Field(description="Keyword or short phrase to search for across KB article titles and bodies. Case-insensitive substring match."),
    ],
) -> dict:
    """Search the runbook knowledge base by keyword.

    Returns every article whose title or body contains the query text - there
    may be more than one match, and matches are not deduplicated or ranked by
    relevance beyond simple containment. In particular, some queries (e.g.
    "refund") deliberately return two articles that mildly contradict each
    other on different dates; this tool does not resolve that conflict, it
    only surfaces both so the caller can weigh them with their dates.

    Returns {"results": [{filename, title, last_updated, excerpt}]}. Zero
    matches returns {"results": []} - this is a valid, non-error outcome, not
    a failure.

    Example queries: "refund policy", "production incident", "slow dashboard".
    """
    query_lower = query.lower()
    results = []
    for path in sorted(RUNBOOKS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if query_lower not in text.lower():
            continue
        title_match = TITLE_RE.search(text)
        updated_match = LAST_UPDATED_RE.search(text)
        results.append(
            {
                "filename": path.name,
                "title": title_match.group(1) if title_match else path.stem,
                "last_updated": updated_match.group(1) if updated_match else None,
                "excerpt": text.strip()[:200],
            }
        )
    return {"results": results}


@server.tool()
def get_customer_history(
    customer_id: Annotated[
        str,
        Field(description="Customer identifier, e.g. 'CUST-0007'. Must match a customer_id in the customers table exactly."),
    ],
) -> dict:
    """Look up a customer's profile plus their full ticket and resolution history.

    Returns {"customer": {...}, "tickets": [...], "resolutions": [...]} on
    success. If customer_id doesn't match any known customer, returns a
    structured tool error with errorCategory="not_found" (not retryable -
    the caller should ask for a corrected ID, not retry the same call).

    If the environment variable SIMULATE_DB_DOWN is set (used to exercise
    failure handling deliberately), this returns errorCategory="access_failure"
    (retryable) instead of querying the database at all.

    Example queries: "look up this customer's account and past tickets before
    responding to their new complaint".
    """
    import os

    if os.environ.get("SIMULATE_DB_DOWN"):
        return tool_error(
            "access_failure",
            retryable=True,
            retry_after_ms=2000,
            suggestion="The customer database is temporarily unavailable. Retry shortly, or escalate if this persists.",
        )

    conn = connect()
    customer_row = conn.execute(
        "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if customer_row is None:
        conn.close()
        return tool_error(
            "not_found",
            retryable=False,
            suggestion=f"No customer found with customer_id={customer_id!r}. Verify the ID and try again.",
        )

    tickets = [
        dict(row)
        for row in conn.execute(
            "SELECT ticket_id, subject, status, seed_category, created_at "
            "FROM tickets WHERE customer_id = ? ORDER BY created_at",
            (customer_id,),
        )
    ]
    resolutions = [
        dict(row)
        for row in conn.execute(
            "SELECT r.resolution_id, r.ticket_id, r.resolution_type, r.summary, r.created_at "
            "FROM resolutions r JOIN tickets t ON r.ticket_id = t.ticket_id "
            "WHERE t.customer_id = ? ORDER BY r.created_at",
            (customer_id,),
        )
    ]
    conn.close()

    return {"customer": dict(customer_row), "tickets": tickets, "resolutions": resolutions}


@server.tool()
def get_recent_logs(
    query: Annotated[
        str | None,
        Field(description="Substring to filter log lines by, case-insensitive. Omit to return recent lines regardless of content."),
    ] = None,
    level: Annotated[
        Literal["INFO", "WARN", "ERROR"] | None,
        Field(description="Restrict results to a specific log level. Omit to include all levels."),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum number of matching lines to return, most recent first.", ge=1, le=200),
    ] = 20,
) -> dict:
    """Search synthetic log snippets across all log files by keyword and/or level.

    Returns {"results": [{timestamp, level, source_file, line}]}, most recent
    first, capped at `limit`. Zero matches returns {"results": []} - a valid
    empty result, not an error.

    Example queries: "look for timeout or 503 errors around the time this
    incident ticket was filed".
    """
    query_lower = query.lower() if query else None
    matches = []
    for path in sorted(LOGS_DIR.glob("*.log")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            m = LOG_LINE_RE.match(line)
            if not m:
                continue
            timestamp, _source, line_level, _rest = m.groups()
            if level and line_level != level:
                continue
            if query_lower and query_lower not in line.lower():
                continue
            matches.append(
                {
                    "timestamp": timestamp,
                    "level": line_level,
                    "source_file": path.name,
                    "line": line,
                }
            )

    matches.sort(key=lambda m: m["timestamp"], reverse=True)
    return {"results": matches[:limit]}


@server.tool()
def create_refund(
    customer_id: Annotated[str, Field(description="Customer identifier, e.g. 'CUST-0007'.")],
    ticket_id: Annotated[str, Field(description="Ticket identifier this refund resolves, e.g. 'TKT-0005'. Must belong to customer_id.")],
    amount_usd: Annotated[float, Field(description="Refund amount in US dollars. Must be positive.")],
    reason: Annotated[str, Field(description="Short human-readable justification for the refund, recorded in the audit trail.")],
) -> dict:
    """Issue a refund and record it as a resolution against a ticket.

    This is a destructive/financial action. It performs the refund
    unconditionally when inputs are valid - it does NOT enforce any dollar
    threshold itself. A separate PreToolUse hook (added in a later build
    step) blocks calls above a $50 threshold regardless of what the calling
    agent decides; that enforcement is deliberately external to this tool.

    Returns the created resolution row on success. Returns a structured tool
    error (errorCategory="invalid_input") if amount_usd is non-positive, or
    errorCategory="not_found" if customer_id/ticket_id don't exist or the
    ticket doesn't belong to the given customer.
    """
    if amount_usd <= 0:
        return tool_error(
            "invalid_input",
            retryable=False,
            suggestion="amount_usd must be a positive number.",
        )

    conn = connect()
    customer_row = conn.execute(
        "SELECT customer_id FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if customer_row is None:
        conn.close()
        return tool_error(
            "not_found",
            retryable=False,
            suggestion=f"No customer found with customer_id={customer_id!r}.",
        )

    ticket_row = conn.execute(
        "SELECT ticket_id, customer_id FROM tickets WHERE ticket_id = ?", (ticket_id,)
    ).fetchone()
    if ticket_row is None or ticket_row["customer_id"] != customer_id:
        conn.close()
        return tool_error(
            "not_found",
            retryable=False,
            suggestion=f"Ticket {ticket_id!r} was not found for customer {customer_id!r}.",
        )

    created_at = datetime.now(UTC).isoformat()
    summary = f"Refund of ${amount_usd:.2f} issued: {reason}"
    cursor = conn.execute(
        "INSERT INTO resolutions (ticket_id, resolution_type, summary, created_at) "
        "VALUES (?, 'refund_issued', ?, ?)",
        (ticket_id, summary, created_at),
    )
    conn.commit()
    resolution_id = cursor.lastrowid
    conn.close()

    return {
        "resolution_id": resolution_id,
        "ticket_id": ticket_id,
        "resolution_type": "refund_issued",
        "summary": summary,
        "created_at": created_at,
    }


if __name__ == "__main__":
    server.run()
