# corpus

`repos.csv` is the evaluation corpus. Per the PRD it is built once in Clay on the 14-day Growth trial, exported, and committed. Nothing at runtime calls Clay.

**It is currently header-only.** The Clay build has not been done (it needs a Clay account and the trial clock). Steps and column configuration: `docs/CLAY_RUNBOOK.md`.

Columns: `repo` (owner/name), `stars`, `open_issues`, `language`, `uses_actions`, `fixes_links` (resolvable `Fixes #N` issue-to-PR links), `domain` (Use AI classification), `held_out` (true for repos used only at evaluation time; at least 2).

Generated files (committed by the collector): `instances_swebench.parquet`, `instances_harvested.parquet`, `split.json` (frozen cutoff and held-out repos), `tuned_params.json`, `tuning_grid.parquet`.
