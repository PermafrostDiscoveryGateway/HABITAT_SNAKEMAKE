# Running locally

Every run needs a config file passed with `--configfile`. Two are provided:

| Config | Use |
|---|---|
| `config/config.test.yaml` | Smoke test: synthetic scene, untrained model |
| `config/config.local.yaml` | Real scenes on this machine (edit the paths first) |

Add `-n` to any command for a dry run that lists the jobs without running them.

## Smoke test

```bash
snakemake --configfile config/config.test.yaml --cores 2
```

On the first run this:

1. builds `.venv-habitat/` (`build_env`, a few minutes);
2. creates a synthetic 1024×1024, 4-band scene in EPSG:3413, a footprint shapefile for it, and an untrained UNet++ model (`make_test_data`, written to `test_data/`);
3. runs HABITAT on the scene on the CPU (`infer`, about a minute).

The result is `results/test/synthetic_scene_final.shp`. Because the model is untrained, the polygons are meaningless; what matters is that the file exists and is georeferenced inside the footprint.

## Real scenes

Edit `config/config.local.yaml`:

```yaml
scene_dir: data/scenes            # input Maxar GeoTIFFs (4+ bands; HABITAT uses bands 2-4)
scene_suffix: .tif
# scenes: [scene_a, scene_b]      # optional; default is every *.tif in scene_dir

footprint: data/footprints/footprints.shp   # S_FILENAME column = scene file name; null to skip clipping
no_data_value: 0                            # used only when footprint is null

weights: data/model_weights/<name>.pth      # pickled torch model from HABITAT's model_train.py
output_dir: results/local

device: cpu          # or mps on Apple silicon
threads_per_scene: 4

model:               # must match how the weights were trained
  size: 512
  overlap: 0.5
  classes: 3
  encoder: resnet50
```

Then:

```bash
snakemake --configfile config/config.local.yaml --cores 4
```

`--cores` caps the total CPU threads. Each scene uses `threads_per_scene` of them, so `--cores 8` with `threads_per_scene: 4` runs two scenes at once.

!!! note
    Each scene's footprint is looked up in the footprint shapefile by its file name (`S_FILENAME`). A scene that is missing from the shapefile fails.

## Outputs

| Path | Contents |
|---|---|
| `<output_dir>/<scene>_final.shp` (+ `.dbf`, `.shx`, `.prj`, `.cpg`) | Infrastructure polygons with a `class` attribute |
| `logs/infer/<scene>.log` | HABITAT's output for the scene, starting with the HABITAT commit used |
| `benchmarks/infer/<scene>.tsv` | Runtime for the scene (`s` column, in seconds) |
| `logs/build_env.log` | Environment build output |

HABITAT deletes its intermediate rasters (clipped, stitched, morphed, georeferenced) once a scene is done.

Snakemake skips scenes whose output already exists, so an interrupted run can just be started again. To redo one scene, delete its `_final.shp` or pass `--forcerun infer` with that output as the target.

## Using the benchmarks

The runtimes in `benchmarks/infer/` are the basis for estimating GPU-hours on Delta. To combine them:

```bash
cat benchmarks/infer/*.tsv | awk '$1!="s" {n++; s+=$1} END {printf "%d scenes, mean %.0f s\n", n, s/n}'
```
