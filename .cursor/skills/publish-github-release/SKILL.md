---
name: publish-github-release
description: >-
  Publishes a new GitHub Release (semver tag + notes) for llm_from_here so CI workflows that checkout releases/latest pick up new code. Use when shipping main after merging work, cutting v*.**.**, triggering Episode Release workflows, or when the user asks to publish or ship a release.
disable-model-invocation: true
---

# Publish a GitHub release (llm_from_here)

## Why this matters

`.github/workflows/release_episode.yml` and `.github/workflows/release_episode_test.yml` **checkout the latest GitHub Release tag**, not `main`. Until a new **GitHub Release** exists pointing at merged commits, those workflows still run **older code**.

## Preconditions

- [ ] Desired commits are **merged into default branch** (typically `main`) and CI on that branch is green enough for your judgment.
- [ ] **`gh` is authenticated** with repo scope (`gh auth status`).
- [ ] GitHub Actions secrets exist (`OPENROUTER_API_KEY`, `YT_API_KEY`, etc.). Refresh via `.env` + `gh secret set` if needed (never echo secret values in chat logs).

## One canonical flow

### 1. Pick version

Tags use a **`v` prefix** (examples already on remote: `v0.9.2`). Pick next semver bump (`patch`, `minor`, `major`).

### 2. Align packaged version

Dynamic packaging reads **`src/llm_from_here/__init__.py`** `__version__`. Before tagging:

- Set `__version__ = '<semver-without-v-prefix>'` to match the tag number **exactly** (e.g. tag `v0.10.0` → `'0.10.0'`).
- Commit on **`main`** (or merge PR that bumps this).

### 3. Create the GitHub Release (recommended)

From the repo root, on tip of **`main`** with releases fetched:

```bash
git checkout main && git pull origin main
TAG=v0.X.Y    # replace
git push origin main      # ensure bump commit is on origin main first if applicable

gh release create "$TAG" --repo mibass/llm_from_here --generate-notes --title "$TAG"
```

`gh release create` builds the release **from current HEAD on default branch** and creates the tag (`TAG`) pointing there unless it already exists.

**Alternative**: manual annotated tag + `gh release create` from existing tag:

```bash
git pull origin main
git tag -a v0.X.Y -m "v0.X.Y"
git push origin v0.X.Y
gh release create v0.X.Y --repo mibass/llm_from_here --generate-notes
```

### 4. Smoke-verify workflows

- **Test Episode Release** (`workflow_dispatch`): pulls **`releases/latest`**. Run once after publishing so ShowRunner runs against **the tag just shipped**.
- **Episode Release** (scheduled prod): ensure **`LLMFH_ENV`** expectations match prod Podbean behavior.

Optional Actions parity:

- If production uploads rely on **`SUPABASE_STORAGE_BUCKET`**, ensure CI workflows expose it via **`env`** or duplicate YAML bucket naming (`configs/configv3.yaml`).

### 5. Never expose secrets

Sync `.env` → Actions secrets with `gh secret set` piping stdin only; never print secret bodies into transcripts.

## Quick sanity checklist before tagging

- [ ] Version bump committed (`__init__.py` matches forthcoming tag).
- [ ] Default branch pushed **before** `gh release create`.
- [ ] Release workflows documented caveat remembered (they ignore unpublished commits).
