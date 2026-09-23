---
name: release
description: Cut a versioned release of podcast-manager (vX.Y.Z tag → versioned GHCR images and a GitHub Release), check what is unreleased, and decide when a release is due. Use when cutting a release, writing release notes, or after merging or deploying, to say whether it is time for one.
---

### What a release is

Deploys and releases are separate. Every merge to `main` publishes `:<sha>` images and can be deployed (`deploy` skill). A release marks a point for people who self-host: a `vX.Y.Z` tag, images tagged `:X.Y.Z` (plus `:X.Y` and `:X` while it is the newest in that line), and a GitHub Release with notes. `.github/workflows/release.yml` does all of it when a tag is pushed. The images are retagged from the commit's `:<sha>`, not rebuilt, so the tagged commit must be on `main` with CI finished.

### What is unreleased

A draft release titled "Unreleased: N commits since vX.Y.Z" tracks it. After every green CI run on `main` the workflow rewrites it from `.github/scripts/unreleased-draft.sh`: counts, new migrations, config changes, the generated PR list, and a verdict on whether to cut. It is a tracker, so never publish it. To check it locally:

```bash
git fetch --tags origin && DRY_RUN=1 .github/scripts/unreleased-draft.sh
```

### When to suggest a cut

After merging a PR or deploying, run the dry run and pass its verdict on to the user in one line. The script's rules (keep them in step with the script):

- **Cut now:** a new migration; a change to `.env.example` or the compose/stack files (upgrading needs action); app changes waiting 14+ days; 10+ app commits waiting.
- **Good time:** app changes waiting 7+ days.
- **Not yet:** otherwise. **No release needed:** only docs, CI or tests changed.

Use judgement on top of that:

- A **security fix**, or a fix for a bug users are hitting (data loss, a wrong playlist write), should go out as a patch release promptly, whatever the counts say.
- Prefer cutting what production already runs and has run cleanly for about a day. If `main` has app changes that aren't deployed yet, suggest deploying first.

### Picking the version

- **Major:** upgrading needs more than pulling the new image. That means a required env or config change, a removed feature someone relied on, or an API change that breaks installed iOS builds.
- **Minor:** new features or behaviour, including migrations that run on their own at container start.
- **Patch:** fixes only.

### Cutting it

1. Write `docs/releases/vX.Y.Z.md`: a short intro, **Highlights** for users (not a PR list, since GitHub appends that), and **Upgrading** (migrations, config, re-login, anything else to do). Base it on the PR bodies since the last tag (`git log vLAST..origin/main`). Land it on `main` through a PR, and follow the style of the earlier files in `docs/releases/`.
2. Once CI on `main` is green for that commit, tag it:
   ```bash
   git fetch origin && git tag -a vX.Y.Z origin/main -m "Podcast Manager X.Y.Z" && git push origin vX.Y.Z
   ```
3. Watch the Release workflow (`gh run list --workflow release.yml`). It waits up to 30 minutes for the `:<sha>` images, retags them, creates the Release, and deletes the Unreleased draft.

If the Release already exists, the workflow leaves it alone. Edit notes after the fact with `gh release edit`. A bad tag can be deleted (`git push origin :vX.Y.Z` plus `gh release delete`) only if nobody has pulled it yet. Otherwise ship the next patch.

### Deploying a release

`IMAGE_TAG=X.Y.Z REGISTRY=ghcr.io/marco308 ./deploy.sh all`, or check out the tag and deploy as usual: the tag's commit has the same `:<sha>` image.
