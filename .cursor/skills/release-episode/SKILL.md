---
name: release-episode
description: >-
  Runs and evaluates llm_from_here episode releases locally across dev, prod, and free modes.
  Uses the current working tree and branch (no GitHub checkout). Runs ShowRunner with correct
  env, deletes Podbean episodes on request, and analyzes show_runner.log / agent_trace.log with
  structured reports. Use when releasing an episode, local test/prod episode release, free-mode
  smoke runs, deleting Podbean episodes, or analyzing episode release logs.
disable-model-invocation: true
---

# Release an episode (llm_from_here)

All episode releases run **locally** from the current repo checkout. Use whatever branch and commits are already on disk — do **not** dispatch GitHub Actions workflows or checkout release tags.

## Quick start

1. **Pick mode** — if unclear, ask the user: `dev`, `prod`, or `free`.
2. **Preflight** — note branch/commit, verify `.env`, run `preflight_env.py`.
3. **Run** — pytest gate, then ShowRunner with mode-specific env.
4. **Monitor** — tail logs in the run output folder or stderr (`LLMFH_SHOWRUNNER_LOG_STDOUT=1`).
5. **Report** — analyze logs using templates in [REPORTING.md](REPORTING.md).

## Local source of truth

```bash
git branch --show-current
git rev-parse --short HEAD
git status --short
```

Runs always reflect the **current working tree** on the active branch, including uncommitted changes. No `gh workflow run`, no `releases/latest` checkout.

## Modes

| Mode | `LLMFH_ENV` | Podbean publish | Supabase prefix | LLM/TTS cost |
|------|-------------|-----------------|-----------------|--------------|
| **dev** | `dev` (default) | Skipped (`only_in_prod`) | `dev_*` | Paid |
| **prod** | `prod` | Yes | Production names | Paid |
| **free** | `dev` (default) | Skipped | `dev_*` | Free chat + gTTS; Lyria skipped |

### dev — smoke release (local)

Validates the full pipeline without publishing to Podbean.

```bash
uv sync --extra dev
uv run python scripts/preflight_env.py --strict --skip-podbean
uv run pytest tests/test*.py
uv run python -m llm_from_here.showRunner configs/configv3.yaml --output-dir outputs
```

`LLMFH_ENV` unset or `dev` → Podbean upload skipped via `only_in_prod: True` in `configs/configv3.yaml`.

### prod — publish episode (local)

Ships a real episode to Podbean. **Confirm with the user before running.**

**Default: `--clear-cache`.** Prod publishes must not reuse cached stitch/podcast metadata or segment timelines from prior runs (stale cache can publish wrong guests or audio). Omit `--clear-cache` only when the user explicitly asks to use cache (e.g. "keep cache", "skip clear-cache").

```bash
uv sync --extra dev
uv run python scripts/preflight_env.py --strict
uv run pytest tests/test*.py
LLMFH_ENV=prod \
  uv run python -m llm_from_here.showRunner configs/configv3.yaml --output-dir outputs --clear-cache
```

A successful dev run does **not** prove Podbean publish — only `LLMFH_ENV=prod` enables upload.

### free — zero-cost local run

Cheap smoke test without paid OpenRouter chat/TTS/Lyria.

```bash
uv sync --extra dev
uv run python scripts/preflight_env.py --strict --skip-podbean
LLMFH_OPENROUTER_FREE_MODE=1 \
  uv run python -m llm_from_here.showRunner configs/configv3.yaml --output-dir outputs
```

Expectations when `LLMFH_OPENROUTER_FREE_MODE=1`:
- Chat routes to `openrouter/free` (paid `OPENROUTER_MODEL` ignored).
- Slow TTS uses gTTS instead of paid OpenRouter TTS.
- Lyria beds skipped; intro/story music falls back to YouTube search.
- Optional override: `LLMFH_OPENROUTER_FREE_CHAT_MODEL=<slug>`.

Combine with prod only when the user explicitly wants a free-tier prod publish (rare):

```bash
LLMFH_ENV=prod LLMFH_OPENROUTER_FREE_MODE=1 \
  uv run python -m llm_from_here.showRunner configs/configv3.yaml --output-dir outputs --clear-cache
```

## Preflight checklist

```
Episode release preflight:
- [ ] Mode chosen: dev / prod / free
- [ ] Branch and commit noted (git branch --show-current; git rev-parse --short HEAD)
- [ ] Working tree state acceptable (uncommitted changes intentional?)
- [ ] For prod: user confirmed Podbean publish intent
- [ ] For prod: `--clear-cache` included (unless user asked to keep cache)
- [ ] .env secrets present (never echo values): OPENROUTER_API_KEY, YT_API_KEY, FREESOUND_API_KEY, PODBEAN_*, SUPASET_*
- [ ] preflight_env.py passed
```

```bash
uv run python scripts/preflight_env.py --strict --skip-podbean   # dev/free
uv run python scripts/preflight_env.py --strict                  # prod
```

Optional: `preflight_env.py --require-ffmpeg --require-deno` for YouTube download parity.

