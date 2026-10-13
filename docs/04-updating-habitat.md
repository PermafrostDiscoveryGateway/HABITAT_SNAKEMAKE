# Updating HABITAT

`HABITAT/` is a git submodule. This repository records one specific HABITAT commit, so every result can be traced to the exact HABITAT code that produced it. The commit in use is also printed at the top of each `logs/process_scene/<scene>.log`.

## Automatic update before each run

`run_delta.sh` runs `scripts/update_habitat.sh` before each real run (not dry runs), which fast-forwards `HABITAT/` to the latest `origin/main`. It prints `Updated HABITAT from <old> to <new>` when it moves. If a Snakemake run is already in progress in this checkout, the fetch fails (no network), `HABITAT/` has local changes, or its history has diverged, it prints a warning and the run continues on the current commit.

For a local run, update first:

```bash
scripts/update_habitat.sh && snakemake --configfile config/config.local.yaml --cores 2
```

After an update, `git status` shows `HABITAT` as modified. Commit the new pointer (see [Testing and committing](#testing-and-committing)) so the repository records the commit the results came from.

Run `UPDATE_HABITAT=false ./run_delta.sh` to keep the pinned commit. The rest of this page covers updating by hand.

## Which commit is in use

```bash
git submodule status
```

The hash shown is the HABITAT commit this repository uses.

## Updating to the latest HABITAT

```bash
git submodule update --remote HABITAT
```

This moves `HABITAT/` to the newest commit on HABITAT's `main`. To use a specific commit or tag instead:

```bash
git -C HABITAT fetch
git -C HABITAT checkout <commit-or-tag>
```

## Checking what changed

Before committing the update, look at what changed in HABITAT:

```bash
git diff --submodule=log HABITAT
git -C HABITAT diff <old-commit> HEAD --stat
```

Pay attention to anything that affects `scripts/habitat_runner.py`:

- **Config attributes.** List every config attribute HABITAT reads:

    ```bash
    grep -ho "Operational_Config\.[A-Z_]*" HABITAT/*.py | sort -u
    ```

    Each one must be defined in `Operational_Config` in `scripts/habitat_runner.py`. If HABITAT starts reading a new attribute, add it there (and to the configs, if it should be settable).

- **Module and entry point names.** The runner depends on `operational_config`, `final_model_config`, `Operational_Config`, `Final_Config` and `full_pipeline.py --image`. If any of these are renamed, the runner must change to match.

- **Output names.** The `process_scene` rule expects `<scene>_final.shp` (written in `postprocess.py`). If that file name changes, update the rule's `output:`.

- **Dependencies.** New or upgraded imports belong in `envs/requirements.txt`.

## Testing and committing

Run the smoke test against the new commit:

```bash
snakemake --configfile config/config.test.yaml --cores 2
```

The HABITAT commit is a parameter of the `process_scene` rule, so after an update Snakemake treats existing outputs as out of date and reruns them. No `--forcerun` is needed.

If the test passes, commit the new pointer:

```bash
git add HABITAT
git commit -m "Update HABITAT to $(git -C HABITAT rev-parse --short HEAD)"
git push
```

!!! warning "Real-data runs rerun too"
    The same rule applies to `config.local.yaml` (and later Delta) runs: after a HABITAT update, every finished scene counts as out of date. To keep existing outputs and process only the new scenes, add `--rerun-triggers mtime` to the command.

## Pulling someone else's update

When another person has updated the submodule, `git pull` changes the recorded commit but does not change the files in `HABITAT/`. Run this after pulling:

```bash
git submodule update --init
```

Or set `git config submodule.recurse true` once, so `git pull` does it for you.

## Don't edit HABITAT here

Changes made directly inside `HABITAT/` show up only as a "modified content" note on the submodule and are easy to lose. Fix HABITAT in the HABITAT repository, then update the submodule here. If a fix is needed only for running under this workflow, put it in `scripts/habitat_runner.py`.
