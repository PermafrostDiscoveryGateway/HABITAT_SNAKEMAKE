# Shared by every HABITAT workflow: config constants, helpers, the run's id and
# benchmark folder, and the two setup steps (0 build_environment, 1 download_model).
# Included first by the Snakefile, so everything below is defined before any other
# rule file is read.

import os
import re
import subprocess
from datetime import datetime, timezone


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
