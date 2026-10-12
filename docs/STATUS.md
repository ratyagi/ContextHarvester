# PRD status

Honest state of every PRD item. Update it whenever something changes. Nothing here is estimated: "built" means the code exists and is unit-tested, "run" means a real run produced output.

## Why nothing has been run on real data yet

The session that built this has an egress policy that blocks `github.com` (other than this repo), `huggingface.co` and the LLM APIs, but allows `api.github.com` and PyPI. So MiniLM weights, SWE-bench Verified and third-party clones could not be fetched, and no benchmark number exists. The GitHub Actions workflows run with open network; `eval.yml` is the way to produce the first real numbers.

## Success criteria (PRD)

| Item | State |
|---|---|
| CLI runs end to end on an arbitrary public Python repo in under 60 seconds | **Holds for small and mid-sized repos, fails for a large one.** `pallets/jinja`: cold rank 21s, replay 21s. `huggingface/transformers` (4,957 indexed files): **cold rank 742s**, of which embedding the files was 697s (94%). The replay of a closed issue on the same repo took 57s, but its embedding stage took 19s versus 697s, which is consistent with the embedding cache from the rank step being reused, so it is not a cold figure. All timings from the `demo` workflow on a GitHub-hosted runner, Oct 12, 2026. See `docs/FINDINGS.md` (Performance). |
| Evaluated on SWE-bench Verified and at least 4 self-harvested repos, 2 held out | **Done.** Real run committed in `results/`: 127 SWE-bench Verified test instances, 350 self-harvested test instances (17 repos), 90 on 3 held-out repos. 0 instances excluded, 0 leakage failures. |
| Recall@10 against all four baselines, ablation table published | **Done.** All baselines and the full pipeline reported on identical indexes with bootstrap CIs and paired margin vs BM25; see `README.md` and `docs/FINDINGS.md`. The full pipeline beats BM25 on SWE-bench (+0.096, CI +0.034 to +0.162) but not on the self-harvested control (+0.003, CI -0.028 to +0.032). |
| Snapshot-leakage test passing | **Done.** `tests/test_snapshot_leakage.py`. The same guard runs on every evaluated instance and failures are listed. |
| Static results live on GitHub Pages | **Done.** Deployed via the `pages` workflow (confirmed by the owner on Oct 12, 2026). Live at https://ratyagi.github.io/ContextHarvester/ (linked from the README). |
| README states method, number, limitation in first three paragraphs | **Done.** Method, the number (with the control that disagrees), and the lower-bound limitation. |
| Clay corpus build recorded, column config screenshotted, `corpus/repos.csv` committed | **Partly done.** Built in Clay on the Growth trial; `corpus/repos.csv` (20 repos, 3 held out) and the raw export are committed and covered by `tests/test_corpus.py`. Screen recording done and linked ([video](https://youtu.be/dfvmURSpRbc), `docs/evidence/README.md`). Screenshots are in `docs/evidence/`: plan allowance, workbook, HTTP API accounts, finished table, and the Use AI column config. **Not captured:** settings screenshots of the `gh`, `fixes_raw` and `actions` HTTP API columns (the recording shows them). |

## In progress: scalable cold path (owner chose the option that scales, Oct 12, 2026)

Built behind options, defaults unchanged so the committed results stay reproducible: candidate-scoped semantic search (embeds only the top lexical hits, cost bounded by K, not repo size), a regex import extractor, and memoized tokenization. Tested for equivalence and bounds. **Not yet measured:** the recall cost (run the `experiments` workflow, dev instances only) and the cold time on a large repo (run the `demo` workflow with `scope=candidates`). The PRD's semantic stage says one embedding per file for every file, so adopting this as the default needs a PRD amendment, which waits for those numbers and the owner's approval.

## Pipeline stages

Snapshot, lexical, semantic, structural, fusion, rerank, score: all built and tested. Rerank, the provider-fallback layer, the GitHub harvester, and the `rank` and `replay` commands are tested with mocks and a local repo only (no live API calls or real clones were possible). The tune and eval workflows have exercised MiniLM, real clones and the harvester on real repos. The LLM rerank has still not run against a live provider and is not in the evaluation.

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

## PRD amendments

On Oct 12, 2026 the owner approved removing the `clay-run/agent-plugins` issue/PR deliverable from the PRD (see `docs/PRD.md`, Amendments). It no longer appears in the success criteria.
