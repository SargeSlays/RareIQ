from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from threading import RLock
from typing import Iterable
import unicodedata


@dataclass(frozen=True, slots=True)
class TCGDefinition:
    game_id: str
    name: str
    aliases: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = (
        "catalog",
        "visual_recognition",
        "inventory",
    )
    enabled: bool = True

    def payload(self) -> dict[str, object]:
        result = asdict(self)
        result["aliases"] = list(self.aliases)
        result["providers"] = list(self.providers)
        result["capabilities"] = list(self.capabilities)
        return result


class TCGRegistryService:
    """Owns game identities independently from their catalog adapters."""

    def __init__(
        self,
        games: Iterable[TCGDefinition] = (),
        config_path: Path | None = None,
    ) -> None:
        self._lock = RLock()
        self._games: dict[str, TCGDefinition] = {}
        self._config_path = config_path
        for game in games:
            self.register(game)
        self._selection = self._load_selection()

    def register(self, game: TCGDefinition) -> None:
        game_id = self._normalize(game.game_id)
        if not game_id:
            raise ValueError("TCG game_id is required")
        with self._lock:
            self._games[game_id] = game

    def get(self, game_id: str) -> TCGDefinition | None:
        with self._lock:
            return self._games.get(self._normalize(game_id))

    def resolve(self, value: str) -> TCGDefinition | None:
        wanted = self._normalize(value)
        with self._lock:
            for game in self._games.values():
                names = (game.game_id, game.name, *game.aliases)
                if wanted in {self._normalize(item) for item in names}:
                    return game
        return None

    def status(self) -> dict[str, object]:
        with self._lock:
            games = sorted(self._games.values(), key=lambda item: item.name.casefold())
        return {
            "ok": True,
            "default_game_id": "pokemon",
            "automatic_detection": True,
            "manual_selection": True,
            "selection": self.selection(),
            "games": [game.payload() for game in games],
        }

    def selection(self) -> dict[str, object]:
        with self._lock:
            mode = str(self._selection.get("mode") or "auto")
            selected = self._normalize(str(self._selection.get("game_id") or ""))
            if mode != "manual" or selected not in self._games:
                mode = "auto"
                selected = "pokemon" if "pokemon" in self._games else next(iter(self._games), "")
            resolved = self._games.get(selected)
            resolved_game_id = resolved.game_id if resolved is not None else ""
            return {
                "mode": mode,
                "game_id": resolved_game_id if mode == "manual" else None,
                "resolved_game_id": resolved_game_id,
            }

    def configure_selection(self, mode: str = "auto", game_id: str | None = None) -> dict[str, object]:
        normalized_mode = str(mode or "auto").strip().casefold()
        if normalized_mode not in {"auto", "manual"}:
            raise ValueError("TCG selection mode must be auto or manual")
        normalized_game = self._normalize(game_id or "")
        if normalized_mode == "manual":
            game = self.resolve(normalized_game)
            if game is None or not game.enabled:
                raise ValueError(f"Unknown or disabled TCG game: {game_id or ''}")
            normalized_game = self._normalize(game.game_id)
        else:
            normalized_game = ""
        with self._lock:
            self._selection = {"mode": normalized_mode, "game_id": normalized_game or None}
            self._save_selection()
        return {"ok": True, "selection": self.selection()}

    def _load_selection(self) -> dict[str, object]:
        if self._config_path is None or not self._config_path.exists():
            return {"mode": "auto", "game_id": None}
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"mode": "auto", "game_id": None}
        except (OSError, ValueError):
            return {"mode": "auto", "game_id": None}

    def _save_selection(self) -> None:
        if self._config_path is None:
            return
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._config_path.with_suffix(self._config_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._selection, indent=2), encoding="utf-8")
        temporary.replace(self._config_path)

    @staticmethod
    def _normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
        return "".join(
            character
            for character in decomposed
            if character.isalnum() and not unicodedata.combining(character)
        )
