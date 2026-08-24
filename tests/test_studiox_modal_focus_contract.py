from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")


def test_shortcut_sheet_is_inert_and_hidden_from_accessibility_tree_by_default() -> None:
    shortcut = HTML[HTML.index('class="shortcut-overlay"'):HTML.index('class="operator-toast"')]
    assert 'role="dialog"' in shortcut
    assert 'aria-modal="true"' in shortcut
    assert 'aria-labelledby="shortcutOverlayTitle"' in shortcut
    assert 'aria-hidden="true" inert' in shortcut
    assert 'id="shortcutOverlayTitle"' in shortcut


def test_modal_focus_is_trapped_for_all_operator_dialogs() -> None:
    assert "const STUDIOX_MODAL_FOCUSABLE=" in JS
    assert 'document.addEventListener("keydown",trapStudioXModalFocus,true)' in JS
    assert 'if(event.key!=="Tab") return' in JS
    assert "node.getClientRects().length>0" in JS
    assert "active===first||!modal.contains(active)" in JS
    assert "active===last||!modal.contains(active)" in JS
    assert "if(reference&&!reference.hidden)return reference" in JS
    assert "if(latency&&!latency.hidden)return latency" in JS
    assert 'shortcuts?.classList.contains("visible")' in JS


def test_modal_close_restores_the_opening_control() -> None:
    assert "const studioXModalReturnFocus=new WeakMap()" in JS
    assert "studioXModalReturnFocus.set(modal,active)" in JS
    assert "const target=previous?.isConnected?previous:fallbackFocus" in JS
    assert "if(target?.isConnected) requestAnimationFrame(()=>target.focus())" in JS
    assert 'enterStudioXModal(overlay,$("referenceLightboxClose"))' in JS
    assert 'leaveStudioXModal(overlay,$("cardArt"))' in JS
    assert '$("cardArt").setAttribute("role","button")' in JS
    assert '$("cardArt").setAttribute("aria-label","Enlarge reference artwork")' in JS
    assert ".card-art:focus-visible" in CSS
    assert ".card-art img:focus-visible" not in CSS
    assert "leaveStudioXModal(overlay)" in JS


def test_shortcut_open_and_close_updates_inert_and_accessibility_state() -> None:
    start = JS.index("function toggleShortcutOverlay")
    end = JS.index("function shortcutBackdropClose", start)
    section = JS[start:end]
    assert 'overlay.toggleAttribute("inert",!visible)' in section
    assert 'overlay.setAttribute("aria-hidden",String(!visible))' in section
    assert 'enterStudioXModal(overlay,overlay.querySelector(".shortcut-close"))' in section
    assert "else leaveStudioXModal(overlay)" in section