## Run ShowRunner (canonical)

```bash
uv sync --extra dev
uv run pytest tests/test*.py
uv run python -m llm_from_here.showRunner configs/configv3.yaml --output-dir outputs
```

Optional flags: `--output-dir <dir>`. **`--clear-cache`:** required by default for **prod**; optional for dev/free when forcing a clean rerun.

**Cache caution:** `stitchAudio`, `podcastManager`, and `segmentsToTimeline` cache hits can publish stale episode metadata or audio. Grep logs for `phase=cache` before trusting a prod publish.

**Config:** `configs/configv3.yaml` is canonical.

**Lyria:** off unless `LLMFH_LYRIA_ENABLED=1` (default off → YouTube music fallback).

**Model routing** (YAML `global_params.model_routing`, env overrides):
- `LLMFH_FILTER_MODEL`, `LLMFH_STRUCTURED_MODEL`, `LLMFH_PROSE_MODEL`
- Use `openrouter:<slug>` prefix for OpenRouter models.

**Gemini TTS:** default `google/gemini-3.1-flash-tts-preview` + `Sadachbia`; narrator lines use sparse inline tags (`[neutral]`, `[positive]`, etc.) from script LLMs only.

**yt-dlp tuning** (local `.env`):
- `YT_DLP_COOKIE_FILE`, `YT_DLP_PLAYER_CLIENT`, `YT_DLP_EXTRACTOR_ARGS_JSON`, `YT_DLP_COMPAT_OPTIONS`, `YT_DLP_IMPERSONATE`, `YT_DLP_SOCKET_TIMEOUT`, `YT_DLP_VERBOSE`

## Monitor local run

```bash
# Mirror logs to terminal
LLMFH_SHOWRUNNER_LOG_STDOUT=1 uv run python -m llm_from_here.showRunner configs/configv3.yaml --output-dir outputs

# Find latest run folder
ls -td outputs/*_run* outputs/show_run* 2>/dev/null | head -1

# Tail logs during or after run
tail -f outputs/show_runN/show_runner.log
tail -f outputs/show_runN/agent_trace.log
```

Per-run output: `{output_dir}/{show_name}_runN/` (default `outputs/show_runN/`).

## Log locations

| File | Path | Contents |
|------|------|----------|
| `show_runner.log` | `{output_dir}/{show_name}_runN/` | Main pipeline; plugin phases, errors |
| `agent_trace.log` | same folder | Guest agent + filter LLM JSON traces |

Logger format: `%(asctime)s:%(name)s:%(levelname)s:%(message)s`

Structured context in `show_runner.log`:
```
run_id=<uuid> plugin=<name> phase=<phase> message=<text>
```
Phases: `init`, `skip`, `cache`, `import`, `execute`, `results`, `finalize`

`agent_trace.log` kinds:
- `pydantic_ai_run` — guest agent search (`scope`, `usage`, `output`, `new_messages`)
- `filter_llm` — video filter (`guest_name`, `title`, `kept` bool)

## Post-run analysis

After the run, produce a report using [REPORTING.md](REPORTING.md):

1. Fill **Release Run Summary** with mode, branch, commit, output folder, status.
2. Run the **Log Analysis Checklist** against local logs.
3. Apply **Issue Recognition** patterns for YouTube, audio, Podbean.
4. Write **Recommendations** with concrete next steps.

**Quick grep targets** in `show_runner.log`:
- `phase=execute` + `ERROR` / `Exception`
- `No youtube audio result`, `Retreiving youtube`
- `Lyria`, `fallback`, `LLMFH_OPENROUTER_FREE_MODE`
- `only_in_prod`, `lfh_podbean`, `skip`
- `phase=cache` on `stitchAudio`, `podcastManager`, `segmentsToTimeline` (stale publish risk in prod)

**Quick checks** in `agent_trace.log`:
- `"kept": false` — rejected videos
- Low `usage` or empty `output` — agent failures

**Diagnostics** (optional):

```bash
uv run python scripts/diagnose_lyria.py
uv run python evals/eval_guest_agent.py [--guest "Name"]
```

## Podbean deletion

Only when the user **explicitly** requests deletion. Full procedure: [PODBEAN.md](PODBEAN.md).

```bash
# Always dry-run first
uv run python scripts/delete_podbean_episode.py --match "Episode 65" --dry-run
# Then delete after user confirms matches
uv run python scripts/delete_podbean_episode.py --match "Episode 65"
```

Pipeline auto-prune: `lfh_podbean` in configv3 deletes oldest episode when `max_episodes` (3) reached — prod only.

## Never expose secrets

- Do not echo `.env` values in chat or logs.
- Repo uses legacy `SUPASET_URL` / `SUPASET_KEY` env names (map from `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` if needed).

## Related docs

- [REPORTING.md](REPORTING.md) — report templates
- [PODBEAN.md](PODBEAN.md) — deletion guardrails
- [docs/supabase.md](../../../docs/supabase.md) — Supabase bootstrap and secrets
