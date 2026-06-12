---
name: publish-github-release
description: >-
  Publishes a semver GitHub Release (tag + notes) for llm_from_here after merging
  to main. Episode releases run locally via the release-episode skill, not GitHub
  Actions. Use when shipping main, cutting v*.**.**, or when the user asks to
  publish or ship a version tag.
disable-model-invocation: true
---

# Publish a GitHub release (llm_from_here)

## Why this matters

GitHub Releases provide **version tags and release notes** for shipped commits. Episode publishes run **locally** from the repo checkout (see [release-episode/SKILL.md](../release-episode/SKILL.md)); there are no GitHub Actions episode workflows.

## Preconditions

- [ ] Desired commits are **merged into default branch** (typically `main`) and CI on that branch is green enough for your judgment.
- [ ] **`gh` is authenticated** with repo scope (`gh auth status`).

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

### 4. Smoke-verify locally (optional)

After tagging, run a **dev** ShowRunner smoke from the tagged commit if you want parity with the release:

```bash
git checkout v0.X.Y   # or stay on main if tag points there
uv run pytest tests/test*.py
uv run python scripts/preflight_env.py --strict --skip-podbean
uv run python -m llm_from_here.showRunner configs/configv3.yaml --output-dir outputs
```

For prod Podbean publish, follow [release-episode/SKILL.md](../release-episode/SKILL.md) with `LLMFH_ENV=prod` and `--clear-cache`.

## Quick sanity checklist before tagging

- [ ] Version bump committed (`__init__.py` matches forthcoming tag).
- [ ] Default branch pushed **before** `gh release create`.
