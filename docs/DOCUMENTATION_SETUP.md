# Documentation Setup

These docs are built with [mkdocs](https://www.mkdocs.org/) and the Material theme, the same way as [water_timeseries_argo_workflow](https://github.com/PermafrostDiscoveryGateway/water_timeseries_argo_workflow).

## Building locally

```bash
pip install -r docs/requirements.txt
mkdocs serve
```

Then open <http://localhost:8000>. The site rebuilds whenever a file changes.

`mkdocs build --strict` writes the static site to `site/` (excluded from git) and fails on broken links. CI runs the same command.

## Adding a page

Add a markdown file under `docs/`, then list it in the `nav` section of `mkdocs.yml`.

## Deployment

`.github/workflows/docs.yml` builds the site on every pull request. On every push to `main`, it also deploys the site to GitHub Pages at <https://PermafrostDiscoveryGateway.github.io/HABITAT_SNAKEMAKE/>.

Deployment requires GitHub Pages to be enabled with **GitHub Actions** as the source (Settings → Pages → Build and deployment → Source).
