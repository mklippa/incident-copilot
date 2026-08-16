"""Synthetic data generator for Incident Copilot.

Deterministic and idempotent: seeds the RNG, drops/recreates the SQLite
schema, and overwrites the runbook/log fixture files. Safe to rerun.

Usage: uv run python -m incident_copilot.generate_data
"""

import random
from datetime import datetime, timedelta
from pathlib import Path

from incident_copilot.db import connect, reset_schema

SEED = 42

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOKS_DIR = REPO_ROOT / "runbooks"
LOGS_DIR = REPO_ROOT / "logs"

PLANS = ["free", "pro", "enterprise"]

FIRST_NAMES = [
    "Ava", "Noah", "Mia", "Liam", "Zoe", "Ethan", "Ivy", "Owen",
    "Luna", "Kai", "Nora", "Theo",
]
LAST_NAMES = [
    "Kim", "Patel", "Garcia", "Nguyen", "Muller", "Rossi", "Andersen",
    "Okafor", "Silva", "Haddad", "Larsson", "Costa",
]


def make_customers(n: int) -> list[dict]:
    customers = []
    for i in range(1, n + 1):
        first = FIRST_NAMES[(i - 1) % len(FIRST_NAMES)]
        last = LAST_NAMES[(i - 1) % len(LAST_NAMES)]
        signup = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 600))
        customers.append(
            {
                "customer_id": f"CUST-{i:04d}",
                "name": f"{first} {last}",
                "email": f"{first.lower()}.{last.lower()}@example.com",
                "plan": random.choice(PLANS),
                "signup_date": signup.date().isoformat(),
            }
        )
    return customers


# Each template: (category, severity, subject, body).
# "{customer}" and "{plan}" are filled in per assigned customer.
TICKET_TEMPLATES = [
    # --- billing ---
    ("billing", "P2", "Payment failed on renewal",
     "Hi, my {plan} plan renewal payment failed this morning and I got an email saying "
     "my account will be downgraded in 48 hours. My card on file should be valid. Can "
     "someone check what happened?"),
    ("billing", "P3", "Question about invoice line item",
     "There's a line item on this month's invoice labeled 'proration adjustment' that I "
     "don't recognize. Can you explain what it's for?"),
    ("billing", "P2", "Refund request for accidental upgrade",
     "I accidentally upgraded from {plan} to a higher tier and was charged immediately. "
     "I meant to stay on my current plan. Can I get a refund for the difference?"),
    ("billing", "P3", "How do I update my billing email",
     "I need invoices to go to a different email address going forward. Where do I "
     "change that in settings?"),
    ("billing", "P1", "Charged three times for the same invoice",
     "I was just charged three separate times for this month's invoice, all within the "
     "same minute. That's a significant overcharge and I need this reversed today."),
    # --- bug_report ---
    ("bug_report", "P2", "CSV export is missing the last column",
     "When I export my report to CSV, the rightmost column ('status') is silently "
     "dropped. It's present in the on-screen table, just missing from the download."),
    ("bug_report", "P3", "Dark mode toggle resets on page refresh",
     "Every time I refresh the page, dark mode switches back to light mode even though "
     "I set it explicitly in preferences. Minor annoyance but noticed it a few times."),
    ("bug_report", "P2", "Search returns stale results after editing a ticket",
     "After I edit a ticket's title, the search index still shows the old title for a "
     "few minutes. Not a huge deal but confusing for my team."),
    ("bug_report", "P3", "Typo in the onboarding email",
     "Small thing, but the welcome email says 'Your acount is ready' - missing a c in "
     "'account'."),
    # --- production_incident ---
    ("production_incident", "P1", "Entire dashboard is down for all users",
     "Our whole team is getting a 500 error on every page of the dashboard as of about "
     "10 minutes ago. This is blocking all of our workflows right now."),
    ("production_incident", "P1", "API returning 503 for all requests",
     "Every API call we make is returning 503 Service Unavailable, starting about 15 "
     "minutes ago. This is a full outage for us, please escalate immediately."),
    ("production_incident", "P1", "Cannot log in - authentication service down",
     "Nobody on our team can log in right now, we all get 'authentication service "
     "unavailable' immediately after entering credentials. This started this morning."),
    ("production_incident", "P2", "Webhook deliveries failing intermittently",
     "About 1 in 5 of our webhook deliveries are failing with a timeout. It's not a "
     "total outage but it's happening consistently enough to cause data gaps."),
    # --- performance ---
    ("performance", "P2", "Dashboard takes 20+ seconds to load",
     "Loading the main dashboard has been taking 20-30 seconds for the past two days, "
     "compared to the usual 2-3 seconds. It's slow but does eventually load."),
    ("performance", "P3", "Slight lag when switching between tabs",
     "I've noticed a small delay, maybe half a second, when switching between tabs in "
     "the app. Not blocking anything, just a bit sluggish."),
    ("performance", "P2", "Large report generation times out",
     "Generating a report with more than ~5000 rows times out after about 30 seconds "
     "instead of completing. Smaller reports work fine."),
    # --- account ---
    ("account", "P3", "Need to reset my password",
     "I'm locked out of my account and the password reset email never arrived. Can you "
     "help me regain access?"),
    ("account", "P2", "Two-factor authentication codes not accepted",
     "My authenticator app codes are being rejected as invalid every time, even right "
     "after generating a fresh one. I can't get into my account."),
    ("account", "P3", "How do I transfer ownership of my workspace",
     "I'm leaving the company and need to transfer workspace ownership to a colleague. "
     "What's the process for that?"),
    # --- other ---
    ("other", "P3", "Feature request: bulk export",
     "Would love the ability to export multiple reports at once instead of one at a "
     "time. Not urgent, just a suggestion."),
    ("other", "P3", "General feedback on the new UI",
     "Just wanted to say the new navigation redesign is a big improvement. No issue to "
     "report, just positive feedback."),
    # --- deliberately ambiguous (could read as performance OR production_incident) ---
    ("performance", "P1", "App is extremely slow for our whole team",
     "Since about an hour ago, literally every page takes 15+ seconds to load for "
     "everyone on our team, no exceptions. It's technically still loading, but at this "
     "point it's unusable for real work and it's affecting our entire org, not just one "
     "person."),
    ("production_incident", "P2", "Some pages slow, others seem fine",
     "A few of our team members are seeing very slow load times on the reports page "
     "specifically, but the rest of the app seems normal and not everyone is affected. "
     "Hard to tell if this is isolated or the start of something bigger."),
    ("billing", "P2", "Downgrade didn't take effect but I was still charged full price",
     "I downgraded my plan two weeks ago but this month's invoice still charged me the "
     "{plan}-tier price. Not sure if the downgrade failed or if this is a billing cycle "
     "quirk."),
    ("bug_report", "P1", "Data export contains another customer's rows",
     "This is concerning: my CSV export today included several rows that are clearly "
     "not my data - different company names and emails I don't recognize. Flagging this "
     "as urgent since it looks like a data isolation issue."),
]


