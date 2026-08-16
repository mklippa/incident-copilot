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
