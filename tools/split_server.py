"""Move API areas out of pipecat_server.py into crm_routes/ without changing behaviour.

    python3 tools/split_server.py plan <path pattern> ...       # what would move, and why not
    python3 tools/split_server.py move <module> "<docstring>" <path pattern> ...

Patterns are shell-style matches on route paths, e.g. ``/api/calls`` ``/api/calls/*``. The
matching routes move, with every helper that only they use, wherever it is defined. A
definition moves only when nothing else uses it: no other code in pipecat_server.py, no
test, script or route module (``server.x``, ``core.x``, ``from pipecat_server import x``).
Everything shared stays where it is, so nothing has to be re-exported and module-level
settings that tests replace keep one owner.

In the moved code a route decorator ``@app.get`` becomes ``@router.get``; a name the server
module defines becomes ``core.name``, resolved at call time; a name the server imports is
imported again by the new module. The run refuses, and changes nothing, when a moved
definition binds a local variable with the same name as a server-level one it also reads,
or when it can't account for a name. Check the result with tools/check_split.py.
"""
from __future__ import annotations

import ast
import fnmatch
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "pipecat_server.py"
ROUTES = ROOT / "crm_routes"
HEADER_RE = re.compile(r"^# ─── (.+?)\s*─+\s*$")
ROUTE_METHODS = {"get", "post", "put", "delete", "patch"}
INCLUDE_MARK = "# Imported last: each module reaches this one's helpers at call time."
EXTERNAL_GLOBS = ["tests/*.py", "test_*.py", "conftest.py", "crm_*.py", "crm_routes/*.py",
                  "migrate_to_postgres.py", "tools/*.py"]


# ─── Reading the server ─────────────────────────────────────────────────────
class Stmt:
    def __init__(self, node: ast.stmt, lines: List[str]):
        self.node = node
        first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        start = first
        while start > 1 and lines[start - 2].lstrip().startswith("#") and not HEADER_RE.match(lines[start - 2]):
            start -= 1                                     # comments directly above travel with it
        self.start, self.first, self.end = start, first, node.end_lineno
        self.binds = module_bindings(node)
        self.refs = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        self.section = ""


def module_bindings(node: ast.stmt) -> Set[str]:
    """Names a top-level statement binds in the module namespace."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    names: Set[str] = set()
    stack = [node]
    while stack:
        current = stack.pop()
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(child.name)
            elif isinstance(child, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                continue
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                names |= module_bindings(child)
            else:
                stack.append(child)
    return names


def read_server() -> Tuple[str, List[str], List[Stmt]]:
    source = SERVER.read_text(encoding="utf-8")
    lines = source.split("\n")
    stmts = [Stmt(node, lines) for node in ast.parse(source).body]
    headers = [(i + 1, m.group(1)) for i, line in enumerate(lines) if (m := HEADER_RE.match(line))]
    for stmt in stmts:
        stmt.section = next((title for line, title in reversed(headers) if line < stmt.first), "")
    return source, lines, stmts


def external_names() -> Set[str]:
    """Server names used from outside pipecat_server.py."""
    found: Set[str] = set()
    for pattern in EXTERNAL_GLOBS:
        for path in ROOT.glob(pattern):
            text = path.read_text(encoding="utf-8")
            found |= set(re.findall(r"\b(?:server|core|pipecat_server)\.([A-Za-z_]\w*)", text))
            found |= set(re.findall(r"""["']pipecat_server\.([A-Za-z_]\w*)""", text))
            for group in re.findall(r"from pipecat_server import \(?([^)\n]+(?:\n[^)\n]+)*)\)?", text):
                found |= {n.strip().split(" as ")[0] for n in group.replace("\n", ",").split(",") if n.strip()}
    return found


# ─── Deciding what moves ────────────────────────────────────────────────────
def _route_decorated(node: ast.AST) -> Tuple[bool, bool]:
    """(has a route decorator, has some other @app decorator)."""
    route = other = False
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "app":
            if target.attr in ROUTE_METHODS:
                route = True
            else:
                other = True
    return route, other


def _movable_kind(stmt: Stmt) -> bool:
    node = stmt.node
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return True
    if isinstance(node, ast.Assign):
        return all(isinstance(t, ast.Name) for t in node.targets)
    return isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)


def route_paths(node: ast.AST) -> List[str]:
    paths = []
    for dec in getattr(node, "decorator_list", []):
        if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "app" and dec.func.attr in ROUTE_METHODS):
            paths.append(ast.literal_eval(dec.args[0]))
    return paths


