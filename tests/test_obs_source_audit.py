import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from rareiq.services.obs_service import ObsService
from rareiq.services.obs_source_audit import clean_origin, inspect_scene


ORIGIN = "http://127.0.0.1:9040"


class ReadOnlyClient:
    """Only read methods exist: mutations cannot accidentally pass these tests."""

    def __init__(self, plan, *, protocol_dicts=False):
        self.protocol_dicts = protocol_dicts
        self.calls = []
        self.disconnected = 0
        self.scenes = {}
        self.inputs = {}
        for item in plan:
            self.scenes[item["scene"]] = [{
                "sourceName": item["source"], "inputKind": "browser_source",
                "sceneItemEnabled": True, "sceneItemId": 1,
                "sceneItemTransform": {"cropLeft": 0, "cropRight": 0, "cropTop": 0, "cropBottom": 0},
            }]
            self.inputs[item["source"]] = {
                "inputKind": "browser_source", "inputSettings": {
                    "url": item["url"], "width": item["width"], "height": item["height"],
                    "reroute_audio": item["audio"], "shutdown": False, "restart_when_active": False,
                },
            }

    def get_scene_list(self):
        self.calls.append(("scenes",))
        value = [{"sceneName": name} for name in self.scenes]
        return {"scenes": value} if self.protocol_dicts else SimpleNamespace(scenes=value)

    def get_scene_item_list(self, name):
        self.calls.append(("items", name))
        value = deepcopy(self.scenes[name])
        return {"sceneItems": value} if self.protocol_dicts else SimpleNamespace(scene_items=value)

    def get_input_settings(self, name):
        self.calls.append(("settings", name))
        value = deepcopy(self.inputs[name])
        if self.protocol_dicts:
            return value
        return SimpleNamespace(input_kind=value["inputKind"], input_settings=value["inputSettings"])

    def disconnect(self):
        self.disconnected += 1


@pytest.fixture
def audit(monkeypatch, tmp_path):
    service = ObsService(tmp_path / "obs.json")
    service.configure({"enabled": True, "password": "private-obs-credential"})
    client = ReadOnlyClient(service.bootstrap_plan(ORIGIN))
    monkeypatch.setattr(service, "_client", lambda: client)
    monkeypatch.setattr(service, "diagnostic", lambda: {"code": "ready"})
    return service, client


def row(report, key="program"):
    return next(item for item in report["sources"] if item["key"] == key)


def codes(result):
    return {item["code"] for item in result["issues"]}


@pytest.mark.parametrize("protocol_dicts", [False, True])
def test_all_sources_checked_using_reads_only_without_writing_settings(audit, protocol_dicts):
    service, client = audit
    client.protocol_dicts = protocol_dicts
    before = service.config_path.read_bytes()
    report = service.audit_sources(ORIGIN)
    assert report["connected"] is True and report["read_only"] is True
    assert report["configuration_ok"] is True
    assert report["configured"] == report["total"] == 14
    assert report["attention"] == report["unavailable"] == 0
    assert report["checked_at"] > 0
    assert row(report, "set_chase")["width"] == 1280
    assert row(report, "set_chase")["height"] == 320
    assert client.disconnected == 1
    assert len(client.calls) == 29
    assert service.config_path.read_bytes() == before
    assert "private-obs-credential" not in json.dumps(report)


@pytest.mark.parametrize("diagnostic", ["disabled", "port_closed", "client_missing"])
def test_offline_is_not_checked_not_missing_or_ready(audit, monkeypatch, diagnostic):
    service, client = audit
    monkeypatch.setattr(service, "diagnostic", lambda: {"code": diagnostic})
    report = service.audit_sources(ORIGIN)
    assert report["connected"] is False and report["configuration_ok"] is False
    assert report["unavailable"] == 14 and report["configured"] == report["attention"] == 0
    assert all(codes(item) == {"not_checked"} for item in report["sources"])
    assert client.calls == [] and client.disconnected == 0


@pytest.mark.parametrize("missing_scene", [False, True])
def test_missing_scene_and_source_have_actionable_distinct_results(audit, missing_scene):
    service, client = audit
    if missing_scene:
        del client.scenes["RareIQ Program"]
    else:
        client.scenes["RareIQ Program"] = []
    report = service.audit_sources(ORIGIN)
    assert report["configured"] == 13 and report["attention"] == 1
    assert row(report)["state"] == "missing"
    assert codes(row(report)) == {"scene_missing" if missing_scene else "source_missing"}


def test_checks_url_native_dimensions_audio_lifecycle_visibility_and_cropping(audit):
    service, client = audit
    client.inputs["RareIQ Set Chase Browser"]["inputSettings"].update({
        "url": ORIGIN + "/creator/set-chase?secret=do-not-return", "width": 1920, "height": 1080,
        "reroute_audio": True, "shutdown": True, "restart_when_active": True,
        "css": "private-custom-css",
    })
    entry = client.scenes["RareIQ Set Chase"][0]
    entry["sceneItemEnabled"] = False
    entry["sceneItemTransform"]["cropTop"] = 20
    report = service.audit_sources(ORIGIN)
    assert codes(row(report, "set_chase")) == {
        "url_mismatch", "size_mismatch", "audio_routing", "shutdown_enabled",
        "restart_enabled", "source_hidden", "source_cropped",
    }
    assert report["attention"] == 1 and report["configured"] == 13
    assert "do-not-return" not in json.dumps(report) and "private-custom-css" not in json.dumps(report)
    assert row(report, "set_chase")["url"] == ORIGIN + "/overlay/set-chase"


