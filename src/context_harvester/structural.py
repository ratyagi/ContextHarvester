"""Import graph, one hop (PRD: Structural). Surfaces files the issue text never names."""
from __future__ import annotations

import ast
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from .files import RepoFile


def _module_names(path: str) -> list[str]:
    parts = path[:-3].split("/")  # strip .py
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return []
    # full dotted path plus every suffix (handles src/ layouts); suffixes of 1 part are too ambiguous
    return [".".join(parts[i:]) for i in range(len(parts)) if len(parts) - i >= 2 or i == 0]


@dataclass
class ImportGraph:
    forward: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # file -> files it imports
    reverse: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # file -> files importing it


def _shared_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a.split("/"), b.split("/")):
        if x != y:
            break
        n += 1
    return n


# An import statement as extracted from source: ("import", [dotted names]) or ("from", level, module, [names]).
FROM_RE = re.compile(r"^[ \t]*from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[^\n#;]*)", re.M)
IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+([^\n#;]+)", re.M)


def _ast_imports(text: str) -> list[tuple]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return []
    out: list[tuple] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.append(("import", [a.name for a in node.names]))
        elif isinstance(node, ast.ImportFrom):
            out.append(("from", node.level, node.module or "", [a.name for a in node.names if a.name != "*"]))
    return out


def _regex_imports(text: str) -> list[tuple]:
    """Same extraction without building an AST: a line scan is several times cheaper on large files.

    Handles relative imports, aliases and parenthesized multi-line name lists. Unlike the AST it can match
    an `import` line inside a docstring; that rare noise is measured against the AST graph on dev instances.
    """
    out: list[tuple] = []
    for m in IMPORT_RE.finditer(text):
        out.append(("import", [part.split()[0] for part in m.group(1).split(",") if part.strip()]))
    for m in FROM_RE.finditer(text):
        names = [part.split()[0] for part in m.group(3).strip("() \t").replace("\n", " ").split(",") if part.strip()]
        out.append(("from", len(m.group(1)), m.group(2), [n for n in names if n != "*"]))
    return out


def build_graph(files: list[RepoFile], mode: str = "ast") -> ImportGraph:
    """mode 'ast' (default) parses each file; mode 'regex' scans import lines (faster, same edges on valid code)."""
    extract = _regex_imports if mode == "regex" else _ast_imports
    by_mod: dict[str, list[str]] = defaultdict(list)
    for f in files:
        for m in _module_names(f.path):
            by_mod[m].append(f.path)

    def resolve(mod: str, importer: str) -> str | None:
        cands = by_mod.get(mod)
        if not cands:
            return None
        return max(cands, key=lambda c: (_shared_prefix(c, importer), -len(c)))

    g = ImportGraph()
    for f in files:
        pkg_parts = f.path.split("/")[:-1]
        targets: set[str] = set()

        def add_longest(name: str) -> bool:
            parts = name.split(".")
            for i in range(len(parts), 0, -1):  # longest prefix that is a repo module
                t = resolve(".".join(parts[:i]), f.path)
                if t:
                    targets.add(t)
                    return True
            return False

        for imp in extract(f.text):
            if imp[0] == "import":
                for name in imp[1]:
                    add_longest(name)
                continue
            _, level, module, names = imp
            if level:
                base = pkg_parts[: len(pkg_parts) - (level - 1)]
                mod = ".".join(base + ([module] if module else []))
            else:
                mod = module
            if not mod:
                continue
            # `from pkg import util` imports the submodule; only fall back to the package itself
            # (its __init__) when a name is not a submodule, e.g. a function or class.
            subs = [resolve(f"{mod}.{n}", f.path) for n in names]
            targets.update(t for t in subs if t)
            if not subs or any(t is None for t in subs):
                add_longest(mod)
        targets.discard(f.path)
        for t in targets:
            g.forward[f.path].add(t)
            g.reverse[t].add(f.path)
    return g


def expand(
    seeds: list[tuple[str, float]],
    graph: ImportGraph,
    n_seed: int = 10,
    max_per_seed: int = 6,
    reverse_weight: float = 0.5,
    hub_damping: bool = False,
) -> list[tuple[str, float]]:
    """One hop from the top seeds. A neighbor scores the sum of its parents' seed scores times edge weight.

    Forward edges (what a hit imports) weigh 1.0; reverse edges (what imports a hit) weigh reverse_weight.
    Per-seed neighbor count is capped so hub modules cannot flood the list.
    """
    scores: dict[str, float] = defaultdict(float)
    for path, s in seeds[:n_seed]:
        nbrs = [(n, 1.0) for n in sorted(graph.forward.get(path, ()))] + [
            (n, reverse_weight) for n in sorted(graph.reverse.get(path, ()))
        ]
        # prefer low-degree neighbors: a file that imports everything says little
        nbrs.sort(key=lambda nw: (-nw[1], len(graph.reverse.get(nw[0], ())) + len(graph.forward.get(nw[0], ()))))
        for n, w in nbrs[:max_per_seed]:
            if hub_damping:  # a module that imports or is imported by everything says little about this issue
                w = w / math.log2(2 + len(graph.forward.get(n, ())) + len(graph.reverse.get(n, ())))
            scores[n] += s * w
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
