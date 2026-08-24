from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "rareiq"
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
    "uvicorn": "uvicorn",
}


def _declared_distributions() -> set[str]:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {
        re.split(r"[<>=!~]", line, maxsplit=1)[0].strip().lower()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
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
    assert (ROOT / "requirements.txt").is_file()
    assert "python -m pip install -r requirements.txt" in launcher