def plan(patterns: Iterable[str]) -> Tuple[List[Stmt], Dict[str, str]]:
    _, _, stmts = read_server()
    patterns = list(patterns)
    seeds = [s for s in stmts if any(fnmatch.fnmatchcase(p, pat) for p in route_paths(s.node) for pat in patterns)]
    if not seeds:
        raise SystemExit(f"No route matches {' '.join(patterns)}")
    pinned = external_names()
    stay_reason: Dict[str, str] = {}

    def movable(stmt: Stmt) -> bool:
        name = ", ".join(sorted(stmt.binds)) or f"line {stmt.first}"
        reason = ("runs at import time" if not _movable_kind(stmt) else
                  "app-level hook" if _route_decorated(stmt.node)[1] else
                  "rebinds module state" if any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(stmt.node)) else
                  "used outside pipecat_server.py" if stmt.binds & pinned else "")
        if reason:
            stay_reason[name] = reason
        return not reason

    # The routes, plus every helper they reach that isn't itself a route.
    by_name = {n: s for s in stmts for n in s.binds}
    moving: List[Stmt] = [s for s in seeds if movable(s)]
    queue = list(moving)
    while queue:
        for name in queue.pop().refs:
            helper = by_name.get(name)
            if helper and helper not in moving and not route_paths(helper.node) and _movable_kind(helper) \
                    and not isinstance(helper.node, (ast.Import, ast.ImportFrom)) and movable(helper):
                moving.append(helper)
                queue.append(helper)
    moving.sort(key=lambda s: s.start)
    bound_elsewhere = {n for s in stmts if s not in moving for n in s.binds}
    changed = True
    while changed:
        changed = False
        staying = [s for s in stmts if s not in moving]
        for stmt in list(moving):
            users = [s for s in staying if s.refs & stmt.binds]
            if users or stmt.binds & bound_elsewhere:
                user_names = sorted({n for u in users for n in u.binds}) or ["import-time code"]
                why = (f"used by {', '.join(user_names[:4])}" + (f" and {len(user_names) - 4} more" if len(user_names) > 4 else "")
                       if users else "also bound elsewhere")
                stay_reason[", ".join(sorted(stmt.binds))] = why
                moving.remove(stmt)
                changed = True
    return moving, stay_reason


# ─── Writing the module ─────────────────────────────────────────────────────
def _local_bindings(node: ast.AST) -> Set[str]:
    """Every name bound anywhere inside a definition (arguments, assignments, loops…)."""
    names: Set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not node:
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names |= module_bindings(n)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            names.add(n.name)
    return names


