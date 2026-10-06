# Running on Delta

On [NCSA Delta](https://docs.ncsa.illinois.edu/systems/delta/en/latest/index.html), Snakemake runs on a login node and submits each scene's `process_scene` job to Slurm as a **1-GPU job**. Everything else runs on the login node, which has internet access: building the environment, downloading the weights, and fetching the sample scene.

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

Logs (`logs/`) and benchmarks (`benchmarks/`) go in the checkout.

!!! note "Allocation name"
    The paths and the Slurm account (`biyc-delta-gpu`) assume HABITAT runs under the **biyc** allocation, like water_timeseries. On a login node, `accounts` lists your allocations. If the GPU allocation has a different name, change `slurm_account` in `profiles/delta/config.yaml` and the `/projects/...` and `/work/hdd/...` paths in `config/config.delta.yaml`.

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
| `build_environment` | login node | Builds the venv. A few minutes; torch with its CUDA libraries is several GB. |
| `download_model` | login node | The ~187 MB model from HABITAT's Google Drive folder |
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
- **GPU timing:** `benchmarks/process_scene/yellowknife_wv03_20230808.tsv`. Compare it with the ~271 s on a laptop CPU.
- **Run log:** `logs/process_scene/yellowknife_wv03_20230808.log`. Slurm's own logs are under `.snakemake/slurm_logs/`.

## Resources and cost

Set in `profiles/delta/config.yaml`:

| Setting | Value | Why |
|---|---|---|
| `slurm_partition` | `gpuA40x4` | Charged at **0.5×** per GPU-hour, against 1.0× for `gpuA100x4`. HABITAT runs one 512 px tile at a time, which doesn't need an A100. |
| `gpu` (process_scene) | 1 | HABITAT uses a single GPU |
| `threads_per_scene` (config) | 16 | Slurm `--cpus-per-task`. Tiling and post-processing run on the CPU. 16 is a quarter of a 4-GPU node. |
| `mem_mb` | 60000 | HABITAT holds every tile's prediction in memory (~3 MB per tile) until stitching, so full scenes need tens of GB |
| `runtime` | 60 min | Plenty for the sample. Raise it for full scenes (Delta's maximum is 48 h). |
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
- set `runtime` in the profile from the sample's timing, scaled to the scene size, with some headroom;
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
