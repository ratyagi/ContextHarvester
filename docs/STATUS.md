# PRD status

Honest state of every PRD item. Update it whenever something changes. Nothing here is estimated: "built" means the code exists and is unit-tested, "run" means a real run produced output.

## Why nothing has been run on real data yet

The session that built this has an egress policy that blocks `github.com` (other than this repo), `huggingface.co` and the LLM APIs, but allows `api.github.com` and PyPI. So MiniLM weights, SWE-bench Verified and third-party clones could not be fetched, and no benchmark number exists. The GitHub Actions workflows run with open network; `eval.yml` is the way to produce the first real numbers.

## Success criteria (PRD)

| Item | State |
|---|---|
| CLI runs end to end on an arbitrary public Python repo in under 60 seconds | Built (`ch rank`, `ch replay`, `--json`). **Not verified** on a real repo; timing is printed on every run. Blobless clone, a content-hash embedding cache and chunk caps are in for speed. |
| Evaluated on SWE-bench Verified and at least 4 self-harvested repos, 2 held out | Harness built and tested on a synthetic repo. **Not run.** Needs `corpus/repos.csv`. |
| Recall@10 against all four baselines, ablation table published | Built (random, BM25, embeddings, BM25+embeddings, full; same indexes; bootstrap CIs and paired margin vs BM25). **Not run.** |
| Snapshot-leakage test passing | **Done.** `tests/test_snapshot_leakage.py`. The same guard runs on every evaluated instance and failures are listed. |
| Static results live on GitHub Pages | Page and `pages.yml` built. **Needs Pages enabled** (Settings > Pages > GitHub Actions) and real results. |
| README states method, number, limitation in first three paragraphs | Method and limitation done. **Number pending**, and the README says so. |
| One substantive issue or PR on `clay-run/agent-plugins` | **Not done.** Needs a person with a Clay account; this session has no access to that repo. |
| Clay corpus build recorded, column config screenshotted, `corpus/repos.csv` committed | **Not done.** `corpus/repos.csv` is header-only. Steps in `docs/CLAY_RUNBOOK.md`. |

## Pipeline stages

Snapshot, lexical, semantic, structural, fusion, rerank, score: all built and tested. Rerank and the provider-fallback layer are tested with mocks only (no live API calls were possible).

## Evaluation protocol

Worktree snapshot, forward time split frozen to `corpus/split.json`, tuning on dev only, issue-text fix stripping plus with/without reporting, filtered and unfiltered gold, held-out repos, sources never pooled: all built.

## Decisions the PRD does not settle (please confirm or overrule)

1. Test files are excluded from harvested gold, to match SWE-bench's patch / test_patch split. The PRD only names test fixtures.
2. Only `.py` files are indexed. Gold files that are not indexed (or that the fix adds) cannot be retrieved, so they are dropped from recall. The raw count is kept as `n_gold_raw`.
3. Harvested base commit is the parent of the PR's first commit, the commit before the fix work.
4. Token counts use about 4 chars per token everywhere, so budgets are consistent and need no tokenizer download.
5. The "naive embedding" baseline uses the same chunked-and-pooled per-file vector as the semantic retriever, so the ablation isolates fusion and the graph rather than the embedding recipe.
6. Gemini is called through the standard endpoint, not the batch API. Batch can be added for large eval runs.
7. One tuned parameter set (`corpus/tuned_params.json`) is used for all sources, tuned on dev instances of both.

## Open PRD questions (need a person)

Which Clay posting; visa sponsorship for new-grad roles; whether the Clay API works on Free; Python only or add TypeScript (cut list item 1 is currently applied: Python only).
