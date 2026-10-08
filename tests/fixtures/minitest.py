"""A tiny pytest stand-in for the test suite, so CI needs no third-party
package. It runs plain `def test_*()` functions and writes JUnit XML the way
pytest does (classname = dotted module path, name = function name).

    python minitest.py [--junit PATH] [file.py | file.py::test_name ...]

With no arguments it runs every test_*.py under the current directory.
Exit code 1 if any test failed or errored.
"""
from __future__ import annotations

import importlib.util
import sys
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path


def _load(path: Path):
    name = "mt_" + "_".join(path.with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent.resolve()))  # kept, as pytest's rootdir insertion is
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str]) -> int:
    junit = None
    if "--junit" in argv:
        i = argv.index("--junit")
        junit = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    targets = argv or [str(p).replace("\\", "/") for p in sorted(Path(".").rglob("test_*.py"))]
    suite = ET.Element("testsuite", name="minitest")
    failed = 0
    for target in targets:
        file, _, func = target.partition("::")
        path = Path(file)
        classname = file[:-3].replace("/", ".") if file.endswith(".py") else file
        try:
            mod = _load(path)
            names = [func] if func else [n for n in dir(mod) if n.startswith("test_")]
        except Exception as e:
            case = ET.SubElement(suite, "testcase", classname=classname, name=func or "collect")
            ET.SubElement(case, "error", message=f"{type(e).__name__}: {e}").text = traceback.format_exc()
            failed += 1
            continue
        for name in names:
            case = ET.SubElement(suite, "testcase", classname=classname, name=name)
            fn = getattr(mod, name, None)
            if fn is None:
                suite.remove(case)  # an unknown id is simply not reported, like pytest
                continue
            try:
                fn()
            except AssertionError as e:
                ET.SubElement(case, "failure", message=f"AssertionError: {e}").text = traceback.format_exc()
                failed += 1
            except Exception as e:
                # pytest reports exceptions raised in the test body as failures too
                ET.SubElement(case, "failure", message=f"{type(e).__name__}: {e}").text = traceback.format_exc()
                failed += 1
    if junit:
        Path(junit).parent.mkdir(parents=True, exist_ok=True)
        root = ET.Element("testsuites")
        root.append(suite)
        ET.ElementTree(root).write(junit, encoding="utf-8", xml_declaration=True)
    print(f"{len(suite)} run, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
