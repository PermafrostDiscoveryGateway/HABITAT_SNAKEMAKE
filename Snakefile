# HABITAT inference as a Snakemake workflow.
#
# One `infer` job per scene runs HABITAT's full_pipeline.py (clip -> tile ->
# infer -> stitch -> morphology -> georeference -> polygonize) through
# scripts/habitat_runner.py, which points HABITAT at the paths in the config
# without editing the HABITAT submodule.
#
# Local smoke test with a synthetic scene and an untrained model:
#   snakemake --configfile config/config.test.yaml --cores 2
#
# Local run on real data (edit the paths first):
#   snakemake --configfile config/config.local.yaml --cores 2
#
# Dry run: add -n.

import os
import subprocess

if not config:
    raise WorkflowError("Pass a config, e.g. --configfile config/config.test.yaml")


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

# The HABITAT commit is a param of `infer`, so moving the submodule to a new
# commit marks existing outputs as out of date (see docs/04-updating-habitat.md).
HABITAT_COMMIT = subprocess.run(["git", "-C", HABITAT_DIR, "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip() or "unknown"


def scenes():
    """Scenes from the config, or every *SCENE_SUFFIX file in scene_dir."""
    if config.get("scenes"):
        return [os.path.splitext(s)[0] if s.endswith(SCENE_SUFFIX) else s
                for s in config["scenes"]]
    return glob_wildcards(os.path.join(SCENE_DIR, "{scene}" + SCENE_SUFFIX)).scene


rule all:
    input:
        expand(os.path.join(OUTPUT_DIR, "{scene}_final.shp"), scene=scenes()),


# Python environment for every HABITAT step, rebuilt when the requirements change.
rule build_env:
    input:
        "envs/requirements.txt",
    output:
        touch(ENV_READY),
    params:
        env=ENV_DIR,
        python=config["environment"].get("python", "3.10"),
    log:
        "logs/build_env.log",
    shell:
        """
        (uv venv --allow-existing --python {params.python} {params.env} &&
         uv pip install --python {params.env}/bin/python -r {input}) > {log} 2>&1
        """


# Synthetic inputs referenced by config/config.test.yaml.
rule make_test_data:
    input:
        ENV_READY,
    output:
        scene="test_data/scenes/synthetic_scene.tif",
        footprint="test_data/footprints/footprints.shp",
        weights="test_data/weights/untrained_unetpp.pth",
    log:
        "logs/make_test_data.log",
    shell:
        """
        {ENV_PYTHON} scripts/make_test_data.py --scene {output.scene} \
            --footprint {output.footprint} --weights {output.weights} > {log} 2>&1
        """


rule infer:
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
        "logs/infer/{scene}.log",
    benchmark:
        "benchmarks/infer/{scene}.tsv"
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
