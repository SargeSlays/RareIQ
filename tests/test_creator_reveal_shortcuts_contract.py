from pathlib import Path

STATIC = Path("rareiq/web/static")

def test_creator_reveal_shortcuts_are_visible_and_wired():
    html = (STATIC / "control.html").read_text(encoding="utf-8")
    script = (STATIC / "studiox.js").read_text(encoding="utf-8")
    for label in ("Space", "Esc", "Alt+1", "Alt+2", "Alt+3", "Alt+N"):
        assert f"<kbd>{label}</kbd>" in html
    assert "function handleCreatorRevealShortcut(event)" in script
    assert 'event.code==="Space"&&armed' in script
    assert 'event.key==="Escape"&&armed' in script
    assert 'previewCreatorAnimation("grail")' in script
    assert '$("creatorNextPack")?.click()' in script

def test_shortcuts_are_scoped_away_from_editable_controls():
    script = (STATIC / "studiox.js").read_text(encoding="utf-8")
    assert "creatorShortcutTargetIsEditable(event.target)" in script
    assert 'document.body.dataset.ui4Workspace!=="creator"' in script
    assert 'window.addEventListener("keydown",handleCreatorRevealShortcut)' in script
