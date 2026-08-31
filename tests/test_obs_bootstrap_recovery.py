from types import SimpleNamespace

import pytest

from rareiq.services.obs_service import ObsService


class NamespaceClient:
    """Model OBS's shared scene/input namespace, not independent fake lists."""

    def __init__(self):
        self.scenes = {"Scene": []}
        self.inputs = {}
        self.mutations = []
        self.fail_source = None
        self.canvas = (3840, 2160)
        self.transforms = {}

    def get_version(self):
        return SimpleNamespace(obs_version="test")

    def get_scene_list(self):
        return SimpleNamespace(scenes=[{"sceneName": name} for name in self.scenes])

    def get_scene_item_list(self, name):
        return SimpleNamespace(scene_items=self.scenes[name])

    def get_input_list(self):
        return SimpleNamespace(inputs=[{"inputName": name} for name in self.inputs])

    def get_video_settings(self):
        return SimpleNamespace(base_width=self.canvas[0], base_height=self.canvas[1])

    def set_scene_item_transform(self, scene, item_id, transform):
        assert item_id == 1
        self.transforms[scene] = dict(transform)

    def create_scene(self, name):
        assert name not in self.scenes and name not in self.inputs
        self.scenes[name] = []
        self.mutations.append(("scene", name))

    def create_input(self, scene, source, kind, settings, enabled):
        assert source not in self.scenes and source not in self.inputs, "OBS source name collision"
        if source == self.fail_source:
            raise RuntimeError("Browser source unavailable")
        assert kind == "browser_source" and enabled is True
        self.inputs[source] = dict(settings)
        self.scenes[scene].append({"sourceName": source})
        self.mutations.append(("input", source))
        return SimpleNamespace(scene_item_id=1)


@pytest.fixture
def bootstrap(monkeypatch, tmp_path):
    service = ObsService(tmp_path / "obs.json")
    service.configure({"enabled": True})
    client = NamespaceClient()
    monkeypatch.setattr(service, "_client", lambda: client)
    monkeypatch.setattr(service, "status", lambda: {"connected": True})
    monkeypatch.setattr(service, "diagnostic", lambda: {"code": "ready"})
    return service, client


def test_bootstrap_creates_distinct_browser_inputs_and_is_idempotent(bootstrap):
    service, client = bootstrap
    result = service.bootstrap("http://127.0.0.1:9040", dry_run=False)
    assert result["ready"] is True
    assert len(result["created"]) == len(client.inputs) == 14
    assert not (set(client.scenes) & set(client.inputs))
    assert client.scenes["Scene"] == []
    assert all(settings["width"] == 1920 and settings["height"] == 1080 for name, settings in client.inputs.items() if name != "RareIQ Set Chase Browser")
    assert client.inputs["RareIQ Set Chase Browser"]["width"] == 1280
    assert client.inputs["RareIQ Set Chase Browser"]["height"] == 320
    assert len(client.transforms) == 14
    assert all(transform["boundsType"] == "OBS_BOUNDS_SCALE_INNER" and transform["boundsWidth"] == 3840 and transform["boundsHeight"] == 2160 for scene, transform in client.transforms.items() if scene != "RareIQ Set Chase")
    assert "Scene" not in client.transforms
    mutations = list(client.mutations)
    again = service.bootstrap("http://127.0.0.1:9040", dry_run=False)
    assert again["ready"] is True
    assert again["created"] == []
    assert again["preserve_count"] == 14
    assert client.mutations == mutations


def test_bootstrap_repairs_empty_scenes_but_preserves_existing_operator_content(bootstrap):
    service, client = bootstrap
    for item in service.bootstrap_plan("http://127.0.0.1:9040"):
        client.scenes[item["scene"]] = []
    client.scenes["RareIQ Graphics"] = [{"sourceName": "Custom graphics"}]
    preview = service.bootstrap("http://127.0.0.1:9040", dry_run=True)
    assert preview["ready"] is True
    assert preview["complete_count"] == preview["create_count"] == 13
    assert preview["preserve_count"] == 1
    assert client.mutations == []
    result = service.bootstrap("http://127.0.0.1:9040", dry_run=False)
    assert len(result["created"]) == 13
    assert all(action == "input" for action, _ in client.mutations)
    assert client.scenes["RareIQ Graphics"] == [{"sourceName": "Custom graphics"}]


