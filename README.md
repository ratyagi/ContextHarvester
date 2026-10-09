# Context Harvester

Given a repository and an issue, Context Harvester returns the ranked minimal set of files a coding agent needs to read to fix it, with a one-line reason per file and a running token count. It fuses three independent signals: BM25 over file contents, MiniLM embeddings in FAISS, and a one-hop import graph, using reciprocal rank fusion. A single LLM pass at the end drops files and writes the reasons, stopping at a token budget. The LLM does not do the retrieval.

**The number:** file-level recall@10 against the files the merged fix touched, on a forward time split with the fix excluded from the index. On SWE-bench Verified (127 instances after the 2022-05-06 cutoff, filtered gold) the full pipeline reaches **0.795 vs 0.699 for BM25, a margin of +0.096** (95% CI +0.034 to +0.162, paired bootstrap). On the issues with no patch or file name in the text it is 0.765 vs 0.634 (+0.132, CI +0.047 to +0.218). **The independent control does not agree.** On self-harvested `Fixes #N` links from 17 repos SWE-bench never covered (350 instances) the full pipeline scores 0.687 vs BM25's 0.684 (+0.003, CI -0.028 to +0.032), and on 3 held-out repos (90 instances) 0.832 vs 0.832. Embeddings alone lose to BM25 on both sources, and the import graph's own contribution is not statistically established on either (paired CI includes zero). Sources are reported separately and never pooled, and the LLM rerank stage is not part of these numbers. Full tables are at the bottom, the interpretation is in [`docs/FINDINGS.md`](docs/FINDINGS.md), the spec is [`docs/PRD.md`](docs/PRD.md), and the status of every PRD item is in [`docs/STATUS.md`](docs/STATUS.md).

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
ch split corpus/instances_*.parquet               # freeze cutoff; held-out repos come from repos.csv; commit split.json
ch tune corpus/instances_*.parquet                    # dev instances only (before cutoff, non-held-out)
ch eval corpus/instances_swebench.parquet --out results/swebench --web-data web/data/swebench
ch eval corpus/instances_harvested.parquet --out results/harvested --web-data web/data/harvested
python scripts/merge_results.py                       # results page data + this README's table
```

Leakage guards, all enforced in code: the index is a `git worktree` at the commit before the fix; the fix commit must not be an ancestor of the snapshot; every gold file's blob must differ from its post-fix blob (SWE-bench: the gold patch must apply forward and not in reverse); instances failing any guard are excluded and listed, never silently dropped (`tests/test_snapshot_leakage.py`). Time split is forward only, repos can be held out entirely, and issues containing a patch or naming a gold file are flagged and reported with and without. Gold-set filter rules are in `src/context_harvester/gold.py`.

Configurations compared on identical indexes: random, BM25, embeddings only, BM25 + embeddings (RRF, no graph), and the full pipeline. Cost axis: recall at fixed token budgets and median tokens to reach all gold files.

Infrastructure: none. GitHub Actions for compute, Parquet in the repo, a static page on GitHub Pages. See the PRD for what is deliberately not used.

## Clay corpus

The evaluation corpus (`corpus/repos.csv`, 20 Python repos, 3 held out) was built once in Clay on the Growth trial and committed. Nothing at runtime calls Clay. Walkthrough recording: [youtu.be/dfvmURSpRbc](https://youtu.be/dfvmURSpRbc). Details and exclusions: [`corpus/README.md`](corpus/README.md), [`docs/evidence/`](docs/evidence/README.md).

## Results

<!-- RESULTS:START -->
**harvested, test, filtered gold, all issues** (n=350)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.023 | 0.043 (0.027, 0.061) | 0.092 | -0.641 (-0.686, -0.597) | - | 471459 |
| BM25 over file contents | 0.583 | 0.684 (0.643, 0.724) | 0.785 | - | - | 63978 |
| Embeddings only (single pooled vector/file) | 0.479 | 0.589 (0.547, 0.630) | 0.696 | -0.095 (-0.136, -0.058) | - | 53453 |
| BM25 + embeddings (RRF, no graph) | 0.606 | 0.699 (0.661, 0.737) | 0.803 | +0.015 (-0.012, 0.042) | - | 63305 |
| BM25 + embeddings + import graph (RRF) | 0.551 | 0.687 (0.650, 0.723) | 0.795 | +0.003 (-0.028, 0.032) | -0.012 (-0.034, 0.009) | 80018 |

**harvested, test, filtered gold, issues without fix text/file names** (n=247)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.020 | 0.046 (0.026, 0.069) | 0.095 | -0.598 (-0.653, -0.544) | - | 433687 |
| BM25 over file contents | 0.534 | 0.644 (0.595, 0.692) | 0.762 | - | - | 77440 |
| Embeddings only (single pooled vector/file) | 0.431 | 0.555 (0.504, 0.605) | 0.678 | -0.089 (-0.136, -0.040) | - | 69607 |
| BM25 + embeddings (RRF, no graph) | 0.568 | 0.669 (0.621, 0.716) | 0.786 | +0.025 (-0.006, 0.057) | - | 78290 |
| BM25 + embeddings + import graph (RRF) | 0.516 | 0.659 (0.615, 0.703) | 0.777 | +0.015 (-0.020, 0.051) | -0.010 (-0.035, 0.016) | 92824 |

**harvested, test, unfiltered gold, all issues** (n=350)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.023 | 0.043 (0.027, 0.061) | 0.092 | -0.641 (-0.686, -0.597) | - | 473932 |
| BM25 over file contents | 0.582 | 0.685 (0.643, 0.724) | 0.784 | - | - | 64097 |
| Embeddings only (single pooled vector/file) | 0.479 | 0.589 (0.547, 0.630) | 0.698 | -0.095 (-0.136, -0.058) | - | 53846 |
| BM25 + embeddings (RRF, no graph) | 0.607 | 0.700 (0.662, 0.737) | 0.803 | +0.015 (-0.012, 0.042) | - | 63876 |
| BM25 + embeddings + import graph (RRF) | 0.551 | 0.686 (0.649, 0.722) | 0.795 | +0.002 (-0.028, 0.031) | -0.014 (-0.035, 0.008) | 81022 |

**harvested, test, unfiltered gold, issues without fix text/file names** (n=247)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.020 | 0.046 (0.026, 0.069) | 0.095 | -0.599 (-0.654, -0.543) | - | 438217 |
| BM25 over file contents | 0.532 | 0.645 (0.597, 0.693) | 0.760 | - | - | 79276 |
| Embeddings only (single pooled vector/file) | 0.430 | 0.555 (0.503, 0.604) | 0.679 | -0.090 (-0.137, -0.041) | - | 70116 |
| BM25 + embeddings (RRF, no graph) | 0.568 | 0.670 (0.623, 0.716) | 0.784 | +0.025 (-0.006, 0.057) | - | 79773 |
| BM25 + embeddings + import graph (RRF) | 0.516 | 0.658 (0.615, 0.702) | 0.778 | +0.013 (-0.021, 0.049) | -0.011 (-0.037, 0.013) | 93232 |

**harvested, held_out, filtered gold, all issues** (n=90)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.088 | 0.115 (0.064, 0.171) | 0.179 | -0.717 (-0.791, -0.641) | - | 329632 |
| BM25 over file contents | 0.744 | 0.832 (0.774, 0.887) | 0.893 | - | - | 35534 |
| Embeddings only (single pooled vector/file) | 0.618 | 0.776 (0.715, 0.837) | 0.866 | -0.056 (-0.104, -0.007) | - | 46212 |
| BM25 + embeddings (RRF, no graph) | 0.768 | 0.839 (0.783, 0.894) | 0.918 | +0.007 (-0.024, 0.037) | - | 33297 |
| BM25 + embeddings + import graph (RRF) | 0.659 | 0.832 (0.778, 0.886) | 0.916 | +0.000 (-0.037, 0.038) | -0.006 (-0.035, 0.022) | 44692 |

**harvested, held_out, filtered gold, issues without fix text/file names** (n=56)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.061 | 0.098 (0.047, 0.163) | 0.159 | -0.724 (-0.818, -0.626) | - | 313285 |
| BM25 over file contents | 0.738 | 0.822 (0.741, 0.895) | 0.872 | - | - | 37701 |
| Embeddings only (single pooled vector/file) | 0.595 | 0.743 (0.661, 0.821) | 0.854 | -0.079 (-0.153, -0.008) | - | 55593 |
| BM25 + embeddings (RRF, no graph) | 0.763 | 0.829 (0.757, 0.896) | 0.915 | +0.007 (-0.033, 0.048) | - | 40736 |
| BM25 + embeddings + import graph (RRF) | 0.647 | 0.820 (0.751, 0.884) | 0.920 | -0.002 (-0.054, 0.048) | -0.010 (-0.042, 0.022) | 46196 |

**harvested, held_out, unfiltered gold, all issues** (n=90)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.088 | 0.114 (0.064, 0.170) | 0.178 | -0.713 (-0.786, -0.637) | - | 329632 |
| BM25 over file contents | 0.740 | 0.826 (0.767, 0.881) | 0.887 | - | - | 35534 |
| Embeddings only (single pooled vector/file) | 0.614 | 0.772 (0.712, 0.834) | 0.860 | -0.054 (-0.102, -0.005) | - | 46212 |
| BM25 + embeddings (RRF, no graph) | 0.764 | 0.834 (0.779, 0.889) | 0.913 | +0.007 (-0.022, 0.037) | - | 33297 |
| BM25 + embeddings + import graph (RRF) | 0.656 | 0.829 (0.774, 0.883) | 0.911 | +0.002 (-0.034, 0.039) | -0.005 (-0.034, 0.023) | 44692 |

**harvested, held_out, unfiltered gold, issues without fix text/file names** (n=56)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.061 | 0.096 (0.046, 0.163) | 0.158 | -0.717 (-0.810, -0.618) | - | 313285 |
| BM25 over file contents | 0.732 | 0.813 (0.734, 0.886) | 0.864 | - | - | 37701 |
| Embeddings only (single pooled vector/file) | 0.589 | 0.737 (0.654, 0.817) | 0.845 | -0.076 (-0.149, -0.007) | - | 55593 |
| BM25 + embeddings (RRF, no graph) | 0.757 | 0.822 (0.750, 0.888) | 0.906 | +0.009 (-0.031, 0.049) | - | 40736 |
| BM25 + embeddings + import graph (RRF) | 0.643 | 0.814 (0.744, 0.880) | 0.913 | +0.001 (-0.050, 0.050) | -0.008 (-0.039, 0.023) | 46196 |

**swebench, test, filtered gold, all issues** (n=127)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.010 | 0.034 (0.008, 0.066) | 0.050 | -0.665 (-0.745, -0.580) | - | 1251916 |
| BM25 over file contents | 0.557 | 0.699 (0.625, 0.774) | 0.785 | - | - | 36762 |
| Embeddings only (single pooled vector/file) | 0.523 | 0.654 (0.576, 0.734) | 0.813 | -0.045 (-0.138, 0.040) | - | 27506 |
| BM25 + embeddings (RRF, no graph) | 0.679 | 0.760 (0.688, 0.830) | 0.871 | +0.062 (0.008, 0.119) | - | 24283 |
| BM25 + embeddings + import graph (RRF) | 0.730 | 0.795 (0.731, 0.860) | 0.906 | +0.096 (0.034, 0.162) | +0.035 (-0.022, 0.092) | 23726 |

**swebench, test, filtered gold, issues without fix text/file names** (n=93)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.014 | 0.025 (0.000, 0.057) | 0.036 | -0.608 (-0.707, -0.507) | - | 1251916 |
| BM25 over file contents | 0.492 | 0.634 (0.538, 0.729) | 0.741 | - | - | 53326 |
| Embeddings only (single pooled vector/file) | 0.479 | 0.631 (0.532, 0.724) | 0.806 | -0.003 (-0.115, 0.110) | - | 26866 |
| BM25 + embeddings (RRF, no graph) | 0.628 | 0.723 (0.633, 0.811) | 0.832 | +0.090 (0.022, 0.163) | - | 36323 |
| BM25 + embeddings + import graph (RRF) | 0.698 | 0.765 (0.679, 0.849) | 0.886 | +0.132 (0.047, 0.218) | +0.042 (-0.026, 0.110) | 27290 |

**swebench, test, unfiltered gold, all issues** (n=127)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.010 | 0.034 (0.008, 0.066) | 0.050 | -0.665 (-0.745, -0.580) | - | 1251916 |
| BM25 over file contents | 0.557 | 0.699 (0.625, 0.774) | 0.785 | - | - | 36762 |
| Embeddings only (single pooled vector/file) | 0.523 | 0.654 (0.576, 0.734) | 0.813 | -0.045 (-0.138, 0.040) | - | 27506 |
| BM25 + embeddings (RRF, no graph) | 0.679 | 0.760 (0.688, 0.830) | 0.871 | +0.062 (0.008, 0.119) | - | 24283 |
| BM25 + embeddings + import graph (RRF) | 0.730 | 0.795 (0.731, 0.860) | 0.906 | +0.096 (0.034, 0.162) | +0.035 (-0.022, 0.092) | 23726 |

**swebench, test, unfiltered gold, issues without fix text/file names** (n=93)

| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |
|---|---|---|---|---|---|---|
| Random files (floor) | 0.014 | 0.025 (0.000, 0.057) | 0.036 | -0.608 (-0.707, -0.507) | - | 1251916 |
| BM25 over file contents | 0.492 | 0.634 (0.538, 0.729) | 0.741 | - | - | 53326 |
| Embeddings only (single pooled vector/file) | 0.479 | 0.631 (0.532, 0.724) | 0.806 | -0.003 (-0.115, 0.110) | - | 26866 |
| BM25 + embeddings (RRF, no graph) | 0.628 | 0.723 (0.633, 0.811) | 0.832 | +0.090 (0.022, 0.163) | - | 36323 |
| BM25 + embeddings + import graph (RRF) | 0.698 | 0.765 (0.679, 0.849) | 0.886 | +0.132 (0.047, 0.218) | +0.042 (-0.026, 0.110) | 27290 |
<!-- RESULTS:END -->
