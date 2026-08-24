from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "tools" / "release_check.py"
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "release-quality.yml"


def _load_release_check():
    spec = importlib.util.spec_from_file_location("rareiq_release_check", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_gate_discovers_and_compiles_active_python_sources():
    release_check = _load_release_check()
    sources = release_check.python_sources(PROJECT_ROOT)

    assert PROJECT_ROOT / "app.py" in sources
    assert PROJECT_ROOT / "rareiq" / "web" / "server.py" in sources
    assert SCRIPT_PATH in sources
    assert release_check.check_python_syntax(PROJECT_ROOT) == len(sources)


def test_release_gate_discovers_active_javascript_sources():
    release_check = _load_release_check()
    sources = release_check.javascript_sources(PROJECT_ROOT)

    assert PROJECT_ROOT / "rareiq" / "web" / "static" / "studiox.js" in sources
    assert all(path.suffix == ".js" for path in sources)


def test_windows_ci_uses_the_same_pinned_release_gate():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "runs-on: windows-latest" in workflow
    assert 'python-version: "3.13.12"' in workflow
    assert "python -m pip install -r requirements-dev.txt" in workflow
    assert "python -B tools/release_check.py --require-node" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow


def test_release_checklist_documents_the_canonical_command_and_data_independence():
    checklist = (PROJECT_ROOT / "docs" / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "tools\\release_check.py --require-node" in checklist
    assert "does not require cameras" in checklist
    assert "no development suffix" in checklist
