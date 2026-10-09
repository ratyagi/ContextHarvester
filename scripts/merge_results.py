"""Combine per-source results into the page data and README block. Sources stay separate rows, never pooled."""
import json
from pathlib import Path

import pandas as pd

from context_harvester import report

parts = sorted(Path("results").glob("*/per_instance.parquet"))
# recompute from per-instance rows (cheap) so report changes never need a re-evaluation
summary = pd.concat([report.summarize(pd.read_parquet(p)) for p in parts], ignore_index=True)
for p in parts:
    report.summarize(pd.read_parquet(p)).to_parquet(p.parent / "summary.parquet", index=False)
metas, excluded = {}, []
for p in sorted(Path("web/data").glob("*/results.json")):
    d = json.loads(p.read_text())
    metas[p.parent.name] = d["meta"]
    excluded += d["excluded"]
Path("web/data").mkdir(parents=True, exist_ok=True)
Path("web/data/results.json").write_text(json.dumps({
    "meta": next(iter(metas.values()), {}) | {"per_source": metas},
    "labels": report.LABELS,
    "summary": json.loads(summary.to_json(orient="records")),
    "excluded": excluded,
}, indent=1))
report.update_readme(Path("README.md"), summary)
print(f"merged {len(parts)} result sets")
