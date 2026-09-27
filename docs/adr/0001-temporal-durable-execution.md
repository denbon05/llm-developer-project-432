# Temporal for durable execution instead of a task queue

**Status:** accepted

Card generation and document parsing take seconds to minutes. A generated card
can then wait days for a human decision. We run this work as Temporal workflows,
not as tasks on a message queue with workers (for example Celery on RabbitMQ).

A queue guarantees that a *message* is delivered. It knows nothing about
progress *inside* a handler. When a worker dies halfway through, the job's
status stays stuck at the last value it wrote. The redelivered message then
starts from scratch and pays for the model calls again. A queue also has no way
to express "wait three days for a moderator" without occupying a worker for the
whole wait.

Temporal records each completed activity in the workflow history. After a crash
it resumes from the first activity that did not complete. A human wait is a
`wait_condition` that costs nothing while it waits.

## Consequences

- **One background mechanism.** The project uses no message queue. Adding one
  would be a second way to do the same thing.
- **The status of record stays in Postgres.** A dedicated `record_job_status`
  activity writes it. Temporal history is internal and never shown as a job's
  status.
- **The revision loop is written twice, on purpose.** `services/pipeline.py`
  has `run_pipeline()` for the synchronous preview, and the workflow runs the
  same algorithm with activities. Workflow code must be deterministic, because
  it is replayed. Sharing the loop across that boundary would bring logging and
  I/O concerns into replay. The two copies share `MAX_GENERATION_ATTEMPTS` and
  are tested against the same scenarios.
- **Timeouts and retry policies are constants in workflow code**, not settings.
  Values read from the environment could differ between replays.
- **Human decisions arrive as signals.** Temporal Updates with validators would
  make the API's "is this job awaiting a decision" check atomic. That upgrade
  is deferred.
- **Development runs Temporal's single-binary dev server in Compose**, with its
  state persisted to a volume.
