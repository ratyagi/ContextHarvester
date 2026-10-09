# corpus

`repos.csv` is the evaluation corpus. Per the PRD it is built once in Clay on the 14-day Growth trial, exported, and committed. Nothing at runtime calls Clay.

**Built in Clay on the Growth trial (Oct 9, 2026)** from `clay_seed.csv` (24 candidates). `clay_export_raw.csv` is the untouched Clay export. `repos.csv` is the selected corpus: 20 repos. Steps and column configuration: `docs/CLAY_RUNBOOK.md`. Recording of the build: https://youtu.be/dfvmURSpRbc.

Excluded from the raw export: `bokeh/bokeh` (primary language TypeScript), `PyCQA/flake8` (6 `Fixes #N` links, below 30), `pyca/cryptography` (many fixes touch Rust, which is not indexed), `tiangolo/fastapi` (its `fixes_links` call errored in Clay and was not rerun, so it has no count or domain).

Held out (evaluation only): `networkx/networkx` (data/scientific), `urllib3/urllib3` (HTTP/networking), `tornadoweb/tornado` (web framework). Chosen after the Clay export, from pure-Python repos in different domains. `uses_actions` is the number of GitHub Actions workflow files. `fixes_links` is a GitHub search count of merged PRs with `fixes #` in the body, so it is approximate.

Columns: `repo` (owner/name), `stars`, `open_issues`, `language`, `uses_actions`, `fixes_links` (resolvable `Fixes #N` issue-to-PR links), `domain` (Use AI classification), `held_out` (true for repos used only at evaluation time; at least 2).

Generated files (committed by the collector): `instances_swebench.parquet`, `instances_harvested.parquet`, `split.json` (frozen cutoff and held-out repos), `tuned_params.json`, `tuning_grid.parquet`.
