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
