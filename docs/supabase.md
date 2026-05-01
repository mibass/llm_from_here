# Supabase setup (portable bootstrap)

This project uses Supabase for:

- **`supasets` / `supaqueue` tables** — [`SupaSet`](../src/llm_from_here/supaSet.py), [`SupaQueue`](../src/llm_from_here/supaQueue.py)
- **Storage** — [`supabaseBucketManager`](../src/llm_from_here/plugins/supabaseBucketManager.py) (default bucket `llmfh` in [`configs/configv3.yaml`](../configs/configv3.yaml))

Schema lives in [`supabase/migrations/`](../supabase/migrations/). Provision hosted projects locally with the Supabase CLI (or `npx supabase@latest`).

## Prerequisites

1. [Supabase CLI](https://supabase.com/docs/guides/cli) **or** Node **`npx`** on your PATH.
2. A Supabase **account personal access token** (Dashboard → Account → Access Tokens). Export as **`SUPABASE_ACCESS_TOKEN`** or put it in repo-root **`.env`** (gitignored).

**Do not** add **`SUPABASE_ACCESS_TOKEN`** to GitHub Actions. Use it only on your machine to create/link projects and push migrations.

## Environment variables

### Runtime (ShowRunner, CI, GitHub Actions)

| Variable | Purpose |
| -------- | ------- |
| **`SUPABASE_URL`** | Project API URL, e.g. `https://<project-ref>.supabase.co` |
| **`SUPABASE_SERVICE_ROLE_KEY`** | JWT **`service_role`** key (server-side; bypasses RLS) |

Legacy aliases (still supported): **`SUPASET_URL`**, **`SUPASET_KEY`**, and **`SUPABASE_API_KEY`** (same role as service role key).

### Bootstrap-only (local `.env`)

| Variable | When |
| -------- | ---- |
| **`SUPABASE_ACCESS_TOKEN`** | Always for CLI |
| **`SUPABASE_PROJECT_NAME`** | Create mode: display name |
| **`SUPABASE_ORG_ID`** | Create mode |
| **`SUPABASE_REGION`** | Create mode (e.g. `us-east-1`) |
| **`SUPABASE_DB_PASSWORD`** | Create mode: Postgres password for the **new** project (stored by Supabase; optional in `.env` after bootstrap unless you need direct DB access) |
| **`SUPABASE_PROJECT_REF`** | **Link-only** mode: skips `projects create` |
| **`SUPABASE_STORAGE_BUCKET`** | Optional; when set, overrides `bucket_name` in YAML (e.g. configv3 `llmfh`) |

Shell exports override `.env` (python-dotenv `override=False`), matching ShowRunner behavior.

## One-shot bootstrap

From the repository root:

```bash
uv run python scripts/bootstrap_supabase.py
```

Or:

```bash
./scripts/bootstrap_supabase.sh
```

**Create a new hosted project** — set in `.env`:

- `SUPABASE_ACCESS_TOKEN`
- `SUPABASE_PROJECT_NAME` (or pass as first positional argument)
- `SUPABASE_ORG_ID` — find with `supabase projects list` / Dashboard
- `SUPABASE_REGION`
- `SUPABASE_DB_PASSWORD`

**Use an existing project** — set **`SUPABASE_PROJECT_REF`** (Dashboard URL contains it). Omit create-only variables.

The script will:

1. Optionally **`supabase projects create`**
2. Wait until the project reports **`ACTIVE_HEALTHY`** (or similar)
3. Fetch API keys, **`supabase link`**, **`supabase db push`**
4. Run **`scripts/supabase_create_bucket.py`** for the storage bucket (default `llmfh`)
5. Print blocks you can paste into **`.env`** and into **GitHub repository secrets**

Use **`--dry-run`** to preview **`db push`** without applying migrations or creating the bucket (keys are still printed).

### Duplicate project name

If **`projects create`** fails because the name exists, choose another name **or** switch to link-only mode with **`SUPABASE_PROJECT_REF`** for that project and rerun.

## GitHub Actions secrets

After bootstrap, set repository secrets used by [release_episode.yml](../.github/workflows/release_episode.yml) and [release_episode_test.yml](../.github/workflows/release_episode_test.yml):

| Secret | Value |
| ------ | ----- |
| **`SUPASET_URL`** | Same as **`SUPABASE_URL`** |
| **`SUPASET_KEY`** | Same as **`SUPABASE_SERVICE_ROLE_KEY`** |

(Optionally rename workflows later to `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`; until then, map canonical names to the existing secret names.)

**Never** store **`SUPABASE_ACCESS_TOKEN`** in Actions for this flow—provision Supabase locally, then paste URL + service role key only.

## Manual fallback

- Run SQL in **SQL Editor**: copy [`supabase/migrations/20250430180000_init_llmfh.sql`](../supabase/migrations/20250430180000_init_llmfh.sql).
- Create bucket **Storage → New bucket** named **`llmfh`** (or set **`SUPABASE_STORAGE_BUCKET`**).

## Smoke check

With `.env` populated:

```bash
uv run python scripts/preflight_env.py --strict --skip-podbean
uv run pytest tests/integration -m integration
```

(Integration tests require live credentials. OpenRouter-backed tests default to free-tier chat routing unless `LLMFH_INTEGRATION_USE_FREE_OPENROUTER=0`.)