def make_tickets(customers: list[dict]) -> list[dict]:
    tickets = []
    base_time = datetime(2026, 8, 1, 9, 0, 0)
    for i, (category, severity, subject, body_tpl) in enumerate(TICKET_TEMPLATES, start=1):
        customer = random.choice(customers)
        body = body_tpl.format(customer=customer["name"], plan=customer["plan"])
        created_at = base_time + timedelta(
            hours=random.randint(0, 24 * 14), minutes=random.randint(0, 59)
        )
        tickets.append(
            {
                "ticket_id": f"TKT-{i:04d}",
                "customer_id": customer["customer_id"],
                "subject": subject,
                "body": body,
                "seed_category": category,
                "seed_severity": severity,
                "status": "open",
                "created_at": created_at.isoformat(),
            }
        )
    return tickets


RUNBOOKS = {
    "kb-001-refund-policy-2025-01.md": """\
# Refund Policy

*Last updated: 2025-01-15*

Customers may request a full refund within **14 days** of any charge, no
questions asked. After 14 days, refunds are issued at support's discretion
on a case-by-case basis, typically prorated to the unused portion of the
billing period.

Refund requests should be submitted via a support ticket with the invoice
ID. Approved refunds are processed within 5-7 business days.
""",
    "kb-002-refund-policy-2026-06.md": """\
# Refund Policy

*Last updated: 2026-06-01*

Refunds are only guaranteed within **7 days** of a charge. Between 7 and 30
days, a refund may be issued as account credit rather than a cash refund,
at support's discretion. After 30 days, charges are final and non-refundable
except where required by law.

Refund requests should be submitted via a support ticket with the invoice
ID. Approved refunds are processed within 3-5 business days.

> Note: this policy supersedes prior refund documentation for all new
> requests submitted after the effective date above.
""",
    "kb-003-app-performance-troubleshooting.md": """\
# Troubleshooting: Slow Application Performance

*Last updated: 2026-03-10*

Common causes of slow dashboard or report load times:

1. **Large report size** - reports over ~5,000 rows can take significantly
   longer to render. Recommend the customer filter or paginate.
2. **Client-side network conditions** - ask the customer to check if the
   slowness is specific to one network/location.
3. **Elevated backend latency** - check the internal latency dashboard for
   the affected time window before assuming a client-side cause.

Escalate to production-incident handling (see `kb-004`) if the slowness is
sudden, affects multiple customers simultaneously, and correlates with a
backend latency spike - that pattern indicates an infrastructure issue
rather than an individual customer's data volume.
""",
    "kb-004-production-incident-response.md": """\
# Production Incident Response

*Last updated: 2026-02-20*

Classify as a **P1 production incident** when:

- A service is fully unavailable (5xx errors, timeouts) for multiple
  customers simultaneously, OR
- Authentication/login is broken for any customer, OR
- Data integrity is at risk (e.g. one customer's data appearing in
  another's account).

For confirmed P1s: escalate immediately with the structured handoff
(Customer ID / Summary / Root cause / Recommended action) rather than
attempting to resolve independently. Do not wait for a full root-cause
analysis before escalating - escalate first, investigate in parallel.
""",
    "kb-005-bug-report-triage.md": """\
# Bug Report Triage

*Last updated: 2026-04-05*

When triaging a bug report:

- **Cosmetic/UI-only issues** (typos, minor visual glitches) are P3 unless
  they block a core workflow.
- **Data-correctness bugs** (wrong or missing data in exports, reports, or
  displays) are at minimum P2, and P1 if the wrong data belongs to a
  *different customer* - treat any cross-customer data leakage as a
  security-adjacent incident and escalate immediately rather than filing a
  routine bug report.
- **Intermittent bugs** should be logged with exact reproduction steps and
  frequency (e.g. "1 in 5 attempts") since they're otherwise hard to
  reproduce internally.
""",
}

