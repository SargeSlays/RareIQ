from pathlib import Path

from rareiq.services.obs_service import ObsService


class _SceneObject:
    def __init__(self, name: str):
        self.scene_name = name


def test_obs_settings_hide_password_and_persist_mapping(tmp_path: Path):
    config = tmp_path / "obs.json"
    service = ObsService(config)
    settings = service.configure({"host": "localhost", "port": 4455, "password": "secret", "enabled": True, "scene_map": {"main-card": "RareIQ Main"}})
    assert settings["password"] == ""
    assert settings["password_configured"] is True
    restored = ObsService(config).settings()
    assert restored["scene_map"]["main-card"] == "RareIQ Main"

    service.configure({"host": "localhost", "port": 4455, "password": "", "enabled": True, "scene_map": {}})
    assert ObsService(config).settings()["password_configured"] is True


def test_disabled_obs_fails_closed(tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")
    status = service.status()
    assert status["connected"] is False
    assert "disabled" in status["error"].lower()


def test_sync_without_mapping_is_noop(tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")
    assert service.sync_scene("main-card") is None


def test_bootstrap_dry_run_is_non_mutating_and_complete(tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")
    result = service.bootstrap("http://127.0.0.1:8765", dry_run=True)
    assert result["dry_run"] is True
    assert len(result["plan"]) == 6
    assert result["created"] == []
    assert all(item["url"].startswith("http://127.0.0.1:8765/") for item in result["plan"])
    assert all(item["width"] == 1920 and item["height"] == 1080 for item in result["plan"])
    assert next(item for item in result["plan"] if item["scene"] == "RareIQ Multi Card")["url"].endswith("/overlay/multi-card")


def test_diagnostic_distinguishes_disabled_and_closed_port(monkeypatch, tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")
    assert service.diagnostic()["code"] == "disabled"
    service.configure({"enabled": True, "host": "127.0.0.1", "port": 4455})
    monkeypatch.setattr("rareiq.services.obs_service.importlib.util.find_spec", lambda name: object())
    monkeypatch.setattr("rareiq.services.obs_service.socket.create_connection", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionRefusedError()))
    assert service.diagnostic()["code"] == "port_closed"


def test_scene_names_normalize_obs_objects_and_protocol_dicts(tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")

    assert service._scene_names([
        _SceneObject("RareIQ Program"),
        {"sceneName": "RareIQ Graphics"},
        {"scene_name": "RareIQ Replay"},
        "RareIQ Main",
    ]) == ["RareIQ Program", "RareIQ Graphics", "RareIQ Replay", "RareIQ Main"]


def test_bootstrap_skips_existing_scene_returned_as_obs_object(monkeypatch, tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")
    service.configure({"enabled": True})

    class Client:
        created = []

        def get_scene_list(self):
            return type("Scenes", (), {"scenes": [_SceneObject("RareIQ Program")]})()

        def create_scene(self, name):
            self.created.append(name)

        def create_input(self, *_args):
            return None

    client = Client()
    monkeypatch.setattr(service, "_client", lambda: client)

    result = service.bootstrap("http://127.0.0.1:8765", dry_run=False)

    assert any(item["scene"] == "RareIQ Program" and item["reason"] == "scene_exists" for item in result["skipped"])
    assert "RareIQ Program" not in client.created
    assert result["scene_map"]["main-card"] == "RareIQ Program"
    assert result["scene_map"]["overhead-grid"] == "RareIQ Multi Card"
    assert ObsService(service.config_path).settings()["scene_map"] == result["scene_map"]


def test_bootstrap_preserves_custom_scene_mapping(monkeypatch, tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")
    service.configure({"enabled": True, "scene_map": {"main-card": "My Custom Main"}})

    class Client:
        def get_scene_list(self):
            return type("Scenes", (), {"scenes": [_SceneObject("RareIQ Program")]})()

        def create_scene(self, _name):
            return None

        def create_input(self, *_args):
            return None

    monkeypatch.setattr(service, "_client", lambda: Client())

    result = service.bootstrap("http://127.0.0.1:8765", dry_run=False)

    assert result["scene_map"]["main-card"] == "My Custom Main"


def test_preflight_authenticates_and_marks_existing_scenes_for_preservation(monkeypatch, tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")
    service.configure({"enabled": True})

    class Client:
        def get_version(self):
            return type("Version", (), {"obs_version": "31.0.0"})()

        def get_scene_list(self):
            return type("Scenes", (), {"scenes": [_SceneObject("RareIQ Program"), _SceneObject("Host Camera")]})()

    monkeypatch.setattr(service, "diagnostic", lambda: {"code": "ready", "message": "reachable", "action": "auth"})
    monkeypatch.setattr(service, "_client", lambda: Client())

    result = service.preflight("http://127.0.0.1:8765")

    assert result["ready"] is True
    assert result["obs_version"] == "31.0.0"
    assert result["preserve_count"] == 1
    assert result["create_count"] == 5
    assert next(item for item in result["plan"] if item["scene"] == "RareIQ Program")["action"] == "preserve"
    assert "Host Camera" in result["existing_scenes"]


def test_preflight_rejects_bad_websocket_password(monkeypatch, tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")
    service.configure({"enabled": True})
    monkeypatch.setattr(service, "diagnostic", lambda: {"code": "ready", "message": "reachable", "action": "auth"})
    monkeypatch.setattr(service, "_client", lambda: (_ for _ in ()).throw(RuntimeError("authentication failed: bad password")))

    result = service.preflight("http://127.0.0.1:8765")

    assert result["ready"] is False
    assert result["diagnostic"]["code"] == "authentication_failed"


def test_obs_commands_are_idempotent_and_validate_scene(monkeypatch, tmp_path: Path):
    service = ObsService(tmp_path / "obs.json")
    service.configure({"enabled": True})

    class Client:
        started = 0
        scene_changes = []

        def get_stream_status(self):
            return type("Status", (), {"output_active": True})()

        def start_stream(self):
            self.started += 1

        def get_scene_list(self):
            return type("Scenes", (), {
                "scenes": [_SceneObject("RareIQ Program")],
                "current_program_scene_name": "RareIQ Program",
            })()

        def set_current_program_scene(self, scene):
            self.scene_changes.append(scene)

    client = Client()
    monkeypatch.setattr(service, "_client", lambda: client)
    monkeypatch.setattr(service, "status", lambda: {"connected": True})

    service.command("start-stream")
    service.command("set-scene", "RareIQ Program")

    assert client.started == 0
    assert client.scene_changes == []

    try:
        service.command("set-scene", "Deleted Scene")
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing OBS scene should fail closed")
