"""The package must stay liftable into any other system: stdlib and itself only."""

import ast
import pathlib
import sys

PACKAGE = pathlib.Path(__file__).resolve().parent.parent


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], 0
        elif isinstance(node, ast.ImportFrom):
            yield (node.module or "").split(".")[0], node.level


def test_only_stdlib_and_itself():
    allowed = set(sys.stdlib_module_names) | {"ocr_feedback", "pytest", ""}
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        for name, level in _imports(path):
            if level:          # relative import inside the package
                continue
            if name not in allowed:
                offenders.append(f"{path.relative_to(PACKAGE)}: {name}")
    assert offenders == []
