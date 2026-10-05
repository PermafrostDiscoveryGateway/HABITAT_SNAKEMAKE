# HABITAT_SNAKEMAKE

Runs [HABITAT](https://github.com/PermafrostDiscoveryGateway/HABITAT) inference (mapping Arctic infrastructure from sub-meter Maxar imagery) as a [Snakemake](https://snakemake.readthedocs.io/) workflow. It runs locally now, and is being set up to run on [NCSA Delta](https://docs.ncsa.illinois.edu/systems/delta/en/latest/index.html).

HABITAT is included unmodified as a git submodule. This repository adds only the orchestration around it: the workflow, its configs, the Python environment and these docs.

## Quick start

```bash
git clone --recurse-submodules https://github.com/PermafrostDiscoveryGateway/HABITAT_SNAKEMAKE.git
cd HABITAT_SNAKEMAKE
snakemake --configfile config/config.test.yaml --cores 2
```

This runs the full pipeline on a synthetic scene with an untrained model, as a check that everything works. See [Running locally](02-running-locally.md) for real data.

## Contents

1. [Setup](01-setup.md): what to install, cloning with the submodule
2. [Running locally](02-running-locally.md): the smoke test, real scenes, configuration, outputs
3. [How it works](03-how-it-works.md): the workflow rules and how the config gets into HABITAT
4. [Updating HABITAT](04-updating-habitat.md): moving to a newer HABITAT commit
