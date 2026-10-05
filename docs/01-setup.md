# Setup

## Requirements

- **Snakemake** 8 or later
- **[uv](https://docs.astral.sh/uv/)**, used by the workflow to build HABITAT's Python environment
- **git**

The packages HABITAT itself needs (torch, segmentation-models-pytorch, rasterio, geopandas, …) don't need to be installed by hand. The `build_env` rule installs them into `.venv-habitat/` the first time the workflow runs, from the versions pinned in `envs/requirements.txt`.

One way to install the two tools:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install snakemake
```

## Cloning

HABITAT is a git submodule, so clone with `--recurse-submodules`:

```bash
git clone --recurse-submodules https://github.com/PermafrostDiscoveryGateway/HABITAT_SNAKEMAKE.git
```

If you already cloned without it, the `HABITAT/` folder will be empty. Fill it in with:

```bash
git submodule update --init
```

To have `git pull` keep the submodule in step automatically, run this once per clone:

```bash
git config submodule.recurse true
```

## Python versions

HABITAT was written for Python 3.7 and torch 1.10. The environment here uses Python 3.10 with the newest versions that still support the older library calls HABITAT makes:

| Package | Pin | Why |
|---|---|---|
| `segmentation-models-pytorch` | 0.2.1 | The model weights are a pickled 0.2.1 model |
| `tifffile` | 2021.11.2 | `postprocess.py` uses `tiff.imsave`, removed later |
| `scikit-image` | 0.19.3 | `postprocess.py` passes `selem=`, removed later |
| `numpy` | 1.26 | Required by the above |

Changing `envs/requirements.txt` rebuilds the environment on the next run.
