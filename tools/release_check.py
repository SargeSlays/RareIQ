from __future__ import annotations

import argparse
from html.parser import HTMLParser
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_TARGET = (3, 13)
LOCAL_ONLY_FILENAMES = {
    "obs_settings.json",
    "production_history.json",
    "production_session.json",
    "storage_config.json",
    "trading_config.json",
}
PRIVATE_KEY_MARKERS = (
    ("-----BEGIN " + "PRIVATE KEY-----").encode("ascii"),
    ("-----BEGIN RSA " + "PRIVATE KEY-----").encode("ascii"),
)
SOURCE_TEXT_SUFFIXES = {
    ".bat", ".cjs", ".css", ".html", ".js", ".json", ".md", ".ps1",
    ".py", ".toml", ".txt", ".yaml", ".yml",
}


class ReleaseCheckError(RuntimeError):
    pass


def tracked_files(root: Path = PROJECT_ROOT) -> list[Path]:
    """Return Git-tracked files so local ignored state never enters a release."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseCheckError(f"Unable to inspect tracked files: {detail}")
    return [root / item.decode("utf-8", errors="strict") for item in result.stdout.split(b"\0") if item]


def untracked_files(root: Path = PROJECT_ROOT) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseCheckError(f"Unable to inspect untracked files: {detail}")
    return [root / item.decode("utf-8", errors="strict") for item in result.stdout.split(b"\0") if item]


def check_repository_hygiene(
    root: Path = PROJECT_ROOT,
    *,
    paths: Sequence[Path] | None = None,
) -> int:
    """Reject machine credentials and private keys from the source history."""
    sources = list(paths) if paths is not None else tracked_files(root)
    violations: list[str] = []
    for path in sources:
        relative = path.relative_to(root).as_posix()
        name = path.name.lower()
        local_secret = (
            name in LOCAL_ONLY_FILENAMES
            or (name.startswith("rareiq_secrets") and name != "rareiq_secrets.example.json")
            or (name == ".env" or (name.startswith(".env.") and name != ".env.example"))
            or path.suffix.lower() in {".key", ".pem"}
        )
        if local_secret:
            violations.append(relative)
            continue
        if path.is_file() and path.stat().st_size <= 5 * 1024 * 1024:
            content = path.read_bytes()
            if any(marker in content for marker in PRIVATE_KEY_MARKERS):
                violations.append(relative)
    if violations:
        raise ReleaseCheckError(
            "Local credentials/private keys must not be tracked: " + ", ".join(sorted(violations))
        )
    return len(sources)


def check_untracked_source_hygiene(
    root: Path = PROJECT_ROOT,
    *,
    paths: Sequence[Path] | None = None,
) -> int:
    """Apply whitespace checks to new source before it reaches the Git index."""
    sources = list(paths) if paths is not None else untracked_files(root)
    checked = 0
    violations: list[str] = []
    for path in sources:
        if not path.is_file() or path.suffix.lower() not in SOURCE_TEXT_SUFFIXES:
            continue
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            violations.append(f"{relative}: not UTF-8")
            continue
        checked += 1
        for line_number, line in enumerate(text.splitlines(), 1):
            if line.endswith((" ", "\t")):
                violations.append(f"{relative}:{line_number}: trailing whitespace")
        normalized = text.replace("\r\n", "\n")
        if normalized.endswith("\n\n"):
            violations.append(f"{relative}: extra blank line at EOF")
    if violations:
        raise ReleaseCheckError("Untracked source hygiene failed: " + "; ".join(violations))
    return checked


def python_sources(root: Path = PROJECT_ROOT) -> list[Path]:
    sources = [root / "app.py"]
    for directory in ("rareiq", "tests", "tools"):
        sources.extend((root / directory).rglob("*.py"))
    return sorted(
        path
        for path in sources
        if path.is_file() and "__pycache__" not in path.parts
    )


def javascript_sources(root: Path = PROJECT_ROOT) -> list[Path]:
    return sorted((root / "rareiq" / "web" / "static").rglob("*.js"))


class StaticDocument(HTMLParser):
    """Inspect shipped HTML without executing its scripts or calling a server."""

    def __init__(self):
        super().__init__()
        self.references = []
        self.ids = set()
        self.duplicate_ids = set()
        self.scripts = []
        self._script = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        identity = attrs.get("id")
        if identity:
            if identity in self.ids:
                self.duplicate_ids.add(identity)
            self.ids.add(identity)
        for key in ("src", "href", "poster"):
            value = attrs.get(key, "") or ""
            if value.startswith("/static/"):
                self.references.append(value)
        if tag == "script" and not attrs.get("src"):
            kind = (attrs.get("type") or "").strip().lower()
            if kind in ("", "text/javascript", "application/javascript", "module"):
                self._script = {"line": self.getpos()[0], "module": kind == "module", "source": ""}

    def handle_data(self, data):
        if self._script is not None:
            self._script["source"] += data

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append(self._script)
            self._script = None


def static_documents(root: Path = PROJECT_ROOT):
    for path in sorted((root / "rareiq" / "web" / "static").rglob("*.html")):
        document = StaticDocument()
        document.feed(path.read_text(encoding="utf-8-sig"))
        document.close()
        yield path, document


def check_static_documents(root: Path = PROJECT_ROOT) -> int:
    static = (root / "rareiq" / "web" / "static").resolve()
    count = 0
    for path, document in static_documents(root):
        count += 1
        if document.duplicate_ids:
            raise ReleaseCheckError(f"Duplicate HTML IDs: {path}: {', '.join(sorted(document.duplicate_ids))}")
        for reference in document.references:
            relative = unquote(urlsplit(reference).path).removeprefix("/static/")
            target = (static / relative).resolve()
            if not target.is_relative_to(static) or not target.is_file():
                raise ReleaseCheckError(f"Missing static asset: {path}: {reference}")
    return count


def check_python_syntax(root: Path = PROJECT_ROOT) -> int:
    sources = python_sources(root)
    for path in sources:
        source = path.read_text(encoding="utf-8-sig")
        compile(source, str(path), "exec")
    return len(sources)


def check_inline_javascript(executable: str, root: Path) -> int:
    inline_count = 0
    for path, document in static_documents(root):
        for script in document.scripts:
            if not script["source"].strip():
                continue
            result = subprocess.run(
                [executable, "--check", "--input-type=" + ("module" if script["module"] else "commonjs")],
                input=script["source"], cwd=root, capture_output=True,
                text=True, encoding="utf-8", check=False,
            )
            if result.returncode:
                detail = (result.stderr or result.stdout).strip()
                raise ReleaseCheckError(f"Inline JavaScript syntax failed: {path}:{script['line']}\n{detail}")
            inline_count += 1
    return inline_count


def check_javascript_syntax(
    node: str | None = None,
    *,
    require_node: bool = False,
    root: Path = PROJECT_ROOT,
) -> int:
    executable = node or shutil.which("node")
    if not executable:
        if require_node:
            raise ReleaseCheckError("Node.js is required for JavaScript syntax checks.")
        print("[SKIP] JavaScript syntax (Node.js not found)")
        return 0

    sources = javascript_sources(root)
    for path in sources:
        result = subprocess.run(
            [executable, "--check", str(path)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise ReleaseCheckError(f"JavaScript syntax failed: {path}\n{detail}")
    return len(sources) + check_inline_javascript(executable, root)


def run_checked(command: Sequence[str], label: str, *, root: Path = PROJECT_ROOT) -> None:
    print(f"[RUN ] {label}", flush=True)
    result = subprocess.run(list(command), cwd=root, check=False)
    if result.returncode:
        raise ReleaseCheckError(f"{label} failed with exit code {result.returncode}.")
    print(f"[PASS] {label}", flush=True)


def check_javascript_behavior(
    node: str | None = None,
    *,
    require_node: bool = False,
    root: Path = PROJECT_ROOT,
) -> int:
    executable = node or shutil.which("node")
    if not executable:
        if require_node:
            raise ReleaseCheckError("Node.js is required for JavaScript behavior tests.")
        print("[SKIP] JavaScript behavior (Node.js not found)")
        return 0
    suites = sorted((root / "tests" / "browser").rglob("*.test.cjs"))
    if not suites:
        raise ReleaseCheckError("No JavaScript behavior test suites found.")
    run_checked(
        [executable, "--test", *(str(path) for path in suites)],
        "JavaScript behavior tests",
        root=root,
    )
    return len(suites)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RareIQ release-quality gates.")
    parser.add_argument("--node", help="Explicit Node.js executable path.")
    parser.add_argument(
        "--require-node",
        action="store_true",
        help="Fail instead of skipping JavaScript checks when Node.js is unavailable.",
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip Python and JavaScript behavior test suites.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if sys.version_info[:2] != PYTHON_TARGET:
        raise ReleaseCheckError(
            f"RareIQ release checks require Python {PYTHON_TARGET[0]}.{PYTHON_TARGET[1]}; "
            f"received {sys.version_info.major}.{sys.version_info.minor}."
        )

    tracked_count = check_repository_hygiene()
    print(f"[PASS] Repository credential hygiene ({tracked_count} tracked files)")
    untracked_count = check_untracked_source_hygiene()
    print(f"[PASS] Untracked source hygiene ({untracked_count} files)")

    run_checked([sys.executable, "-m", "pip", "check"], "Dependency integrity")

    python_count = check_python_syntax()
    print(f"[PASS] Python syntax ({python_count} files)")

    document_count = check_static_documents()
    print(f"[PASS] HTML IDs and local assets ({document_count} documents)")

    javascript_count = check_javascript_syntax(
        args.node,
        require_node=args.require_node,
    )
    if javascript_count:
        print(f"[PASS] JavaScript syntax ({javascript_count} files/inline scripts)")

    run_checked(["git", "diff", "--check"], "Working-tree whitespace")
    run_checked(["git", "diff", "--cached", "--check"], "Staged whitespace")

    if not args.skip_tests:
        check_javascript_behavior(args.node, require_node=args.require_node)
        run_checked(
            [sys.executable, "-B", "-m", "pytest", "tests", "-q"],
            "Canonical test suite",
        )

    print("[PASS] RareIQ release-quality gate")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleaseCheckError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
