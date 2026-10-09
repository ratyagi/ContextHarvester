"""Mine `Fixes #N` issue-to-PR links from any public repo via the GitHub REST API (PRD: self-harvested ground truth).

Gold = files the merged PR touched. Base commit = parent of the PR's first commit, i.e. the commit
immediately before the fix work. No cloning needed here; snapshotting happens at eval time.
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, asdict

import httpx
import pandas as pd

from .gold import filter_gold, incidental_reason, is_test_file, leaky_issue

API = "https://api.github.com"
LINK = re.compile(r"(?i)\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+)?#(\d+)")

COLUMNS = [
    "instance_id", "source", "repo", "issue_number", "pr_number", "issue_title", "issue_text",
    "created_at", "base_commit", "fix_commit", "gold_files", "gold_patch", "leaky",
]


class GitHub:
    def __init__(self, token: str | None = None, client: httpx.Client | None = None):
        token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.c = client or httpx.Client(headers=headers, timeout=30, follow_redirects=True)

    def get(self, path: str, _sleep=time.sleep, **params):
        """GET with rate-limit handling: wait out a spent quota instead of failing (or silently skipping)."""
        for attempt in range(4):
            r = self.c.get(path if path.startswith("http") else API + path, params=params)
            limited = r.status_code in (403, 429) and (
                r.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in r.headers
            )
            if not limited or attempt == 3:
                r.raise_for_status()
                return r.json()
            if "retry-after" in r.headers:
                wait = float(r.headers["retry-after"])
            else:
                wait = max(0.0, float(r.headers.get("x-ratelimit-reset", 0)) - time.time())
            wait = min(wait + 2, 3700)
            print(f"GitHub rate limit hit; waiting {wait:.0f}s", file=sys.stderr)
            _sleep(wait)

    def paged(self, path: str, limit: int, **params):
        out, page = [], 1
        while len(out) < limit:
            batch = self.get(path, per_page=100, page=page, **params)
            if not batch:
                break
            out.extend(batch)
            page += 1
        return out[:limit]


def linked_issues(text: str) -> list[int]:
    return sorted({int(n) for n in LINK.findall(text or "")})


def gold_from_pr_files(files: list[dict]) -> list[str]:
    """Touched paths, using the pre-image path for renames so it exists in the snapshot."""
    out: list[str] = []
    for f in files:
        for p in (f.get("previous_filename"), f["filename"]):
            if p and p not in out:
                out.append(p)
    return out


def build_instance(gh: GitHub, repo: str, pr: dict, issue_number: int) -> dict | None:
    issue = gh.get(f"/repos/{repo}/issues/{issue_number}")
    if "pull_request" in issue:
        return None
    n = pr["number"]
    commits = gh.paged(f"/repos/{repo}/pulls/{n}/commits", 250)
    if not commits or not commits[0].get("parents"):
        return None
    files = gh.paged(f"/repos/{repo}/pulls/{n}/files", 3000)
    all_files = gold_from_pr_files(files)
    # Source files only: SWE-bench separates patch from test_patch, so tests are not gold here either.
    gold = [f for f in filter_gold(all_files) if not is_test_file(f)]
    if not any(f.endswith(".py") for f in gold):
        return None
    text = f"{issue['title']}\n\n{issue.get('body') or ''}"
    return {
        "instance_id": f"{repo.replace('/', '__')}-{issue_number}",
        "source": "harvested",
        "repo": repo,
        "issue_number": issue_number,
        "pr_number": n,
        "issue_title": issue["title"],
        "issue_text": text,
        "created_at": issue["created_at"],
        "base_commit": commits[0]["parents"][0]["sha"],
        "fix_commit": pr["merge_commit_sha"],
        "gold_files": all_files,  # unfiltered; the filter is applied (and reported) at eval time
        "gold_patch": "",
        "leaky": leaky_issue(text, gold),
    }


def harvest_repo(gh: GitHub, repo: str, max_instances: int = 60, scan_prs: int = 600) -> list[dict]:
    prs = gh.paged(f"/repos/{repo}/pulls", scan_prs, state="closed", sort="updated", direction="desc")
    out, seen = [], set()
    for pr in prs:
        if not pr.get("merged_at") or not pr.get("merge_commit_sha"):
            continue
        for num in linked_issues(f"{pr['title']}\n{pr.get('body') or ''}"):
            if num in seen:
                continue
            try:
                inst = build_instance(gh, repo, pr, num)
            except httpx.HTTPError as e:  # logged, never silent
                print(f"skip {repo}#{num}: {e}", file=sys.stderr)
                continue
            if inst:
                seen.add(num)
                out.append(inst)
        if len(out) >= max_instances:
            break
    return out


def to_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS)
