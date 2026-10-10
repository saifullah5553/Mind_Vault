# Moving Mind_Vault to another machine (laptop → desktop)

Everything that matters is in GitHub, so the move is mostly a `git clone` plus one
setup command. Nothing needs to be copied by hand unless you want your old
generated videos.

---

## What lives where

| Item | In GitHub? | How it gets to the new machine |
|---|---|---|
| All code, configs, prompts, workflows, docs | ✅ yes | `git clone` |
| **Aria's presenter portrait** (`storage/presenter/aria.png` + badge) | ✅ yes | `git clone` |
| Python packages | ❌ | `setup_machine` installs them |
| Piper voice model (~60 MB) | ❌ (too large) | `setup_machine` re-downloads it (free) |
| Ollama + `llama3.2:3b` | ❌ | install Ollama, `setup_machine` pulls the model |
| Wav2Lip + weights (~500 MB) | ❌ (third-party) | `setup_lipsync` rebuilds it, patches included |
| Database (`mind_vault.db`) | ❌ | recreated empty; copy it only if you want history |
| Past videos / review bundles (`storage/`) | ❌ | copy manually **only if you want the old output** |
| Secrets (`.env`) | ❌ **never** | recreate from `.env.example` when you go live |

> There is currently **no `.env`** on the laptop, so there are no secrets to move.
> The database holds only a handful of test rows — not worth carrying.

---

## On the NEW machine

### 1. Install the prerequisites (need installers/admin)
- **Python 3.11+** — <https://www.python.org/downloads/> (tick *"Add Python to PATH"*)
- **Git** — <https://git-scm.com/downloads>
- **Ollama** (free local LLM) — <https://ollama.com>

### 2. Clone the project
```bash
git clone https://github.com/saifullah5553/Mind_Vault.git
```
```bash
cd Mind_Vault
```

### 3. Run the one-command setup
```bash
python -m scripts.setup_machine
```
This installs the Python deps, downloads the Piper voice, pulls the Ollama model,
rebuilds Wav2Lip (with the compatibility patches), initializes the database, and
prints a readiness report.

To skip the big lip-sync download for now: `python -m scripts.setup_machine --skip-lipsync`

### 4. Verify
```bash
python -m scripts.doctor
```
Then produce a video:
```bash
python -m scripts.run_pipeline --category history
```

---

## Optional: carry over old output

Only if you want the previously generated videos and review queue. Copy these
folders from the laptop into the same place on the desktop:

```
storage/review/     old review bundles (videos, scripts, thumbnails)
storage/videos/     rendered videos
mind_vault.db       content/analytics history
```

Use a USB drive, OneDrive, or `scp`. Nothing here is required for the system to run.

---

## If your desktop has a better GPU (likely!)

`python -m scripts.doctor` reports the GPU. With a **6 GB+ NVIDIA card** you unlock
big quality upgrades that the laptop's MX550 (2 GB) could not run:

- **Photoreal Aria face** — `pip install diffusers torch` (CUDA build), then set
  `avatar_provider: stable_diffusion` in `agents/presenter_agent/config.yaml`
  and delete `storage/presenter/aria.png` to regenerate.
- **Natural head motion + blinking** — install
  [SadTalker](https://github.com/OpenTalker/SadTalker) and set
  `lipsync_provider: sadtalker` (plus `sadtalker_cmd`). This is the fix for
  "it still looks like an AI avatar" — Wav2Lip alone only moves the mouth.
- **Much faster renders** — Ollama will use the GPU automatically, and you can
  move up to a larger model (e.g. `ollama pull llama3.1:8b`, then set
  `llm.model` in `config/settings.yaml`).

See [SETUP_AI.md](SETUP_AI.md) for the details of each.

---

## Keeping the two machines in sync

```bash
git pull      # before you start working
git push      # when you finish
```
Runtime artifacts (videos, DB, checkpoints) are intentionally **not** synced —
each machine keeps its own.

---

## Moving the project folder (e.g. C: -> D:, or to another machine)

The **code** is location-independent: `ROOT_DIR` is derived from the source file,
so the database, storage and tool paths all follow the folder automatically.

But artifacts produced by earlier runs record **absolute** paths — the database
(`content.video_path` etc.), review bundles, pipeline checkpoints and publish
manifests. After a move those still point at the old location, so
`scripts.publish_approved` and `run_pipeline --resume` would fail to find their
files.

Fix it in one command after moving:

```bash
python -m scripts.relocate --check    # report what would change
```
```bash
python -m scripts.relocate            # rewrite them to the new root
```

It is idempotent — it only rewrites paths that do not already sit under the
current root, so running it twice is harmless.

### Moving on Windows

Run the copy from *outside* the folder, or Windows will refuse to delete the
source root (a process cannot delete its own working directory):

```bash
robocopy "C:\old\path" "D:\new\path" /E /MOVE /R:2 /W:2
```

Then `python -m scripts.relocate`, and re-open your terminal/editor at the new
path.
