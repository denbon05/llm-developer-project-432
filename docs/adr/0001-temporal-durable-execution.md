# Temporal for durable execution instead of a task queue

**Status:** accepted

Parsing and generation take seconds to minutes, and a card draft can then wait
days for a human decision. We run this work as Temporal workflows, not as tasks
on a message queue (for example Celery on RabbitMQ). A queue redelivers a
message but knows nothing about progress inside it. A crashed handler starts
over and pays for its model calls again, and a multi-day wait occupies a
worker. Temporal resumes from the last completed activity, and a wait costs
nothing.

## Consequences

- **One background mechanism.** No message queue: Temporal carries all
  background work.
- **The status of record stays in Postgres.** A dedicated activity writes it,
  and Temporal history is never shown as a status.
- **The revision loop is written twice, on purpose.** `run_pipeline()` in
  `services/pipeline.py` serves the synchronous preview, and the workflow runs
  the same algorithm with activities. Replayed workflow code must stay
  deterministic, so it can't share a loop that logs and does I/O. Both copies
  use `MAX_GENERATION_ATTEMPTS` and are tested against the same scenarios.
- **Timeouts and retry policies are constants in workflow code**, not
  settings, so every replay sees the same values.
- **Human decisions arrive as signals.** Updates would make the "awaiting a
  decision" check atomic. That upgrade is deferred.
