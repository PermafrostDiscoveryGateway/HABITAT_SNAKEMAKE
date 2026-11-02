# Using this workflow as a module

Another Snakefile (for example one for a different region or model) can reuse these rules with Snakemake's [`module`](https://snakemake.readthedocs.io/en/stable/snakefiles/modularization.html) directive, instead of copying them.

```python
# Snakefile of the calling workflow
module habitat:
    snakefile: github("PermafrostDiscoveryGateway/HABITAT_SNAKEMAKE", path="Snakefile", tag="v0.1.0")
    config: config["habitat"]

use rule * from habitat as habitat_*

rule all:
    input:
        rules.habitat_all.input,
```

`config["habitat"]` is the same set of keys as in `config/config.*.yaml` (`scene_dir`, `weights`, `output_dir`, `environment`, ...). `snakefile:` also takes a local path, for example `"../HABITAT_SNAKEMAKE/Snakefile"`.

The rules come in with the prefix you choose in `use rule * ... as habitat_*` (`habitat_process_scene`, `habitat_build_environment`, ...). To change one, override it after the `use rule` line:

```python
use rule process_scene from habitat as habitat_process_scene with:
    resources:
        runtime=30
```

## What to know

- **Paths in the config are relative to the calling workflow's folder**, not to this repository: `scene_dir`, `output_dir`, `weights`, `environment.path`, and the `logs/` and `benchmarks/` folders. The files of this repository itself (`scripts/`, `envs/requirements.txt`) are found wherever the module comes from.
- **HABITAT is not part of the module.** Set `habitat_dir` to a HABITAT checkout next to the calling workflow. The rules read its commit, so a new commit reruns the scenes ([Updating HABITAT](04-updating-habitat.md)).
- **Pin a `tag` (or a commit), not a branch.** The path of a module's files is part of the job's parameters, so a path that changed between runs would rerun every scene. Snakemake keeps a tag's files in the same place from run to run, but not a branch's.
- **Rule names in profiles carry the prefix.** The Slurm profile of the calling workflow sets `habitat_process_scene`, `habitat_build_environment` and so on under `set-resources` and `set-threads`; `profiles/delta/config.yaml` can be used as a template.
- **`run.json` is not written.** Snakemake ignores `onstart`, `onsuccess` and `onerror` inside a module, so that file (and the table that reads it) comes only from a direct run. The per-rule benchmark files are still written, into `benchmarks_dir/<run_id>/`.
- **The module's `all`** is imported as `habitat_all`, as in the example, so the calling workflow can put it into its own `all` along with its other targets.

## Writing rules that stay reusable

These hold for any rule added to this repository, since modules change how Snakemake finds things:

- Use `repo_file("../scripts/x.py")` (in `rules/common.smk`) for a file of this repository, not `scripts/x.py`. It is relative to the rule file calling it.
- Give a shell command what it needs through `params`, `input` and `output`, not through variables of the rule files: inside a module, Snakemake formats a shell command without them.
- Mark a rule that must run on the login node with `localrule: True` inside the rule, not with a `localrules:` line, which doesn't follow a renamed rule.
