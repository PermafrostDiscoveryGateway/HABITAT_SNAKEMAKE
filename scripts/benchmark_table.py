"""One table of how each step of the workflow went: Snakemake's benchmarks plus Slurm's accounting.

Snakemake's benchmark file (<benchmarks_dir>/.../*.tsv) has wall time, CPU and a memory
figure that can miss short peaks, but nothing about the GPU. Slurm's accounting
(`sacct`) on Delta also has the job's state, the peak host memory, the peak GPU
memory (gres/gpumem), a GPU utilisation figure (gres/gpuutil), CPU time and disk
I/O. This script finds the Slurm job IDs of the workflow's jobs, asks sacct about
them, and prints one row per job, with the benchmark's wall time and CPU load
beside it. Run it on Delta, from the repository folder, after a run:

    python3 scripts/benchmark_table.py --config config/config.delta.yaml
    python3 scripts/benchmark_table.py --config config/config.delta.yaml --rules process_scene

Steps that ran without Slurm (download_imagery and make_test_data, which are local
rules, or every step of a run on a laptop) have a benchmark file but no Slurm job;
they are listed too, with state `local` and only the benchmark's columns. With no
Slurm jobs at all, sacct is not called, so the script also works off Delta:

    python3 scripts/benchmark_table.py --config config/config.sample.yaml

The benchmark files are in the config's `benchmarks_dir` (default `benchmarks`), which
--config reads; or name the folder yourself with --benchmarks. By default every attempt
is listed, failed and cancelled ones too; --completed lists only the jobs that finished
(state COMPLETED). The table is also written to <benchmarks folder>/summary.tsv (--out
changes that).

Job IDs come from two places, because the Slurm plugin deletes the log file of a
job that succeeded and keeps only failed ones (and clears all of them after 10 days):
the file names under .snakemake/slurm_logs/rule_<rule>/<wildcards>/<job id>.log, and
the "Job N has been submitted with SLURM jobid <id> (log: <path>)" lines in
Snakemake's own run logs under .snakemake/log/, which name the same path even when
the file has been deleted. Every attempt is listed, including failed ones (an
out-of-memory kill shows as OUT_OF_MEMORY). Uses only the standard library.

Columns:
  rule, label     the rule and its wildcards, e.g. process_scene yellowknife_wv03_20230808
  job_id, state, partition, elapsed_s     from sacct (`local` for steps that ran without Slurm)
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
                  of that rule and label, on the newest completed job only (the file is
                  overwritten per run). The benchmark's memory and load are NA on macOS
"""

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

SACCT_FIELDS = "JobID,Partition,State,ElapsedRaw,MaxRSS,TRESUsageInMax,AllocTRES,ExitCode"
COLUMNS = ["rule", "label", "job_id", "state", "partition", "elapsed_s", "host_mem_gib", "gpu_mem_gib",
           "gpu_util_pct", "cpu_s", "disk_gib", "bench_wall_s", "bench_mean_load", "bench_max_rss_mib"]
UNITS = {"K": 1 / 1024**2, "M": 1 / 1024, "G": 1.0, "T": 1024.0}  # to GiB


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


def parse_tres(text):
    """'cpu=00:19:38,gres/gpumem=15152M,...' -> dict."""
    return dict(item.split("=", 1) for item in (text or "").split(",") if "=" in item)


LOG_PATH = re.compile(r"rule_([^/\s]+)/(?:(.+)/)?(\d+)\.log$")
SUBMITTED = re.compile(r"SLURM jobid (\d+) \(log: ([^)]+)\)")


def find_jobs(slurm_logs, snakemake_logs):
    """[(rule, label, job_id)] from the Slurm plugin's log files and Snakemake's run logs."""
    found = {}
    if Path(slurm_logs).is_dir():
        for log in Path(slurm_logs).glob("rule_*/**/*.log"):
            m = LOG_PATH.search(log.relative_to(slurm_logs).as_posix())
            if m and log.stem.isdigit():
                found[m.group(3)] = (m.group(1), m.group(2) or "-", m.group(3))
    for run_log in Path(snakemake_logs).glob("*.snakemake.log"):
        for jid, path in SUBMITTED.findall(run_log.read_text(errors="replace")):
            m = LOG_PATH.search(path)
            if m and m.group(3) == jid:
                found.setdefault(jid, (m.group(1), m.group(2) or "-", jid))
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
        jid, partition, state, elapsed, maxrss, tres, alloc, exitcode = f[:8]
        base = jid.split(".")[0]
        if "." not in jid:
            jobs[base] = {"state": state.split()[0] if state else "?", "partition": partition,
                          "elapsed_s": int(elapsed) if elapsed.isdigit() else None}
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
    if args.config:
        return config_value(args.config, "benchmarks_dir") or "benchmarks"
    return "benchmarks"


