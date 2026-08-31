from __future__ import annotations

import importlib.util
import hmac
import json
import re
import threading
import socket
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rareiq.services.broadcast_source_catalog import broadcast_sources
from rareiq.services.obs_source_audit import clean_origin, inspect_scene, issue, new_result, summarize


@dataclass(frozen=True)
class ObsStreamRouteProbe:
    """Private stream-route evidence whose public view and repr omit credentials."""

    inspected: bool
    connected: bool
    verified_at: float
    service_type: str | None
    provider: str | None
    key_configured: bool
    _stream_key: str | None = field(default=None, repr=False, compare=False)
    _server_url: str | None = field(default=None, repr=False, compare=False)

    def public_status(self) -> dict[str, Any]:
        return {
            "inspected": self.inspected,
            "provider": self.provider,
            "service_type": self.service_type,
            "key_configured": self.key_configured,
        }

    def matches_stream_key(self, expected: str, *, provider: str) -> bool:
        if not self.inspected or not self.connected or self.provider != provider:
            return False
        actual = self._normalized_key(self._stream_key)
        candidate = self._normalized_key(expected)
        return bool(actual and candidate and hmac.compare_digest(actual, candidate))

    def matches_stream_route(
        self,
        expected_key: str,
        expected_server: str,
        *,
        provider: str,
    ) -> bool:
        """Privately compare both encoder credentials without exposing either."""
        if (
            not self.inspected
            or not self.connected
            or self.provider not in (None, provider)
        ):
            return False
        actual_key = self._normalized_key(self._stream_key)
        candidate_key = self._normalized_key(expected_key)
        actual_server = self._normalized_server(self._server_url)
        candidate_server = self._normalized_server(expected_server)
        return bool(
            actual_key
            and candidate_key
            and actual_server
            and candidate_server
            and hmac.compare_digest(actual_key, candidate_key)
            and hmac.compare_digest(actual_server, candidate_server)
        )

    @staticmethod
    def _normalized_key(value: str | None) -> str:
        # Twitch documents bandwidth-test mode as a query suffix on the key.
        return str(value or "").strip().partition("?")[0]

    @staticmethod
    def _normalized_server(value: str | None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw if "://" in raw else f"rtmps://{raw}")
        scheme = parsed.scheme.lower()
        host = str(parsed.hostname or "").lower().rstrip(".")
        if not scheme or not host or parsed.username or parsed.password or parsed.fragment:
            return ""
        try:
            port = parsed.port
        except ValueError:
            return ""
        default_port = 443 if scheme == "rtmps" else 1935 if scheme == "rtmp" else None
        port_part = "" if port in (None, default_port) else f":{port}"
        path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
        query_part = f"?{parsed.query}" if parsed.query else ""
        return f"{scheme}://{host}{port_part}{path}{query_part}"

    @classmethod
    def unavailable(cls) -> ObsStreamRouteProbe:
        return cls(False, False, 0.0, None, None, False)


