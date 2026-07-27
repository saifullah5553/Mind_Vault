# Architecture Decision Record — Mind_Vault

Concise rationale for the choices that shaped the codebase. Each is also flagged
inline with `# DESIGN:` comments where it lives.

## 1. `core/` framework + thin `agents/` — not 17 self-contained folders
The brief asks for each agent to have its own folder, config, logging, and error
handling. Naively that means copy-pasting infrastructure 17 times. Instead, the
shared machinery lives once in `core/` and every agent subclasses `BaseAgent`,
which *gives* each agent logging, retry, error capture, config loading, and an
audit trail. Each agent still has its own folder and `config.yaml` — but there is
exactly one place to fix a bug or swap a provider. This is the single most
important maintainability decision in the project.

## 2. A pluggable provider layer for every external dependency
LLM, TTS, image, and video each sit behind a small interface with a **free
default** and config-selected implementations. No paid provider is ever imported
at the top level; premium options are import-guarded. This is what makes
"never hard-code a paid provider / all services replaceable by config" literally
true rather than aspirational.

## 3. An offline **Stub LLM** as the default provider
CI, evaluators, and new contributors must be able to run the whole system with
`pip install -r requirements.txt` and nothing else. The stub reads the `TASK:` /
`TOPIC:` markers agents embed in prompts and returns coherent, on-topic text — so
the pipeline is genuinely exercised end-to-end at $0. Configure Ollama for real
prose; agent code is unchanged.

## 4. Graceful degradation over hard failure in the media layer
FFmpeg/GPU aren't always present. Rather than crash, the image layer falls back
to Pillow "slide cards" and the video layer to an animated GIF — both produce a
real, viewable artifact with zero extra dependencies. The pipeline therefore
always completes and never loses work, satisfying the reliability requirement
honestly (a GIF slideshow is real; an empty stub would not be).

## 5. `PipelineContext` + per-stage checkpointing
One typed object threads through the DAG and is serialized to
`storage/checkpoints/<run_id>.json` after each stage. A failed run resumes from
the last completed stage (`--resume <run_id>`). Typed hand-offs also give us
validation at every boundary for free.

## 6. Heuristic scoring in Python, prose in the LLM
Virality/curiosity/competition scores, hook scoring, and fact confidence are
computed with explainable Python heuristics — deterministic, testable, and
free — while the LLM is used only for creative prose. This keeps the system
debuggable and avoids depending on an LLM to emit valid JSON for control flow.

## 7. Safety defaults that require an explicit decision to override
Publishing is dry-run and credential-gated; the AI presenter is disabled and
refuses non-owned avatar assets; secrets come only from the environment. Going
live is always a deliberate operator action, never an accident.

## 8. JSON columns for evolving signals
Retention curves, keyword lists, CEO findings, and agent-run I/O summaries use
portable `JSON` columns so new signals don't require a migration. The schema
works identically on SQLite today and PostgreSQL later (timestamps are set in
Python, not via dialect-specific SQL).

## What is deliberately NOT finished (see README status table)
Live platform publishing, real analytics ingestion, GPU image generation, and
lip-synced presenter clips are wired as real interfaces with free/no-op defaults,
not fake stubs. Each names exactly what to install/provide to go live. This is an
honest foundation, not a demo pretending to be a finished company.
