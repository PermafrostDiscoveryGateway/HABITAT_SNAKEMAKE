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

import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone

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

HABITAT_DIR = config.get("habitat_dir", "HABITAT")
ENV_DIR = config["environment"]["path"]
ENV_PYTHON = os.path.join(ENV_DIR, "bin", "python")
ENV_READY = os.path.join(ENV_DIR, ".ready")

SCENE_DIR = config["scene_dir"]
SCENE_SUFFIX = config.get("scene_suffix", ".tif")
OUTPUT_DIR = config["output_dir"]
FOOTPRINT = config.get("footprint")
MODEL = config.get("model", {})
# Where the benchmark files go: benchmarks/ in the checkout unless the config
# says otherwise, so a config can keep its own.
BENCH_ROOT = config.get("benchmarks_dir") or "benchmarks"

# One folder per run, named by the UTC time the run started. Slurm jobs run
# this Snakefile again, so they must get the run's id rather than make their
# own: it is exported here for the jobs sbatch starts, and run_delta.sh sets it
# up front. `--config run_id=...` overrides it (the table script takes the
# YYYYMMDDTHHMMSSZ form).
RUN_ID = (config.get("run_id") or os.environ.get("HABITAT_RUN_ID")
          or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
if not re.fullmatch(r"\d{8}T\d{6}Z", str(RUN_ID)):
    raise WorkflowError(f"run_id must look like 20261026T153045Z (UTC), not {RUN_ID!r}")
os.environ["HABITAT_RUN_ID"] = str(RUN_ID)
BENCH_DIR = os.path.join(BENCH_ROOT, str(RUN_ID))


# The HABITAT commit is a param of `process_scene`, so moving the submodule to a new
# commit marks existing outputs as out of date (see docs/04-updating-habitat.md).
# The checkout is shared by everyone on the allocation, so git's ownership
# check is waived for it; otherwise anyone but its owner reads no commit and
# every scene reruns.
def habitat_commit():
    habitat = os.path.abspath(HABITAT_DIR)
    git = subprocess.run(["git", "-c", f"safe.directory={habitat}", "-C", habitat,
                          "rev-parse", "HEAD"], capture_output=True, text=True)
    if git.returncode != 0:
        raise WorkflowError(f"Could not read the HABITAT commit in {habitat}:\n"
                            f"{git.stderr.strip()}")
    return git.stdout.strip()


HABITAT_COMMIT = habitat_commit()


def workflow_commit():
    """The commit of this repository, with '-dirty' if it has uncommitted changes."""
    git = ["git", "-C", workflow.basedir]
    head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True)
    if head.returncode != 0:
        return None
    dirty = subprocess.run(git + ["status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
    return head.stdout.strip() + ("-dirty" if dirty else "")


def scenes():
    """Scenes from the config, or every *SCENE_SUFFIX file in scene_dir."""
    if config.get("scenes"):
        return [s[:-len(SCENE_SUFFIX)] if s.endswith(SCENE_SUFFIX) else s
                for s in config["scenes"]]
    return glob_wildcards(os.path.join(SCENE_DIR, "{scene}" + SCENE_SUFFIX)).scene


rule all:
    input:
        expand(os.path.join(OUTPUT_DIR, "{scene}_final.shp"), scene=scenes()),


# What was run, so a benchmark folder says what it measured. Written when the
# jobs start (not on a dry run) and completed when the run ends;
# scripts/benchmark_table.py reads it, including snakemake_log to tell which
# Slurm jobs belong to the run.
RUN_JSON = os.path.join(BENCH_DIR, "run.json")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_run_json(**fields):
    os.makedirs(BENCH_DIR, exist_ok=True)
    info = {}
    if os.path.exists(RUN_JSON):
        with open(RUN_JSON) as fh:
            info = json.load(fh)
    info.update(fields)
    with open(RUN_JSON, "w") as fh:
        json.dump(info, fh, indent=2, default=str)
        fh.write("\n")


onstart:
    run_log = log[0] if isinstance(log, (list, tuple)) and log else log
    update_run_json(
        run_id=str(RUN_ID),
        start_time=utc_now(),
        status="running",
        host=socket.gethostname(),
        user=os.environ.get("USER"),
        command=" ".join(sys.argv),
        snakemake_log=os.path.basename(str(run_log)) if run_log else None,
        configfiles=[str(f) for f in workflow.overwrite_configfiles],
        workflow_commit=workflow_commit(),
        habitat_commit=HABITAT_COMMIT,
        scenes=scenes(),
        config=config,
    )


onsuccess:
    update_run_json(end_time=utc_now(), status="success")


onerror:
    update_run_json(end_time=utc_now(), status="failed")


# Step 0. Python environment for every HABITAT step, rebuilt when the
# requirements change.
rule build_environment:
    input:
        "envs/requirements.txt",
    output:
        touch(ENV_READY),
    params:
        env=ENV_DIR,
        python=config["environment"].get("python", "3.10"),
    log:
        "logs/build_environment.log",
    benchmark:
        os.path.join(BENCH_DIR, "build_environment.tsv")
    shell:
        """
        (uv venv --allow-existing --python {params.python} {params.env} &&
         uv pip install --python {params.env}/bin/python -r {input}) > {log} 2>&1
        """


# Step 1. Model weights, downloaded when the config gives a weights_url and the file
# isn't already at `weights`.
rule download_model:
    output:
        config["weights"],
    params:
        url=config.get("weights_url", ""),
    log:
        "logs/download_model.log",
    benchmark:
        os.path.join(BENCH_DIR, "download_model.tsv")
    shell:
        """
        if [ -z "{params.url}" ]; then
            echo "{output} is missing and the config has no weights_url" > {log}; exit 1
        fi
        curl -fsSL -o {output:q} "{params.url}" 2> {log}
        """


# The smoke test's untrained model comes from make_test_data, not a download.
ruleorder: make_test_data > download_model


# Not a pipeline step: synthetic inputs referenced by config/config.test.yaml.
rule make_test_data:
    input:
        ENV_READY,
    output:
        scene="test_data/scenes/synthetic_scene.tif",
        footprint="test_data/footprints/footprints.shp",
        weights="test_data/weights/untrained_unetpp.pth",
    log:
        "logs/make_test_data.log",
    benchmark:
        os.path.join(BENCH_DIR, "make_test_data.tsv")
    shell:
        """
        {ENV_PYTHON} scripts/make_test_data.py --scene {output.scene} \
            --footprint {output.footprint} --weights {output.weights} > {log} 2>&1
        """


# Step 2. Test scenes cut from Maxar Open Data, listed under maxar_open_samples in
# the config (see config/config.sample.yaml).
SAMPLES = config.get("maxar_open_samples") or {}


rule download_imagery:
    input:
        ENV_READY,
    output:
        os.path.join(SCENE_DIR, "{sample}" + SCENE_SUFFIX),
    wildcard_constraints:
        sample="|".join(SAMPLES) or "^$",
    params:
        s=lambda wc: SAMPLES[wc.sample],
    log:
        "logs/download_imagery/{sample}.log",
    benchmark:
        os.path.join(BENCH_DIR, "download_imagery", "{sample}.tsv")
    shell:
        """
        {ENV_PYTHON} scripts/fetch_maxar_open_sample.py \
            --ms-url {params.s[ms_url]} --pan-url {params.s[pan_url]} \
            --lon {params.s[lon]} --lat {params.s[lat]} --size-m {params.s[size_m]} \
            --out {output} > {log} 2>&1
        """


# Steps 3-8 for one scene, on one GPU.
rule process_scene:
    input:
        env=ENV_READY,
        scene=os.path.join(SCENE_DIR, "{scene}" + SCENE_SUFFIX),
        weights=config["weights"],
        footprint=[FOOTPRINT] if FOOTPRINT else [],
    output:
        os.path.join(OUTPUT_DIR, "{scene}_final.shp"),
    params:
        image=lambda wc: wc.scene + SCENE_SUFFIX,
        footprint=f"--footprint {FOOTPRINT}" if FOOTPRINT else "",
        device=config.get("device", "cuda"),
        no_data=config.get("no_data_value", 0),
        size=MODEL.get("size", 512),
        overlap=MODEL.get("overlap", 0.5),
        classes=MODEL.get("classes", 3),
        encoder=MODEL.get("encoder", "resnet50"),
        habitat_commit=HABITAT_COMMIT,
    log:
        "logs/process_scene/{scene}.log",
    benchmark:
        os.path.join(BENCH_DIR, "process_scene", "{scene}.tsv")
    threads: config.get("threads_per_scene", 1)
    shell:
        """
        (echo "HABITAT commit: {params.habitat_commit}"
         OMP_NUM_THREADS={threads} {ENV_PYTHON} scripts/habitat_runner.py \
            --habitat-dir {HABITAT_DIR} --scene-dir {SCENE_DIR} --output-dir {OUTPUT_DIR} \
            --weights {input.weights} --image {params.image} {params.footprint} \
            --device {params.device} --no-data-value {params.no_data} \
            --size {params.size} --overlap {params.overlap} --classes {params.classes} \
            --encoder {params.encoder}) > {log} 2>&1
        """
