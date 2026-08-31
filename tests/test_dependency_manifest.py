from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "rareiq"
RUNTIME_MANIFEST = ROOT / "requirements.txt"
DEVELOPMENT_MANIFEST = ROOT / "requirements-dev.txt"
CONSTRAINTS_MANIFEST = ROOT / "constraints.txt"
IMPORT_TO_DISTRIBUTION = {
    "PIL": "pillow",
    "cv2": "opencv-python",
    "cv2_enumerate_cameras": "cv2-enumerate-cameras",
    "fastapi": "fastapi",
    "httpx": "httpx",
    "numpy": "numpy",
    "obsws_python": "obsws-python",
    "pydantic": "pydantic",
    "rapidocr": "rapidocr",
    "starlette": "starlette",
    "uvicorn": "uvicorn",
}


def _declared_distributions() -> set[str]:
    lines = RUNTIME_MANIFEST.read_text(encoding="utf-8").splitlines()
    return {
        re.split(r"[<>=!~]", line, maxsplit=1)[0].strip().lower()
        for line in lines
        if line.strip() and not line.lstrip().startswith(("#", "-"))
    }


def test_active_runtime_imports_are_declared() -> None:
    imported = set()
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    external = imported - set(sys.stdlib_module_names) - {"rareiq"}
    assert external <= IMPORT_TO_DISTRIBUTION.keys()
    assert {
        IMPORT_TO_DISTRIBUTION[name] for name in external
    } <= _declared_distributions()


def test_launcher_installs_the_checked_in_manifest() -> None:
    launcher = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert RUNTIME_MANIFEST.is_file()
    assert 'cd /d "%~dp0"' in launcher
    assert "py -3.13 -m venv .venv" in launcher
    assert "python -m pip install -r requirements.txt" in launcher
    assert "python -m pip install --upgrade pip" not in launcher
    assert "python -B tools\\server_control.py start --open" in launcher


def test_runtime_and_development_dependencies_are_separated_and_pinned() -> None:
    runtime_lines = [
        line.strip()
        for line in RUNTIME_MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip()
        and not line.lstrip().startswith(("#", "-"))
    ]
    development_lines = [
        line.strip()
        for line in DEVELOPMENT_MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert all("==" in line for line in runtime_lines)
    assert not any(line.lower().startswith("pytest") for line in runtime_lines)
    assert development_lines == ["-r requirements.txt", "pytest==9.1.1"]


def test_known_green_transitive_dependency_graph_is_constrained() -> None:
    constraint_lines = [
        line.strip()
        for line in CONSTRAINTS_MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "-c constraints.txt" in RUNTIME_MANIFEST.read_text(encoding="utf-8").splitlines()
    assert all("==" in line for line in constraint_lines)
    assert len(constraint_lines) == len({line.split("==", 1)[0].lower().replace("_", "-") for line in constraint_lines})
    assert "omegaconf==2.3.1" in constraint_lines
    assert "antlr4-python3-runtime==4.9.3" in constraint_lines


def test_python_target_is_explicit_and_matches_the_launcher() -> None:
    python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    launcher = (ROOT / "start.bat").read_text(encoding="utf-8")

    assert python_version.startswith("3.13.")
    assert "py -3.13 -m venv .venv" in launcher
