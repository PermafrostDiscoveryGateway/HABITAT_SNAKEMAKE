#!/usr/bin/env bash
# The benchmark table of the latest run (see docs/05-running-on-delta.md).
#
# Usage, on a Delta login node, from anywhere:
#   ./benchmarks.sh                  # latest run
#   ./benchmarks.sh --compare        # latest run against the one before
#   ./benchmarks.sh --list           # every run
#   ./benchmarks.sh --run 20261026   # one run: its id, or the start of it
#   ./benchmarks.sh --all            # every run in one table
#   CONFIG=config/other.yaml ./benchmarks.sh      # another config's benchmarks_dir
# Any other arguments go to scripts/benchmark_table.py (--help lists them).

set -euo pipefail

CONFIG="${CONFIG:-config/config.delta.yaml}"

# Slurm's job logs are under .snakemake/ in the repo root, so run from there.
cd "$(dirname "${BASH_SOURCE[0]}")"

read -ra CONFIGS <<< "$CONFIG"
exec python3 scripts/benchmark_table.py --config "${CONFIGS[@]}" "$@"
