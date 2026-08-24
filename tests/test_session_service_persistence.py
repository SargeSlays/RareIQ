from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Barrier, Lock

from rareiq.services.session_service import SessionService


def test_concurrent_session_startup_uses_independent_atomic_temp_files(
    tmp_path: Path,
    monkeypatch,
):
    replace_barrier = Barrier(2)
    replace_lock = Lock()
    replace_calls = 0
    replaced_sources: list[Path] = []
    original_replace = os.replace

    def synchronized_replace(source, destination):
        nonlocal replace_calls
        source_path = Path(source)
        if source_path.name.endswith(".tmp"):
            replaced_sources.append(source_path)
            with replace_lock:
                replace_calls += 1
                should_synchronize = replace_calls <= 2
            if should_synchronize:
                replace_barrier.wait(timeout=5)
        return original_replace(source, destination)

    monkeypatch.setattr("rareiq.services.session_service.os.replace", synchronized_replace)

    with ThreadPoolExecutor(max_workers=2) as executor:
        services = list(executor.map(lambda _: SessionService(tmp_path), range(2)))

    assert len(services) == 2
    assert len(replaced_sources) >= 2
    assert len(set(replaced_sources)) == 2
    assert json.loads((tmp_path / "active_session.json").read_text(encoding="utf-8"))
    assert not list(tmp_path.glob("*.tmp"))
