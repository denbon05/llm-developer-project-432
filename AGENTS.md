# Agent rules

## Workflow

- Read the step's spec in `docs/specs/` before writing code for it. The spec
  is the source of truth. If the code has to deviate, update the spec in the
  same change.
- Respect the decisions in `docs/adr/`. Don't "fix" something an ADR explains.
  To change one, propose a new ADR.
- Use the vocabulary in `CONTEXT.md` for code, logs and docs. Never use a word
  it lists under _Avoid_.
- Keep module and directory names exactly as the layout in
  `docs/specs/02-platform-foundation.md` defines them.
- When a change affects how the service is installed, configured or run, update
  the README's Installation and Usage sections in the same change.

## Architecture

- SQL lives only in `app/repositories/`. The one exception is the readiness
  probe in `app/core/db.py`.
- Only `app/llm/client.py` talks to the model provider. SDK types and errors
  never leave it.
- `app/services/` never imports FastAPI, Temporal or database drivers.
- Routers stay thin: parse, call, map the response.
- The environment is read only through `app/core/config.py`.
- Workflow code is deterministic: no I/O, no settings, no wall-clock time.
- Hold a database connection for one operation, never across a model call.

## Code

- Function names are verbs. Boolean names start with `is_`, `has_`, `can_`,
  `should_` or `was_`.
- No magic numbers or strings if used 2+ times: use a named constant, following the file's
  existing style.
- Read the target file and its neighbours first, and reuse existing names and
  helpers.
- Write everything in English: code, prompts, docs, data.
- Keep docstrings simple and limited to what the item does; put context and
  rationale in comments.

## Tests

- No test may need a model server. Substitute the LLM client interface.
- Database tests use testcontainers, never the developer's Compose database.

## Git

- One commit per step on `main`, with the message `feat: <title> (step NN)`.
  The commit message references the step's spec.
- Commit messages use Conventional Commits.
- Never edit or delete `.github/workflows/hexlet-check.yml`.
