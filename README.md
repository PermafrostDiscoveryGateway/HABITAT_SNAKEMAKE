# HABITAT_SNAKEMAKE

Runs [HABITAT](https://github.com/PermafrostDiscoveryGateway/HABITAT) inference with Snakemake. The goal is running it on NCSA Delta, but for now it runs locally.

**Documentation:** <https://PermafrostDiscoveryGateway.github.io/HABITAT_SNAKEMAKE/> (source in [`docs/`](docs/))

HABITAT is included as a git submodule (`HABITAT/`) pinned to a specific commit, and is never edited here. Each scene becomes one `infer` job, which runs HABITAT's `full_pipeline.py` (clip → tile → infer → stitch → morphology → georeference → polygonize) and writes `<output_dir>/<scene>_final.shp`.

## Quick start

You need `snakemake` (8 or later) and [`uv`](https://docs.astral.sh/uv/). The workflow builds HABITAT's own Python environment on first run.

```bash
git clone --recurse-submodules https://github.com/PermafrostDiscoveryGateway/HABITAT_SNAKEMAKE.git
cd HABITAT_SNAKEMAKE
snakemake --configfile config/config.test.yaml --cores 2
```

This smoke test runs the full pipeline on a synthetic scene with an untrained model.

To run the real model on real imagery without licensed data, download the weights (see [Running locally](docs/02-running-locally.md#model-weights)) and run `snakemake --configfile config/config.sample.yaml --cores 8`. That builds a 2 km scene of downtown Yellowknife from Maxar Open Data.

For your own scenes, edit `config/config.local.yaml`, then run:

```bash
snakemake --configfile config/config.local.yaml --cores 4
```

See [Running locally](docs/02-running-locally.md) for configuration and outputs.

## Keeping HABITAT up to date

This repo records one HABITAT commit, and the workflow always runs that commit. New commits to HABITAT have no effect here until the submodule is updated and the change is committed. That way, every result traces back to the exact HABITAT code that produced it; the commit is printed at the top of each `logs/infer/<scene>.log`.

To move to the latest HABITAT:

```bash
git submodule update --remote HABITAT          # check out HABITAT's latest main
git diff --submodule=log HABITAT               # review what changed
snakemake --configfile config/config.test.yaml --cores 2   # smoke test
git add HABITAT && git commit -m "Update HABITAT to $(git -C HABITAT rev-parse --short HEAD)"
git push
```

When reviewing the changes, check for anything `scripts/habitat_runner.py` depends on:
- new or renamed `Operational_Config` attributes;
- renamed modules;
- a different output file name;
- new dependencies, which go in `envs/requirements.txt`.

After someone else updates it, run `git submodule update --init` after `git pull`, or set `git config submodule.recurse true` once so `git pull` does it automatically.

Snakemake treats outputs made with an older HABITAT commit as out of date and reruns them. Add `--rerun-triggers mtime` to keep them.

The full checklist is in [Updating HABITAT](docs/04-updating-habitat.md).
