# How it works

## Layout

```
HABITAT_SNAKEMAKE/
├── HABITAT/                    # submodule, never edited here
├── Snakefile                   # the workflow
├── config/
│   ├── config.test.yaml        # smoke test
│   └── config.local.yaml       # real scenes, local machine
├── envs/requirements.txt       # HABITAT's Python environment
├── scripts/
│   ├── habitat_runner.py       # runs HABITAT for one scene with our config
│   └── make_test_data.py       # synthetic inputs for the smoke test
├── docs/                       # this site
└── mkdocs.yml
```

## Rules

| Rule | Runs | Output |
|---|---|---|
| `build_env` | Once, and again when `envs/requirements.txt` changes | `.venv-habitat/` |
| `make_test_data` | Only when a config asks for the files under `test_data/` | Synthetic scene, footprint, weights |
| `infer` | Once per scene | `<output_dir>/<scene>_final.shp` |
| `all` | Default target | All scenes' shapefiles |

`infer` replaces HABITAT's `run_workflow.py`, which wrote and `sbatch`-ed one job file per scene. Snakemake handles that now, along with throttling, retries and skipping finished scenes.

## Getting the config into HABITAT

Every HABITAT module starts with `from operational_config import *`, and `dataloader.py` also runs `from final_model_config import *`. Both files hardcode paths on the cluster HABITAT was developed on.

Setting `PYTHONPATH` doesn't override them, because running `python HABITAT/full_pipeline.py` puts `HABITAT/` first on `sys.path`. Instead, `scripts/habitat_runner.py`:

1. builds an `Operational_Config` class from its command-line arguments (which the `infer` rule fills in from the config), and a minimal `Final_Config`;
2. puts them into `sys.modules` as `operational_config` and `final_model_config`, so HABITAT's imports get these instead of its own files;
3. adds `HABITAT/` to `sys.path` and runs `full_pipeline.py --image=<scene>` with `runpy`.

A side benefit is that HABITAT's real `final_model_config.py` is never imported. Importing it builds a ResNet101 model and downloads ImageNet weights, which inference doesn't need.

The runner also handles three other things:

- **No GPU.** HABITAT calls `.to('cuda')` directly. When `device` is `cpu` or `mps`, the runner sends those calls to that device instead, and loads the weights with `map_location` set to it.
- **TensorFlow.** `dataloader.py` imports TensorFlow, but only uses it for training. If it isn't installed, the runner puts a stub in its place.
- **Running without a footprint.** `full_pipeline.py` sets `no_data_value` only when it clips to a footprint, but uses it either way. With `footprint: null`, the runner provides it from the config.

All of this depends on HABITAT's module and attribute names, so check it again whenever HABITAT is updated ([Updating HABITAT](04-updating-habitat.md)).
