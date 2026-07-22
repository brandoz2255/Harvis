#!/usr/bin/env bash
# Scan Harvis repo for commits in the last N hours.
# Silent success if no commits. Output summary block if commits found.
set -euo pipefail

HOURS="${1:-1}"
REPO_DIR="/home/node/.openclaw/workspace/Harvis"

[ -d "$REPO_DIR/.git" ] || exit 0

cd "$REPO_DIR"
git fetch --all --quiet 2>/dev/null || exit 0

COMMITS=$(git log --all --since="${HOURS} hours ago" \
  --pretty=format:"- %h %s (%an, %ar)" --abbrev-commit 2>/dev/null | head -20)

[ -z "$COMMITS" ] && exit 0

COMMIT_COUNT=$(echo "$COMMITS" | wc -l)

CHANGED_FILES=$(git log --all --since="${HOURS} hours ago" \
  --name-only --pretty=format: 2>/dev/null \
  | sort -u | grep -v '^$' | head -15)

DIFF_STATS=$(git log --all --since="${HOURS} hours ago" \
  --shortstat --pretty=format: 2>/dev/null \
  | grep -v '^$' | tail -5)

cat <<EOF
COMMITS_COUNT: $COMMIT_COUNT

COMMITS:
$COMMITS

FILES_CHANGED:
$CHANGED_FILES

DIFF_STATS:
$DIFF_STATS
EOF
