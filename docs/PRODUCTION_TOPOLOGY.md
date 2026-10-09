# Production topology vs. this portfolio version

This repo is a CLI plus a static results page on purpose (PRD: Deliberately not used). If this ran for a platform team in production, it would look different:

- **Indexing service.** Index per repo and per merge to the default branch, stored by commit. The 60-second cold-start goal disappears for repos already indexed; only the issue embedding and fusion run per request.
- **Vector store.** Per-repo FAISS or pgvector shards once a monorepo has hundreds of thousands of files. A few thousand files per repo do not justify one here.
- **Serving.** A small stateless API (or MCP tool) in front of the index, so parallel agents share one index instead of each rebuilding it.
- **Evaluation.** The same harness, scheduled, against that team's own merged PRs as ground truth, with the leakage guards unchanged.

None of it is built here because nothing in the demo needs it, and a stack diagram of services that never ran proves nothing.
