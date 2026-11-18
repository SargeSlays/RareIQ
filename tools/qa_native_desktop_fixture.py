"""Explicit local native-output rehearsal fixture, never a production launcher.

Usage: python -B tools/qa_native_desktop_fixture.py NEW_F_DIRECTORY [PORT]
All runtime state is isolated before app import. Constructor workers and external
network are disabled; the real asset, composition, signaling and native APIs run.
The fixture never exposes stop/shutdown endpoints or opens a device.
"""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import threading
from types import ModuleType


def main():
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("Supply a NEW isolated directory on F: and optional port")
    root = Path(sys.argv[1]).resolve()
    if not root.is_absolute() or (os.name == "nt" and root.drive.casefold() != "f:"):
        raise SystemExit("Native rehearsal evidence must use an absolute F: directory")
    root.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    os.environ.update(PRODUCER_DESKTOP="1", RAREIQ_HOST="127.0.0.1",
                      RAREIQ_PORT=sys.argv[2] if len(sys.argv) == 3 else "8769",
                      RAREIQ_REMOTE_ACCESS="0", PRODUCER_GUEST_INGRESS_PORT="")
    os.chdir(root)

    # The fixture deliberately has no account credential provider.
    class EmptySecrets:
        def __init__(self, *_args, **_kwargs): pass
        def get(self, _key, default=None): return default
        def public_status(self): return {}
    empty = ModuleType("rareiq.core.secrets")
    empty.SecretsManager, empty.secrets = EmptySecrets, EmptySecrets()
    sys.modules[empty.__name__] = empty

    from rareiq.core.storage import StorageManager
    import rareiq.core.storage as storage_module
    config_path = root / "storage_config.json"
    config_path.write_text(json.dumps({key: str(root / "runtime" / key)
        for key in StorageManager.REQUIRED_PATHS}), encoding="utf-8")
    storage_module.storage = StorageManager(config_path, project_root=root)
    storage_module.storage.initialize()

    connect, connect_ex, resolve = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
    def local(host):
        if host in {None, "localhost", ""}: return True
        try: return ipaddress.ip_address(host).is_loopback
        except ValueError: return False
    def guarded_connect(sock, address):
        if isinstance(address, tuple) and not local(address[0]):
            raise OSError("External network disabled in native rehearsal")
        return connect(sock, address)
    def guarded_connect_ex(sock, address):
        if isinstance(address, tuple) and not local(address[0]):
            raise OSError("External network disabled in native rehearsal")
        return connect_ex(sock, address)
    def guarded_resolve(host, *args, **kwargs):
        if not local(host): raise OSError("External DNS disabled in native rehearsal")
        return resolve(host, *args, **kwargs)
    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = guarded_connect, guarded_connect_ex, guarded_resolve

    # This older checkout has constructor-owned card workers. Do not allow them
    # to run before the base fixture replaces device/provider dependencies.
    start, suppressed = threading.Thread.start, []
    threading.Thread.start = lambda thread: suppressed.append(thread.name)
    try:
        from tools import qa_greenroom_fixture
    finally:
        threading.Thread.start = start
    (root / "isolation.json").write_text(json.dumps({"synthetic_only": True,
        "external_network": False, "hardware": False, "constructor_workers_suppressed": suppressed}, indent=2), encoding="utf-8")
    sys.argv = [sys.argv[0], str(root / "fixture"), os.environ["RAREIQ_PORT"]]
    qa_greenroom_fixture.main(native_desktop=True)


if __name__ == "__main__":
    main()