class ObsService:
    """Optional OBS WebSocket v5 adapter backed by obsws-python when installed."""

    DEFAULT_SCENE_MAP = {
        "main-card": "RareIQ Program",
        "overhead-grid": "RareIQ Multi Card",
        "host": "RareIQ Program",
        "break": "RareIQ Production Screen",
        "starting-soon": "RareIQ Production Screen",
    }

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._lock = threading.RLock()
        self._config: dict[str, Any] = {"host": "127.0.0.1", "port": 4455, "password": "", "enabled": False, "scene_map": {}}
        self._stream_route_probe = ObsStreamRouteProbe.unavailable()
        self._load()

    def _load(self) -> None:
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(value, dict): self._config.update(value)
        except (OSError, ValueError, TypeError): pass

    def _persist(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(f"{self.config_path.suffix}.tmp")
        temporary.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
        temporary.replace(self.config_path)

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            update = {"host": str(payload.get("host") or "127.0.0.1")[:255], "port": max(1, min(65535, int(payload.get("port") or 4455))), "enabled": bool(payload.get("enabled")), "scene_map": dict(payload.get("scene_map") or {})}
            # The settings form intentionally submits an empty password when
            # the operator wants to keep the stored secret.
            if str(payload.get("password") or ""):
                update["password"] = str(payload["password"])[:500]
            previous = deepcopy(self._config)
            self._config.update(deepcopy(update))
            try:
                self._persist()
            except Exception:
                self._config = previous
                raise
            self._stream_route_probe = ObsStreamRouteProbe.unavailable()
            return self.settings()

    def settings(self) -> dict[str, Any]:
        with self._lock:
            value = deepcopy(self._config)
            value["password_configured"] = bool(value.get("password"))
        value["password"] = ""
        value["client_installed"] = importlib.util.find_spec("obsws_python") is not None
        return value

    def _client(self):
        if not self._config.get("enabled"): raise RuntimeError("OBS integration is disabled")
        if importlib.util.find_spec("obsws_python") is None: raise RuntimeError("obsws-python is not installed")
        import obsws_python as obs  # type: ignore
        return obs.ReqClient(host=self._config["host"], port=self._config["port"], password=self._config.get("password") or "", timeout=3)

    @contextmanager
    def _connection(self):
        # Serialize commands with settings changes and always release the
        # short-lived request socket, including when an OBS request fails.
        with self._lock:
            client = self._client()
            try:
                yield client
            finally:
                disconnect = getattr(client, "disconnect", None)
                if callable(disconnect):
                    try:
                        disconnect()
                    except Exception:
                        # Cleanup must not mask the original command result.
                        pass

    @staticmethod
    def _scene_name(scene: Any) -> str:
        """Normalize obsws-python objects and protocol dictionaries."""
        if isinstance(scene, str):
            return scene.strip()
        if isinstance(scene, dict):
            return str(scene.get("sceneName") or scene.get("scene_name") or "").strip()
        return str(
            getattr(scene, "scene_name", None)
            or getattr(scene, "sceneName", None)
            or ""
        ).strip()

    @classmethod
    def _scene_names(cls, scenes: Any) -> list[str]:
        return [name for scene in list(scenes or []) if (name := cls._scene_name(scene))]

    @staticmethod
    def _response_value(response: Any, snake_name: str, camel_name: str) -> Any:
        if isinstance(response, dict):
            return response.get(snake_name, response.get(camel_name))
        return getattr(response, snake_name, getattr(response, camel_name, None))

    @classmethod
    def _stream_route_from_response(cls, response: Any) -> ObsStreamRouteProbe:
        service_type = str(
            cls._response_value(response, "stream_service_type", "streamServiceType") or ""
        ).strip()
        settings = cls._response_value(
            response,
            "stream_service_settings",
            "streamServiceSettings",
        )
        if not isinstance(settings, dict):
            settings = {}
        service_name = str(settings.get("service") or "").strip().lower()
        server = str(settings.get("server") or "").strip()
        stream_key = str(settings.get("key") or "").strip()
        provider = cls._stream_provider(service_name=service_name, server=server)
        return ObsStreamRouteProbe(
            inspected=True,
            connected=True,
            verified_at=time.time(),
            service_type=service_type or None,
            provider=provider,
            key_configured=bool(stream_key),
            _stream_key=stream_key or None,
            _server_url=server or None,
        )

    @staticmethod
    def _stream_provider(*, service_name: str, server: str) -> str | None:
        if service_name in {"x", "x live", "x media studio"} or "twitter" in service_name:
            return "x"
        if "facebook" in service_name:
            return "facebook"
        if "kick" in service_name:
            return "kick"
        if "rumble" in service_name:
            return "rumble"
        if "twitch" in service_name:
            return "twitch"
        if "youtube" in service_name:
            return "youtube"
        parsed = urlparse(server if "://" in server else f"//{server}")
        host = str(parsed.hostname or "").lower().rstrip(".")
        if host in {
            "stream.kick.com",
            "fa723fc1b171.global-contribute.live-video.net",
        }:
            return "kick"
        if (
            host == "live.twitch.tv"
            or host.endswith(".contribute.live-video.net")
            or host.endswith(".contribute.video.net")
        ):
            return "twitch"
        if (
            host.endswith(".rtmp.youtube.com")
            or host.endswith(".upload.youtube.com")
        ):
            return "youtube"
        if host == "live-api-s.facebook.com":
            return "facebook"
        return None

    def cached_stream_route_probe(self) -> ObsStreamRouteProbe:
        with self._lock:
            return self._stream_route_probe

    def _set_stream_route_probe(self, probe: ObsStreamRouteProbe) -> None:
        with self._lock:
            self._stream_route_probe = probe

    @staticmethod
    def _connection_error(exc: Exception) -> dict[str, str]:
        message = str(exc)
        authentication = any(token in message.lower() for token in ("auth", "password", "identified"))
        return {
            "code": "authentication_failed" if authentication else "websocket_error",
            "message": "OBS rejected the WebSocket password" if authentication else message,
            "action": "Check the OBS WebSocket password" if authentication else "Check OBS WebSocket Server Settings",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def _status_locked(self) -> dict[str, Any]:
        result = {"connected": False, "scenes": [], "current_scene": None, "streaming": False, "recording": False, **self.settings()}
        self._set_stream_route_probe(ObsStreamRouteProbe.unavailable())
        result["stream_service"] = self.cached_stream_route_probe().public_status()
        result["diagnostic"] = self.diagnostic()
        if result["diagnostic"]["code"] != "ready":
            result["error"] = result["diagnostic"]["message"]
            return result
        try:
            with self._connection() as client:
                version = client.get_version()
                scenes = client.get_scene_list()
                stream = client.get_stream_status()
                record = client.get_record_status()
                result.update({"connected": True, "obs_version": getattr(version, "obs_version", None), "scenes": self._scene_names(getattr(scenes, "scenes", [])), "current_scene": getattr(scenes, "current_program_scene_name", None), "streaming": bool(getattr(stream, "output_active", False)), "recording": bool(getattr(record, "output_active", False))})
                route_request = getattr(client, "get_stream_service_settings", None)
                if callable(route_request):
                    try:
                        route_probe = self._stream_route_from_response(route_request())
                        self._set_stream_route_probe(route_probe)
                        result["stream_service"] = route_probe.public_status()
                    except Exception:
                        # A failed route check cannot keep old route evidence.
                        # Other successful OBS status reads remain useful.
                        pass
        except Exception as exc:
            result["error"] = str(exc); result["diagnostic"] = self._connection_error(exc)
        return result

    def diagnostic(self) -> dict[str, str]:
        if not self._config.get("enabled"): return {"code": "disabled", "message": "OBS integration is disabled", "action": "Enable OBS synchronization and save settings"}
        if importlib.util.find_spec("obsws_python") is None: return {"code": "client_missing", "message": "OBS client dependency is not installed", "action": "Install obsws-python"}
        host, port = str(self._config.get("host") or "127.0.0.1"), int(self._config.get("port") or 4455)
        try:
            with socket.create_connection((host, port), timeout=.75): pass
        except socket.gaierror: return {"code": "host_unreachable", "message": f"OBS host {host} cannot be resolved", "action": "Check the OBS host address"}
        except (ConnectionRefusedError, TimeoutError, OSError): return {"code": "port_closed", "message": f"Nothing is listening at {host}:{port}", "action": "Open OBS and enable Tools → WebSocket Server Settings"}
        return {"code": "ready", "message": "OBS WebSocket port is reachable", "action": "Authenticating"}

    def command(self, action: str, scene: str | None = None) -> dict[str, Any]:
        if action not in {"start-stream", "stop-stream", "start-record", "stop-record", "set-scene"} or (action == "set-scene" and not scene):
            raise ValueError("unsupported_obs_action")
        with self._connection() as client:
            if action in {"start-stream", "stop-stream"}:
                active = bool(getattr(client.get_stream_status(), "output_active", False))
                if action == "start-stream" and not active: client.start_stream()
                elif action == "stop-stream" and active: client.stop_stream()
            elif action in {"start-record", "stop-record"}:
                active = bool(getattr(client.get_record_status(), "output_active", False))
                if action == "start-record" and not active: client.start_record()
                elif action == "stop-record" and active: client.stop_record()
            elif action == "set-scene":
                scenes = client.get_scene_list()
                available = set(self._scene_names(getattr(scenes, "scenes", [])))
                if scene not in available:
                    raise ValueError(f"OBS scene does not exist: {scene}")
                current = str(getattr(scenes, "current_program_scene_name", None) or "")
                if current != scene:
                    client.set_current_program_scene(scene)
        return self.status()

    def sync_scene(self, rareiq_scene_id: str) -> dict[str, Any] | None:
        target = (self._config.get("scene_map") or {}).get(rareiq_scene_id)
        if not target or not self._config.get("enabled"): return None
        return self.command("set-scene", str(target))

    @staticmethod
    def bootstrap_plan(base_url: str) -> list[dict[str, Any]]:
        root = base_url.rstrip("/")
        return [{**item, "url": f"{root}{item['path']}"} for item in broadcast_sources()]

    @staticmethod
    def _bootstrap_transform(item: dict[str, Any], canvas_width: int, canvas_height: int) -> dict[str, Any]:
        fit = {"positionX": 0.0, "positionY": 0.0, "alignment": 5,
               "boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsAlignment": 0,
               "boundsWidth": canvas_width, "boundsHeight": canvas_height}
        if item.get("placement") == "bottom-center":
            # No native upscaling, at most 92% width / 30% height; this also
            # keeps the strip on-screen for portrait and smaller canvases.
            scale = min(1.0, canvas_width * .92 / item["width"], canvas_height * .30 / item["height"])
            width, height = item["width"] * scale, item["height"] * scale
            margin = min(canvas_width, canvas_height) * .025
            fit.update(positionX=(canvas_width - width) / 2,
                       positionY=canvas_height - height - margin,
                       boundsWidth=width, boundsHeight=height)
        return fit

    @classmethod
    def _bootstrap_actions(cls, client: Any, plan: list[dict[str, Any]], existing: set[str]) -> list[dict[str, Any]]:
        """Only fill empty scenes; never change existing operator content."""
        annotated = []
        for item in plan:
            action = "create"
            if item["scene"] in existing:
                response = client.get_scene_item_list(item["scene"])
                items = cls._response_value(response, "scene_items", "sceneItems")
                if not isinstance(items, list):
                    raise RuntimeError(f"Could not inspect OBS scene: {item['scene']}")
                action = "preserve" if items else "complete"
            annotated.append({**item, "action": action})
        return annotated

    def preflight(self, base_url: str) -> dict[str, Any]:
        """Authenticate and calculate a non-mutating OBS bootstrap plan."""
        plan = self.bootstrap_plan(base_url)
        diagnostic = self.diagnostic()
        result: dict[str, Any] = {
            "ready": False,
            "plan": plan,
            "existing_scenes": [],
            "create_count": len(plan),
            "preserve_count": 0,
            "diagnostic": diagnostic,
        }
        if diagnostic.get("code") != "ready":
            return result
        try:
            with self._connection() as client:
                version = client.get_version()
                scenes = client.get_scene_list()
                existing = set(self._scene_names(getattr(scenes, "scenes", [])))
                annotated = self._bootstrap_actions(client, plan, existing)
            preserve_count = sum(item["action"] == "preserve" for item in annotated)
            result.update({
                "ready": True,
                "plan": annotated,
                "existing_scenes": sorted(existing),
                "create_count": len(annotated) - preserve_count,
                "complete_count": sum(item["action"] == "complete" for item in annotated),
                "preserve_count": preserve_count,
                "obs_version": getattr(version, "obs_version", None),
                "diagnostic": {"code": "authenticated", "message": "OBS WebSocket authenticated", "action": "Review the scene plan, then create"},
            })
        except Exception as exc:
            result["diagnostic"] = self._connection_error(exc)
        return result

    def bootstrap(self, base_url: str, *, dry_run: bool = True) -> dict[str, Any]:
        plan = self.bootstrap_plan(base_url)
        if dry_run:
            return {"dry_run": True, "created": [], "skipped": [], **self.preflight(base_url)}
        created, skipped = [], []
        with self._connection() as client:
            scenes = client.get_scene_list()
            existing_scenes = set(self._scene_names(getattr(scenes, "scenes", [])))
            plan = self._bootstrap_actions(client, plan, existing_scenes)
            inputs = self._response_value(client.get_input_list(), "inputs", "inputs")
            if not isinstance(inputs, list):
                raise RuntimeError("Could not inspect OBS source names")
            video = client.get_video_settings()
            canvas_width = self._response_value(video, "base_width", "baseWidth")
            canvas_height = self._response_value(video, "base_height", "baseHeight")
            if not isinstance(canvas_width, int) or not isinstance(canvas_height, int) or min(canvas_width, canvas_height) <= 0:
                raise RuntimeError("Could not inspect OBS canvas size")
            # OBS scenes and inputs share a global source-name namespace.
            occupied = existing_scenes | {item["scene"] for item in plan}
            occupied.update(str(self._response_value(item, "input_name", "inputName") or "") for item in inputs)
            for item in plan:
                if item["action"] == "preserve":
                    skipped.append({**item, "reason": "scene_exists"}); continue
                if item["action"] == "create":
                    client.create_scene(item["scene"])
                source, suffix = item["source"], 2
                while source in occupied:
                    source = f"{item['source']} ({suffix})"
                    suffix += 1
                item["source"] = source
                try:
                    response = client.create_input(item["scene"], item["source"], "browser_source", {"url": item["url"], "width": item["width"], "height": item["height"], "reroute_audio": bool(item.get("audio")), "shutdown": False, "restart_when_active": False}, True)
                    occupied.add(source)
                    scene_item_id = self._response_value(response, "scene_item_id", "sceneItemId")
                    if not isinstance(scene_item_id, int):
                        raise RuntimeError("OBS did not return the new scene item ID")
                    client.set_scene_item_transform(item["scene"], scene_item_id, self._bootstrap_transform(item, canvas_width, canvas_height))
                    created.append(item)
                except Exception as exc:
                    skipped.append({**item, "reason": f"input_failed: {exc}"})
            available_scenes = {item["scene"] for item in plan if item["action"] == "preserve"} | {item["scene"] for item in created}
            scene_map = dict(self._config.get("scene_map") or {})
            mapped: dict[str, str] = {}
            for rareiq_scene, obs_scene in self.DEFAULT_SCENE_MAP.items():
                if rareiq_scene not in scene_map and obs_scene in available_scenes:
                    scene_map[rareiq_scene] = obs_scene
                    mapped[rareiq_scene] = obs_scene
            if mapped:
                previous = self._config["scene_map"]
                self._config["scene_map"] = scene_map
                try:
                    self._persist()
                except Exception:
                    self._config["scene_map"] = previous
                    raise
        failures = [item for item in skipped if item["reason"] != "scene_exists"]
        result = {"dry_run": False, "ready": not failures, "plan": plan, "created": created, "skipped": skipped, "mapped": mapped, "scene_map": scene_map, "create_count": len(failures), "preserve_count": len(skipped) - len(failures), "status": self.status()}
        if failures:
            result["diagnostic"] = {"code": "bootstrap_incomplete", "message": f"{len(failures)} browser sources could not be created", "action": "Review source errors and preview again to complete empty scenes"}
        return result

    def audit_sources(self, base_url: str) -> dict[str, Any]:
        """Read managed scene/input settings only; never activate or repair output."""
        plan = self.bootstrap_plan(clean_origin(base_url))
        rows = [new_result(item) for item in plan]
        diagnostic = self.diagnostic()
        connected = False
        if diagnostic.get("code") == "ready":
            deadline = time.monotonic() + 12
            try:
                with self._connection() as client:
                    response = self._response_value(client.get_scene_list(), "scenes", "scenes")
                    if not isinstance(response, list):
                        raise ValueError("Scene list unavailable")
                    scenes = set(self._scene_names(response))
                    connected = True
                    settings_cache = {}

                    def read_settings(name: str) -> dict[str, Any]:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Source audit budget reached")
                        if name not in settings_cache:
                            value = client.get_input_settings(name)
                            settings_cache[name] = {"kind": self._response_value(value, "input_kind", "inputKind"),
                                                    "settings": self._response_value(value, "input_settings", "inputSettings")}
                        return settings_cache[name]

                    for index, item in enumerate(plan):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Source audit budget reached")
                        if item["scene"] not in scenes:
                            rows[index] = issue(rows[index], "scene_missing", "Scene missing. Preview Plan can add it without replacing existing scenes.", state="missing")
                            continue
                        entries = self._response_value(client.get_scene_item_list(item["scene"]), "scene_items", "sceneItems")
                        if not isinstance(entries, list):
                            raise ValueError("Scene contents unavailable")
                        rows[index] = inspect_scene(item, entries, read_settings)
                diagnostic = {"code": "checked", "message": "Configuration snapshot only; check the actual picture and audio before a show."}
            except Exception:
                # A dropped request invalidates the snapshot, including earlier
                # green rows. Exception text and foreign source settings stay private.
                connected = False
                rows = [new_result(item) for item in plan]
                diagnostic = {"code": "inspection_failed", "message": "OBS source inspection did not finish. Check the connection and try again; no settings were changed."}
        for row in rows:
            if row["state"] == "unavailable" and not row["issues"]:
                issue(row, "not_checked", "Not checked. Connect OBS and run Check sources again.", state="unavailable")
        return {"connected": connected, "checked_at": time.time(), "read_only": True,
                "diagnostic": diagnostic, **summarize(rows)}
