#!/usr/bin/env bash
# Keep the "Unreleased" draft release in step with main: what has merged since
# the last version tag, and whether it's time to cut the next release. Run by
# the Release workflow after every green CI run on main and after each release
# (which empties it, so the draft is deleted).
#
# Locally, to see the same summary without touching GitHub:
#   git fetch --tags origin && DRY_RUN=1 .github/scripts/unreleased-draft.sh
#
# The draft carries the placeholder tag "unreleased". It is a tracker, not a
# release to publish: releases are cut by pushing a vX.Y.Z tag.
set -euo pipefail

GH_REPO="${GH_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
REF="${REF:-origin/main}"
DRAFT_TAG=unreleased

HEAD_SHA=$(git rev-parse "$REF")
LAST=$(git describe --tags --abbrev=0 --match 'v[0-9]*' "$HEAD_SHA" 2>/dev/null) || {
    echo "No version tag reachable from $REF; nothing to compare against."
    exit 0
}
COMMITS=$(git rev-list --count "$LAST..$HEAD_SHA")

DRAFT_ID=""
if [[ -z "${DRY_RUN:-}" ]]; then
    DRAFT_ID=$(gh api "repos/$GH_REPO/releases?per_page=100" \
        --jq "map(select(.draft and .tag_name == \"$DRAFT_TAG\")) | .[0].id // empty")
fi

if (( COMMITS == 0 )); then
    echo "Nothing merged since $LAST."
    if [[ -n "$DRAFT_ID" ]]; then
        gh api -X DELETE "repos/$GH_REPO/releases/$DRAFT_ID" >/dev/null
        echo "Deleted the Unreleased draft."
    fi
    exit 0
fi

# --- What has changed ---------------------------------------------------------
changed() { git diff --name-only "$LAST" "$HEAD_SHA" -- "$@"; }
APP_PATHS=(backend frontend ios ':(exclude)backend/tests')
# Commits that change what ships (images or the iOS app), not docs, CI or tests.
SHIPPED=$(git rev-list --count "$LAST..$HEAD_SHA" -- "${APP_PATHS[@]}")
MIGRATIONS=$(git diff --diff-filter=A --name-only "$LAST" "$HEAD_SHA" -- 'backend/alembic/versions/*.py' \
    | sed 's|.*/||' | paste -sd, - | sed 's/,/, /g')
ENV_CHANGED=$(changed backend/.env.example docker-compose.yml docker-stack-traefik.example.yml | wc -l | tr -d ' ')
IOS_CHANGED=$(changed ios | wc -l | tr -d ' ')

NOW=$(date -u +%s)
# Age of the oldest waiting app change (or of any change, when none is an app one).
# git log lists newest first, so the oldest is the last line. Not `--reverse |
# head -1`: head exits after one line, git's next write then dies of SIGPIPE,
# and pipefail turns that into exit 141 (it did, on the first run on main).
OLDEST_TS=$(git log --format=%ct "$LAST..$HEAD_SHA" -- "${APP_PATHS[@]}" | tail -1)
OLDEST_TS=${OLDEST_TS:-$(git log --format=%ct "$LAST..$HEAD_SHA" | tail -1)}
OLDEST_DAYS=$(( (NOW - OLDEST_TS) / 86400 ))
LAST_DATE=$(git log -1 --format=%cs "$LAST^{commit}")

# --- When to cut --------------------------------------------------------------
# The rules the release skill (.claude/skills/release) describes; keep in step.
reasons=()
[[ -n "$MIGRATIONS" ]] && reasons+=("a new migration, which self-hosters should get with upgrade notes")
(( ENV_CHANGED > 0 )) && reasons+=("configuration files changed, so upgrading needs action")
(( OLDEST_DAYS >= 14 )) && reasons+=("changes have waited ${OLDEST_DAYS} days")
(( SHIPPED >= 10 )) && reasons+=("${SHIPPED} app changes are waiting")

if (( SHIPPED == 0 )); then
    VERDICT="No release needed: only docs, CI or tests changed."
elif (( ${#reasons[@]} > 0 )); then
    joined=$(printf '%s; ' "${reasons[@]}")
    VERDICT="**Cut a release now:** ${joined%; }."
elif (( OLDEST_DAYS >= 7 )); then
    VERDICT="**Good time to cut a release:** app changes have waited ${OLDEST_DAYS} days."
else
    VERDICT="Not yet, unless one of these is a fix people are hitting or a security fix. Otherwise let it batch with the next change."
fi

yesno() { (( $1 > 0 )) && echo yes || echo no; }
SUMMARY="**Since ${LAST}** (${LAST_DATE}): ${COMMITS} commits; the oldest app change has waited ${OLDEST_DAYS} days.

- Commits that change the app: ${SHIPPED}
- New migrations: ${MIGRATIONS:-none}
- Config files changed (\`.env.example\`, compose/stack files): $(yesno "$ENV_CHANGED")
- iOS app changed: $(yesno "$IOS_CHANGED")

${VERDICT}"

TITLE="Unreleased: ${COMMITS} commits since ${LAST}"

if [[ -n "${DRY_RUN:-}" ]]; then
    echo "$TITLE"
    echo
    echo "$SUMMARY"
    echo
    git log --format='- %s' "$LAST..$HEAD_SHA"
    exit 0
fi

NOTES=$(gh api "repos/$GH_REPO/releases/generate-notes" \
    -f tag_name="$DRAFT_TAG" -f target_commitish="$HEAD_SHA" -f previous_tag_name="$LAST" --jq .body)

BODY="> Kept up to date by the Release workflow. This is a tracker, not a release: don't publish it. Cut a release by pushing a version tag (see \`.claude/skills/release\`).

${SUMMARY}

${NOTES}"

if [[ -n "$DRAFT_ID" ]]; then
    gh api -X PATCH "repos/$GH_REPO/releases/$DRAFT_ID" \
        -f name="$TITLE" -f body="$BODY" -f target_commitish="$HEAD_SHA" >/dev/null
    echo "Updated the Unreleased draft: $TITLE"
else
    gh api -X POST "repos/$GH_REPO/releases" \
        -f tag_name="$DRAFT_TAG" -f target_commitish="$HEAD_SHA" \
        -f name="$TITLE" -f body="$BODY" -F draft=true >/dev/null
    echo "Created the Unreleased draft: $TITLE"
fi