def test_soundboard_requires_obs_audio_routing_and_does_not_test_playback(audit):
    service, client = audit
    source = next(item["source"] for item in service.bootstrap_plan(ORIGIN) if item["key"] == "soundboard")
    client.inputs[source]["inputSettings"]["reroute_audio"] = False
    report = service.audit_sources(ORIGIN)
    assert codes(row(report, "soundboard")) == {"audio_routing"}
    assert "actual picture and audio" in report["diagnostic"]["message"]


@pytest.mark.parametrize("rename", ["RareIQ Program Browser (2)", "My renamed program"])
def test_namespace_suffix_and_renamed_clean_browser_input_are_recognized(audit, rename):
    service, client = audit
    client.inputs[rename] = client.inputs.pop("RareIQ Program Browser")
    client.scenes["RareIQ Program"][0]["sourceName"] = rename
    assert service.audit_sources(ORIGIN)["configuration_ok"] is True


def test_duplicate_matches_are_flagged_and_settings_read_once(audit):
    service, client = audit
    client.scenes["RareIQ Program"].append(deepcopy(client.scenes["RareIQ Program"][0]))
    report = service.audit_sources(ORIGIN)
    assert codes(row(report)) == {"multiple_sources"}
    assert client.calls.count(("settings", "RareIQ Program Browser")) == 1
    assert len(client.scenes["RareIQ Program"]) == 2


def test_wrong_input_type_and_unknown_visibility_cannot_be_green(audit):
    service, client = audit
    client.inputs["RareIQ Program Browser"]["inputKind"] = "image_source"
    client.scenes["RareIQ Program"][0]["inputKind"] = "image_source"
    assert codes(row(service.audit_sources(ORIGIN))) == {"wrong_kind"}
    client.inputs["RareIQ Program Browser"]["inputKind"] = "browser_source"
    del client.scenes["RareIQ Program"][0]["sceneItemEnabled"]
    del client.scenes["RareIQ Program"][0]["sceneItemTransform"]
    assert codes(row(service.audit_sources(ORIGIN))) == {"visibility_unknown", "crop_unknown"}


@pytest.mark.parametrize("failure", ["network", "settings", "scenes", "items", "deadline"])
def test_partial_or_malformed_check_discards_green_rows_and_closes_connection(audit, monkeypatch, failure):
    service, client = audit
    if failure == "network":
        original = client.get_input_settings
        def read(name):
            if name == "RareIQ Graphics Browser":
                raise OSError("secret-password-from-server")
            return original(name)
        monkeypatch.setattr(client, "get_input_settings", read)
    elif failure == "settings":
        client.inputs["RareIQ Graphics Browser"]["inputSettings"] = None
    elif failure == "scenes":
        monkeypatch.setattr(client, "get_scene_list", lambda: {"scenes": None})
    elif failure == "items":
        monkeypatch.setattr(client, "get_scene_item_list", lambda _: {"sceneItems": None})
    else:
        times = iter([0, 1, 2, 13])
        monkeypatch.setattr("rareiq.services.obs_service.time.monotonic", lambda: next(times))
    report = service.audit_sources(ORIGIN)
    assert report["connected"] is False and report["configuration_ok"] is False
    assert report["configured"] == 0 and report["unavailable"] == 14
    assert report["diagnostic"]["code"] == "inspection_failed"
    assert client.disconnected == 1
    assert "secret-password-from-server" not in json.dumps(report)


@pytest.mark.parametrize("count,browser", [(65, False), (17, True)])
def test_unexpectedly_large_scene_has_bounded_work(count, browser):
    item = ObsService.bootstrap_plan(ORIGIN)[0]
    entries = [{"sourceName": str(i), "inputKind": "browser_source" if browser else "image_source"} for i in range(count)]
    def forbidden(_):
        pytest.fail("Should not inspect inputs after scene budget exceeded")
    result = inspect_scene(item, entries, forbidden)
    assert result["state"] == "unavailable" and codes(result) == {"scene_complex"}


@pytest.mark.parametrize("value", ["ftp://localhost", "http://user:secret@localhost", "http://localhost/path",
                                   "http://localhost?token=secret", "http://localhost#secret", "http://localhost:bad",
                                   "http://localhost:0", "http://localhost:65536", "http:///", "http://[broken"])
def test_only_clean_origin_is_accepted(value):
    with pytest.raises(ValueError):
        clean_origin(value)


def test_clean_origin_accepts_local_lan_and_ipv6_without_fetching_them():
    for value in (ORIGIN, "https://studio.local", "http://10.0.0.2:9040", "http://[::1]:9040"):
        assert clean_origin(value + "/") == value


def test_api_uses_only_read_only_service_method_and_redacts_invalid_origin(audit, monkeypatch):
    from rareiq.web import server
    service, client = audit
    monkeypatch.setattr(server, "obs", service)
    result = asyncio.run(server.check_obs_sources(server.ObsSourceAuditRequest(base_url=ORIGIN)))
    assert result["ok"] is True and result["audit"]["configuration_ok"] is True
    calls = list(client.calls)
    invalid = asyncio.run(server.check_obs_sources(server.ObsSourceAuditRequest(base_url="http://user:secret@localhost")))
    assert invalid.status_code == 400 and b"secret" not in invalid.body
    assert client.calls == calls
    assert any(route.path == "/api/production/obs/sources/check" for route in server.app.routes)
