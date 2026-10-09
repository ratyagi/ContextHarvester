# Context Harvester

Given a repository and an issue, Context Harvester returns the ranked minimal set of files a coding agent needs to read to fix it, with a one-line reason per file and a running token count. It fuses three independent signals: BM25 over file contents, MiniLM embeddings in FAISS, and a one-hop import graph, using reciprocal rank fusion. A single LLM pass at the end drops files and writes the reasons, stopping at a token budget. The LLM does not do the retrieval.

**The number:** file-level recall@10 against the files the merged fix touched, compared with BM25 and embedding baselines, on SWE-bench Verified and on self-harvested `Fixes #N` links from other repos, reported separately and never pooled. **No full run has been completed yet, so there is no headline number in this README.** The table at the bottom fills in from `ch eval`; until then nothing is claimed. The spec is [`docs/PRD.md`](docs/PRD.md) and the honest status of every PRD item is in [`docs/STATUS.md`](docs/STATUS.md).

**Limitation, stated up front:** recall against changed files is a lower bound on the true target. An agent must read more than it edits, such as the interface a changed file implements or the caller it breaks, so a highly ranked file that is not in the gold set is not necessarily a false positive. Also: SWE-bench repos are likely over-represented in model training data, so the self-harvested set is the control, and incidental files (lockfiles, changelogs, generated code, version bumps, test fixtures) are filtered from gold with both filtered and unfiltered recall reported.

## Use

```bash
pip install -e ".[dev]"
ch rank pallets/click 1234                  # open issue: ranked files, reasons, cumulative tokens
ch rank pallets/click 1234 --json           # same, for an agent calling it as a tool
ch replay pallets/click 2000                # closed issue: snapshot before the fix, then grade vs the merged PR
```

Rerank uses the first available provider among `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`. With none set (or `--no-rerank`) you get the fusion ranking with signal-based reasons. Set `GITHUB_TOKEN` to avoid API rate limits.

## Evaluation pipeline

```bash
ch swebench                                           # SWE-bench Verified -> corpus/instances_swebench.parquet
ch harvest                                            # corpus/repos.csv (from Clay) -> corpus/instances_harvested.parquet
ch split corpus/instances_*.parquet --held-out a/b --held-out c/d   # freeze cutoff + held-out repos, commit split.json
ch tune corpus/instances_*.parquet                    # dev instances only (before cutoff, non-held-out)
ch eval corpus/instances_swebench.parquet --out results/swebench --web-data web/data/swebench
ch eval corpus/instances_harvested.parquet --out results/harvested --web-data web/data/harvested
python scripts/merge_results.py                       # results page data + this README's table
```

Leakage guards, all enforced in code: the index is a `git worktree` at the commit before the fix; the fix commit must not be an ancestor of the snapshot; every gold file's blob must differ from its post-fix blob (SWE-bench: the gold patch must apply forward and not in reverse); instances failing any guard are excluded and listed, never silently dropped (`tests/test_snapshot_leakage.py`). Time split is forward only, repos can be held out entirely, and issues containing a patch or naming a gold file are flagged and reported with and without. Gold-set filter rules are in `src/context_harvester/gold.py`.

Configurations compared on identical indexes: random, BM25, embeddings only, BM25 + embeddings (RRF, no graph), and the full pipeline. Cost axis: recall at fixed token budgets and median tokens to reach all gold files.

Infrastructure: none. GitHub Actions for compute, Parquet in the repo, a static page on GitHub Pages. See the PRD for what is deliberately not used.

## Results

<!-- RESULTS:START -->
_No evaluation has been run yet._
<!-- RESULTS:END -->
