# Mind_Vault

> A modular, **$0-first** AI media company that researches, writes, produces, and (optionally) publishes
> educational videos about **Human Psychology** and **Human History** — designed to scale into an
> autonomous, self-improving content business.

Mind_Vault is **not** a single video generator. It is an orchestrated fleet of independent agents
managed by an **AI CEO**, backed by a real database, a pluggable model layer, and an automation harness.
Every external dependency (LLM, TTS, image, publishing) is swappable through configuration — nothing paid
is ever hard-coded.

---

## Table of contents

1. [What actually works today](#what-actually-works-today)
2. [Architecture](#architecture)
3. [Quick start](#quick-start)
4. [Configuration](#configuration)
5. [Running the pipeline](#running-the-pipeline)
6. [The API & dashboard](#the-api--dashboard)
7. [Database schema](#database-schema)
8. [Agents](#agents)
9. [Automation (GitHub Actions)](#automation-github-actions)
10. [Testing](#testing)
11. [Design decisions](#design-decisions)
12. [Roadmap & honest status](#roadmap--honest-status)

---

## What actually works today

This repository is a **runnable foundation**, not a slideware mock-up. With **zero paid services and no GPU**,
you can:

- Initialize the full database (`python -m scripts.init_db`)
- Run the **entire content pipeline end-to-end in offline "stub" mode** (`python -m scripts.run_pipeline`)
  and get a real script, scene plan, narration audio, slide images, and an assembled `.mp4` on disk
- Start the FastAPI backend and browse the dashboard
- Run the test suite (`pytest`)

The pipeline is designed to **degrade gracefully**: if `ollama`, `ffmpeg`, `pyttsx3`, or Stable Diffusion
aren't installed, each stage falls back to a free, dependency-light implementation and logs what it did,
so the DAG always completes and never loses work.

To go from "runs offline" to "publishes to YouTube," you add credentials and heavier models — see
[Roadmap & honest status](#roadmap--honest-status). The seams are already there.

---

## Architecture

```
                          ┌───────────────────┐
                          │     AI CEO AGENT   │  orchestrates, approves, learns
                          └─────────┬─────────┘
                                    │
   ┌──────────────┬─────────────┬───┴───────────┬──────────────┬───────────────┐
   │              │             │               │              │               │
 Trend         Topic        Research         Fact          Script           Hook
Discovery    Generator +     Agent          Checker        Writer          Engine
             Opportunity
   │              │             │               │              │               │
   └──────────────┴─────────────┴───────┬───────┴──────────────┴───────────────┘
                                        │
   ┌──────────────┬─────────────┬───────┴───────┬──────────────┬───────────────┐
 Visual         Voice        Presenter        Video          Quality          SEO
Planner        Pipeline      Pipeline        Generator      Controller       Agent
   │              │             │               │              │               │
   └──────────────┴─────────────┴───────┬───────┴──────────────┴───────────────┘
                                        │
                     ┌──────────────┬───┴────────┬──────────────┐
                  Publishing     Analytics    Competitor      Learning
                    Agent          Agent      Intelligence      Agent
```

**Layering** (a deliberate decision — see [Design decisions](#design-decisions)):

- `core/` — the shared framework: config, logging, database, LLM abstraction, media abstraction,
  schemas, dedup, the `BaseAgent` class, the registry, and the orchestrator.
- `agents/` — the 17 agents, each in its **own folder with its own `config.yaml`**, importing shared
  infrastructure from `core/` instead of duplicating it.
- `api/` — FastAPI application.
- `dashboard/` — static monitoring UI.
- `workflows/` + `.github/workflows/` — automation.

---

## Quick start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2. Install (runtime deps are intentionally light; heavy/optional ones are extras)
pip install -r requirements.txt

# 3. Create your local secrets file (never committed)
cp .env.example .env        # Windows: copy .env.example .env

# 4. Initialize the database
python -m scripts.init_db

# 5. Run the whole pipeline once, fully offline, $0
python -m scripts.run_pipeline --category psychology

# 6. (optional) Start the API + dashboard
uvicorn api.main:app --reload
# then open http://127.0.0.1:8000/dashboard
```

Everything above works with **only** the base `requirements.txt` and no external accounts.

---

## Configuration

All behavior is controlled by [`config/settings.yaml`](config/settings.yaml) and environment variables in
`.env`. **No provider is hard-coded.** To switch the LLM from the offline stub to local Ollama:

```yaml
llm:
  provider: ollama        # stub | ollama | openai(optional) | anthropic(optional)
  model: llama3.1
```

Secrets (API keys, OAuth tokens) live **only** in `.env` / GitHub Secrets and are read via environment
variables — never written to YAML or code. See [`.env.example`](.env.example).

---

## Running the pipeline

```bash
python -m scripts.run_pipeline --category psychology --format short
python -m scripts.run_pipeline --category history --format long
```

The orchestrator runs the full DAG (trend → topic → research → fact-check → script → hook → visual →
voice → presenter → video → quality → SEO), persists everything to the database, writes artifacts to
`storage/`, and prints a run summary. Publishing is **dry-run by default** (`publishing.dry_run: true`).

---

## The API & dashboard

`uvicorn api.main:app --reload` exposes:

- `GET /health` — service + DB health
- `GET /api/content` — list produced content
- `GET /api/topics` — topic pipeline
- `GET /api/analytics/summary` — performance rollup
- `GET /api/ceo/report` — latest AI CEO weekly report
- `POST /api/pipeline/run` — trigger a production run
- `GET /dashboard` — the monitoring UI

---

## Database schema

Implemented in [`core/database/models.py`](core/database/models.py) with SQLAlchemy (SQLite now,
PostgreSQL-ready). Tables: `content`, `content_memory`, `analytics`, `topics`, `sources`, `ai_memory`,
`hooks`, `thumbnails`, `ceo_reports`, `agent_runs`. Full field list in that file and in
[Design decisions](#design-decisions).

---

## Agents

Each agent lives in `agents/<name>/` with `agent.py` + `config.yaml`, subclasses `BaseAgent`, and gets
structured logging, retry/backoff, error capture, and a persisted `agent_runs` record for free. See
[`agents/`](agents/).

---

## Automation (GitHub Actions)

`.github/workflows/` contains: daily research, Mon/Wed/Fri short production, Sunday long-form,
daily analytics, and the Sunday-night AI CEO review. All run on free GitHub-hosted runners.

---

## Testing

```bash
pytest -q
```

Tests cover config loading, database models, dedup thresholds, the agent base lifecycle, and a full
offline pipeline smoke test.

---

## Design decisions

See inline `# DESIGN:` comments throughout the code and the dedicated section in
[`docs/DECISIONS.md`](docs/DECISIONS.md).

---

## Roadmap & honest status

| Capability | Status | To go live you add |
|---|---|---|
| Framework, DB, config, logging, dedup, orchestrator, API | ✅ Complete & runnable | — |
| Text agents (trend/topic/research/fact/script/hook/SEO/CEO) | ✅ Functional (stub + Ollama), template-driven prompts | Ollama or an API key for higher quality |
| Prompt templates (`prompts/templates/`) | ✅ Editable text drives every LLM call | tune tone without touching code |
| Thumbnail testing engine | ✅ Multiple Pillow variants + A/B table + selection | CTR data to auto-pick winners |
| Content calendar (rolling 90-day, balanced) | ✅ Built + API + `build_calendar` | — |
| Natural voice | ✅ Piper/Coqui XTTS wired (female), auto-fallback to pyttsx3/silence | `pip install piper-tts` + a female voice model (free) |
| AI presenter "Aria" | ✅ Consistent synthetic persona, portrait generated & composited as PiP, disclosed as AI | GPU + Stable Diffusion (photoreal face) + SadTalker/Wav2Lip (lip-sync) — all free/open-source |
| Image generation | ✅ Free fallback (Pillow slide cards) | Stable Diffusion / ComfyUI + GPU |
| Video assembly | ✅ Real **.mp4** via bundled ffmpeg (`pip install imageio-ffmpeg`), GIF fallback | richer motion graphics later |
| Captions | ✅ Synced `.srt` generated + attached to uploads | — |
| Long-form documentaries (8–15 min) | ✅ Chaptered generator; can weave related shorts into one doc | — |
| Background music | ✅ Procedural royalty-safe bed (or your tracks) + narration ducking + intro/outro swell | drop royalty-free tracks in `storage/music/` (optional) |
| Batch production | ✅ `scripts.batch` produces N videos from the calendar with schedule | — |
| Quality scorecard | ✅ hook / storytelling / fact / originality / retention / copyright-risk | — |
| Review + manual approval | ✅ Every video held in `storage/review/` until approved (`scripts.review`) | — |
| Publishing (YouTube/TikTok/IG/FB) | ✅ Real uploaders (httpx), credential-gated, **dry-run + private + approval-gated** | add credentials + `dry_run: false` (see docs/PUBLISHING.md) |
| Analytics ingestion | 🔶 Schema + simulated ingest | Platform Data APIs |
| Self-learning loop | ✅ Framework + rules updates on stored analytics | more real data over time |

🔶 = real interface with a working free/no-op default, ready for the paid/heavy upgrade — **not** a fake stub.

### Note on the offline stub and the originality gate

The offline **Stub LLM** is deliberately template-based, so its prose is stylistically
repetitive. The originality gate (min 85) correctly notices this: the **first** video on a
fresh database publishes, and later stub videos that read too similarly are **withheld**
(non-fatal — the artifact is kept, publishing is skipped). This is the dedup system working
as designed. With Ollama or a real LLM, distinct topics diverge far more and publish freely.
To demonstrate the full **published → analytics → learning → CEO** loop offline at $0, run:

```bash
python -m scripts.seed_demo      # seeds published videos, then runs analytics+learning+CEO
python -m scripts.build_calendar # prints the rolling balanced content calendar
```

### Content operations: batch → review → approve → publish

Nothing publishes automatically. The safe production workflow:

```bash
# 1. Produce a batch from the 90-day calendar (each lands in review as 'pending')
python -m scripts.batch --count 5 --category both        # or --format long
python -m scripts.run_pipeline --format long             # one long documentary

# 2. Review the queue and inspect any bundle (video + script + thumbnail + scorecard)
python -m scripts.review list
python -m scripts.review show <run_id>

# 3. Approve (or reject) — approval is the ONLY path to publishing
python -m scripts.review approve <run_id>

# 4. Publish approved videos — stays PRIVATE + dry-run until you flip those
python -m scripts.publish_approved
```

Each review bundle lives in `storage/review/<run_id>/` with the final video,
`script.txt`, `thumbnail.png`, `captions.srt`, `metadata.json`, and a
`review.json` scorecard (hook / storytelling / fact / originality / retention /
copyright-risk). Videos are gated by `publishing.require_manual_approval: true`.

### The AI presenter "Aria" — how to reach photorealism

The presenter is a **fictional, fully AI-generated persona** (a person who does not
exist), disclosed as AI in every description, with a **fixed seed** so she looks the
same in every video. Configuration lives in
[`agents/presenter_agent/config.yaml`](agents/presenter_agent/config.yaml).

What you get **now at $0 / CPU**: a consistent stylized portrait composited as
picture-in-picture, plus natural voice once Piper is installed. This is honest — it is
*not* a photorealistic talking human.

To make her a **photorealistic, lip-synced human** (all free / open-source, but needs
an NVIDIA GPU):

1. **Face** — `pip install diffusers torch` → set `avatar_provider: stable_diffusion`.
   Stable Diffusion renders her synthetic face from the fixed seed (delete
   `storage/presenter/aria.png` once to regenerate).
2. **Natural voice** — `pip install piper-tts`, drop a female voice `.onnx` into
   `storage/voices/` (or set `PIPER_MODEL`). Coqui XTTS is an even richer option.
3. **Lip-sync** — install [SadTalker](https://github.com/OpenTalker/SadTalker) (or
   Wav2Lip) → set `lipsync_provider: sadtalker`. She then talks in sync with the narration.

No GPU? The same result is available via **paid APIs** (HeyGen/D-ID for the avatar,
ElevenLabs for voice) — each slots behind the identical presenter/TTS interface.
