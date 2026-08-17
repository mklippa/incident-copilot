"""Manual smoke test for the Incident Copilot MCP server's four tools.

Exercises the tools through the real MCP client/server protocol (in-process,
no subprocess) rather than calling the Python functions directly, so it also
catches schema/serialization issues. Deliberately covers the pairs of cases
called out in the spec's task 2.2: a valid empty result vs. a simulated
access failure, and the two contradictory KB articles surfacing together.

Usage: uv run python mcp-server/smoke_test.py
"""

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("mcp_server_module", REPO_ROOT / "mcp-server" / "server.py")
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)

from mcp.client import Client  # noqa: E402

sys.path.insert(0, str(REPO_ROOT))
from incident_copilot.db import connect  # noqa: E402


def tool_json(result) -> dict:
    return json.loads(result.content[0].text)


def check(label: str, condition: bool) -> None:
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(1)


async def main() -> None:
    conn = connect()
    real_customer_id = conn.execute("SELECT customer_id FROM customers LIMIT 1").fetchone()[0]
    real_ticket = conn.execute(
        "SELECT ticket_id FROM tickets WHERE customer_id = ? LIMIT 1", (real_customer_id,)
    ).fetchone()[0]
    conn.close()

    client = Client(server_module.server)
    async with client:
        # search_knowledge_base: contradictory pair both surface
        result = await client.call_tool("search_knowledge_base", {"query": "refund"})
        data = tool_json(result)
        filenames = {r["filename"] for r in data["results"]}
        check(
            "search_knowledge_base('refund') returns both contradictory refund-policy articles",
            {"kb-001-refund-policy-2025-01.md", "kb-002-refund-policy-2026-06.md"} <= filenames,
        )

        # search_knowledge_base: valid empty result, not an error
        result = await client.call_tool("search_knowledge_base", {"query": "nonexistent-xyz-123"})
        check(
            "search_knowledge_base(no match) returns empty results, not an error",
            tool_json(result) == {"results": []} and not result.is_error,
        )

        # get_customer_history: success path
        result = await client.call_tool("get_customer_history", {"customer_id": real_customer_id})
        check(
            "get_customer_history(real customer) succeeds",
            "customer" in tool_json(result) and not result.is_error,
        )

        # get_customer_history: not_found
        result = await client.call_tool("get_customer_history", {"customer_id": "CUST-9999"})
        check(
            "get_customer_history(bogus customer) returns errorCategory=not_found",
            tool_json(result).get("errorCategory") == "not_found",
        )

        # get_customer_history: simulated DB-down
        os.environ["SIMULATE_DB_DOWN"] = "true"
        result = await client.call_tool("get_customer_history", {"customer_id": real_customer_id})
        os.environ.pop("SIMULATE_DB_DOWN")
        down_data = tool_json(result)
        check(
            "get_customer_history(SIMULATE_DB_DOWN) returns errorCategory=access_failure",
            down_data.get("errorCategory") == "access_failure" and down_data.get("isRetryable") is True,
        )

        # get_recent_logs: keyword match
        result = await client.call_tool("get_recent_logs", {"query": "timeout"})
        check(
            "get_recent_logs(query='timeout') returns matching lines",
            len(tool_json(result)["results"]) > 0,
        )

        # create_refund: success path, verify DB row written
        result = await client.call_tool(
            "create_refund",
            {
                "customer_id": real_customer_id,
                "ticket_id": real_ticket,
                "amount_usd": 25.0,
                "reason": "smoke test refund",
            },
        )
        refund_data = tool_json(result)
        check("create_refund(valid) succeeds", "resolution_id" in refund_data)

        conn = connect()
        row = conn.execute(
            "SELECT * FROM resolutions WHERE resolution_id = ?",
            (refund_data["resolution_id"],),
        ).fetchone()
        conn.close()
        check("create_refund wrote a resolutions row", row is not None and row["resolution_type"] == "refund_issued")

        # create_refund: invalid amount
        result = await client.call_tool(
            "create_refund",
            {"customer_id": real_customer_id, "ticket_id": real_ticket, "amount_usd": -5, "reason": "bad"},
        )
        check(
            "create_refund(negative amount) returns errorCategory=invalid_input",
            tool_json(result).get("errorCategory") == "invalid_input",
        )

        # runbook resources: listed and individually readable
        resources = await client.list_resources()
        uris = {str(r.uri) for r in resources.resources}
        check(
            "list_resources() includes both contradictory refund-policy runbooks",
            {"runbook://kb-001-refund-policy-2025-01.md", "runbook://kb-002-refund-policy-2026-06.md"} <= uris,
        )

        result = await client.read_resource("runbook://kb-001-refund-policy-2025-01.md")
        check(
            "read_resource(kb-001) returns the article's markdown body",
            "refund" in result.contents[0].text.lower(),
        )

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