def _import_lines(stmts: List[Stmt], used: Set[str], core: bool) -> List[str]:
    """Imports for the new module, grouped standard library, third party, project."""
    plain: Dict[str, int] = {}
    froms: Dict[str, List[str]] = {"fastapi": ["APIRouter"]}
    for stmt in stmts:
        node = stmt.node
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.asname or alias.name).split(".")[0] in used:
                    plain[f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")] = 1
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.name + (f" as {alias.asname}" if alias.asname else "")
                if (alias.asname or alias.name) in used and name not in froms.get(node.module, []):
                    froms.setdefault(node.module, []).append(name)
    if core:
        plain["import pipecat_server as core"] = 1

    def group(module: str) -> int:
        top = module.split(".")[0]
        return 0 if top in sys.stdlib_module_names else 2 if top.startswith("crm_") or top == "pipecat_server" else 1

    lines: Dict[int, List[str]] = {0: [], 1: [], 2: []}
    for line in plain:
        lines[group(line.split()[1])].append(line)
    for module, names in froms.items():
        line = f"from {module} import {', '.join(sorted(names, key=str.lower))}"
        if len(line) > 110:
            line = f"from {module} import (" + ",\n    ".join(sorted(names, key=str.lower)) + ")"
        lines[group(module)].append(line)
    blocks = [sorted(lines[g], key=lambda l: (l.startswith("from "), l.split()[1])) for g in (0, 1, 2) if lines[g]]
    return [line for block in blocks for line in block + [""]][:-1]


def _rewrite(text_lines: List[str], node: ast.AST, offset: int, core_names: Set[str]) -> List[str]:
    """Rewrite server-level names in one statement; positions are UTF-8 byte offsets."""
    edits: Dict[int, List[Tuple[int, int, str]]] = {}
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "app":
            v = target.value
            edits.setdefault(v.lineno, []).append((v.col_offset, v.end_col_offset, "router"))
    decorator_apps = set()
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "app":
            decorator_apps.add(id(target.value))
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in core_names and id(n) not in decorator_apps:
            if n.lineno != n.end_lineno:
                raise SystemExit(f"Name spans lines at {n.lineno}")
            edits.setdefault(n.lineno, []).append((n.col_offset, n.end_col_offset, f"core.{n.id}"))
    out = list(text_lines)
    for lineno, changes in edits.items():
        index = lineno - offset
        raw = out[index].encode("utf-8")
        for start, end, new in sorted(changes, reverse=True):
            raw = raw[:start] + new.encode("utf-8") + raw[end:]
        out[index] = raw.decode("utf-8")
    return out


def move(module: str, docstring: str, sections: List[str]) -> None:
    source, lines, stmts = read_server()
    moving, stay_reason = plan(sections)
    if not moving:
        raise SystemExit("Nothing in those sections can move")
    moving_names = {n for s in moving for n in s.binds}
    import_stmts = [s for s in stmts if isinstance(s.node, (ast.Import, ast.ImportFrom))]
    imported = {n for s in import_stmts for n in s.binds}
    defined = {n for s in stmts for n in s.binds} - imported - moving_names
    import builtins
    used_imports: Set[str] = set()
    body: List[str] = []
    for stmt in moving:
        refs = stmt.refs
        clash = (refs & defined) & _local_bindings(stmt.node)
        if clash:
            raise SystemExit(f"{', '.join(sorted(stmt.binds))} binds a local with a server-level name: {sorted(clash)}")
        unknown = refs - defined - imported - moving_names - _local_bindings(stmt.node) - set(dir(builtins)) - {"app"}
        if unknown:
            raise SystemExit(f"{', '.join(sorted(stmt.binds))} reads names I can't place: {sorted(unknown)}")
        used_imports |= refs & imported
        chunk = lines[stmt.start - 1:stmt.end]
        chunk = _rewrite(chunk, stmt.node, stmt.start, refs & defined)
        body.append("\n".join(chunk))
    uses_core = any("core." in chunk for chunk in body)
    imports = _import_lines(import_stmts, used_imports, uses_core)
    text = f'"""{docstring.strip()}\n"""\n' + "\n".join(imports)
    text += "\n\nrouter = APIRouter()\n\n\n" + "\n\n\n".join(body) + "\n"
    target = ROUTES / f"{module}.py"
    if target.exists():
        raise SystemExit(f"{target} already exists")
    target.write_text(text, encoding="utf-8")

    # Remove the moved statements and any section left empty, then include the router.
    drop = {i for s in moving for i in range(s.start, s.end + 1)}
    kept = [line for i, line in enumerate(lines, 1) if i not in drop]
    kept = _drop_empty_sections(kept)
    text = "\n".join(kept)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    alias = f"_{module}_routes"
    text = text.replace(INCLUDE_MARK, INCLUDE_MARK + f"\nfrom crm_routes import {module} as {alias}  # noqa: E402", 1)
    text = text.rstrip("\n") + f"\napp.include_router({alias}.router)\n"
    SERVER.write_text(text, encoding="utf-8")
    print(f"Moved {len(moving)} definitions ({sum(s.end - s.start + 1 for s in moving)} lines) to {target.relative_to(ROOT)}")
    _report_staying(stay_reason)


def _drop_empty_sections(lines: List[str]) -> List[str]:
    """A header followed only by blank or comment lines before the next header is removed."""
    out: List[str] = []
    i = 0
    while i < len(lines):
        if HEADER_RE.match(lines[i]) and "moved to their own modules" not in lines[i]:
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("#")) and not HEADER_RE.match(lines[j]):
                j += 1
            if j >= len(lines) or HEADER_RE.match(lines[j]):
                i = j
                continue
        out.append(lines[i])
        i += 1
    return out


def _report_staying(stay_reason: Dict[str, str]) -> None:
    for name, why in sorted(stay_reason.items()):
        print(f"  stays: {name} — {why}")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in {"plan", "move"}:
        raise SystemExit(__doc__)
    if sys.argv[1] == "plan":
        moving, stay = plan(sys.argv[2:])
        for stmt in moving:
            print(f"  moves: {', '.join(sorted(stmt.binds))} ({stmt.end - stmt.start + 1} lines)")
        _report_staying(stay)
    else:
        move(sys.argv[2], sys.argv[3], sys.argv[4:])
