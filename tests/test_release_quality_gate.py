from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


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


def test_repository_hygiene_rejects_local_credentials_and_private_keys(tmp_path):
    gate = _load_release_check()
    safe = tmp_path / "rareiq_secrets.example.json"
    safe.write_text('{"password": "replace-me"}', encoding="utf-8")
    assert gate.check_repository_hygiene(tmp_path, paths=[safe]) == 1

    for name, content in [
        ("obs_settings.json", "{}"),
        (".env.local", "TOKEN=value"),
        ("certificate.pem", "placeholder"),
        ("ordinary.txt", "-----BEGIN " + "PRIVATE KEY-----"),
    ]:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        with pytest.raises(gate.ReleaseCheckError, match="must not be tracked"):
            gate.check_repository_hygiene(tmp_path, paths=[path])


def test_untracked_source_hygiene_catches_whitespace_before_staging(tmp_path):
    gate = _load_release_check()
    clean = tmp_path / "clean.py"
    clean.write_text("value = 1\n", encoding="utf-8")
    assert gate.check_untracked_source_hygiene(tmp_path, paths=[clean]) == 1

    for name, content in [
        ("trailing.py", "value = 1  \n"),
        ("blank.js", "const value = 1;\n\n"),
    ]:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        with pytest.raises(gate.ReleaseCheckError, match="Untracked source hygiene failed"):
            gate.check_untracked_source_hygiene(tmp_path, paths=[path])


def test_all_shipped_html_has_unique_ids_and_existing_local_assets():
    assert _load_release_check().check_static_documents(PROJECT_ROOT) >= 30


@pytest.mark.parametrize("html,reason", [
    ('<div id="same"></div><button id="same"></button>', "Duplicate HTML IDs"),
    ('<script src="/static/missing.js?v=1"></script>', "Missing static asset"),
    ('<img src="/static/%2e%2e/private.png">', "Missing static asset"),
])
def test_html_gate_rejects_broken_assets_and_duplicate_ids(tmp_path, html, reason):
    static = tmp_path / "rareiq/web/static"
    static.mkdir(parents=True)
    (static / "sample.html").write_text(html, encoding="utf-8")
    gate = _load_release_check()
    with pytest.raises(gate.ReleaseCheckError, match=reason):
        gate.check_static_documents(tmp_path)


def test_inline_script_gate_checks_classic_and_modules_but_not_json(tmp_path, monkeypatch):
    gate = _load_release_check()
    static = tmp_path / "rareiq/web/static"
    static.mkdir(parents=True)
    (static / "sample.html").write_text('<script>const x = 1;</script><script type="module">export const y = 2;</script><script type="application/ld+json">{}</script>', encoding="utf-8")
    from types import SimpleNamespace
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs["input"]))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.check_javascript_syntax("node", root=tmp_path) == 2
    assert calls[0] == (["node", "--check", "--input-type=commonjs"], "const x = 1;")
    assert calls[1][0][-1] == "--input-type=module"
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="bad script", stdout=""))
    with pytest.raises(gate.ReleaseCheckError, match="Inline JavaScript syntax failed"):
        gate.check_javascript_syntax("node", root=tmp_path)


def test_windows_ci_uses_the_same_pinned_release_gate():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "runs-on: windows-latest" in workflow
    assert 'python-version: "3.13.12"' in workflow
    assert "python -m pip install -r requirements-dev.txt" in workflow
    assert "python -B tools/release_check.py --require-node" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow
    assert '"codex/**"' in workflow


def test_release_checklist_documents_the_canonical_command_and_data_independence():
    checklist = (PROJECT_ROOT / "docs" / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "tools\\release_check.py --require-node" in checklist
    assert "does not require cameras" in checklist
    assert "no development suffix" in checklist


def test_javascript_behavior_gate_runs_real_suites_with_explicit_node(monkeypatch):
    gate = _load_release_check()
    commands = []
    monkeypatch.setattr(gate, "run_checked", lambda command, label, **kwargs: commands.append((command, label, kwargs)))
    count = gate.check_javascript_behavior("node-explicit", require_node=True)
    assert count >= 1
    command, label, options = commands[0]
    assert command[:2] == ["node-explicit", "--test"]
    assert str(PROJECT_ROOT / "tests" / "browser" / "overlay_runtime.test.cjs") in command
    assert len(command) == count + 2
    assert options["root"] == PROJECT_ROOT


def test_javascript_behavior_gate_requires_node_when_requested(monkeypatch):
    gate = _load_release_check()
    monkeypatch.setattr(gate.shutil, "which", lambda _name: None)
    with pytest.raises(gate.ReleaseCheckError, match="Node.js is required"):
        gate.check_javascript_behavior(require_node=True)
    assert gate.check_javascript_behavior() == 0


def test_javascript_behavior_gate_cannot_pass_with_missing_suites(tmp_path):
    gate = _load_release_check()
    with pytest.raises(gate.ReleaseCheckError, match="No JavaScript behavior"):
        gate.check_javascript_behavior("node-explicit", root=tmp_path)


def test_javascript_behavior_failures_fail_the_gate(monkeypatch):
    gate = _load_release_check()
    def failed(*_args, **_kwargs):
        raise gate.ReleaseCheckError("JavaScript behavior tests failed")
    monkeypatch.setattr(gate, "run_checked", failed)
    with pytest.raises(gate.ReleaseCheckError, match="behavior tests failed"):
        gate.check_javascript_behavior("node-explicit")


@pytest.mark.parametrize("skip_tests", [False, True])
def test_main_runs_both_behavior_suites_unless_skipped(monkeypatch, skip_tests):
    gate = _load_release_check()
    commands = []
    behavior = []
    monkeypatch.setattr(gate, "PYTHON_TARGET", gate.sys.version_info[:2])
    monkeypatch.setattr(gate, "run_checked", lambda command, *_args, **_kwargs: commands.append(command))
    monkeypatch.setattr(gate, "check_python_syntax", lambda: 1)
    monkeypatch.setattr(gate, "check_repository_hygiene", lambda: 1)
    monkeypatch.setattr(gate, "check_untracked_source_hygiene", lambda: 0)
    monkeypatch.setattr(gate, "check_javascript_syntax", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(gate, "check_javascript_behavior", lambda node, **kwargs: behavior.append((node, kwargs)))
    args = ["--require-node", "--node", "node-explicit"]
    if skip_tests:
        args.append("--skip-tests")
    assert gate.main(args) == 0
    assert bool(behavior) is not skip_tests
    assert any("pytest" in command for command in commands) is not skip_tests
    if not skip_tests:
        assert behavior == [("node-explicit", {"require_node": True})]