def test_bootstrap_avoids_unrelated_input_name_collisions_without_replacing_sources(bootstrap):
    service, client = bootstrap
    client.inputs["RareIQ Program Browser"] = {"url": "https://operator.example"}
    result = service.bootstrap("http://127.0.0.1:9040", dry_run=False)
    assert result["ready"] is True
    assert client.inputs["RareIQ Program Browser"]["url"] == "https://operator.example"
    assert client.scenes["RareIQ Program"] == [{"sourceName": "RareIQ Program Browser (2)"}]


def test_failed_source_is_not_reported_ready_or_mapped_and_retry_completes_it(bootstrap):
    service, client = bootstrap
    client.fail_source = "RareIQ Program Browser"
    failed = service.bootstrap("http://127.0.0.1:9040", dry_run=False)
    assert failed["ready"] is False
    assert failed["diagnostic"]["code"] == "bootstrap_incomplete"
    assert failed["create_count"] == 1
    assert failed["preserve_count"] == 0
    assert "main-card" not in failed["scene_map"]
    assert client.scenes["RareIQ Program"] == []
    client.fail_source = None
    repaired = service.bootstrap("http://127.0.0.1:9040", dry_run=False)
    assert repaired["ready"] is True
    assert len(repaired["created"]) == 1
    assert repaired["preserve_count"] == 13
    assert repaired["scene_map"]["main-card"] == "RareIQ Program"
    assert len(client.inputs) == 14


def test_bootstrap_fails_closed_if_existing_scene_cannot_be_inspected(bootstrap, monkeypatch):
    service, client = bootstrap
    client.scenes["RareIQ Program"] = []
    monkeypatch.setattr(client, "get_scene_item_list", lambda _: SimpleNamespace())
    assert service.preflight("http://127.0.0.1:9040")["ready"] is False
    with pytest.raises(RuntimeError, match="Could not inspect"):
        service.bootstrap("http://127.0.0.1:9040", dry_run=False)
    assert client.mutations == []


@pytest.mark.parametrize("canvas", [(1920, 1080), (3840, 2160), (1080, 1920), (720, 1280), (640, 360)])
def test_chase_is_a_bottom_strip_on_landscape_portrait_and_small_canvases(bootstrap, canvas):
    service, client = bootstrap
    client.canvas = canvas
    service.bootstrap("http://127.0.0.1:9040", dry_run=False)
    source = client.inputs["RareIQ Set Chase Browser"]
    assert source["url"] == "http://127.0.0.1:9040/overlay/set-chase"
    assert source["reroute_audio"] is False
    assert source["shutdown"] is False and source["restart_when_active"] is False
    transform = client.transforms["RareIQ Set Chase"]
    width, height = transform["boundsWidth"], transform["boundsHeight"]
    assert width / height == pytest.approx(4)
    assert width <= min(1280, canvas[0] * .92) + 1e-6
    assert height <= min(320, canvas[1] * .30) + 1e-6
    assert transform["positionX"] == pytest.approx((canvas[0] - width) / 2)
    assert transform["positionY"] > 0
    assert transform["positionY"] + height == pytest.approx(canvas[1] - min(canvas) * .025)


def test_chase_operator_layout_is_never_repositioned(bootstrap):
    service, client = bootstrap
    client.scenes["RareIQ Set Chase"] = [{"sourceName": "My custom chase bar"}]
    result = service.bootstrap("http://127.0.0.1:9040", dry_run=False)
    assert result["ready"] is True
    assert "RareIQ Set Chase" not in client.transforms
    assert client.scenes["RareIQ Set Chase"] == [{"sourceName": "My custom chase bar"}]
