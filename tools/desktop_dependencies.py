"""Vendor an explicit installed dependency closure without executing packages.

Only RECORD-listed files inside approved purelib roots are copied. Extra roots
also nominate their installed distributions as pinned entry points (e.g. PyAV).
This inventory is not a determination of binary redistribution rights.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from email.parser import Parser
import hashlib
import io
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


MAX_METADATA_BYTES = 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_RECORD_FILES = 100_000


class DependencyVendorError(ValueError):
    """Public errors contain a fixed reason only, never a local path."""


def _fail(reason):
    raise DependencyVendorError(reason)


def _within(path, root):
    return path == root or root in path.parents


def _text(path, root, limit):
    resolved = path.resolve(strict=True)
    if not _within(resolved, root) or not resolved.is_file():
        _fail("dependency_metadata_escape")
    if not 0 < resolved.stat().st_size <= limit:
        _fail("dependency_metadata_size")
    with resolved.open("rb") as handle:
        raw = handle.read(limit + 1)
    if not 0 < len(raw) <= limit:
        _fail("dependency_metadata_size")
    return raw.decode("utf-8-sig")


def _requirement(raw):
    value = Requirement(raw)
    if value.url or value.extras:
        _fail("dependency_requirement_unsupported")
    return value


def _active(value):
    return value.marker is None or value.marker.evaluate({"extra": ""})


def _exact(value):
    specs = list(value.specifier)
    if len(specs) != 1 or specs[0].operator != "==" or "*" in specs[0].version:
        _fail("dependency_root_version_required")
    Version(specs[0].version)


def _requirements(path):
    root = path.resolve(strict=True).parent
    roots, constraints, visiting = [], [], set()

    def read(current, constraint=False):
        current = current.resolve(strict=True)
        if not _within(current, root) or current in visiting:
            _fail("dependency_requirements_invalid")
        visiting.add(current)
        try:
            for raw in _text(current, root, MAX_METADATA_BYTES).splitlines():
                line = raw.split(" #", 1)[0].strip()
                if not line or line.startswith("#"):
                    continue
                directive = re.fullmatch(r"(-r|--requirement|-c|--constraint)\s+(.+)", line)
                if directive:
                    relative = PurePosixPath(directive[2].replace("\\", "/"))
                    if relative.is_absolute() or PureWindowsPath(directive[2]).drive:
                        _fail("dependency_requirements_invalid")
                    read(current.parent.joinpath(*relative.parts), constraint or directive[1] in {"-c", "--constraint"})
                    continue
                value = _requirement(line)
                if _active(value):
                    _exact(value)
                    (constraints if constraint else roots).append(value)
        finally:
            visiting.remove(current)

    read(path)
    if not roots:
        _fail("dependency_requirements_empty")
    return roots, constraints


@dataclass
class _Distribution:
    root: Path
    directory: Path
    name: str
    version: str
    license: str
    requirements: list[Requirement]


def _license(metadata):
    value = metadata.get("License-Expression") or metadata.get("License") or ""
    value = " ".join(value.split())
    # Full license texts are retained as files. Inventory fields stay short and
    # cannot echo an accidentally embedded local-machine path.
    if not value or len(value) > 512 or "\\" in value or re.search(r"[A-Za-z]:|(?:^|\s)/", value):
        return "unspecified"
    return value


def _distributions(root):
    found = []
    for directory in sorted(root.glob("*.dist-info")):
        if not directory.is_dir() or not _within(directory.resolve(strict=True), root):
            _fail("dependency_metadata_escape")
        metadata = Parser().parsestr(_text(directory / "METADATA", root, MAX_METADATA_BYTES))
        name, version = metadata.get("Name", ""), metadata.get("Version", "")
        if (len(metadata.get_all("Name", [])) != 1 or len(metadata.get_all("Version", [])) != 1
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", name) or not version):
            _fail("dependency_metadata_invalid")
        Version(version)
        requirements = []
        for raw in metadata.get_all("Requires-Dist", []):
            # Optional-extra requirements are outside the selected closure.
            value = Requirement(raw)
            if _active(value):
                requirements.append(_requirement(raw))
        found.append(_Distribution(root, directory, name, version, _license(metadata), requirements))
    return found


def _digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _files(distribution):
    root = distribution.root
    rows = csv.reader(io.StringIO(_text(distribution.directory / "RECORD", root, MAX_RECORD_BYTES)))
    result, retained_rows = {}, []
    for count, row in enumerate(rows, 1):
        if count > MAX_RECORD_FILES or len(row) != 3 or not row[0]:
            _fail("dependency_record_invalid")
        raw = row[0]
        relative = PurePosixPath(raw.replace("\\", "/"))
        if relative.is_absolute() or PureWindowsPath(raw).drive or ".." in relative.parts:
            continue  # Old pip temporary bytecode and console scripts can be external.
        if (not relative.parts or any(part.casefold() == "__pycache__" for part in relative.parts)
                or relative.parts[0].casefold() in {"bin", "scripts"}
                or relative.suffix.casefold() in {".pyc", ".pyo", ".pth", ".egg-link"}):
            continue
        if "\x00" in raw or any(":" in part for part in relative.parts):
            _fail("dependency_record_invalid")
        if ((row[1] and not re.fullmatch(r"(?:sha256|sha384|sha512)=[A-Za-z0-9_-]+", row[1]))
                or (row[2] and not row[2].isdigit())):
            _fail("dependency_record_invalid")
        source = root.joinpath(*relative.parts)
        resolved = source.resolve(strict=True)
        if not _within(resolved, root):
            _fail("dependency_file_escape")
        if not resolved.is_file():
            _fail("dependency_file_invalid")
        result[relative.as_posix()] = resolved
        retained_rows.append([relative.as_posix(), row[1], row[2]])
    required = [distribution.directory / "METADATA", distribution.directory / "RECORD"]
    for path in required:
        relative = path.relative_to(root).as_posix()
        if relative not in result:
            _fail("dependency_record_incomplete")
    # Do not redistribute stale temporary-machine paths inside RECORD itself.
    record_name = (distribution.directory / "RECORD").relative_to(root).as_posix()
    clean_record = io.StringIO(newline="")
    csv.writer(clean_record, lineterminator="\n").writerows(retained_rows)
    result[record_name] = clean_record.getvalue().encode("utf-8")
    return result


def vendor_dependencies(target: Path, production_roots: list[Path], requirements_path: Path,
                        extra_roots: list[Path]) -> list[dict]:
    """Copy the validated closure and return a deterministic, path-free inventory.

    All versions, paths, source hashes and existing destination collisions are
    checked before any copy. Existing identical files make replay idempotent.
    """
    try:
        return _vendor(Path(target), production_roots, Path(requirements_path), extra_roots)
    except DependencyVendorError:
        raise
    except Exception:
        raise DependencyVendorError("dependency_vendor_failed") from None


def _vendor(target, production_roots, requirements_path, extra_roots):
    production = [Path(root).resolve(strict=True) for root in production_roots]
    extras = [Path(root).resolve(strict=True) for root in extra_roots]
    approved = list(dict.fromkeys(production + extras))
    target = target.resolve()
    if not production or any(not root.is_dir() for root in approved):
        _fail("dependency_root_invalid")
    if any(_within(target, root) or _within(root, target) for root in approved):
        _fail("dependency_target_overlaps_source")
    entry, constraints = _requirements(requirements_path)
    available = {}
    for roots, extra in ((production, False), (extras, True)):
        group = {}
        for root in dict.fromkeys(roots):
            distributions = _distributions(root)
            if extra and not distributions:
                _fail("dependency_extra_root_empty")
            for distribution in distributions:
                key = canonicalize_name(distribution.name)
                if key in group:
                    _fail("dependency_distribution_ambiguous")
                group[key] = distribution
                if extra:
                    entry.append(_requirement(f"{distribution.name}=={distribution.version}"))
        available.update(group)  # Explicit extra roots take precedence.
    selected, pending = {}, list(entry)
    while pending:
        requirement = pending.pop()
        key = canonicalize_name(requirement.name)
        distribution = available.get(key)
        if distribution is None:
            _fail("dependency_missing")
        if not requirement.specifier.contains(distribution.version, prereleases=True):
            _fail("dependency_version_mismatch")
        if any(canonicalize_name(rule.name) == key and not rule.specifier.contains(distribution.version, prereleases=True) for rule in constraints):
            _fail("dependency_version_mismatch")
        if key not in selected:
            selected[key] = distribution
            pending.extend(distribution.requirements)
    copies, manifest = {}, []
    for key, distribution in sorted(selected.items()):
        names, aggregate = [], hashlib.sha256()
        for relative, source in sorted(_files(distribution).items()):
            digest = hashlib.sha256(source).hexdigest() if isinstance(source, bytes) else _digest(source)
            existing = copies.get(relative.casefold())
            if existing and existing[2] != digest:
                _fail("dependency_file_collision")
            if existing:
                relative = existing[0]
            else:
                copies[relative.casefold()] = (relative, source, digest)
            names.append(relative)
            aggregate.update((relative + "\0" + digest + "\n").encode("utf-8"))
        manifest.append({"name": distribution.name, "version": distribution.version,
                         "license": distribution.license, "files": names,
                         "file_count": len(names), "sha256": aggregate.hexdigest()})
    for relative, _, digest in copies.values():
        destination = target / relative
        if not _within(destination.resolve(), target):
            _fail("dependency_target_escape")
        if destination.is_symlink() or (hasattr(destination, "is_junction") and destination.is_junction()):
            _fail("dependency_target_escape")
        if destination.exists() and (not destination.is_file() or _digest(destination) != digest):
            _fail("dependency_file_collision")
    for relative, source, digest in copies.values():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not _within(destination.resolve(), target):
            _fail("dependency_target_escape")
        try:
            with destination.open("xb") as output:
                if isinstance(source, bytes):
                    output.write(source)
                else:
                    with source.open("rb") as incoming:
                        while chunk := incoming.read(1024 * 1024):
                            output.write(chunk)
        except FileExistsError:
            pass
        if _digest(destination) != digest:
            _fail("dependency_file_changed")
    return manifest
