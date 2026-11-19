"""Generated local files only: one encode, independent muxing and target stops."""
from dataclasses import FrozenInstanceError
from fractions import Fraction
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import shared_encoder_worker as worker


def libraries(monkeypatch):
    cache = Path("F:/Caches/ProducerPlease/python-packages")
    if importlib.util.find_spec("av") is None and cache.is_dir():
        monkeypatch.syspath_prepend(str(cache))
    return pytest.importorskip("av"), pytest.importorskip("numpy")


def config(tmp_path, *, vod=False):
    return {"width": 64, "height": 64, "fps": 30, "codec": "libx264", "bitrate": 500000,
            "audioBitrateKbps": 96, "keyframeSeconds": 1, "twitchVod": vod, "artifactRoot": str(tmp_path),
            "targets": [{"id": "first", "testOutput": str(tmp_path / "first.flv"), "twitchVod": vod},
                        {"id": "second", "testOutput": str(tmp_path / "second.flv"), "twitchVod": False}]}


def control(identifier):
    data = json.dumps({"id": identifier}).encode()
    return worker.base.HEADER.pack(ord("T"), len(data), 0) + data


def generated(np, *, frames=45, vod=False, stop_at=None):
    stream = BytesIO()
    for index in range(frames):
        if stop_at == index:
            stream.write(control("first"))
        pts = round(index * 1000000 / 30)
        image = np.zeros((64, 64, 4), dtype=np.uint8)
        image[:, :, 0], image[:, :, 3] = index * 3, 255
        stream.write(worker.base.HEADER.pack(ord("V"), image.nbytes, pts))
        stream.write(image.tobytes())
        for kind, frequency in (("A", 440), ("B", 880)) if vod else (("A", 440),):
            mono = (.15 * np.sin(np.arange(index * 1600, (index + 1) * 1600) * 2 * np.pi * frequency / 48000)).astype("<f4")
            data = np.column_stack((mono, mono)).tobytes()
            stream.write(worker.base.HEADER.pack(ord(kind), len(data), pts))
            stream.write(data)
    stream.write(worker.base.HEADER.pack(ord("E"), 0, 0))
    stream.seek(0)
    return stream


def events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


@pytest.mark.parametrize("change", ["empty", "too_many", "duplicate", "bad_id", "two_modes", "unknown", "vod_mismatch", "wrong_vod_platform"])
def test_invalid_target_contract_is_rejected_before_output_side_effects(tmp_path, change):
    value = config(tmp_path)
    if change == "empty": value["targets"] = []
    if change == "too_many": value["targets"] *= 5
    if change == "duplicate": value["targets"][1]["id"] = "first"
    if change == "bad_id": value["targets"][0]["id"] = "../private"
    if change == "two_modes": value["targets"][0]["destination"] = {"serverUrl": "x", "streamKey": "secret"}
    if change == "unknown": value["targets"][0]["script"] = "private"
    if change == "vod_mismatch": value["twitchVod"] = True
    if change == "wrong_vod_platform":
        value["twitchVod"] = True
        value["targets"][0] = {"id": "first", "twitchVod": True,
            "destination": {"serverUrl": "rtmps://provider.com/app", "streamKey": "private", "platform": "youtube"}}
    with pytest.raises(worker.base.EncoderError, match="invalid_encoder_config"):
        worker.validate_config(value)
    assert list(tmp_path.iterdir()) == []


def test_packets_are_immutable_and_target_backpressure_is_local():
    packet = worker.EncodedPacket("V", b"encoded", 1, 1, 1, Fraction(1, 30), True)
    with pytest.raises(FrozenInstanceError):
        packet.pts = 2
    assert "encoded" not in repr(packet)
    first = worker.TargetMux({"id": "first", "twitchVod": False}, {}, {}, None, None, codec="libx264", wire_verified=False)
    second = worker.TargetMux({"id": "second", "twitchVod": False}, {}, {}, None, None, codec="libx264", wire_verified=False)
    for _ in range(worker.MAX_QUEUE_PACKETS):
        assert first.enqueue(packet)
    assert not first.enqueue(packet) and first.error == "encoder_backpressure" and first.abort.is_set()
    assert first.queue.qsize() == worker.MAX_QUEUE_PACKETS and first.queue_bytes <= worker.MAX_QUEUE_BYTES
    assert second.enqueue(packet) and not second.abort.is_set()
    archive = worker.EncodedPacket("B", b"private-archive", 0, 0, 1024, Fraction(1, 48000), True)
    assert second.enqueue(archive) and second.queue.qsize() == 1  # Live-only target receives no B.


