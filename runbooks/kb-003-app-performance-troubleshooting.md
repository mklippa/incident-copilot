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
