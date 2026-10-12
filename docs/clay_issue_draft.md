# Draft issue for clay-run/agent-plugins

Status: **drafted, not posted.** `CONTRIBUTING.md` in that repo says it is a read-only distribution home and pull requests are not accepted; issues are welcome. The PRD asks for "one substantive issue or PR", so an issue satisfies it. Post it from your own GitHub account, then record the link in `docs/STATUS.md`.

Grounding: everything below was checked against `clay-run/agent-plugins` at commit `a813258` (plugin v2.32.0, CLI 1.9.0), and the error messages are the exact strings Clay returned while I built the evaluation corpus for this project on the Growth trial.

---

**Title:** `tables-error-sweep`: diagnosis table has no rows for HTTP API column failures (missing User-Agent, unresolved column reference)

**Body:**

### Summary

`clay/skills/tables-error-sweep/SKILL.md` ("5. Diagnose", lines 71 to 81) maps errored-cell messages to root causes: rate limits, bad credentials, empty upstream input, gated skips, and a catch-all "provider-specific error text". It has no guidance for failures from an **HTTP API** column. A search of the whole repo at `a813258` finds zero mentions of "HTTP API", so an agent sweeping a table that calls a REST API has nothing to classify these with, and the catch-all row ("Read the message literally; often a data-quality issue in the input") points it at the wrong cause for the two cases below.

### What I hit

I used a Growth-trial table of 24 repositories with HTTP API columns calling `https://api.github.com/repos/<repo>`. Three distinct failures, in the order I met them:

1. **Missing User-Agent.** Status 403, content: `Request forbidden by administrative rules. Please make sure your request has a User-Agent header`. The column sends no User-Agent by default and GitHub rejects such requests. Fix: add a `User-Agent` header to the saved account.
2. **Column reference not resolved.** Status 404, content: `{"message": "Not Found", ...}`. The URL field contained the text `{{repo}}` typed by hand instead of a column reference, so the literal characters were sent.
3. **Host and path run together.** Error `-3008`: `getaddrinfo ENOTFOUND api.github.compallets`. After inserting the column reference, the `/repos/` segment was lost, producing a malformed hostname.

None of these is a data-quality problem in the input row, which is what the current catch-all row suggests. All three are request-construction problems, and all three show as errored cells for every row in the column, not for a subset.

### Suggested change

Add rows to the diagnosis table, for example:

| Message pattern | Likely root cause | Direction |
|---|---|---|
| 403 with "User-Agent", "forbidden by administrative rules" | The HTTP API column sends no `User-Agent` and the target API requires one (GitHub does) | Add a `User-Agent` header (on the saved account or the column) and rerun |
| `ENOTFOUND`, `-3008`, or 404 on **every** row of an HTTP API column | The request URL is malformed: a column reference that did not resolve, or host and path concatenated | Inspect the URL the column actually sent; rebuild it with a column reference inserted from the picker, or build it in a Formula column and reference that |

A short note that errors affecting 100% of rows in one column usually indicate request construction rather than row data would also help the agent choose between "sample the messages" and "fix the column".

### Context

Found while building an evaluation corpus for a retrieval project. I used the Clay UI, not the CLI, so I have not confirmed whether `clay tables rows get` returns these exact strings; the suggestion concerns how the skill classifies errored-cell messages regardless of source. Happy to test a revised skill against the same table.
