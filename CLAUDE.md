# CLAUDE.md

## STRICT RULE: THE PRD IS THE SPEC

`docs/PRD.md` is the single source of truth for this project. Every action in this repo follows it.

1. **Read the relevant PRD sections before starting any task.** Do not work from memory of it.
2. **Do everything the PRD says.** Every goal, stage, baseline, metric, leakage guard, deliverable, and success criterion is in scope. Nothing in the PRD is optional unless the PRD itself puts it on the cut list, and then only the user may invoke a cut.
3. **Do nothing the PRD forbids.** The non-goals, the "Deliberately not used" list, and the "What is deliberately avoided" list are hard limits. No patch generation. No hosted vector DB, Redis, AWS services, or Terraform. No Clay call in the demo path. No Claygent or Clay table as a data store.
4. **Do not change the stack.** Python, `typer`, `rank_bm25` or Tantivy, local `all-MiniLM-L6-v2`, in-process FAISS, Parquet in the repo, static GitHub Pages, GitHub Actions, and an LLM provider-fallback layer for reranking only.
5. **Never cut:** the BM25 baseline, the snapshot-leakage test, or the ablation.
6. **If the PRD and a request conflict, or the PRD is silent or ambiguous, stop and ask the user.** Do not decide alone. If the PRD itself must change, edit `docs/PRD.md` only after the user approves, and say so in the commit message.
7. **Tie work to the PRD.** Commit messages and PR descriptions name the PRD section or success-criteria item they serve.
8. **Report honestly.** Never fake or estimate a result. Every number in the README or results page comes from a real run. Report configurations that lost. State the lower-bound caveat on recall unprompted. If something in the PRD cannot be done from this environment (for example the Clay trial, screen recording, or opening a PR on `clay-run/agent-plugins`), say so plainly and leave it listed as open in `docs/STATUS.md`. Do not simulate it.

## Evaluation integrity (from the PRD protocol)

- Index only the pre-fix snapshot (`git worktree` at the commit before the fix). Never current `main`.
- Forward time split. No random shuffling. Tune only on issues before the cutoff.
- Report with and without instances where the issue text contains the fix or names the file.
- Report filtered and unfiltered gold recall. The filter rules live in code and in the README.
- Hold out at least two repos for evaluation only.
- SWE-bench Verified and self-harvested results are reported separately, never pooled.

## Layout

- `docs/PRD.md`: the spec. `docs/STATUS.md`: PRD checklist with real status.
- `src/context_harvester/`: the package. `tests/`: pytest, including the snapshot-leakage test.
- `corpus/repos.csv`: Clay-exported corpus, committed. `results/`: Parquet outputs.
- `web/`: static results page for GitHub Pages. `.github/workflows/`: collector and Pages deploy.

## Style

Concise code, small modules, no speculative abstractions. Comments explain why, not what. Run `pytest` before every commit.
