# HABITAT_SNAKEMAKE

Runs [HABITAT](https://github.com/PermafrostDiscoveryGateway/HABITAT) inference with Snakemake. The goal is running it on NCSA Delta, but for now it runs locally.

HABITAT is included as a git submodule (`HABITAT/`) pinned to a specific commit, and is never edited here. Each scene becomes one `infer` job, which runs HABITAT's `full_pipeline.py` (clip → tile → infer → stitch → morphology → georeference → polygonize) and writes `<output_dir>/<scene>_final.shp`.

## Setup

```bash
git clone --recurse-submodules https://github.com/PermafrostDiscoveryGateway/HABITAT_SNAKEMAKE.git
cd HABITAT_SNAKEMAKE
```

(In an existing clone: `git submodule update --init`.)

You need `snakemake` (8 or later) and [`uv`](https://docs.astral.sh/uv/). The Python environment HABITAT runs in (`.venv-habitat/`, pinned in `envs/requirements.txt`) is built by the workflow on first run, so there is nothing to activate.

## Smoke test

This test creates a synthetic 4-band scene, a footprint and an **untrained** model, then runs the full pipeline on them on the CPU:

```bash
snakemake --configfile config/config.test.yaml --cores 2
```

The output goes to `results/test/synthetic_scene_final.shp`. The polygons are meaningless; the test only shows that every step runs.

## Running on real scenes

Edit `config/config.local.yaml`: set `scene_dir`, `footprint`, `weights` and the `model` settings matching those weights. Then:

```bash
snakemake --configfile config/config.local.yaml --cores 4 -n   # dry run
snakemake --configfile config/config.local.yaml --cores 4
```

Snakemake skips scenes whose `_final.shp` already exists, so an interrupted run can just be restarted.

| Path | What |
|---|---|
| `logs/infer/<scene>.log` | HABITAT's output for each scene |
| `benchmarks/infer/<scene>.tsv` | Runtime per scene (use these to estimate GPU-hours) |
| `logs/build_env.log` | Environment build |

## How the config gets into HABITAT

HABITAT reads its settings from `operational_config.py` and `final_model_config.py`, which hardcode paths on the original cluster. `scripts/habitat_runner.py` puts replacement modules under those names into `sys.modules` before running `full_pipeline.py`, so HABITAT uses the paths from our config. The runner also:

- sends HABITAT's hardcoded `.to('cuda')` calls to `device` (`cpu`, or `mps` on Apple silicon) when there is no GPU, and loads the weights with `map_location` set to that device;
- stubs out `tensorflow`, which HABITAT only uses for training;
- supplies `no_data_value` when `footprint` is null (`full_pipeline.py` otherwise fails with a NameError in that case).

These rely on HABITAT's module and attribute names, so after moving the submodule to a newer HABITAT commit, run the smoke test again.
