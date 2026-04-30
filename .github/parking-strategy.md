# Parked GitHub Actions workflows

This directory holds GitHub Actions workflows that should NOT run in the
current monorepo, but WILL run in the post-split `ai-platform-sdk` repo.

GitHub Actions only auto-discovers workflows under `.github/workflows/`,
so the hyphenated `.github-pending/` is intentional — it suppresses
execution here. At carve-out time (see Phase 5 / Task 9 of the
multi-repo restructure plan), this directory is renamed to `.github/`
in the new repo:

```bash
git filter-repo --subdirectory-filter platform-sdk
mkdir -p .github
mv .github-pending/workflows .github/workflows
rmdir .github-pending
```

## Workflows in this directory

- `workflows/release.yml` — fires on `git push --tags v*.*.*`. Runs
  unit tests, then builds and pushes the base Docker image to
  `ghcr.io/narisun/ai-python-base:3.11-sdk{VERSION}` (and the
  `:3.11-sdk-latest` floating tag).

## Operational notes

- **First GHCR push:** GHCR creates the package in the actor namespace
  on first push. After the initial `v0.4.0` tag, you may need to
  manually grant the `ai-platform-sdk` repo "write" access to the
  `ai-python-base` package via GitHub's package settings UI. Subsequent
  pushes work without reconfiguration.

- **Path invariant:** `release.yml` runs `pytest tests/unit -v`. This
  assumes the post-split layout where `platform_sdk/` and `tests/` are
  siblings at the repo root. The carve-out MUST use
  `git filter-repo --subdirectory-filter platform-sdk` (not `--path`)
  so the `platform-sdk/` prefix is stripped uniformly. Any other
  filter-repo invocation will leave `platform_sdk` nested and break the
  workflow.

- **Local Docker testing:** before tagging a release, validate the base
  image build manually:

  ```bash
  cd platform-sdk
  docker build -f docker/base/Dockerfile \
    --build-arg SDK_VERSION=0.4.0 \
    -t ghcr.io/narisun/ai-python-base:3.11-sdk0.4.0 \
    .
  ```

  This is what the workflow runs in CI; testing it locally first
  catches Dockerfile bugs before they hit GHCR.