def read_benchmarks(benchmarks):
    """{(rule, label): first row} of every benchmark file: <rule>.tsv or <rule>/<label>.tsv."""
    found = {}
    root = Path(benchmarks)
    if not root.is_dir():
        return found
    for path in sorted(root.glob("**/*.tsv")):
        parts = path.relative_to(root).with_suffix("").parts
        if parts == ("summary",):
            continue  # this script's own output
        rows = list(csv.DictReader(path.open(), delimiter="\t"))
        if rows and "s" in rows[0]:
            found[(parts[0], "/".join(parts[1:]) or "-")] = rows[0]
    return found


def fmt(value, digits=1):
    if value is None or value == "NA":
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except ValueError:
        return str(value)


def bench_columns(row):
    row = row or {}
    return {"bench_wall_s": fmt(row.get("s"), 0), "bench_mean_load": fmt(row.get("mean_load"), 0),
            "bench_max_rss_mib": fmt(row.get("max_rss"), 0)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rules", nargs="*", help="only these rules (default: every rule)")
    p.add_argument("--slurm-logs", default=".snakemake/slurm_logs", help="where the Slurm plugin keeps job logs")
    p.add_argument("--snakemake-logs", default=".snakemake/log", help="Snakemake's own run logs")
    p.add_argument("--config", help="the workflow config (e.g. config/config.delta.yaml); gives the benchmarks folder")
    p.add_argument("--benchmarks", help="the benchmarks folder (overrides --config; default ./benchmarks)")
    p.add_argument("--completed", action="store_true",
                   help="only jobs that finished (state COMPLETED); by default failed and cancelled attempts are listed too")
    p.add_argument("--out", help="also write the table here (TSV); default <benchmarks folder>/summary.tsv")
    p.add_argument("--sacct-file", help="read this saved `sacct -j ... -P -n --format=" + SACCT_FIELDS + "` output "
                   "instead of running sacct (for testing)")
    args = p.parse_args()

    bench_dir = benchmarks_folder(args)
    out_file = args.out or str(Path(bench_dir) / "summary.tsv")
    wanted = lambda rule: not args.rules or rule in args.rules
    jobs = [j for j in find_jobs(args.slurm_logs, args.snakemake_logs) if wanted(j[0])]
    benches = {k: v for k, v in read_benchmarks(bench_dir).items() if wanted(k[0])}
    if not jobs and not benches:
        sys.exit(f"No Slurm jobs under {args.slurm_logs} or {args.snakemake_logs} and no benchmark files in "
                 f"{bench_dir}" + (f" for rules {args.rules}" if args.rules else "") + ". Run the workflow first.")
    if args.completed:
        print("--completed: only jobs that finished (failed and cancelled attempts are left out)", file=sys.stderr)
    if jobs:
        text = Path(args.sacct_file).read_text() if args.sacct_file else run_sacct([j[2] for j in jobs])
        acct = parse_sacct(text)
    else:
        acct = {}

    rows, newest_done, slurm_steps = [], {}, set()
    for rule, label, jid in jobs:
        a = acct.get(jid)
        if a is None:
            continue  # sacct has no record (older than its retention, or not a job of this account)
        slurm_steps.add((rule, label))
        if a["state"] == "COMPLETED":
            newest_done[(rule, label)] = max(newest_done.get((rule, label), 0), int(jid))
        elif args.completed:
            continue
        rows.append((rule, label, jid, a))
    out = []
    for rule, label, jid, a in rows:
        bench = benches.get((rule, label)) if newest_done.get((rule, label)) == int(jid) else None
        out.append({"rule": rule, "label": label, "job_id": jid, "state": a["state"], "partition": a["partition"],
                    "elapsed_s": fmt(a["elapsed_s"], 0), "host_mem_gib": fmt(a["host_mem_gib"]),
                    "gpu_mem_gib": fmt(a["gpu_mem_gib"]), "gpu_util_pct": fmt(a["gpu_util_pct"], 0),
                    "cpu_s": fmt(a["cpu_s"], 0), "disk_gib": fmt(a["disk_gib"]), **bench_columns(bench)})
    # Steps with a benchmark but no Slurm job: local rules, or a run without Slurm.
    for (rule, label), bench in benches.items():
        if (rule, label) not in slurm_steps:
            row = {c: "-" for c in COLUMNS}
            row.update(rule=rule, label=label, state="local", partition="local", **bench_columns(bench))
            out.append(row)
    out.sort(key=lambda r: (r["rule"], r["label"], int(r["job_id"]) if r["job_id"].isdigit() else 0))

    if not out:
        print("No jobs to show" + (" (--completed: none of them finished)" if args.completed else "")
              + ". Nothing written.", file=sys.stderr)
        return
    widths = {c: max(len(c), *(len(str(r[c])) for r in out)) for c in COLUMNS}
    print("  ".join(c.ljust(widths[c]) for c in COLUMNS))
    for r in out:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in COLUMNS))
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t")
        w.writeheader()
        w.writerows(out)
    print(f"\nwritten to {out_file}  (benchmark files read from {bench_dir})", file=sys.stderr)


if __name__ == "__main__":
    main()
