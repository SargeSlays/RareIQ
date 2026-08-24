from __future__ import annotations

from typing import Any

from rareiq.plugins.pokemon import PokemonPlugin


class PluginManager:
    def __init__(self) -> None:
        self._plugins = {
            "pokemon": PokemonPlugin(),
        }

    def get(self, plugin_id: str) -> Any:
        return self._plugins[plugin_id]

    def list_plugins(self) -> list[dict[str, Any]]:
        return [
            {
                "plugin_id": plugin.plugin_id,
                "display_name": plugin.display_name,
                "version": plugin.version,
                "providers": list(plugin.provider_ids()),
                "signals": list(plugin.recognition_signals()),
            }
            for plugin in self._plugins.values()
        ]


plugin_manager = PluginManager()
