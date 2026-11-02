# Running on Delta

On [NCSA Delta](https://docs.ncsa.illinois.edu/systems/delta/en/latest/index.html), Snakemake runs on a login node and submits each scene's `process_scene` job to Slurm as a **1-GPU job**. Building the environment and downloading the weights are small **CPU jobs** (`biyc-delta-cpu`, partition `cpu`). Fetching the sample scenes (`download_imagery`) still runs on the login node, which has internet access.

| File | What it sets |
|---|---|
| `config/config.delta.yaml` | Paths on Delta, `device: cuda`, CPU cores per job, the scenes to run |
| `profiles/delta/config.yaml` | Slurm executor, account, partition, memory, time limit, 1 GPU per `process_scene` job |
| `run_delta.sh` | Installs uv and Snakemake if missing, and runs Snakemake with both of the above inside `tmux` |

## Layout

| Path | Contents |
|---|---|
| `/projects/biyc/habitat` | This repo checkout and the venv (`venv/`) |
| `/work/hdd/biyc/habitat/data` | Model weights and input scenes |
| `/work/hdd/biyc/habitat/results` | Output shapefiles |
| `/work/hdd/biyc/habitat/benchmarks` | Benchmark files, one folder per config (`benchmarks_dir`) |

Logs (`logs/`) go in the checkout; benchmarks go to `benchmarks_dir` in the config.

!!! note "Allocation name"
    The paths and the Slurm accounts (`biyc-delta-gpu`, and `biyc-delta-cpu` for the CPU jobs) assume HABITAT runs under the **biyc** allocation, like water_timeseries. On a login node, `accounts` lists your allocations. If the GPU allocation has a different name, change the `slurm_account` entries in `profiles/delta/config.yaml` and the `/projects/...` and `/work/hdd/...` paths in `config/config.delta.yaml`.

## First run

Run everything on a Delta login node (`ssh login.delta.ncsa.illinois.edu`).

### 1. Clone under /projects

```bash
cd /projects/biyc
git clone --recurse-submodules https://github.com/PermafrostDiscoveryGateway/HABITAT_SNAKEMAKE.git habitat
mkdir -p /work/hdd/biyc/habitat
chmod -R g+rwX habitat /work/hdd/biyc/habitat
find habitat /work/hdd/biyc/habitat -type d -exec chmod g+s {} +
```

The group permissions let anyone on the allocation run the workflow and reuse the venv.

### 2. Dry run

```bash
/projects/biyc/habitat/run_delta.sh -n
```

The first time, this installs `uv` and Snakemake (with the Slurm executor plugin) into `~/.local/bin`. It then lists the jobs:

| Job | Where | What |
|---|---|---|
| `build_environment` | Slurm, CPU | Builds the venv. A few minutes; torch with its CUDA libraries is several GB. |
| `download_model` | Slurm, CPU | The ~187 MB model from HABITAT's Google Drive folder |
| `download_imagery` | login node | The Yellowknife sample scene (~120 MB read, 130 MB written) |
| `process_scene` | Slurm, 1 GPU | HABITAT on the scene |

### 3. Run

```bash
/projects/biyc/habitat/run_delta.sh
```

This starts Snakemake in a `tmux` session called `habitat`, because Snakemake has to stay running on the login node until the Slurm jobs finish. Detach with `Ctrl-b d`. To reattach, ssh to **the same login node** (`hostname` shows which one, e.g. `dt-login03.delta.ncsa.illinois.edu`) and run:

```bash
tmux attach -t habitat
```

To check on the Slurm job itself:

```bash
squeue -u $USER
```

### 4. Results

- **Polygons:** `/work/hdd/biyc/habitat/results/sample/yellowknife_wv03_20230808_final.shp`. They should match the laptop run.
- **Timing, memory and GPU use:** `/work/hdd/biyc/habitat/benchmarks/sample/<run_id>/process_scene/yellowknife_wv03_20230808.tsv` for the time (compare it with the ~271 s on a laptop CPU), and `./benchmarks.sh` for the time, peak memory and GPU use of every job in the latest run (see [Benchmarks and job statistics](#benchmarks-and-job-statistics)). Use them to set `runtime` and `mem_mb` in the profile.
- **Run log:** `logs/process_scene/yellowknife_wv03_20230808.log`. Slurm's own logs are under `.snakemake/slurm_logs/`.

## Benchmarks and job statistics

Three sources describe how a job went, and they don't measure the same thing:

| Source | What it has | Caution |
|---|---|---|
| Snakemake's benchmark file, one per job; every step has one | Wall time, CPU time and load, a memory figure, file I/O | It samples, so its memory figure can miss short peaks (in darts-nextgen's runs on Delta it was 4% to 20% below `sacct`). It has no GPU column, and the format is fixed by Snakemake. |
| Slurm's accounting, `sacct` | State, elapsed time, peak host memory (`MaxRSS`, in KiB), CPU time, disk I/O, and on Delta the GPU: `gres/gpumem` (GPU memory) and `gres/gpuutil` (GPU utilisation) in the `TRESUsageInMax` field | The best source for peak memory; use it to set `mem_mb`. Slurm's documentation does not say whether `gpuutil` is an average or a peak, so compare runs of the same kind with it, but don't read it as a precise average. Local rules (`download_imagery`) are not Slurm jobs and have no record. |
| `scripts/benchmark_table.py` (`./benchmarks.sh`) | Both of the above in one table: one row per Slurm job (every attempt, failed ones included), with the benchmark's wall time, CPU load and memory next to Slurm's memory, GPU and disk numbers; steps that ran on the login node are listed with state `local` | Run it on Delta, from the repository folder, after a run. It finds the job IDs from `.snakemake/slurm_logs/` and from Snakemake's own run logs in `.snakemake/log/` (the Slurm plugin deletes the log file of a job that succeeded, and every log after 10 days, but the run logs still name them). `sacct` itself keeps records for longer. |

### Runs

Every run writes into its own folder, `<benchmarks_dir>/<run_id>/`, where `run_id` is the UTC time the run started (`20261026T153045Z`). Running the same inputs twice gives two folders, so the runs can be compared. `config/config.delta.yaml` sets `benchmarks_dir` to `/work/hdd/biyc/habitat/benchmarks/sample`; give each new config or region its own, so a region's runs stay together. Without the setting, the folder is `benchmarks/` in the checkout.

`run_delta.sh` sets the id when it starts; the Slurm jobs inherit it, so every job of a run writes into the same folder. A run that has nothing to do (every output exists) and a dry run create no folder. Snakemake skips scenes whose output exists, so to measure the same scenes again, add `--forceall`: `./run_delta.sh --forceall`.

| File | Contents |
|---|---|
| `<run_id>/build_environment.tsv`, `<run_id>/download_model.tsv`, `<run_id>/make_test_data.tsv` | Snakemake's benchmark of that step |
| `<run_id>/download_imagery/<scene>.tsv`, `<run_id>/process_scene/<scene>.tsv` | Snakemake's benchmark of that step for one scene |
| `<run_id>/run.json` | What the run was: `start_time`, `end_time`, `status` (`running`, `success` or `failed`), `host`, `user`, the `command`, the config files and the full `config`, the `scenes`, the HABITAT commit and this repository's commit (`-dirty` if it had uncommitted changes), and the name of Snakemake's run log (which is how the table matches Slurm jobs to the run) |
| `<run_id>/summary.tsv` | The table, as the script last wrote it for this run |

A benchmark file has Snakemake's fixed columns: `s` and `h:m:s` (wall time), `max_rss`, `max_vms`, `max_uss`, `max_pss` (memory, MB), `io_in`, `io_out` (MB read and written), `mean_load` and `cpu_time`. It has no timestamp, run or config of its own; the folder and `run.json` say which run it belongs to, and the table adds what Slurm knows (state, start time, peak memory, GPU).

Snakemake writes a benchmark file when its job succeeds, so a failed attempt leaves none; the table still lists it, from Slurm. Benchmark files written before runs had folders (`<benchmarks_dir>/<rule>/...`) show up as the run `unversioned`.

```bash
./benchmarks.sh
```

This is the table of the latest run (`python3 scripts/benchmark_table.py --config config/config.delta.yaml` does the same; `CONFIG=config/other.yaml ./benchmarks.sh` reads another config's folder). It starts with a line saying what the run was, and writes the table to `<run_id>/summary.tsv`. Other views:

| Command | Shows |
|---|---|
| `./benchmarks.sh --list` | Every run: start, status, config, commits, scene count |
| `./benchmarks.sh --run 20261026` | One run: a `run_id`, the start of one, `latest` or `previous` |
| `./benchmarks.sh --compare` | The latest run against the one before, one row per step: `A -> B (+x%)` for time, host memory, GPU memory and CPU time |
| `./benchmarks.sh --compare 20261025 20261026` | Any two runs |
| `./benchmarks.sh --all` | Every run in one table (also written to `<benchmarks_dir>/summary.tsv`) |

By default every attempt is listed, including failed and cancelled ones (an out-of-memory kill shows as `OUT_OF_MEMORY`); `--completed` lists only the jobs that finished, and `--rules process_scene` limits it to some rules. A Slurm job is matched to its run through the run log named in `run.json`; a job from before this was recorded goes to `unversioned`, or to the latest run that started before the job was submitted. To check one job by hand:

```bash
sacct -j <jobid> --format=JobID,State,Elapsed,MaxRSS,TRESUsageInMax%110
```

The GPU's use over time is not recorded; if that is needed, a sampler would have to run inside the job.

### Measured on Delta

From `benchmark_table.py` after the runs of the 22 NWT tiles (`config/tiles.nwt.yaml`) and the Yellowknife sample, all on `gpuA40x4` (2026-10-25):

| Step | Elapsed | Peak host memory | Peak GPU memory | `gpuutil` | CPU time |
|---|---|---|---|---|---|
| `process_scene`, 23 scenes | 29 to 310 s | 1.7 to 9.3 GiB | 0.0 to 1.1 GiB | 0 to 84 | 26 to 225 s |
| `build_environment` (venv already in place) | 15 s | 0.2 GiB | | | 1 s |
| `download_model` | 18 s | 0.3 GiB | | | 2 s |
| `download_imagery`, Yellowknife (login node) | 44 s (benchmark) | | | | |

HABITAT barely uses the A40: about 1 GiB of its 48 GB, and `gpuutil` reaches the 80s only for the full ~5 km tiles (the Yellowknife window shows 3). Each job used less than one of its 16 cores on average, and most of the time goes to the CPU-side steps (clipping, stitching, morphology, polygonizing). A 1-GPU job is charged as a quarter node, so asking for less memory or fewer cores would not lower the cost; the profile keeps `mem_mb: 60000` and only shortens `runtime`.

## Resources and cost

Set in `profiles/delta/config.yaml`:

| Setting | Value | Why |
|---|---|---|
| `slurm_partition` | `gpuA40x4` | Charged at **0.5×** per GPU-hour, against 1.0× for `gpuA100x4`. HABITAT runs one 512 px tile at a time, which doesn't need an A100. |
| `gpu` (process_scene) | 1 | HABITAT uses a single GPU |
| `threads_per_scene` (config) | 16 | Slurm `--cpus-per-task`. Tiling and post-processing run on the CPU. 16 is a quarter of a 4-GPU node. |
| `mem_mb` | 60000 | HABITAT holds every tile's prediction in memory (~3 MB per tile) until stitching, so full scenes need tens of GB |
| `runtime` | 10 min (process_scene) | Whole ~5 km Maxar tiles took at most about 5 minutes on an A40 (see below). Raise it for larger scenes (Delta's maximum is 48 h). |
| `build_environment`, `download_model` | `cpu` partition, `biyc-delta-cpu`; 8000 MB / 30 min and 2000 MB / 10 min | Small CPU jobs, so they don't use GPU hours. Set from their measured runs (below), with room for a build of the venv from scratch, which hasn't been measured. |
| `jobs` | 8 | Maximum scenes queued or running at once |

To check how much allocation is left:

```bash
accounts
```

To use A100s instead, set `slurm_partition: "gpuA100x4"`. To accept either, set `"gpuA40x4,gpuA100x4"`, but each job is then charged at the rate of whichever partition it lands on.

## Real scenes

Once there are scenes on Delta, edit `config/config.delta.yaml`:

```yaml
scene_dir: /work/hdd/biyc/habitat/data/scenes     # wherever they are
footprint: /work/hdd/biyc/habitat/data/footprints/<file>.shp
# scenes: [...]   # remove to run every *.tif in scene_dir
output_dir: /work/hdd/biyc/habitat/results/<region>
```

Then:
- set `runtime` and `mem_mb` in the profile from the sample's numbers (`python3 scripts/benchmark_table.py --config config/config.delta.yaml`), scaled to the scene size, with some headroom;
- set `benchmarks_dir` to a new folder for the region, so its runs are kept apart from the sample's;
- start with a dry run (`-n`) and one or two scenes, then run the rest.

Snakemake skips finished scenes, and `keep-going` means one failed scene doesn't stop the others. If a run is interrupted, start it again.

## Troubleshooting

| Problem | Likely cause |
|---|---|
| `sbatch: error: Invalid account` | `slurm_account` doesn't match one listed by `accounts` |
| Job pending with `MaxGRESPerAccount` | The allocation's GPU limit is reached; jobs wait in the queue |
| `process_scene` fails with `CUDA error` or `no CUDA GPUs` | The job didn't get a GPU. Check that `gpu: 1` is under `set-resources: process_scene` in the profile. |
| `process_scene` killed with `OUT_OF_MEMORY` | Scene too large for `mem_mb`; raise it (memory above a quarter node may be charged as more GPUs) |
| `process_scene` hits `TIMEOUT` | Raise `runtime` |
| Snakemake stopped when you logged out | It wasn't in `tmux`; use `run_delta.sh` |
