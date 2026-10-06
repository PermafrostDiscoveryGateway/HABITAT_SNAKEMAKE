#!/usr/bin/env bash
# Run HABITAT on Delta (see docs/05-running-on-delta.md).
#
# Usage, from anywhere, on a Delta login node:
#   ./run_delta.sh                 # run config/config.delta.yaml
#   ./run_delta.sh -n              # dry run; any arguments go to snakemake
#   CONFIG=config/other.yaml ./run_delta.sh
#
# A real run is started inside a tmux session (habitat), since snakemake has
# to keep running on the login node until every Slurm job is done. Detach
# with Ctrl-b d; reattach from the same login node with
#   tmux attach -t habitat
#
# Nothing needs to be activated first: snakemake comes from `uv tool install`
# (~/.local/bin), and every job runs with the venv the build_environment rule builds
# at environment.path in the config.

set -euo pipefail

CONFIG="${CONFIG:-config/config.delta.yaml}"

# Repo root = the directory holding this script, wherever it's checked out.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# Shared allocation directories stay group-writable.
umask 002

# A virtualenv or conda env activated in this shell would only get in the way.
unset VIRTUAL_ENV CONDA_PREFIX PYTHONPATH PYTHONHOME

export PATH="$HOME/.local/bin:$PATH"

if [[ ! -f HABITAT/full_pipeline.py ]]; then
    echo "Fetching the HABITAT submodule"
    git submodule update --init
fi
if ! command -v uv >/dev/null; then
    echo "Installing uv into ~/.local/bin"
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
if ! command -v snakemake >/dev/null; then
    echo "Installing snakemake + the Slurm executor plugin with uv"
    uv tool install snakemake --with snakemake-executor-plugin-slurm
fi

CMD=(snakemake --configfile "$CONFIG" --profile profiles/delta "$@")

DRY_RUN=false
for arg in "$@"; do
    [[ "$arg" == "-n" || "$arg" == "--dry-run" || "$arg" == "--dryrun" ]] && DRY_RUN=true
done

# Already in tmux, or just a dry run: run here.
if [[ -n "${TMUX:-}" || "$DRY_RUN" == true ]]; then
    echo "Running in $REPO_ROOT on $(hostname):"
    echo "  ${CMD[*]}"
    exec "${CMD[@]}"
fi

SESSION="habitat"
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session $SESSION already exists on $(hostname); attaching to it."
    exec tmux attach -t "$SESSION"
fi

echo "Starting tmux session $SESSION on $(hostname)."
echo "Detach with Ctrl-b d; reattach later with: ssh $(hostname) then tmux attach -t $SESSION"
# Re-run this script inside tmux ($TMUX is set there, so it runs snakemake
# directly), then keep a shell open so the output stays readable afterwards.
tmux new-session -d -s "$SESSION" -c "$REPO_ROOT" \
    "$(printf '%q ' env CONFIG="$CONFIG" "$0" "$@"); exec bash"
exec tmux attach -t "$SESSION"