def packets(av, path, kind):
    with av.open(str(path)) as media:
        stream = media.streams.video[0] if kind == "V" else media.streams.audio[0]
        return [(bytes(packet), packet.pts, packet.dts, packet.time_base, packet.is_keyframe)
                for packet in media.demux(stream) if packet.size]


def test_one_template_encodes_once_and_two_muxers_preserve_identical_packets(tmp_path, monkeypatch, capsys):
    av, np = libraries(monkeypatch)
    value = config(tmp_path, vod=True)
    worker.run(value, generated(np, vod=True))
    output = events(capsys)
    ready = next(event for event in output if event["event"] == "ready" and "targetId" not in event)
    assert ready["videoEncoderInstances"] == 1 and ready["targetMuxerCount"] == 2 and ready["audioEncoderCount"] == 2
    assert output[-1]["event"] == "stopped" and "targetId" not in output[-1]
    assert output[-1]["videoFrames"] == 45 and output[-1]["audioSamples"] == output[-1]["vodAudioSamples"] == 72000
    for kind in ("V", "A"):
        assert packets(av, tmp_path / "first.flv", kind) == packets(av, tmp_path / "second.flv", kind)
    for identifier in ("first", "second"):
        stopped = [event for event in output if event["event"] == "stopped" and event.get("targetId") == identifier]
        assert len(stopped) == 1 and stopped[0]["running"] is False and stopped[0]["videoFrames"] == 45
    with av.open(str(tmp_path / "first.flv")) as media:
        assert len(media.streams.audio) == 2
        assert len(list(media.decode(video=0))) == 45
    with av.open(str(tmp_path / "second.flv")) as media:
        assert len(media.streams.audio) == 1
    assert worker.base.verify_twitch_vod_wire((tmp_path / "first.flv").read_bytes())
    assert all(not event["platformVerified"] and not event["platformLiveVerified"] and not event["vodPlatformVerified"] for event in output)


def test_target_stop_does_not_end_shared_encoder_or_other_target(tmp_path, monkeypatch, capsys):
    av, np = libraries(monkeypatch)
    value = config(tmp_path)
    worker.run(value, generated(np, frames=60, stop_at=15))
    output = events(capsys)
    first = next(event for event in output if event["event"] == "stopped" and event.get("targetId") == "first")
    second = next(event for event in output if event["event"] == "stopped" and event.get("targetId") == "second")
    assert first["running"] is False and "code" not in first and first["videoFrames"] <= 15
    assert second["videoFrames"] == output[-1]["videoFrames"] == 60
    with av.open(str(tmp_path / "second.flv")) as media:
        assert len(list(media.decode(video=0))) == 60


def test_target_mux_failure_is_redacted_and_does_not_stop_healthy_output(tmp_path, monkeypatch, capsys):
    av, np = libraries(monkeypatch)
    original = worker.TargetMux.mux_packet
    def failing(self, output, packet, stream):
        if self.spec["id"] == "first" and self.counts["packets"] >= 2:
            raise RuntimeError("private URL and stream-key detail")
        return original(self, output, packet, stream)
    monkeypatch.setattr(worker.TargetMux, "mux_packet", failing)
    worker.run(config(tmp_path), generated(np, frames=60))
    output = events(capsys)
    assert "private" not in json.dumps(output)
    error = next(event for event in output if event["event"] == "error")
    assert error["targetId"] == "first" and error["running"] is True and error["code"] == "encoder_failed"
    stopped = next(event for event in output if event["event"] == "stopped" and event.get("targetId") == "first")
    assert stopped["running"] is False and stopped["code"] == "encoder_failed"
    assert output[-1]["videoFrames"] == 60
    with av.open(str(tmp_path / "second.flv")) as media:
        assert len(list(media.decode(video=0))) == 60


def test_shared_input_failure_closes_all_targets_without_claiming_global_stopped(tmp_path, monkeypatch, capsys):
    libraries(monkeypatch)
    malformed = BytesIO(worker.base.HEADER.pack(ord("X"), 0, 0))
    with pytest.raises(worker.base.EncoderError, match="invalid_encoder_packet"):
        worker.run(config(tmp_path), malformed)
    output = events(capsys)
    assert {event["targetId"] for event in output if event["event"] == "stopped"} == {"first", "second"}
    assert not any(event["event"] == "stopped" and "targetId" not in event for event in output)
