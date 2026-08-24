from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    return JS[JS.index(start):JS.index(end)]


def test_single_is_the_safe_default_and_schema_is_versioned() -> None:
    assert 'const CAMERA_WORKSPACE_KEY="rareiq.studiox.cameraWorkspace.v1"' in JS
    assert 'layout:"single"' in JS
    assert 'activeSlot:1' in JS
    assert 'sources:{"1":null,"2":null,"3":null,"4":null}' in JS
    assert 'const savedLayout=value?.layout==="dual-stack"?"dual-side":value?.layout' in JS
    assert 'CAMERA_WORKSPACE_LAYOUTS.includes(savedLayout)?savedLayout:"single"' in JS


def test_exactly_four_layout_options_and_four_unique_tiles_exist() -> None:
    for value in ("single", "dual-side", "triple", "quad"):
        assert HTML.count(f'data-camera-layout-option="{value}"') == 1
        assert f'data-camera-layout="{value}"' in CSS
    assert HTML.count('class="camera-layout-diagram"') == 4
    assert 'data-camera-layout-option="dual-stack"' not in HTML
    assert 'data-camera-layout="dual-stack"' not in CSS
    assert 'role="group" aria-label="Camera workspace layout"' in HTML
    assert HTML.count('id="cameraFeed"') == 1
    for slot in (3, 4):
        assert HTML.count(f'id="cameraWorkspaceSlot{slot}"') == 1


def test_staging_tiles_never_fabricate_camera_one_media() -> None:
    assert HTML.count('id="cameraFeed"') == 1
    for slot in (3, 4):
        tile = HTML[HTML.index(f'id="cameraWorkspaceSlot{slot}"'):]
        tile = tile[:tile.index("</section>")]
        assert "cameraFeed" not in tile
        assert tile.count(f'id="cameraSlot{slot}Preview"') == 1
        assert "<iframe" not in tile
        assert f'`/api/camera-slots/${{slot}}/stream`' in JS


def test_staging_changes_are_presentation_only_and_promotion_is_explicit() -> None:
    staging = section("function setCameraWorkspaceSource", "function setCameraWorkspaceSide")
    assert "selectCamera()" not in staging
    assert "resetRecognitionPresentation" not in staging
    promote = section("async function promoteCameraWorkspaceSlot", "function normalizeSecondaryBayPreferences")
    assert 'await api(`/api/camera-slots/${slot}/activate`,{method:"POST"})' in promote
    assert 'cameraWorkspacePreferences.activeSlot=slot' in promote
    assert "resetRecognitionPresentation" not in promote


def test_layout_and_slot_assignments_persist_and_invalid_values_normalize() -> None:
    assert "localStorage.setItem(CAMERA_WORKSPACE_KEY,JSON.stringify(cameraWorkspacePreferences))" in JS
    assert "normalizeCameraWorkspacePreferences" in JS
    assert '[1,2,3,4].includes(Number(value?.activeSlot))' in JS
    assert '["unassigned","player-1","player-2"]' in JS
    assert 'value?.layout==="dual-stack"?"dual-side"' in JS


def test_single_reclaims_workspace_and_multi_layouts_are_contained() -> None:
    assert '[data-camera-layout="single"] .studiox-secondary-bay{display:none}' in CSS
    assert '[data-camera-layout="single"] .camera-stage-inner' in CSS
    assert "aspect-ratio:16/9" in CSS
    assert '[data-camera-layout="triple"] #cameraWorkspaceSlot3' in CSS
    assert '[data-camera-layout="quad"] #cameraWorkspaceSlot4' in CSS
    assert "overflow:hidden" in CSS


def test_handlers_and_ids_remain_unique() -> None:
    for handler in (
        '$("cameraWorkspaceLayout")?.addEventListener("click"',
        '$("cameraSlot1Side")?.addEventListener',
        'promoteCameraWorkspaceSlot(slot)',
    ):
        assert handler in JS
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    assert len(ids) == len(set(ids))


def test_camera_workspace_uses_one_dark_toolbar_and_shared_tile_headers() -> None:
    assert HTML.count('class="camera-workspace-layout-control camera-workspace-toolbar"') == 1
    toolbar = HTML[HTML.index('class="camera-workspace-layout-control camera-workspace-toolbar"'):]
    toolbar = toolbar[:toolbar.index('</div>\n        <div class="viewer-inspection-header camera-tile-header"')]
    assert 'id="cameraWorkspaceActiveSlot"' not in toolbar
    assert 'id="cameraSlot1Side"' not in toolbar
    assert 'data-camera-layout-option=' in toolbar
    assert 'id="manageCamerasButton"' in HTML
    assert "Camera-workspace visual system" in CSS
    assert "--camera-toolbar-height:56px" in CSS
    assert "--camera-tile-header-height:64px" in CSS
    assert "background:#0b1822" in CSS
    assert ".camera-layout-buttons" in CSS
    assert ".camera-layout-diagram" in CSS
    assert ".secondary-bay-header" in CSS
    assert ".camera-workspace-staging-tile>header" in CSS


