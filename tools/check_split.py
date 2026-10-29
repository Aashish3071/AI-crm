"""Prove a split changed no API behaviour: compare this tree with a git revision.

    python3 tools/check_split.py [revision]        # default HEAD

Loads the app from both trees (on throwaway storage) and checks that
1. the OpenAPI description is identical — every path, method, parameter and body model;
2. the same handlers exist, by method, path and function name;
3. every route's path still reaches the same handler first, now that moved routes sit
   after the ones left in pipecat_server.py.
Exits non-zero, listing each difference, when any check fails.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DUMP = r"""
import json, sys
import crm_test_isolation  # noqa: F401  (throwaway storage)
import pipecat_server as server

def walk(routes):
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from walk(inner.routes)
        elif getattr(route, "methods", None) and hasattr(route, "path_regex"):
            yield route

routes = [{"methods": sorted(r.methods), "path": r.path, "regex": r.path_regex.pattern,
           "handler": f"{r.endpoint.__module__}.{r.endpoint.__name__}"} for r in walk(server.app.router.routes)]
json.dump({"openapi": server.app.openapi(), "routes": routes}, sys.stdout, sort_keys=True)
"""


def dump(tree: Path) -> dict:
    result = subprocess.run([sys.executable, "-c", DUMP], cwd=tree, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"Could not load the app from {tree}:\n{result.stderr[-3000:]}")
    return json.loads(result.stdout)


def sample(path: str) -> str:
    return re.sub(r"\{[^}:]+:path\}", "x1/x2", re.sub(r"\{[^}:]+\}", "x1", path))


def first_match(routes: list, method: str, path: str) -> str:
    for route in routes:
        if method in route["methods"] and re.match(route["regex"], path):
            return route["handler"].split(".")[-1]
    return "(none)"


def main() -> int:
    revision = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "base.tar"
        subprocess.run(["git", "archive", "-o", str(archive), revision], cwd=ROOT, check=True)
        base_tree = Path(tmp) / "base"
        with tarfile.open(archive) as tar:
            tar.extractall(base_tree, filter="data")
        before, after = dump(base_tree), dump(ROOT)

    problems = []
    if json.dumps(before["openapi"], sort_keys=True) != json.dumps(after["openapi"], sort_keys=True):
        old_paths, new_paths = before["openapi"]["paths"], after["openapi"]["paths"]
        for path in sorted(set(old_paths) | set(new_paths)):
            if old_paths.get(path) != new_paths.get(path):
                problems.append(f"OpenAPI differs at {path}")
        if not problems:
            problems.append("OpenAPI differs outside paths (components)")

    def handlers(state):
        return Counter((m, r["path"], r["handler"].split(".")[-1]) for r in state["routes"] for m in r["methods"])
    for label, diff in (("missing", handlers(before) - handlers(after)), ("added", handlers(after) - handlers(before))):
        problems += [f"Route {label}: {m} {p} → {h}" for (m, p, h) in sorted(diff)]

    samples = {(m, sample(r["path"])) for state in (before, after) for r in state["routes"] for m in r["methods"]}
    for method, path in sorted(samples):
        old, new = first_match(before["routes"], method, path), first_match(after["routes"], method, path)
        if old != new:
            problems.append(f"{method} {path} reached {old}, now {new}")

    moved = Counter(r["handler"].rsplit(".", 1)[0] for r in after["routes"])
    print(f"{len(after['routes'])} routes; by module: " + ", ".join(f"{k} {v}" for k, v in sorted(moved.items())))
    for problem in problems:
        print("  ✗", problem)
    print("No behaviour change in routing or the API description." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
