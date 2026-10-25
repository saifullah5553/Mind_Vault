# Local autopilot

Mind_Vault produces real videos only on a machine that has Ollama, the Piper
voice and ffmpeg. GitHub-hosted runners have none of these, so the cloud
workflows are manual-only and run the test suite instead. Daily production runs
here, through `scripts/autopilot.py`.

## What it does each day

| When                         | Job        | What happens                                         |
|------------------------------|------------|------------------------------------------------------|
| every day                    | `research` | refresh trends, topics and competitor intel          |
| `publishing.short_days`      | `short`    | one vertical Short, rendered into the review folder  |
| `publishing.long_days`       | `long`     | one landscape documentary, into the review folder    |
| `autopilot.review_day`       | `review`   | weekly CEO report (learning waits for live analytics)|
| every day                    | `backup`   | zip of database, config and logs                     |

The CEO agent picks the category, keeping the mix close to `strategy.category_mix`.
"Today" is the date in `publishing.timezone`.

## Safety gates (preflight)

A render job is **blocked**, not run, when any of these is true:

- Ollama is not running, or the configured model is not pulled. The LLM layer
  would otherwise fall back to placeholder stub scripts.
- There is no Piper voice model, so the narration would be silent.
- Free disk space is below `autopilot.min_free_gb`.
- `publishing.dry_run` **and** `publishing.require_manual_approval` are both off.
  That would mean public uploads with no human check, which has not been approved.

A blocked or crashed job makes the run exit with code 1, so Task Scheduler shows
it as failed. A script rejected by the pre-render quality gate counts as done for
the day; retrying it would only burn CPU on the same weak material.

Nothing is uploaded by the autopilot. Finished videos wait in `storage/review/`
until you approve them:

```bash
python -m scripts.review list
```

```bash
python -m scripts.review approve <run_id>
```

## Commands

```bash
python -m scripts.autopilot --plan
```

```bash
python -m scripts.autopilot
```

```bash
python -m scripts.autopilot --job short
```

- `--plan` shows today's jobs and their preflight status without running anything.
- `--date 2026-11-01` plans for another day. `--force` re-runs jobs already done today.
- Only one autopilot runs at a time (`storage/autopilot.lock`). A lock older than
  `autopilot.stale_lock_hours` is treated as a crashed run and taken over.

Results: `storage/autopilot_last_run.json`. Log: `logs/autopilot.log` when the
run is started by `autopilot.cmd`, otherwise `logs/mind_vault.log`.

## Run it every day (Windows Task Scheduler)

```bash
python -m scripts.autopilot --install-task --time 09:00
```

This registers the task "Mind_Vault Autopilot", which runs `autopilot.cmd` daily.
If the PC was off at that time, the task runs at the next start-up. It runs only
while you are signed in, which is also when Ollama is running. Remove it with:

```bash
python -m scripts.autopilot --uninstall-task
```

## Why the learning loop is paused

The analytics agent only reads real platform data in `live` mode, and live
collection is not implemented yet. In `auto` and `simulate` modes it generates
plausible but invented figures. The weekly review therefore skips learning until
`agents/analytics_agent/config.yaml` says `mode: "live"`, so channel strategy is
never tuned to fictional numbers.

## Settings (`config/settings.yaml`)

```yaml
autopilot:
  research_daily: true
  review_day: "sun"
  min_free_gb: 10
  require_real_llm: true
  require_voice: true
  stale_lock_hours: 12
```
