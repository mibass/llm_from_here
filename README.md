

# LLM From Here

This repository contains code for the LLM From Here project.
The primary goal is to produce an automated podcast generator that can use LLMs to
- produce shows scripts
- produce guest lists
- produce intros

The realization of this script into audio is achieved through the main script, named "ShowRunner", which is a dynamic plugin execution system designed to execute a series of plugin scripts defined in a YAML configuration file. The configuration file should contain the name of the show, global parameters, and a list of plugin specifications. Each plugin is executed in order and its results are stored in a global dictionary. To optimize performance, plugin results can be cached in a SQLite database and reloaded in subsequent runs if their specifications haven't changed, unless the cache is explicitly cleared. The plugin execution can be retried in case of validation or assertion errors. The system manages logging of activities and errors, and organizes outputs in unique folders named after the show and run count. Finally, the merged global results from all plugins are dumped into a YAML file in the output folder.

The episodes get generated and posted by Github Actions and can be found at https://llmfromhere.podbean.com/.

## Getting Started

These instructions use `uv` for local development and CI parity.

### Prerequisites

- Python 3.10
- [uv](https://docs.astral.sh/uv/)
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
1. Change into the project directory:
    ```
    cd llm_from_here
    ```
1. Ensure Python **3.10** is used (see [.python-version](.python-version); `uv` will respect it):
    ```
    uv python install 3.10
    ```

1. Sync project dependencies:
    ```
    uv sync --extra dev
    ```

### Preflight (before a full ShowRunner / release-style run)

Check that API keys and binaries are present (fails if anything required is missing):

```bash
uv run python scripts/preflight_env.py --strict --require-ffmpeg
```

For a **non-prod** dry run where Podbean publish is skipped by config, you can omit Podbean credentials:

```bash
uv run python scripts/preflight_env.py --strict --require-ffmpeg --skip-podbean
```

### Configuration

*.env*

This project uses dotenv to set environment variables. Keys are needed for:
* google v3 youtube api `YT_API_KEY`
* freesound api `FREESOUND_API_KEY`
* openai `OPENAI_API_KEY`
* podbean id `PODBEAN_CLIENT_ID`
* podbean secret `PODBEAN_CLIENT_SECRET`
* supabase url `SUPASET_URL`
* supabase key `SUPASET_KEY`

Optional:
* environment selector `LLMFH_ENV` (`prod` for production publishing)
* model override `OPENAI_MODEL_NAME`

### Usage

To run the script:

```bash
uv run python -m llm_from_here.showRunner config.yaml [--clear-cache] [--output-dir <dir>]
```

Optional flags:

    --clear-cache: Use this flag to clear the plugin cache before execution.
    --output-dir: Use this flag to specify the directory where outputs should be stored. Default is ./outputs.

Make sure to provide the path to your YAML configuration file. The script will execute plugins defined in the YAML file, store results in the output folder, and log the execution details.

### Local quality checks

Run the same checks used in CI:

```bash
uv run ruff check .
uv run mypy src tests
uv run pyright
uv run pytest tests/test*.py
uv run pip-audit \
  --ignore-vuln PYSEC-2022-42969 \
  --ignore-vuln CVE-2024-35515
```

Those ignores track transitive gaps (`py` / `sqlitedict`); remove them once upstream publishes fixes you can adopt.

Default CI only runs fast unit tests under `tests/test*.py`. **Integration** tests (live APIs) live in [`tests/integration/`](tests/integration/) and are marked `integration`; run them explicitly when you have real keys and quota:

```bash
uv run pytest tests/integration -m integration
```


