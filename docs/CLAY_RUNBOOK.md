# Clay corpus build runbook (PRD: Clay integration)

Start the Growth trial in week 1. It runs 14 days from activation and only this step needs it.

0. **Day one checks.** Read the real credit allowance and row cap in the dashboard (Clay's pages disagree: 1,000 vs 2,000 credits, 50 vs 200 rows). Test whether the API works on Free before planning around the CLI. Start a screen recording now.
1. **Seed.** One row per candidate Python repository (12 to 20 rows; trial cap is 50 per table).
2. **Cheap filters first.** HTTP API column to `https://api.github.com/repos/{{repo}}`: `stargazers_count`, `open_issues_count`, `language`. A second HTTP API column to `/repos/{{repo}}/actions/workflows` for `total_count > 0`. Keep Python repos with real activity.
3. **Expensive filter second.** HTTP API column counting resolvable `Fixes #N` links, gated with conditional run on step 2 passing. You can cross-check the count with `ch harvest --repo owner/name` (prints instances found). Keep repos with enough links (aim for 30 or more).
4. **Use AI column for domain.** Classify each survivor (web framework, data, CLI, ML, networking, devtools, ...) so the corpus is not twelve web frameworks.
5. **Choose held-out repos.** At least 2, set `held_out = true`. They are used only at evaluation time.
6. **Export and commit** to `corpus/repos.csv` with the columns in `corpus/README.md`.
7. **Evidence.** Keep the 90-second recording of the table building, the CSV export, and a screenshot of the column configuration. Put them under `docs/evidence/` and link from the README.

Avoid: Claygent for deterministic lookups, a Clay table as the data store, any Clay call at demo time.
