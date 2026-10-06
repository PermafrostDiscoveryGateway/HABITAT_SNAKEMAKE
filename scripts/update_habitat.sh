#!/usr/bin/env bash
# Fast-forward the HABITAT submodule to the latest origin/main (or the branch
# given as the first argument). run_delta.sh calls this before each real run;
# run it by hand before a local run. Any failure (a snakemake run in
# progress, no network, local changes, diverged history) only warns, and
# HABITAT stays on its current commit (docs/04-updating-habitat.md).
#
# Usage: scripts/update_habitat.sh [branch]

set -uo pipefail

BRANCH="${1:-main}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HABITAT="$REPO_ROOT/HABITAT"

# The checkout is shared by everyone on the allocation, so git's ownership
# check is waived for it.
git_habitat() { git -c safe.directory="$HABITAT" -C "$HABITAT" "$@"; }

old="$(git_habitat rev-parse --short HEAD)" || {
    echo "WARNING: could not read the HABITAT commit; not updating it." >&2
    exit 0
}
skip() {
    echo "WARNING: $1; staying on HABITAT $old." >&2
    exit 0
}

# Moving HABITAT under a running workflow would change the code its queued
# jobs run without changing the commit recorded for their outputs.
if compgen -G "$REPO_ROOT/.snakemake/locks/*" >/dev/null; then
    skip "a snakemake run is in progress here (.snakemake/locks)"
fi

# Untracked files (HABITAT's own __pycache__/) don't block a fast-forward.
status="$(git_habitat status --porcelain --untracked-files=no)" || skip "git status failed"
[[ -z "$status" ]] || skip "HABITAT has local changes"
git_habitat fetch --quiet origin "$BRANCH" || skip "could not fetch origin/$BRANCH"
git_habitat merge --ff-only --quiet FETCH_HEAD || skip "could not fast-forward to origin/$BRANCH"

new="$(git_habitat rev-parse --short HEAD)"
if [[ "$new" != "$old" ]]; then
    echo "Updated HABITAT from $old to $new (origin/$BRANCH)." \
         "Commit the new submodule pointer to record it."
fi
