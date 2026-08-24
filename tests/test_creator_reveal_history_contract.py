from pathlib import Path

SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")

def test_creator_reveal_history_and_replay_are_wired():
    assert 'id="creatorRevealHistory"' in CONTROL
    assert '@app.post("/api/creator/reveal-sequence/replay")' in SERVER
    assert "async function replayCreatorReveal(revealId)" in STUDIO
    assert 'body:JSON.stringify({reveal_id:revealId})' in STUDIO
    assert 'replay.textContent="Replay"' in STUDIO
