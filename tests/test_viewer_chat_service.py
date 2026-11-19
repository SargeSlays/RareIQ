"""Viewer transcript is bounded, volatile and separate from audience automation."""
from dataclasses import replace
import json

import pytest

from rareiq.services.viewer_chat_service import (
    MAX_CURSOR, TrustedViewerChatMessage, ViewerChatService, deliver_viewer_chat,
)


NOW = 1800000000.0


def message(**changes):
    values = dict(platform="twitch", channel_id="channel-private", message_id="message-private",
                  author_id="author-private", display_name="Viewer", text="Hello <script>literal</script>",
                  occurred_at=NOW)
    return TrustedViewerChatMessage(**(values | changes))


def test_opt_in_is_volatile_idempotent_and_resets_history_on_transitions():
    now = [NOW]
    service = ViewerChatService(clock=lambda: now[0])
    initial = service.status()
    assert initial["active"] is False and initial["messages"] == []
    assert not service.accept(message())["ok"] and not service._seen
    enabled = service.set_listening(True)
    assert enabled["session_id"] != initial["session_id"]
    assert service.set_listening(True)["session_id"] == enabled["session_id"]
    assert service.accept(message()) == {"ok": True, "duplicate": False}
    assert service.accept(message())["duplicate"] is True
    state = service.status(session_id=enabled["session_id"])
    assert state["messages"][0] == {"id": 1, "platform": "twitch", "display_name": "Viewer",
                                     "text": "Hello <script>literal</script>", "occurred_at": NOW,
                                     "received_at": NOW}
    assert all(word not in json.dumps(state) for word in ("channel-private", "author-private", "message-private"))
    assert not service.status(after=1, session_id=enabled["session_id"])["messages"]
    disabled = service.set_listening(False)
    assert disabled["session_id"] != enabled["session_id"] and not service._seen
    assert not disabled["messages"] and not service.active
    now[0] += 1
    service.set_listening(True)
    assert not service.accept(message())["ok"]  # Late message from the previous session.
    assert service.accept(message(occurred_at=now[0]))["ok"]
    assert service.status()["messages"][0]["id"] == 2
    assert ViewerChatService(clock=lambda: now[0]).status()["messages"] == []


def test_retention_count_cursor_gaps_and_dedup_are_bounded():
    now = [NOW]
    service = ViewerChatService(clock=lambda: now[0])
    session = service.set_listening(True)["session_id"]
    for i in range(service.MAX_DEDUP + 4):
        assert service.accept(message(message_id=str(i)))["ok"]
    state = service.status(after=0, session_id=session)
    assert len(state["messages"]) == 300 and len(service._seen) == service.MAX_DEDUP
    assert state["reset"] and state["cursor"] == service.MAX_DEDUP + 4
    assert not service.status(after=state["cursor"], session_id=session)["reset"]
    assert service.status(after=MAX_CURSOR, session_id=session)["reset"]
    assert service.status(after=state["cursor"], session_id="old-session")["reset"]
    assert service.accept(message(message_id=str(service.MAX_DEDUP + 3)))["duplicate"]
    now[0] += service.RETENTION_SECONDS
    assert service.status(after=0, session_id=session)["messages"] == []
    assert not service._seen


@pytest.mark.parametrize("change", [
    {"platform": "other"}, {"channel_id": ""}, {"author_id": "a" * 161},
    {"display_name": "name\n"}, {"text": ""}, {"text": "   "}, {"text": "a" * 4097},
    {"text": "null\x00"}, {"text": "bad\ud800"}, {"occurred_at": float("nan")},
    {"occurred_at": float("inf")}, {"occurred_at": True}, {"occurred_at": "secret"},
])
def test_malformed_trusted_messages_are_rejected_without_echo(change):
    with pytest.raises(ValueError, match="viewer_chat") as error:
        message(**change)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("value", [-1, MAX_CURSOR + 1, True, 1.2, "0"])
def test_invalid_cursors_are_rejected(value):
    with pytest.raises(ValueError):
        ViewerChatService().status(after=value)


def test_only_trusted_fresh_messages_enter_and_sink_faults_are_isolated():
    service = ViewerChatService(clock=lambda: NOW)
    service.set_listening(True)
    with pytest.raises(ValueError):
        service.accept({"text": "untrusted"})
    for stamp in (NOW - 121, NOW + 6):
        assert not service.accept(message(occurred_at=stamp))["ok"]
    assert service.accept(message(text="first line\nsecond\tline"))["ok"]
    with pytest.raises(ValueError):
        service.set_listening("true")
    calls = []
    def failed_sink(value):
        calls.append(value)
        raise RuntimeError("private provider text")
    deliver_viewer_chat(failed_sink, "twitch", "1", "1", "2", "Viewer", "hello", NOW)
    deliver_viewer_chat(failed_sink, "twitch", "1", "2", "2", "Viewer", "bad\x00", NOW)
    assert len(calls) == 1 and "hello" not in repr(calls[0])


def test_dedup_distinguishes_platform_and_channel_and_preserves_public_cursor():
    service = ViewerChatService(clock=lambda: NOW)
    service.set_listening(True)
    original = message()
    for value in (original, replace(original, platform="kick"), replace(original, channel_id="other")):
        assert not service.accept(value)["duplicate"]
    assert [row["id"] for row in service.status()["messages"]] == [1, 2, 3]
