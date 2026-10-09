# Findings

All numbers below come from the committed run in `results/` (per-instance and summary Parquet, `web/data/results.json`). Recall is file-level recall@10 against the files the merged fix touched, with incidental files filtered from gold unless stated. Recall against changed files is a **lower bound** on the true target: a highly ranked file that is not in the gold set is not necessarily a false positive.

## What was run

- Time split frozen before tuning at 2022-05-06. Tuning used dev instances only; held-out repos (`networkx`, `urllib3`, `tornado`) never touched tuning.
- Evaluated the test group and the held-out group: 127 SWE-bench Verified instances, 350 self-harvested test instances (17 repos), 90 self-harvested held-out instances (3 repos).
- The snapshot-leakage guard ran on every instance. **0 instances failed it and 0 were excluded for any other reason.**
- Five configurations on identical indexes: random, BM25, embeddings only, BM25 + embeddings (RRF, no graph), full (adds the one-hop import graph).
- The LLM rerank stage was not evaluated.

## Results (recall@10, filtered gold, all issues)

| Source | n | BM25 | Embeddings | BM25+emb | Full | Full minus BM25 (95% CI) |
|---|---|---|---|---|---|---|
| SWE-bench Verified, test | 127 | 0.699 | 0.654 | 0.760 | 0.795 | +0.096 (+0.034, +0.162) |
| Self-harvested, test | 350 | 0.684 | 0.589 | 0.699 | 0.687 | +0.003 (-0.028, +0.032) |
| Self-harvested, held-out repos | 90 | 0.832 | 0.776 | 0.839 | 0.832 | +0.000 (-0.037, +0.038) |

Without issues that contain a patch or name a gold file: SWE-bench 0.634 (BM25) vs 0.765 (full), +0.132 (+0.047, +0.218); self-harvested test 0.644 vs 0.659, +0.015 (-0.020, +0.051).

## What this says

1. **On SWE-bench Verified the full pipeline beats BM25 by a margin whose confidence interval excludes zero.** Per repo, full is at or above BM25 on all 11 repos in the test group (django: 0.740 to 0.827, n=49).
2. **That result did not replicate on the independent control.** On self-harvested links the full pipeline and BM25 are statistically indistinguishable, overall and on held-out repos. Per repo it is a split: full is ahead on 8 of 17 and behind on 9 (largest drops: sqlalchemy 0.869 to 0.655 on n=7, scrapy 0.799 to 0.610 on n=9, celery 0.633 to 0.523 on n=22).
3. **Embeddings alone lose to BM25** on both sources (significantly on self-harvested: -0.095, CI -0.136 to -0.058). BM25 is a strong baseline on code.
4. **Fusing BM25 and embeddings helps modestly** (+0.062 on SWE-bench with CI +0.008 to +0.119; +0.015 on self-harvested with CI crossing zero).
5. **The import graph's own contribution is not established on either source.** The paired margin of the full pipeline over BM25 + embeddings (no graph) is +0.035 on SWE-bench (95% CI -0.022 to +0.092) and -0.012 on self-harvested (CI -0.034 to +0.009). Both intervals include zero. So the SWE-bench gain over BM25 comes mostly from fusing BM25 with embeddings (+0.062, CI +0.008 to +0.119); the graph's added +0.035 is a point estimate that may be noise. On self-harvested the graph also lowers recall@5 (0.606 to 0.551) and raises median tokens to reach all gold (63k to 80k).

## Not yet established (hypotheses, not findings)

- SWE-bench repos are likely over-represented in model training data, and the 127 test instances are Django-heavy (49). The self-harvested result is what the PRD designates as the control for this. Why the two disagree is untested.
- The graph step may hurt where fixes span few import-connected files, or where hub modules flood the neighbor list. Untested; the grid in `corpus/tuning_grid.parquet` is the starting point.
- The paired interval for the graph is now in the report (finding 5). It is inconclusive on SWE-bench and slightly negative on self-harvested, so the graph step should not be presented as a demonstrated contributor.
