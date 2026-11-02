# What was run, so a benchmark folder says what it measured. Written when the
# jobs start (not on a dry run) and completed when the run ends;
# scripts/benchmark_table.py reads it, including snakemake_log to tell which
# Slurm jobs belong to the run.
#
# Needs RUN_ID, BENCH_DIR, HABITAT_COMMIT, workflow_commit() and scenes() from
# rules/common.smk.

import json
import os
import socket
import sys
from datetime import datetime, timezone


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
