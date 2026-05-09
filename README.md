# LLM From Here

This repository contains code for the LLM From Here project.
The primary goal is to produce an automated podcast generator that can use LLMs to

- produce shows scripts
- produce guest lists
- produce intros

The realization of this script into audio is achieved through the main script, named "ShowRunner", which is a dynamic plugin execution system designed to execute a series of plugin scripts defined in a YAML configuration file. The configuration file should contain the name of the show, global parameters, and a list of plugin specifications. Each plugin is executed in order and its results are stored in a global dictionary. To optimize performance, plugin results can be cached in a SQLite database and reloaded in subsequent runs if their specifications haven't changed, unless the cache is explicitly cleared. The plugin execution can be retried in case of validation or assertion errors. The system manages logging of activities and errors, and organizes outputs in unique folders named after the show and run count. Finally, the merged global results from all plugins are dumped into a YAML file in the output folder.

The episodes get generated and posted by Github Actions and can be found at [https://llmfromhere.podbean.com/](https://llmfromhere.podbean.com/).

## Getting Started

These instructions use `uv` for local development and CI parity.

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- **Deno** (for yt-dlp YouTube JS / “n challenge” solving — unrelated to cookies). Install with `curl -fsSL https://deno.land/install.sh | sh` or your package manager; the installer places `~/.deno/bin/deno`. ShowRunner passes this path to yt-dlp when present (or use `deno` on `PATH`, or set `YT_DLP_DENO`). CI uses [denoland/setup-deno](https://github.com/denoland/setup-deno).
- **macOS:** [Miniconda](https://docs.conda.io/en/latest/miniconda.html) / [Mambaforge](https://github.com/conda-forge/miniforge) for ffmpeg (see below)
- **Linux CI:** ffmpeg comes from the Ubuntu 24.04 archive (pinned in-repo; see [.github/ffmpeg-deb.pin](.github/ffmpeg-deb.pin))

### ffmpeg (macOS — conda)

Audio processing (pydub) needs `ffmpeg` and `ffprobe` on your PATH. On macOS, install a **pinned** build from conda-forge so it matches the FFmpeg **6.1.x** toolchain used in CI (Ubuntu `ffmpeg` package in [.github/ffmpeg-deb.pin](.github/ffmpeg-deb.pin)):

```bash
conda install -c conda-forge "ffmpeg=6.1.1"
```

Use a dedicated env if you like; activate it before `uv run pytest` / ShowRunner so those binaries are on `PATH`.

### Setup

1. Clone the repository:
  ```
    git clone https://github.com/mibass/llm_from_here.git
  ```
2. Change into the project directory:
  ```
    cd llm_from_here
  ```
3. Ensure Python **3.12** is used (see [.python-version](.python-version); `uv` will respect it):
  ```
    uv python install 3.12
  ```
4. Sync project dependencies:
  ```
    uv sync --extra dev
  ```

### Preflight (before a full ShowRunner / release-style run)

Check that API keys and binaries are present (fails if anything required is missing). Preflight loads **`.env`** from the repo root, same as ShowRunner.

```bash
uv run python scripts/preflight_env.py --strict --require-ffmpeg
```

For a **non-prod** dry run where Podbean publish is skipped by config, you can omit Podbean credentials:

```bash
uv run python scripts/preflight_env.py --strict --require-ffmpeg --skip-podbean
```

Include `--require-deno` if you want preflight to fail when Deno is missing (recommended before release-style runs):

```bash
uv run python scripts/preflight_env.py --strict --require-ffmpeg --require-deno --skip-podbean
```

### Configuration

*.env*

This project uses dotenv to set environment variables. Keys are needed for:

- google v3 youtube api `YT_API_KEY`
- freesound api `FREESOUND_API_KEY`
- OpenRouter `OPENROUTER_API_KEY` (chat + slow-path TTS via OpenAI-compatible SDK)
- podbean id `PODBEAN_CLIENT_ID`
- podbean secret `PODBEAN_CLIENT_SECRET`
- Supabase: `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (**service_role** JWT), or legacy `SUPASET_URL` / `SUPASET_KEY`

See [.env.example](.env.example) and **[docs/supabase.md](docs/supabase.md)** for provisioning a new hosted project (CLI bootstrap) and GitHub secret mapping.

Optional:

- environment selector `LLMFH_ENV` (`prod` for production publishing)
- `OPENROUTER_MODEL` (OpenRouter slug; default / example: `deepseek/deepseek-chat-v2.5`)
- `OPENROUTER_TTS_MODEL`, `OPENROUTER_TTS_VOICE` for slow TTS
- `LLMFH_STRUCTURED_OUTPUT_MODE=native|tool` (pydantic-ai structured output style)
- `LLMFH_OPENROUTER_FREE_MODE=1` for zero-cost chat (`openrouter/free`; ignores paid `OPENROUTER_MODEL` from `.env`) and gTTS for slow TTS — optional `LLMFH_OPENROUTER_FREE_CHAT_MODEL` to pick another slug

See [docs/llm_schema_inventory.md](docs/llm_schema_inventory.md) for structured-output model mapping.

### Usage

To run the script:

```bash
uv run python -m llm_from_here.showRunner config.yaml [--clear-cache] [--output-dir <dir>]
```

Optional flags:

```
--clear-cache: Use this flag to clear the plugin cache before execution.
--output-dir: Use this flag to specify the directory where outputs should be stored. Default is ./outputs.
```

Set `LLMFH_SHOWRUNNER_LOG_STDOUT=1` to mirror `showRunner.log` lines to stderr (helpful when piping output).

Make sure to provide the path to your YAML configuration file. The script will execute plugins defined in the YAML file, store results in the output folder, and log the execution details.

### Local quality checks

Run the same checks used in CI:

```bash
uv run ruff check .
uv run mypy src tests
uv run pyright
uv run pytest tests/test*.py
uv run pip-audit \
  --ignore-vuln PYSEC-2022-42969
```

That ignore tracks a transitive gap in `py`; remove it once upstream publishes a fix you can adopt.

Default CI only runs fast unit tests under `tests/test*.py`. **Integration** tests (live APIs) live in `[tests/integration/](tests/integration/)` and are marked `integration`; run them explicitly when you have real keys and quota:

```bash
uv run pytest tests/integration -m integration
```

Those tests default **OpenRouter** to free-tier routing (`LLMFH_OPENROUTER_FREE_MODE=1`, chat uses `openrouter/free`). You still need `OPENROUTER_API_KEY`. To run integration against a paid slug from your `.env`, set `LLMFH_INTEGRATION_USE_FREE_OPENROUTER=0`.

