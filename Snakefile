# HABITAT inference as a Snakemake workflow.
#
# Rules are named after the PDG feature-mapping pipeline steps:
#   Setup (once):   0 build_environment, 1 download_model
#   Per scene:      2 download_imagery, then process_scene for steps 3-8
#                   (clip, tile/patch, inference, stitch,
#                   threshold/morphology/min-size, polygonize)
# process_scene runs all of steps 3-8 in one job, because HABITAT's
# full_pipeline.py passes predictions between them in memory. It runs through
# scripts/habitat_runner.py, which points HABITAT at the paths in the config
# without editing the HABITAT submodule. scripts/update_habitat.sh moves
# HABITAT to the latest origin/main (run_delta.sh calls it before each run).
#
# The rules live in rules/, one file per concern:
#   common.smk      config constants, helpers, build_environment, download_model
#   benchmarks.smk  run.json, written at the start and end of a run
#   imagery.smk     make_test_data, download_imagery
#   inference.smk   process_scene
#
# Local smoke test with a synthetic scene and an untrained model:
#   snakemake --configfile config/config.test.yaml --cores 2
#
# Local run on real data (edit the paths first):
#   snakemake --configfile config/config.local.yaml --cores 2
#
# On NCSA Delta, each `process_scene` job is a 1-GPU Slurm job, and the
# environment build and model download are small CPU jobs (docs/05-running-on-delta.md):
#   ./run_delta.sh
#
# Every rule writes a Snakemake benchmark file into benchmarks_dir/<run_id>/, where
# run_id is the UTC time the run started (e.g. 20261026T153045Z), so two runs of the
# same inputs never overwrite each other. Each run folder also has a run.json (config,
# HABITAT commit, scenes, start/end, status). scripts/benchmark_table.py joins them
# with Slurm's accounting (GPU included): ./benchmarks.sh shows the latest run.
#
# Dry run: add -n.

import os

if not config:
    raise WorkflowError("Pass a config, e.g. --configfile config/config.test.yaml")

# With a cluster executor these run where snakemake runs (the Delta login
# node, which has internet access). Every other rule is submitted as a job; the
# Slurm settings for each (account, partition, memory, time) are in the
# profile, profiles/delta/config.yaml.
localrules:
    all,
    make_test_data,
    download_imagery,


wildcard_constraints:
    scene=r"[^/]+",


include: "rules/common.smk"
include: "rules/benchmarks.smk"
include: "rules/imagery.smk"
include: "rules/inference.smk"


# The default target. It comes after the includes, so it is marked explicitly:
# otherwise the first rule in rules/common.smk would be the default.
rule all:
    default_target: True
    input:
        expand(os.path.join(OUTPUT_DIR, "{scene}_final.shp"), scene=scenes()),