def test_each_tile_owns_source_and_side_controls_with_staging_activation() -> None:
    for slot, source_id in ((1, "cameraSlot1Source"), (2, "stagingSourceSelect"), (3, "cameraSlot3Source"), (4, "cameraSlot4Source")):
        assert HTML.count(f'id="{source_id}"') == 1
        assert HTML.count(f'id="cameraSlot{slot}Side"') == 1
    assert 'data-promote-camera-slot="3"' in HTML
    assert 'data-promote-camera-slot="4"' in HTML
    assert 'id="promoteStagingButton"' in HTML
    camera_one = HTML[HTML.index('id="viewerInspectionHeader"'):HTML.index('<div class="camera-stage-inner">')]
    assert "Activate" not in camera_one


def test_all_camera_headers_share_the_source_side_and_activation_contract() -> None:
    assert HTML.count("camera-tile-header") == 4
    assert HTML.count("camera-source-control") == 4
    assert HTML.count("camera-side-control") == 4
    assert HTML.count("camera-activate-control") == 3
    camera_two = HTML[HTML.index('id="secondaryWorkspaceBay"'):HTML.index('<div class="secondary-bay-content">')]
    assert 'id="stagingSourceSelect"' in camera_two
    assert 'class="secondary-bay-control secondary-source-control camera-tile-control camera-source-control"' in camera_two
    assert ".camera-tile-header .camera-source-control" in CSS
    assert ".secondary-bay-control:first-of-type" not in CSS


def test_dual_and_triple_fill_available_camera_workspace_height() -> None:
    assert '[data-camera-layout="dual-side"],\n  body.studiox-ui4.studiox-premium .camera-workspace[data-camera-layout="triple"]' in CSS
    assert "height:100%!important" in CSS
    assert "height:calc(100% - var(--camera-toolbar-height) - var(--camera-grid-gap) - var(--camera-tile-header-height))!important" in CSS
    assert "height:calc((100% - var(--camera-toolbar-height) - (2 * var(--camera-grid-gap))) / 2)!important" in CSS


def test_camera_visual_hierarchy_is_flattened_without_geometry_changes() -> None:
    assert "camera-workspace visual declutter" in CSS
    assert ".camera-workspace{\n  background:transparent!important;\n  border:0!important" in CSS
    assert "border-bottom:1px solid rgba(142,184,207,.12)!important" in CSS
    assert "border-radius:14px 14px 0 0!important" in CSS
    assert "border-radius:0 0 14px 14px!important" in CSS
    assert "border-left:3px solid rgba(80,215,178,.72)!important" in CSS
    assert "position:static!important;inset:auto!important;transform:none!important" in CSS
    assert 'data-camera-layout="quad"] .premium-scan-status' in CSS
    assert "bottom:calc(50% + 8px)!important" in CSS
    assert "width:calc(50% - 24px)!important" in CSS
    assert "data-camera-layout=\"dual-side\"" in CSS
    assert "data-camera-layout=\"triple\"" in CSS
    assert "data-camera-layout=\"quad\"" in CSS


def test_source_ownership_and_explicit_activation_use_safe_paths() -> None:
    assert '$("cameraSlot1Source")?.addEventListener("change",event=>setActiveCameraWorkspaceSource' in JS
    assert 'await selectCamera()' in section("async function setActiveCameraWorkspaceSource", "function normalizeSecondaryBayPreferences")
    staging = section("function setCameraWorkspaceSource", "function setCameraWorkspaceSide")
    assert "selectCamera()" not in staging
    assert "const owner=[1,2,3,4].find" in staging
    assert '$("promoteStagingButton")?.addEventListener("click",()=>promoteCameraWorkspaceSlot(2))' in JS
    assert "clone.disabled=true" in JS
    assert "— missing" in JS


def test_live_build_marker_matches_cache_version() -> None:
    version = re.search(r'data-studiox-build="([^"]+)"', HTML).group(1)
    assert f'data-studiox-build="{version}"' in HTML
    assert f'/static/studiox.js?v={version}' in HTML
    assert f'/static/studiox_update15.css?v={version}' in HTML
    assert f'/static/studiox_ui4_tokens.css?v={version}' in HTML


def test_empty_states_and_exact_match_are_attached_to_camera_tiles() -> None:
    assert "Choose a source from Manage Cameras" in HTML
    assert "Choose a source from Manage Cameras" in JS
    assert '.camera-workspace[data-camera-layout] .premium-scan-status' in CSS
    assert "max-width:320px" in CSS
    assert "max-width:340px" in CSS


def test_pack_battle_sides_remain_metadata_only() -> None:
    assert HTML.count('<option value="player-1">Player 1</option>') >= 4
    assert HTML.count('<option value="player-2">Player 2</option>') >= 4
    assert "score" not in section("function setCameraWorkspaceSide", "async function promoteCameraWorkspaceSlot").lower()
