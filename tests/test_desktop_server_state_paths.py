"""Exercise real server persistence code without importing application singletons."""
import ast
import json
from pathlib import Path
from typing import Any

import pytest

from rareiq.core.runtime_paths import desktop_config_path

SOURCE = Path(__file__).resolve().parents[1] / 'rareiq/web/server.py'


def server_paths(resource_root):
    namespace = {'BASE_DIR': resource_root / 'rareiq/web', 'desktop_config_path': desktop_config_path,
        'ObsService': lambda path: path, 'json': json, 'Any': Any,
        'PRODUCTION_SESSION': {'active': False, 'metadata': {'name': 'Synthetic session'}}}
    assignments = {'PRODUCTION_SCENE_PATH', 'PRODUCTION_SESSION_PATH', 'PRODUCTION_HISTORY_PATH', 'obs'}
    functions = {'_save_production_session', '_save_production_history', '_load_production_history'}
    body = [node for node in ast.parse(SOURCE.read_text(encoding='utf-8')).body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in assignments for target in node.targets)
        or isinstance(node, ast.FunctionDef) and node.name in functions]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


def test_bundled_session_history_scene_and_obs_paths_use_profile_and_never_touch_resources(tmp_path, monkeypatch):
    resources, profile = tmp_path / 'resources/backend', tmp_path / 'profile/backend'
    resources.mkdir(parents=True)
    seed = resources / 'production_history.json'
    seed.write_text('[{"name":"resource seed must remain unchanged"}]', encoding='utf-8')
    before = seed.read_bytes()
    monkeypatch.setenv('PRODUCER_DESKTOP', '1')
    monkeypatch.setenv('PRODUCER_DESKTOP_DATA_ROOT', str(profile))
    value = server_paths(resources)
    for name in ('PRODUCTION_SCENE_PATH', 'PRODUCTION_SESSION_PATH', 'PRODUCTION_HISTORY_PATH', 'obs'):
        assert value[name].parent == profile
    value['_save_production_session']()
    value['_save_production_history']([{'name': 'Synthetic history'}])
    assert json.loads((profile / 'production_session.json').read_text(encoding='utf-8'))['active'] is False
    assert value['_load_production_history']() == [{'name': 'Synthetic history'}]
    assert seed.read_bytes() == before
    assert list(resources.iterdir()) == [seed]


@pytest.mark.parametrize('desktop', [None, '0', '1'])
def test_development_paths_stay_compatible_without_an_explicit_bundled_data_root(tmp_path, monkeypatch, desktop):
    monkeypatch.delenv('PRODUCER_DESKTOP_DATA_ROOT', raising=False)
    if desktop is None:
        monkeypatch.delenv('PRODUCER_DESKTOP', raising=False)
    else:
        monkeypatch.setenv('PRODUCER_DESKTOP', desktop)
    root = tmp_path / 'developer-project'
    value = server_paths(root)
    assert value['PRODUCTION_SCENE_PATH'] == root / 'production_scenes.json'
    assert value['PRODUCTION_SESSION_PATH'] == root / 'production_session.json'
    assert value['PRODUCTION_HISTORY_PATH'] == root / 'production_history.json'
    assert value['obs'] == root / 'obs_settings.json'