LOGS = {
    "api-gateway-2026-08-10.log": """\
2026-08-10T14:02:11Z api-gateway INFO  request_id=a1f9 method=GET path=/v1/reports status=200 latency_ms=182
2026-08-10T14:02:47Z api-gateway INFO  request_id=b2c0 method=GET path=/v1/dashboard status=200 latency_ms=210
2026-08-10T14:03:15Z api-gateway WARN  request_id=c3d1 method=GET path=/v1/dashboard status=200 latency_ms=4820 note="latency above p99 threshold"
2026-08-10T14:03:16Z api-gateway WARN  request_id=c3d2 method=GET path=/v1/reports status=200 latency_ms=5110 note="latency above p99 threshold"
2026-08-10T14:03:20Z api-gateway ERROR request_id=c3d3 method=POST path=/v1/export status=503 latency_ms=30000 note="upstream timeout: report-worker"
2026-08-10T14:03:22Z api-gateway ERROR request_id=c3d4 method=POST path=/v1/export status=503 latency_ms=30000 note="upstream timeout: report-worker"
2026-08-10T14:05:01Z api-gateway INFO  request_id=d4e5 method=GET path=/v1/dashboard status=200 latency_ms=240 note="latency recovered"
""",
    "worker-timeout-2026-08-12.log": """\
2026-08-12T09:12:03Z report-worker INFO  job_id=job-8891 customer_id=CUST-0007 rows=6210 status=started
2026-08-12T09:12:33Z report-worker WARN  job_id=job-8891 customer_id=CUST-0007 rows=6210 elapsed_ms=30000 note="approaching timeout threshold"
2026-08-12T09:12:34Z report-worker ERROR job_id=job-8891 customer_id=CUST-0007 rows=6210 status=timeout note="job exceeded 30s execution limit"
2026-08-12T09:15:10Z report-worker INFO  job_id=job-8892 customer_id=CUST-0003 rows=412 elapsed_ms=890 status=completed
""",
    "db-pool-exhaustion-2026-08-14.log": """\
2026-08-14T02:31:00Z db-pool INFO  pool=primary size=20 in_use=18 waiting=0
2026-08-14T02:31:45Z db-pool WARN  pool=primary size=20 in_use=20 waiting=6 note="pool at capacity"
2026-08-14T02:31:50Z auth-service ERROR request_id=e7f2 note="connection pool exhausted, could not acquire connection within 5000ms"
2026-08-14T02:31:52Z auth-service ERROR request_id=e7f3 note="connection pool exhausted, could not acquire connection within 5000ms"
2026-08-14T02:33:10Z db-pool INFO  pool=primary size=20 in_use=9 waiting=0 note="pool pressure resolved after autoscale"
""",
}


def write_runbooks() -> None:
    RUNBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, content in RUNBOOKS.items():
        (RUNBOOKS_DIR / filename).write_text(content, encoding="utf-8")


def write_logs() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, content in LOGS.items():
        (LOGS_DIR / filename).write_text(content, encoding="utf-8")


def main() -> None:
    random.seed(SEED)

    conn = connect()
    reset_schema(conn)

    customers = make_customers(12)
    tickets = make_tickets(customers)

    conn.executemany(
        "INSERT INTO customers (customer_id, name, email, plan, signup_date) "
        "VALUES (:customer_id, :name, :email, :plan, :signup_date)",
        customers,
    )
    conn.executemany(
        "INSERT INTO tickets "
        "(ticket_id, customer_id, subject, body, seed_category, seed_severity, status, created_at) "
        "VALUES (:ticket_id, :customer_id, :subject, :body, :seed_category, :seed_severity, :status, :created_at)",
        tickets,
    )
    conn.commit()
    conn.close()

    write_runbooks()
    write_logs()

    print(f"Generated {len(customers)} customers, {len(tickets)} tickets.")
    print(f"Wrote {len(RUNBOOKS)} runbook articles to {RUNBOOKS_DIR}/")
    print(f"Wrote {len(LOGS)} log files to {LOGS_DIR}/")


if __name__ == "__main__":
    main()
