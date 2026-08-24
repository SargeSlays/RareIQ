from __future__ import annotations

import importlib.util
import json
import threading
import socket
from pathlib import Path
from typing import Any


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
            self._config.update(update)
            self._persist()
            return self.settings()

    def settings(self) -> dict[str, Any]:
        value = dict(self._config); value["password"] = ""; value["password_configured"] = bool(self._config.get("password")); value["client_installed"] = importlib.util.find_spec("obsws_python") is not None
        return value

    def _client(self):
        if not self._config.get("enabled"): raise RuntimeError("OBS integration is disabled")
        if importlib.util.find_spec("obsws_python") is None: raise RuntimeError("obsws-python is not installed")
        import obsws_python as obs  # type: ignore
        return obs.ReqClient(host=self._config["host"], port=self._config["port"], password=self._config.get("password") or "", timeout=3)

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
    def _connection_error(exc: Exception) -> dict[str, str]:
        message = str(exc)
        authentication = any(token in message.lower() for token in ("auth", "password", "identified"))
        return {
            "code": "authentication_failed" if authentication else "websocket_error",
            "message": "OBS rejected the WebSocket password" if authentication else message,
            "action": "Check the OBS WebSocket password" if authentication else "Check OBS WebSocket Server Settings",
        }

    def status(self) -> dict[str, Any]:
        result = {"connected": False, "scenes": [], "current_scene": None, "streaming": False, "recording": False, **self.settings()}
        result["diagnostic"] = self.diagnostic()
        if result["diagnostic"]["code"] != "ready":
            result["error"] = result["diagnostic"]["message"]
            return result
        try:
            client = self._client(); version = client.get_version(); scenes = client.get_scene_list(); stream = client.get_stream_status(); record = client.get_record_status()
            result.update({"connected": True, "obs_version": getattr(version, "obs_version", None), "scenes": self._scene_names(getattr(scenes, "scenes", [])), "current_scene": getattr(scenes, "current_program_scene_name", None), "streaming": bool(getattr(stream, "output_active", False)), "recording": bool(getattr(record, "output_active", False))})
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
        client = self._client()
        if action in {"start-stream", "stop-stream"}:
            active = bool(getattr(client.get_stream_status(), "output_active", False))
            if action == "start-stream" and not active: client.start_stream()
            elif action == "stop-stream" and active: client.stop_stream()
        elif action in {"start-record", "stop-record"}:
            active = bool(getattr(client.get_record_status(), "output_active", False))
            if action == "start-record" and not active: client.start_record()
            elif action == "stop-record" and active: client.stop_record()
        elif action == "set-scene" and scene:
            scenes = client.get_scene_list()
            available = set(self._scene_names(getattr(scenes, "scenes", [])))
            if scene not in available:
                raise ValueError(f"OBS scene does not exist: {scene}")
            current = str(getattr(scenes, "current_program_scene_name", None) or "")
            if current != scene:
                client.set_current_program_scene(scene)
        else:
            raise ValueError("unsupported_obs_action")
        return self.status()

    def sync_scene(self, rareiq_scene_id: str) -> dict[str, Any] | None:
        target = (self._config.get("scene_map") or {}).get(rareiq_scene_id)
        if not target or not self._config.get("enabled"): return None
        return self.command("set-scene", str(target))

    @staticmethod
    def bootstrap_plan(base_url: str) -> list[dict[str, Any]]:
        root = base_url.rstrip("/")
        return [
            {"scene": "RareIQ Program", "source": "RareIQ Program", "url": f"{root}/program", "width": 1920, "height": 1080},
            {"scene": "RareIQ Graphics", "source": "RareIQ Graphics", "url": f"{root}/overlay/graphics", "width": 1920, "height": 1080},
            {"scene": "RareIQ Production Screen", "source": "RareIQ Production Screen", "url": f"{root}/production-screen", "width": 1920, "height": 1080},
            {"scene": "RareIQ Replay", "source": "RareIQ Replay", "url": f"{root}/replay", "width": 1920, "height": 1080},
            {"scene": "RareIQ Intelligence", "source": "RareIQ Intelligence", "url": f"{root}/overlay/pokedex", "width": 1920, "height": 1080},
            {"scene": "RareIQ Multi Card", "source": "RareIQ Multi Card", "url": f"{root}/overlay/multi-card", "width": 1920, "height": 1080},
        ]

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
            client = self._client()
            version = client.get_version()
            scenes = client.get_scene_list()
            existing = set(self._scene_names(getattr(scenes, "scenes", [])))
            annotated = [
                {**item, "action": "preserve" if item["scene"] in existing else "create"}
                for item in plan
            ]
            preserve_count = sum(item["action"] == "preserve" for item in annotated)
            result.update({
                "ready": True,
                "plan": annotated,
                "existing_scenes": sorted(existing),
                "create_count": len(annotated) - preserve_count,
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
        client = self._client(); scenes = client.get_scene_list(); existing_scenes = set(self._scene_names(getattr(scenes, "scenes", [])))
        created, skipped = [], []
        for item in plan:
            if item["scene"] in existing_scenes:
                skipped.append({**item, "reason": "scene_exists"}); continue
            client.create_scene(item["scene"])
            try:
                client.create_input(item["scene"], item["source"], "browser_source", {"url": item["url"], "width": item["width"], "height": item["height"], "reroute_audio": False}, True)
                created.append(item)
            except Exception as exc:
                skipped.append({**item, "reason": f"input_failed: {exc}"})
        available_scenes = existing_scenes | {item["scene"] for item in created}
        scene_map = dict(self._config.get("scene_map") or {})
        mapped: dict[str, str] = {}
        for rareiq_scene, obs_scene in self.DEFAULT_SCENE_MAP.items():
            if rareiq_scene not in scene_map and obs_scene in available_scenes:
                scene_map[rareiq_scene] = obs_scene
                mapped[rareiq_scene] = obs_scene
        if mapped:
            with self._lock:
                self._config["scene_map"] = scene_map
                self._persist()
        return {"dry_run": False, "plan": plan, "created": created, "skipped": skipped, "mapped": mapped, "scene_map": scene_map, "status": self.status()}
