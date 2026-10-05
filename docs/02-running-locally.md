# Running locally

Every run needs a config file passed with `--configfile`. Two are provided:

| Config | Use |
|---|---|
| `config/config.test.yaml` | Smoke test: synthetic scene, untrained model |
| `config/config.sample.yaml` | Real model on a free Maxar Open Data scene of Yellowknife |
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

## Model weights

The trained operational model is in the public [HABITAT_model_weights](https://drive.google.com/drive/folders/1wnSIv_oDZlFMHtophpVCiaKSC97uvqEQ) Google Drive folder that HABITAT's README links to. Download `ResNet50-UNet++_512_0.5FTL_0.90A_0.75G_0.5CE_3class.pth` (~187 MB) to `data/model_weights/`:

```bash
mkdir -p data/model_weights
curl -L -o "data/model_weights/ResNet50-UNet++_512_0.5FTL_0.90A_0.75G_0.5CE_3class.pth" \
  "https://drive.usercontent.google.com/download?id=1RW9YmjTa0CiRUJ4-vQraZS2F0rehCA_f&export=download&confirm=t"
```

The other file in that folder (`..._4class.pth`) is an older 4-class model.

## Sample scene: Yellowknife (free imagery)

HABITAT's input imagery is licensed Maxar data, usually obtained through the [Polar Geospatial Center](https://www.pgc.umn.edu/). For testing without it, `config/config.sample.yaml` builds a scene from [Maxar Open Data](https://www.maxar.com/open-data) (CC BY-NC 4.0). It is a 2 km × 2 km window of downtown Yellowknife, NWT, taken by WorldView-3 on 2023-08-08:

```bash
snakemake --configfile config/config.sample.yaml --cores 8
```

The `fetch_maxar_sample` rule (`scripts/fetch_maxar_open_sample.py`) works as follows:
- it reads just that window from the public cloud-optimized GeoTIFFs, so only about 120 MB is downloaded rather than the full files;
- it pansharpens the Blue, Green, Red and NIR1 bands with the panchromatic band;
- it writes a 4,096 × 4,096 pixel, 0.5 m, 4-band uint16 scene to `data/sample/scenes/`.

HABITAT then runs on it with the real weights, and the polygons go to `results/sample/`.

The scene is close to, but not the same as, the PGC pansharpened scenes HABITAT was trained on: the pansharpening method differs, and the projection is UTM 11N rather than polar stereographic. Use it to check that the workflow and model behave sensibly on real imagery, not to measure accuracy.

To add another sample, add an entry under `maxar_open_samples` in the config, giving the `ms_url` and `pan_url` of an ARD tile and a `lon`/`lat` inside it, and list its name under `scenes`. Event catalogs are at `https://maxar-opendata.s3.amazonaws.com/events/catalog.json`.

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
