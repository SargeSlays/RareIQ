from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_TARGET = (3, 13)


class ReleaseCheckError(RuntimeError):
    pass


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


def check_python_syntax(root: Path = PROJECT_ROOT) -> int:
    sources = python_sources(root)
    for path in sources:
        source = path.read_text(encoding="utf-8-sig")
        compile(source, str(path), "exec")
    return len(sources)


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
    return len(sources)


def run_checked(command: Sequence[str], label: str, *, root: Path = PROJECT_ROOT) -> None:
    print(f"[RUN ] {label}", flush=True)
    result = subprocess.run(list(command), cwd=root, check=False)
    if result.returncode:
        raise ReleaseCheckError(f"{label} failed with exit code {result.returncode}.")
    print(f"[PASS] {label}", flush=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RareIQ release-quality gates.")
    parser.add_argument("--node", help="Explicit Node.js executable path.")
    parser.add_argument(
        "--require-node",
        action="store_true",
        help="Fail instead of skipping JavaScript syntax when Node.js is unavailable.",
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip the canonical pytest suite.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if sys.version_info[:2] != PYTHON_TARGET:
        raise ReleaseCheckError(
            f"RareIQ release checks require Python {PYTHON_TARGET[0]}.{PYTHON_TARGET[1]}; "
            f"received {sys.version_info.major}.{sys.version_info.minor}."
        )

    run_checked([sys.executable, "-m", "pip", "check"], "Dependency integrity")

    python_count = check_python_syntax()
    print(f"[PASS] Python syntax ({python_count} files)")

    javascript_count = check_javascript_syntax(
        args.node,
        require_node=args.require_node,
    )
    if javascript_count:
        print(f"[PASS] JavaScript syntax ({javascript_count} files)")

    run_checked(["git", "diff", "--check"], "Working-tree whitespace")
    run_checked(["git", "diff", "--cached", "--check"], "Staged whitespace")

    if not args.skip_tests:
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
