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

## Exact column setup (quick version)

Seed: import `corpus/clay_seed.csv` (25 candidates, written from memory, not verified; the HTTP columns below are what verify them). None are among SWE-bench Verified's 12 repos. Row cap on trial is 50, so this fits.

Add an `Authorization: Bearer <your GitHub token>` header to every HTTP API column below (search is capped at 10 requests/min without one).

1. **Cheap, column `gh`:** HTTP API `GET https://api.github.com/repos/{{repo}}`. Pull out `stargazers_count` as `stars`, `open_issues_count` as `open_issues`, `language`.
2. **Cheap, column `actions`:** `GET https://api.github.com/repos/{{repo}}/actions/workflows`. Pull `total_count` as `uses_actions` (true if > 0).
3. **Expensive, column `fixes_links`:** `GET https://api.github.com/search/issues?q=repo:{{repo}}+is:pr+is:merged+"fixes+%23"+in:body&per_page=1`. Pull `total_count`. **Conditional run:** only when `language == "Python"` and `stars >= 1000` and `uses_actions` is true. Keep rows with `fixes_links >= 30`.
4. **Use AI, column `domain`** (run only on survivors): "Classify this Python project into one of: web framework, HTTP/networking, data/scientific, CLI/devtools, packaging, ML, database/ORM, async/distributed, security, docs/imaging. Repo: {{repo}}. Answer with the label only."
5. **Choose held-out:** from the survivors, mark 2 or more `held_out = true`, in different domains.
6. **Export CSV** with columns `repo,stars,open_issues,language,uses_actions,fixes_links,domain,held_out` and save as `corpus/repos.csv`.
7. **Evidence:** 90-second recording of steps 1 to 6, the CSV export, and a screenshot of the column config. Save under `docs/evidence/`.

Cross-check any repo's real link count with `ch harvest --repo owner/name` (prints instances found).
