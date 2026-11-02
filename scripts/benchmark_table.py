"""One table of how each step of the workflow went: Snakemake's benchmarks plus Slurm's accounting.

Snakemake's benchmark file has wall time, CPU and a memory figure that can miss short
peaks, but nothing about the GPU. Slurm's accounting (`sacct`) on Delta also has the
job's state, the peak host memory, the peak GPU memory (gres/gpumem), a GPU utilisation
figure (gres/gpuutil), CPU time and disk I/O. This script finds the Slurm job IDs of
the workflow's jobs, asks sacct about them, and prints one row per job, with the
benchmark's wall time and CPU load beside it.

Every run of the workflow writes into its own folder, <benchmarks_dir>/<run_id>/, where
run_id is the UTC time the run started (20261026T153045Z). The folder has the benchmark
files and a run.json (config, HABITAT commit, scenes, start, end, status), so two runs of
the same inputs can be compared. Run this on Delta, from the repository folder, after a
run (or use ./benchmarks.sh, which does that with config/config.delta.yaml):

    python3 scripts/benchmark_table.py --config config/config.delta.yaml            # the latest run
    python3 scripts/benchmark_table.py --config config/config.delta.yaml --list     # every run
    python3 scripts/benchmark_table.py --config config/config.delta.yaml --run 20261026
    python3 scripts/benchmark_table.py --config config/config.delta.yaml --all      # every run, one table
    python3 scripts/benchmark_table.py --config config/config.delta.yaml --compare  # latest vs the one before
    python3 scripts/benchmark_table.py --config config/config.delta.yaml --compare 20261025 latest
    python3 scripts/benchmark_table.py --config config/config.delta.yaml --rules process_scene

--run takes a run_id, the start of one (a date is enough if it is unique), `latest` or
`previous`. Steps that ran without Slurm (download_imagery and make_test_data, which are
local rules, or every step of a run on a laptop) have a benchmark file but no Slurm job;
they are listed too, with state `local` and only the benchmark's columns. With no Slurm
jobs at all, sacct is not called, so the script also works off Delta:

    python3 scripts/benchmark_table.py --config config/config.sample.yaml

The benchmarks folder is the config's `benchmarks_dir` (default `benchmarks`), which
--config reads; or name it yourself with --benchmarks. Files written before runs had
their own folders (<benchmarks_dir>/<rule>/...) are shown as run `unversioned`. By
default every attempt is listed, failed and cancelled ones too; --completed lists only
the jobs that finished (state COMPLETED). The table is also written to
<benchmarks folder>/<run_id>/summary.tsv (<benchmarks folder>/summary.tsv for --all;
--out changes that).

A Slurm job is matched to its run through run.json, which names Snakemake's run log
(.snakemake/log/...), and that log names the jobs it submitted. The Slurm plugin
deletes the log file of a job that succeeded and keeps only failed ones (and clears all
of them after 10 days): the file names under
.snakemake/slurm_logs/rule_<rule>/<wildcards>/<job id>.log add to the run logs' list.
A job no run log accounts for goes to the latest run that started before it was
submitted. Every attempt is listed, including failed ones (an out-of-memory kill shows
as OUT_OF_MEMORY). Uses only the standard library.

Columns:
  run_id          the run (UTC start time); only printed when several runs are shown
  rule, label     the rule and its wildcards, e.g. process_scene yellowknife_wv03_20230808
  job_id, state, partition, elapsed_s     from sacct (`local` for steps that ran without Slurm)
  start_time      when sacct says the job started, in UTC (`-` for local steps)
  host_mem_gib    peak memory (sacct MaxRSS, KiB in sacct; shown in GiB). Use this,
                  not the benchmark's max_rss, to size mem_mb: the benchmark samples
                  and can miss peaks
  gpu_mem_gib     peak GPU memory (sacct gres/gpumem), GiB
  gpu_util_pct    sacct gres/gpuutil as reported. Slurm's documentation does not say
                  whether this is an average or a peak, so compare like with like
                  (same partition, similar scenes) and don't read it as a precise average
  cpu_s           CPU seconds of the job's main step
  disk_gib        file I/O of the job's main step (sacct fs/disk), GiB
  bench_wall_s, bench_mean_load, bench_max_rss_mib    from the Snakemake benchmark file
                  of that rule and label in that run, on its newest completed job. The
                  benchmark's memory and load are NA on macOS
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SACCT_FIELDS = "JobID,Partition,State,ElapsedRaw,MaxRSS,TRESUsageInMax,AllocTRES,ExitCode,Submit,Start"
COLUMNS = ["run_id", "rule", "label", "job_id", "state", "partition", "start_time", "elapsed_s", "host_mem_gib",
           "gpu_mem_gib", "gpu_util_pct", "cpu_s", "disk_gib", "bench_wall_s", "bench_mean_load", "bench_max_rss_mib"]
# decimals per column; None is for times: a decimal below 10 s, none above
DIGITS = {"elapsed_s": None, "host_mem_gib": 1, "gpu_mem_gib": 1, "gpu_util_pct": 0, "cpu_s": None, "disk_gib": 1,
          "bench_wall_s": None, "bench_mean_load": 0, "bench_max_rss_mib": 0}
UNITS = {"K": 1 / 1024**2, "M": 1 / 1024, "G": 1.0, "T": 1024.0}  # to GiB
RUN_FORMAT = "%Y%m%dT%H%M%SZ"  # a run_id; the Snakefile makes them the same way
RUN_ID = re.compile(r"\d{8}T\d{6}Z")
UNVERSIONED = "unversioned"  # benchmark files and jobs from before runs had their own folders


def to_gib(text):
    """'73276504K' -> GiB; '15152M' -> GiB; bare numbers are bytes. None if empty."""
    if not text:
        return None
    m = re.fullmatch(r"([\d.]+)([KMGT]?)", text.strip())
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)
    return value * UNITS[unit] if unit else value / 1024**3


def to_seconds(text):
    """'00:19:38', '19:38.123' or '1-02:03:04' -> seconds. None if empty."""
    if not text:
        return None
    days, _, rest = text.rpartition("-")
    parts = [float(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, sec = parts
    return int(days or 0) * 86400 + h * 3600 + m * 60 + sec


def to_utc(text):
    """sacct's local 'YYYY-MM-DDTHH:MM:SS' -> an aware UTC datetime; None for 'Unknown' or empty.

    sacct prints the cluster's local time; this assumes the script runs in the same
    time zone, which it does on a Delta login node.
    """
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S").astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def parse_tres(text):
    """'cpu=00:19:38,gres/gpumem=15152M,...' -> dict."""
    return dict(item.split("=", 1) for item in (text or "").split(",") if "=" in item)


LOG_PATH = re.compile(r"rule_([^/\s]+)/(?:(.+)/)?(\d+)\.log$")
SUBMITTED = re.compile(r"SLURM jobid (\d+) \(log: ([^)]+)\)")


def find_jobs(slurm_logs, snakemake_logs):
    """[(rule, label, job_id, run_log)]: run_log is the name of the Snakemake run log that submitted
    the job (None if only the Slurm plugin's log file names it)."""
    found = {}
    for run_log in Path(snakemake_logs).glob("*.snakemake.log"):
        for jid, path in SUBMITTED.findall(run_log.read_text(errors="replace")):
            m = LOG_PATH.search(path)
            if m and m.group(3) == jid:
                found[jid] = (m.group(1), m.group(2) or "-", jid, run_log.name)
    if Path(slurm_logs).is_dir():
        for log in Path(slurm_logs).glob("rule_*/**/*.log"):
            m = LOG_PATH.search(log.relative_to(slurm_logs).as_posix())
            if m and log.stem.isdigit():
                found.setdefault(m.group(3), (m.group(1), m.group(2) or "-", m.group(3), None))
    return sorted(found.values(), key=lambda j: (j[0], j[1], int(j[2])))


def run_sacct(job_ids):
    try:
        out = subprocess.run(["sacct", "-j", ",".join(job_ids), "-P", "-n", f"--format={SACCT_FIELDS}"],
                             capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("sacct not found: run this on a Delta login node, or pass --sacct-file.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"sacct failed: {e.stderr.strip()}")
    return out


def parse_sacct(text):
    """{job_id: stats} from `sacct -P -n` output with SACCT_FIELDS."""
    jobs, steps = {}, {}
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 8:
            continue
        f += [""] * (10 - len(f))  # output saved before Submit and Start were asked for
        jid, partition, state, elapsed, maxrss, tres, alloc, exitcode, submit, start = f[:10]
        base = jid.split(".")[0]
        if "." not in jid:
            jobs[base] = {"state": state.split()[0] if state else "?", "partition": partition,
                          "elapsed_s": int(elapsed) if elapsed.isdigit() else None,
                          "submit": to_utc(submit), "start": to_utc(start)}
        elif not jid.endswith(".extern"):
            steps.setdefault(base, []).append((to_gib(maxrss) or 0.0, maxrss, tres))
    for base, job in jobs.items():
        # the step that did the work is the one with the largest memory
        _, maxrss, tres = max(steps.get(base, [(0.0, "", "")]), key=lambda s: s[0])
        t = parse_tres(tres)
        job.update(host_mem_gib=to_gib(maxrss) or to_gib(t.get("mem")), gpu_mem_gib=to_gib(t.get("gres/gpumem")),
                   gpu_util_pct=t.get("gres/gpuutil"), cpu_s=to_seconds(t.get("cpu")),
                   disk_gib=to_gib(t.get("fs/disk")))
    return jobs


def config_value(config_file, key):
    """The value of a top-level `key: value` line of a (simple) YAML config, or None."""
    for line in Path(config_file).read_text().splitlines():
        m = re.match(rf"{key}:\s*([^\s#]+)", line)
        if m:
            return m.group(1).strip("'\"")
    return None


def benchmarks_folder(args):
    """--benchmarks, else benchmarks_dir from --config, else ./benchmarks (the workflow's default)."""
    if args.benchmarks:
        return args.benchmarks
    folder = None
    for config in args.config or []:  # several config files: the later one wins, as in snakemake
        folder = config_value(config, "benchmarks_dir") or folder
    return folder or "benchmarks"


def read_runs(root):
    """{run_id: {"info": run.json as a dict, "bench": {(rule, label): first row}}}.

    A run is a folder <root>/<run_id>/ holding <rule>.tsv or <rule>/<label>.tsv files and
    a run.json. Benchmark files directly under <root> (<root>/<rule>...) are from before
    runs had folders; they make up the run `unversioned`.
    """
    runs = {}
    root = Path(root)
    if not root.is_dir():
        return runs

    def run(run_id):
        return runs.setdefault(run_id, {"info": {}, "bench": {}})

    for path in sorted(root.glob("**/*.tsv")):
        parts = list(path.relative_to(root).with_suffix("").parts)
        run_id = parts.pop(0) if RUN_ID.fullmatch(parts[0]) else UNVERSIONED
        if parts == ["summary"]:
            continue  # this script's own output
        if not parts:
            continue
        rows = list(csv.DictReader(path.open(), delimiter="\t"))
        if rows and "s" in rows[0]:
            run(run_id)["bench"][(parts[0], "/".join(parts[1:]) or "-")] = rows[0]
    for folder in root.iterdir():
        if folder.is_dir() and RUN_ID.fullmatch(folder.name):
            info = folder / "run.json"
            try:
                run(folder.name)["info"] = json.loads(info.read_text()) if info.exists() else {}
            except ValueError:
                run(folder.name)  # a run.json cut short is no reason to lose the benchmarks
    return runs


def resolve_run(ref, runs):
    """A run_id, the start of one, `latest` or `previous` -> a run_id of `runs`."""
    real = sorted(r for r in runs if r != UNVERSIONED)
    if ref == "latest" and real:
        return real[-1]
    if ref in ("previous", "prev") and len(real) > 1:
        return real[-2]
    if ref == UNVERSIONED and ref in runs:
        return ref
    matches = [r for r in real if r.startswith(ref.upper())]
    if len(matches) == 1:
        return matches[0]
    sys.exit(f"Run '{ref}': " + ("matches several runs: " + ", ".join(matches) if matches
                                 else "not found. Runs: " + (", ".join(real) or "none")))


def place_job(submit, real_runs):
    """The latest run that started before the job was submitted, or `unversioned`."""
    if submit is None:
        return UNVERSIONED
    earlier = [r for r in real_runs if r <= submit.strftime(RUN_FORMAT)]
    return earlier[-1] if earlier else UNVERSIONED


def fmt(value, digits=1):
    if value is None or value == "NA":
        return "-"
    try:
        value = float(value)
        if digits is None:
            digits = 1 if abs(value) < 10 else 0
        return f"{value:.{digits}f}"
    except ValueError:
        return str(value)


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def run_rows(run_id, jobs, acct, bench, completed_only):
    """The table rows of one run: its Slurm jobs, then the steps that only have a benchmark (`local`)."""
    jobs_found, newest_done, slurm_steps = [], {}, set()
    for rule, label, jid, _ in jobs:
        a = acct.get(jid)
        if a is None:
            continue  # sacct has no record (older than its retention, or not a job of this account)
        slurm_steps.add((rule, label))
        if a["state"] == "COMPLETED":
            newest_done[(rule, label)] = max(newest_done.get((rule, label), 0), int(jid))
        elif completed_only:
            continue
        jobs_found.append((rule, label, jid, a))
    out = []
    for rule, label, jid, a in jobs_found:
        row = bench.get((rule, label)) if newest_done.get((rule, label)) == int(jid) else None
        row = row or {}
        out.append({"run_id": run_id, "rule": rule, "label": label, "job_id": jid, "state": a["state"],
                    "partition": a["partition"],
                    "start_time": a["start"].strftime("%Y-%m-%dT%H:%M:%SZ") if a["start"] else None,
                    "elapsed_s": a["elapsed_s"], "host_mem_gib": a["host_mem_gib"], "gpu_mem_gib": a["gpu_mem_gib"],
                    "gpu_util_pct": a["gpu_util_pct"], "cpu_s": a["cpu_s"], "disk_gib": a["disk_gib"],
                    "bench_wall_s": row.get("s"), "bench_mean_load": row.get("mean_load"),
                    "bench_max_rss_mib": row.get("max_rss")})
    # Steps with a benchmark but no Slurm job: local rules, or a run without Slurm.
    for (rule, label), row in bench.items():
        if (rule, label) not in slurm_steps:
            out.append({c: None for c in COLUMNS} | {
                "run_id": run_id, "rule": rule, "label": label, "job_id": "-", "state": "local",
                "partition": "local", "bench_wall_s": row.get("s"), "bench_mean_load": row.get("mean_load"),
                "bench_max_rss_mib": row.get("max_rss")})
    out.sort(key=lambda r: (r["rule"], r["label"], int(r["job_id"]) if r["job_id"].isdigit() else 0))
    return out


def cell(row, column):
    value = row[column]
    return fmt(value, DIGITS[column]) if column in DIGITS else ("-" if value is None else str(value))


def print_table(rows, columns):
    cells = [{c: cell(r, c) if c in r else str(r.get(c, "-")) for c in columns} for r in rows]
    widths = {c: max(len(c), *(len(r[c]) for r in cells)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns).rstrip())
    for r in cells:
        print("  ".join(r[c].ljust(widths[c]) for c in columns).rstrip())


def run_summary(run_id, run):
    """One line saying what a run was: when, how it ended, which config and commits."""
    info = run["info"]
    if run_id == UNVERSIONED:
        return f"{UNVERSIONED}: benchmark files and jobs from before each run had its own folder"
    started = info.get("start_time") or datetime.strptime(run_id, RUN_FORMAT).strftime("%Y-%m-%dT%H:%M:%SZ")
    bits = [f"started {started}", info.get("status") or "no run.json"]
    if info.get("configfiles"):
        bits.append("config " + " ".join(Path(f).name for f in info["configfiles"]))
    if info.get("habitat_commit"):
        bits.append("HABITAT " + info["habitat_commit"][:7])
    if info.get("workflow_commit"):
        bits.append("workflow " + info["workflow_commit"][:7] + ("-dirty" if info["workflow_commit"].endswith("-dirty") else ""))
    if info.get("scenes") is not None:
        bits.append(f"{len(info['scenes'])} scenes")
    return f"{run_id}: " + ", ".join(bits)


def compare(rows_a, rows_b, id_a, id_b):
    """One row per step in either run: each metric as 'a -> b (+x%)'."""
    def pick(rows):
        # the newest completed attempt of each step, or the last attempt if none completed
        best = {}
        for r in rows:
            key = (r["rule"], r["label"])
            done = r["state"] in ("COMPLETED", "local")
            if key not in best or (done, number(r["job_id"]) or 0) >= (best[key][0], number(best[key][1]["job_id"]) or 0):
                best[key] = (done, r)
        return {k: v[1] for k, v in best.items()}

    a, b = pick(rows_a), pick(rows_b)
    metrics = [("time_s", lambda r: r["elapsed_s"] if r["elapsed_s"] is not None else r["bench_wall_s"], None),
               ("host_mem_gib", lambda r: r["host_mem_gib"], 1), ("gpu_mem_gib", lambda r: r["gpu_mem_gib"], 1),
               ("cpu_s", lambda r: r["cpu_s"], None)]
    out = []
    for key in sorted(set(a) | set(b)):
        row = {"rule": key[0], "label": key[1],
               "state": "/".join(r["state"] if r else "-" for r in (a.get(key), b.get(key)))}
        for name, get, digits in metrics:
            x = number(get(a[key])) if key in a else None
            y = number(get(b[key])) if key in b else None
            text = f"{fmt(x, digits)} -> {fmt(y, digits)}"
            if x is not None and y is not None and x != 0:
                text += f" ({(y - x) / x * 100:+.0f}%)"
            row[name] = text
        out.append(row)
    print(f"A = {id_a}   B = {id_b}   (each cell: A -> B, change)")
    return out, ["rule", "label", "state"] + [m[0] for m in metrics]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rules", nargs="*", help="only these rules (default: every rule)")
    p.add_argument("--slurm-logs", default=".snakemake/slurm_logs", help="where the Slurm plugin keeps job logs")
    p.add_argument("--snakemake-logs", default=".snakemake/log", help="Snakemake's own run logs")
    p.add_argument("--config", nargs="+", help="the workflow config(s) (e.g. config/config.delta.yaml); gives the benchmarks folder")
    p.add_argument("--benchmarks", help="the benchmarks folder (overrides --config; default ./benchmarks)")
    which = p.add_mutually_exclusive_group()
    which.add_argument("--run", help="show this run: a run_id, the start of one, `latest` or `previous` (default: latest)")
    which.add_argument("--all", action="store_true", help="show every run in one table")
    which.add_argument("--list", action="store_true", help="list the runs and what each was, then stop")
    which.add_argument("--compare", nargs="*", metavar="RUN",
                       help="compare two runs step by step (default: previous latest)")
    p.add_argument("--completed", action="store_true",
                   help="only jobs that finished (state COMPLETED); by default failed and cancelled attempts are listed too")
    p.add_argument("--out", help="also write the table here (TSV); default <benchmarks folder>/<run_id>/summary.tsv")
    p.add_argument("--sacct-file", help="read this saved `sacct -j ... -P -n --format=" + SACCT_FIELDS + "` output "
                   "instead of running sacct (for testing)")
    args = p.parse_args()
    if args.compare is not None and len(args.compare) not in (0, 2):
        p.error("--compare takes two runs (or none, for previous and latest)")

    bench_dir = benchmarks_folder(args)
    runs = read_runs(bench_dir)
    real = sorted(r for r in runs if r != UNVERSIONED)
    if args.list:
        if not runs:
            sys.exit(f"No runs in {bench_dir}. Run the workflow first.")
        for run_id in ([UNVERSIONED] if UNVERSIONED in runs else []) + real:
            print(run_summary(run_id, runs[run_id]))
        return

    if args.compare is not None:
        selected = [resolve_run(r, runs) for r in (args.compare or ["previous", "latest"])]
    elif args.all:
        selected = ([UNVERSIONED] if UNVERSIONED in runs else []) + real
    elif args.run:
        selected = [resolve_run(args.run, runs)]
    else:
        selected = real[-1:] or [UNVERSIONED]
    wanted = lambda rule: not args.rules or rule in args.rules

    # Which run each job belongs to: the run log that submitted it, else by when it was submitted.
    log_to_run = {r["info"]["snakemake_log"]: rid for rid, r in runs.items() if r["info"].get("snakemake_log")}
    by_run, unplaced = defaultdict(list), []
    for job in (j for j in find_jobs(args.slurm_logs, args.snakemake_logs) if wanted(j[0])):
        run_id = log_to_run.get(job[3])
        (by_run[run_id] if run_id else unplaced).append(job)
    asked = [j for run_id in selected for j in by_run[run_id]] + unplaced
    acct = {}
    if asked:
        text = Path(args.sacct_file).read_text() if args.sacct_file else run_sacct([j[2] for j in asked])
        acct = parse_sacct(text)
    for job in unplaced:
        if job[2] in acct:
            by_run[place_job(acct[job[2]]["submit"], real)].append(job)

    table = {run_id: run_rows(run_id, by_run[run_id], acct,
                              {k: v for k, v in runs.get(run_id, {"bench": {}})["bench"].items() if wanted(k[0])},
                              args.completed)
             for run_id in selected}
    rows = [r for run_id in selected for r in table[run_id]]
    if not rows:
        sys.exit(f"No jobs or benchmark files for {', '.join(selected)} in {bench_dir}"
                 + (f" for rules {args.rules}" if args.rules else "")
                 + (" (--completed: none of them finished)" if args.completed else "")
                 + ". Run the workflow first.")
    if args.completed:
        print("--completed: only jobs that finished (failed and cancelled attempts are left out)", file=sys.stderr)

    if args.compare is not None:
        compared, columns = compare(table[selected[0]], table[selected[1]], *selected)
        for run_id in selected:
            print(run_summary(run_id, runs.get(run_id, {"info": {}})))
        print()
        print_table(compared, columns)
        if args.out:
            with open(args.out, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=columns, delimiter="\t")
                w.writeheader()
                w.writerows(compared)
            print(f"\nwritten to {args.out}", file=sys.stderr)
        return

    for run_id in selected:
        print(run_summary(run_id, runs.get(run_id, {"info": {}})))
    print()
    print_table(rows, COLUMNS if len(selected) > 1 else COLUMNS[1:])
    if args.out:
        out_file = args.out
    elif len(selected) == 1 and selected[0] != UNVERSIONED:
        out_file = str(Path(bench_dir) / selected[0] / "summary.tsv")
    else:
        out_file = str(Path(bench_dir) / "summary.tsv")
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(COLUMNS)
        w.writerows([cell(r, c) for c in COLUMNS] for r in rows)
    print(f"\nwritten to {out_file}  (benchmark files read from {bench_dir})", file=sys.stderr)


if __name__ == "__main__":
    main()
