# Podbean episode management

Reference for the release-episode skill. Podbean operations require explicit user intent. All publish runs are **local**.

## When Podbean runs

| Context | Publishes? |
|---------|------------|
| Local run (default `LLMFH_ENV=dev`) | No — `only_in_prod: True` in `configs/configv3.yaml` |
| Local run with `LLMFH_ENV=prod` | Yes |
| Local free mode (`LLMFH_OPENROUTER_FREE_MODE=1`, no `LLMFH_ENV=prod`) | No |

Plugin: `lfh_podbean` in configv3 — `max_episodes: 3`, `only_in_prod: True`.

**Prod publish command** (defaults to `--clear-cache`):

```bash
LLMFH_ENV=prod uv run python -m llm_from_here.showRunner configs/configv3.yaml --output-dir outputs --clear-cache
```

Confirm with the user before running. Omit `--clear-cache` only when the user explicitly wants to reuse plugin cache.

## Auto-prune (pipeline)

On upload, if episode count ≥ `max_episodes`, the **oldest** listed episode is deleted automatically (`src/llm_from_here/plugins/podbeanManager.py`). This only runs in prod during a successful publish flow.

Do not rely on auto-prune for mistaken publishes — use manual deletion below.

## Manual deletion

Script: `scripts/delete_podbean_episode.py`

**Auth:** `PODBEAN_CLIENT_ID`, `PODBEAN_CLIENT_SECRET` from environment or repo-root `.env`.

### Required guardrails

1. User must **explicitly** request deletion (title substring or episode identifier).
2. **Always** dry-run first; show matches to the user.
3. User confirms matches before real delete.
4. Never echo credentials in chat or logs.

### Commands

```bash
# Step 1: list matches (mandatory)
uv run python scripts/delete_podbean_episode.py --match "Episode 65" --dry-run

# Step 2: delete after user confirms
uv run python scripts/delete_podbean_episode.py --match "Episode 65"
```

### Options

| Flag | Default | Purpose |
|------|---------|---------|
| `--match` | `Episode 65` | Case-insensitive title substring |
| `--dry-run` | off | List only; no delete |
| `--limit` | 50 | Podbean list page size |
| `--timeout` | 30 | HTTP timeout seconds |

### Exit codes

- `0` — success (or dry-run with matches found)
- `1` — no matches, missing creds, or API error

### API flow (for debugging)

1. OAuth `client_credentials` → `https://api.podbean.com/v1/oauth/token`
2. Paginated `GET /v1/episodes`
3. `POST /v1/episodes/{id}/delete` with `delete_media_file=yes`

## Deletion report template

After any delete (dry-run or real), summarize for the user:

```markdown
## Podbean deletion

**Match string:** <substring>
**Dry-run:** yes | no
**Episodes found:** <count>
**Episodes deleted:** <count or 0>

| id | title | action |
|----|-------|--------|
| ... | ... | would delete / deleted |

**User confirmed:** yes | pending
```

## Troubleshooting

| Issue | Check |
|-------|-------|
| Missing creds | `PODBEAN_CLIENT_ID` / `PODBEAN_CLIENT_SECRET` in `.env` |
| No matches | Broaden `--match`; list uses paginated API (increase `--limit` if catalog is large) |
| OAuth failed | Credential rotation on Podbean dashboard |
| Deleted wrong episode | Dry-run first; use more specific `--match` string |
| Publish skipped | `LLMFH_ENV` must be `prod` — see [SKILL.md](SKILL.md) |

## Related

- Preflight without Podbean: `uv run python scripts/preflight_env.py --strict --skip-podbean`
- Local publish path: `LLMFH_ENV=prod` ShowRunner — see [SKILL.md](SKILL.md)
