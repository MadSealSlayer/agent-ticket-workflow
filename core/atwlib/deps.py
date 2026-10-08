"""Built-in `deps` gate checks: every new third-party import in a changed file
is declared in the manifest that owns the file.

python-imports  nearest requirements*.txt or pyproject.toml above the file.
                `deps.python_extra_requirements` maps shared folders to extra
                manifests that must ALSO declare the import (a shared layer
                packaged into several services).
node-imports    nearest package.json above the file (dependencies,
                devDependencies, peerDependencies, optionalDependencies).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from . import util

PY_ALIASES = {
    "bs4": "beautifulsoup4", "psycopg2": "psycopg2-binary", "sklearn": "scikit-learn",
    "dateutil": "python-dateutil", "jwt": "PyJWT", "yaml": "PyYAML", "PIL": "Pillow",
    "cv2": "opencv-python", "dotenv": "python-dotenv", "google": "google-api-core",
    "attr": "attrs", "Crypto": "pycryptodome", "magic": "python-magic", "docx": "python-docx",
    "opensearchpy": "opensearch-py",
}

NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants", "crypto",
    "dgram", "diagnostics_channel", "dns", "domain", "events", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "path", "perf_hooks", "process", "punycode", "querystring",
    "readline", "repl", "stream", "string_decoder", "sys", "timers", "tls", "trace_events", "tty",
    "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib", "test",
}
NODE_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte")
_NODE_IMPORT = re.compile(
    r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|require\s*\(\s*|import\s+|export\s[^'"]*?from\s*)['"]([^'"]+)['"]""")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


# --------------------------------------------------------------------------- python

def _py_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return set()
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def _py_first_party(root: Path, module: str, file_dir: Path, extra_dirs) -> bool:
    dirs = {file_dir, root, root / "src", *(root / d for d in extra_dirs)}
    d = file_dir
    while root in d.parents or d == root:  # every ancestor up to the root
        dirs.add(d)
        if d == root:
            break
        d = d.parent
    return any((base / f"{module}.py").exists() or (base / module / "__init__.py").exists()
               or (base / module).is_dir() and any((base / module).glob("*.py"))
               for base in dirs)


def _parse_requirements(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        m = re.match(r"^([A-Za-z0-9._-]+)", line)
        if m:
            names.add(normalize(m.group(1)))
    return names


def _parse_pyproject(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    names = set()
    # PEP 621 arrays: dependencies = [...] and optional-dependencies groups.
    for block in re.findall(r"(?:^|\n)\s*[\w-]*dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL):
        names.update(normalize(m) for m in re.findall(r"['\"]\s*([A-Za-z0-9._-]+)", block))
    # Poetry tables: [tool.poetry.dependencies] and group tables.
    for block in re.findall(r"\[tool\.poetry\.(?:group\.[\w-]+\.)?(?:dev-)?dependencies\](.*?)(?=\n\[|\Z)", text, re.DOTALL):
        names.update(normalize(m) for m in re.findall(r"^\s*([A-Za-z0-9._-]+)\s*=", block, re.MULTILINE))
    return names


def _nearest(root: Path, start: Path, names) -> list[Path]:
    d = start
    while True:
        hits = [p for n in names for p in sorted(d.glob(n)) if p.is_file()]
        if hits:
            return hits
        if d == root or root not in d.parents:
            return []
        d = d.parent


def check_python(root: Path, files: list[str], cfg_deps: dict) -> dict:
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    aliases = {**PY_ALIASES, **(cfg_deps.get("aliases") or {})}
    first_party_dirs = cfg_deps.get("first_party") or []
    extra = cfg_deps.get("python_extra_requirements") or []
    ignore = set(cfg_deps.get("ignore") or [])
    missing, unowned = [], []
    cache: dict[Path, set[str]] = {}

    def declared(manifest: Path) -> set[str]:
        if manifest not in cache:
            cache[manifest] = (_parse_pyproject(manifest) if manifest.name == "pyproject.toml"
                               else _parse_requirements(manifest))
        return cache[manifest]

    for f in files:
        fp = root / f
        if not f.endswith(".py") or not fp.is_file():
            continue
        # The nearest manifests count together (requirements.txt OR
        # pyproject.toml). Each extra manifest must declare the import itself.
        nearest = _nearest(root, fp.parent, ("requirements*.txt", "pyproject.toml"))
        extras = [m for m in _extras_for(root, f, extra) if m not in nearest]
        if not nearest and not extras:
            unowned.append(f)
            continue
        for mod in sorted(_py_imports(fp)):
            if mod in stdlib or mod in ignore or _py_first_party(root, mod, fp.parent, first_party_dirs):
                continue
            dist = aliases.get(mod, mod)
            if nearest and not any(normalize(dist) in declared(m) for m in nearest):
                missing.append({"module": mod, "distribution": dist, "file": f,
                                "manifest": " or ".join(util.rel(root, m) for m in nearest)})
            for m in extras:
                if normalize(dist) not in declared(m):
                    missing.append({"module": mod, "distribution": dist, "file": f, "manifest": util.rel(root, m)})
    return {"passed": not missing, "missing": missing, "unowned_files": unowned}


def _extras_for(root: Path, f: str, extra) -> list[Path]:
    out = []
    for rule in extra:
        if util.under_any(f, rule.get("paths", [])):
            for pat in rule.get("requirements", []):
                out += [p for p in root.glob(pat) if p.is_file()]
    return out


# --------------------------------------------------------------------------- node

def _node_package_name(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") and len(parts) > 1 else parts[0]


def check_node(root: Path, files: list[str], cfg_deps: dict) -> dict:
    alias_prefixes = tuple(cfg_deps.get("alias_prefixes") or ("@/", "~/", "#", "$"))
    ignore = set(cfg_deps.get("ignore") or [])
    missing, unowned = [], []
    cache: dict[Path, set[str]] = {}
    for f in files:
        fp = root / f
        if not f.endswith(NODE_EXT) or not fp.is_file():
            continue
        pkgs = _nearest(root, fp.parent, ("package.json",))
        if not pkgs:
            unowned.append(f)
            continue
        pkg = pkgs[0]
        if pkg not in cache:
            data = util.read_json(pkg, default={}) or {}
            cache[pkg] = {n for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
                          for n in (data.get(key) or {})}
            if data.get("name"):
                cache[pkg].add(data["name"])  # self-reference
        text = fp.read_text(encoding="utf-8", errors="ignore")
        for spec in sorted(set(_NODE_IMPORT.findall(text))):
            if spec.startswith((".", "/", "node:", "data:", "http:", "https:")) or spec.startswith(alias_prefixes):
                continue
            name = _node_package_name(spec)
            if name in NODE_BUILTINS or name in ignore or name in cache[pkg]:
                continue
            missing.append({"module": spec, "distribution": name, "file": f, "manifest": util.rel(root, pkg)})
    return {"passed": not missing, "missing": missing, "unowned_files": unowned}


def check(root: Path, files: list[str], cfg_deps: dict) -> dict:
    builtin = cfg_deps.get("builtin")
    if builtin == "python-imports":
        return check_python(root, files, cfg_deps)
    if builtin == "node-imports":
        return check_node(root, files, cfg_deps)
    return {"passed": False, "missing": [], "error": f"unknown deps builtin '{builtin}'"}
