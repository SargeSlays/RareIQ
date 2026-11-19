"""Generated local files only: one encode, independent muxing and target stops."""
from dataclasses import FrozenInstanceError
from fractions import Fraction
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import builtins
import io
import socket
import sys
import threading

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


def recording_config(tmp_path):
    value = config(tmp_path)
    value.pop("artifactRoot")
    value["recordingFile"] = {"path": str(tmp_path / "program.mkv"), "minimumFreeBytes": 256 * 1024 ** 2}
    value["targets"] = [{"id": "recording-local", "recording": True, "twitchVod": False}]
    return value


def test_native_recording_is_decodable_matroska_with_program_video_and_live_aac(tmp_path, monkeypatch, capsys):
    av, np = libraries(monkeypatch)
    worker.run(recording_config(tmp_path), generated(np))
    output = events(capsys)
    assert output[-1]["recordingFinalized"] is True
    path = tmp_path / "program.mkv"
    assert output[-1]["recordingBytes"] == path.stat().st_size > 0
    assert str(tmp_path) not in json.dumps(output)
    with av.open(str(path)) as media:
        assert media.format.name == "matroska,webm"
        assert len(media.streams.video) == len(media.streams.audio) == 1
        assert media.streams.video[0].codec_context.name == "h264"
        assert media.streams.audio[0].codec_context.name == "aac"
        assert len(list(media.decode(video=0))) == 45
    with av.open(str(path)) as media:
        decoded = list(media.decode(audio=0))
        assert sum(frame.samples for frame in decoded) >= 72000
        samples = np.concatenate([frame.to_ndarray()[0] for frame in decoded])
        assert float(np.sqrt(np.mean(samples ** 2))) > .05


@pytest.mark.parametrize("change", ["network", "synthetic", "rehearsal", "vod", "renderer_path", "other_id", "extension", "relative"])
def test_recording_boundary_never_falls_through_to_other_output_modes(tmp_path, change):
    value = recording_config(tmp_path)
    if change == "network": value["targets"][0]["destination"] = {"serverUrl": "private", "streamKey": "private"}
    if change == "synthetic": value["artifactRoot"] = str(tmp_path)
    if change == "rehearsal": value["rehearsal"] = True
    if change == "vod": value["twitchVod"] = True
    if change == "renderer_path": value["targets"][0]["path"] = str(tmp_path / "private.mkv")
    if change == "other_id": value["targets"][0]["id"] = "another"
    if change == "extension": value["recordingFile"]["path"] = str(tmp_path / "file.mp4")
    if change == "relative": value["recordingFile"]["path"] = "file.mkv"
    with pytest.raises(worker.base.EncoderError):
        worker.validate_config(value)
    assert not list(tmp_path.iterdir())


def test_recording_never_overwrites_existing_file_or_hard_link(tmp_path):
    spec = recording_config(tmp_path)["recordingFile"]
    path = Path(spec["path"])
    path.write_bytes(b"owner evidence")
    with pytest.raises(worker.base.EncoderError, match="recording_file_exists"):
        worker.RecordingWriter(spec)
    assert path.read_bytes() == b"owner evidence"
    link = tmp_path / "linked.mkv"
    link.hardlink_to(path)
    with pytest.raises(worker.base.EncoderError, match="recording_file_exists"):
        worker.RecordingWriter({**spec, "path": str(link)})
    assert path.read_bytes() == b"owner evidence"


def test_recording_low_space_refuses_creation_and_later_write_failure_stays_unfinalized(tmp_path, monkeypatch, capsys):
    spec = recording_config(tmp_path)["recordingFile"]
    usage = worker.shutil.disk_usage(tmp_path)
    monkeypatch.setattr(worker.shutil, "disk_usage", lambda _path: usage._replace(free=0))
    with pytest.raises(worker.base.EncoderError, match="insufficient_recording_space"):
        worker.RecordingWriter(spec)
    assert not Path(spec["path"]).exists()
    monkeypatch.undo()
    _av, np = libraries(monkeypatch)
    original = worker.RecordingWriter.write
    def failing(self, data):
        if self.handle.tell() > 500:
            raise OSError("private disk detail")
        return original(self, data)
    monkeypatch.setattr(worker.RecordingWriter, "write", failing)
    worker.run(recording_config(tmp_path), generated(np))
    output = events(capsys)
    assert output[-1]["recordingFinalized"] is False
    assert "private disk" not in json.dumps(output)
    assert any(event["event"] == "error" for event in output)


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


def rehearsal_config(*, vod=False):
    return {"width": 64, "height": 64, "fps": 30, "codec": "libx264", "bitrate": 500000,
            "audioBitrateKbps": 96, "keyframeSeconds": 1, "twitchVod": vod, "rehearsal": True,
            "targets": [{"id": "rehearsal-local", "rehearsal": True, "twitchVod": vod}]}


@pytest.mark.parametrize("vod", [False, True])
def test_rehearsal_config_is_a_distinct_local_contract(vod):
    value = rehearsal_config(vod=vod)
    assert worker.validate_config(value) == value


@pytest.mark.parametrize("flag", [False, None, 0, 1, "true", {}, []])
@pytest.mark.parametrize("location", ["group", "target"])
def test_rehearsal_flags_are_true_only(flag, location):
    value = rehearsal_config()
    (value if location == "group" else value["targets"][0])["rehearsal"] = flag
    with pytest.raises(worker.base.EncoderError, match="invalid_encoder_config"):
        worker.validate_config(value)


@pytest.mark.parametrize("key", ["destination", "testOutput", "testTransport", "artifactRoot", "serverUrl", "streamKey", "transport", "networkVerified"])
@pytest.mark.parametrize("location", ["group", "target"])
def test_rehearsal_rejects_all_destination_artifact_and_transport_fields_even_null(key, location):
    value = rehearsal_config()
    (value if location == "group" else value["targets"][0])[key] = None
    with pytest.raises(worker.base.EncoderError, match="invalid_encoder_config"):
        worker.validate_config(value)


@pytest.mark.parametrize("change", ["mixed", "two_local", "other_id", "missing_target_flag", "missing_group_flag", "target_in_production", "vod_mismatch"])
def test_rehearsal_rejects_cross_mode_and_mismatched_targets(tmp_path, change):
    value = rehearsal_config()
    if change == "mixed": value["targets"].append(config(tmp_path)["targets"][0])
    if change == "two_local": value["targets"] *= 2
    if change == "other_id": value["targets"][0]["id"] = "other"
    if change == "missing_target_flag": value["targets"][0].pop("rehearsal")
    if change == "missing_group_flag": value.pop("rehearsal")
    if change == "target_in_production":
        value = config(tmp_path)
        value["targets"][0]["rehearsal"] = True
    if change == "vod_mismatch": value["twitchVod"] = True
    with pytest.raises(worker.base.EncoderError, match="invalid_encoder_config"):
        worker.validate_config(value)


def test_discard_writer_never_retains_media_and_has_bounded_counts():
    writer = worker.DiscardWriter()
    assert writer.writable() and not writer.seekable() and not writer.readable()
    assert writer.write(b"synthetic") == 9 and writer.bytes_written == 9
    assert not hasattr(writer, "getvalue") and not hasattr(writer, "buffer")
    writer.bytes_written = 2 ** 53 - 2
    assert writer.write(b"x") == 1
    with pytest.raises(worker.base.EncoderError, match="encoder_failed"):
        writer.write(b"x")
    writer.close()
    with pytest.raises(ValueError, match="discard_writer_closed"):
        writer.write(b"x")


def forbid_rehearsal_outputs(monkeypatch, av):
    """After dependencies load, forbid all Python media-file/network paths.

    av.open is restricted to our file-like discard writer, so native FFmpeg
    cannot receive a filename or URL/protocol through that boundary either.
    """
    import certifi
    opened = []
    original = av.open
    def denied(*args, **kwargs):
        raise AssertionError("rehearsal_output_side_effect")
    def discard_only(value, *args, **kwargs):
        assert isinstance(value, worker.DiscardWriter)
        opened.append(value)
        return original(value, *args, **kwargs)
    for owner, name in ((builtins, "open"), (io, "open"), (Path, "open"),
                        (socket, "socket"), (socket, "create_connection"), (socket, "getaddrinfo"),
                        (worker.base, "network_target"), (worker.base, "fixture_transport"),
                        (worker.base, "test_path"), (worker.base, "VerifiedTlsRelay"),
                        (worker.base, "probe_twitch_vod_mux"), (certifi, "where")):
        monkeypatch.setattr(owner, name, denied)
    monkeypatch.setattr(av, "open", discard_only)
    return opened


@pytest.mark.parametrize("vod", [False, True])
def test_actual_rehearsal_encodes_and_muxes_live_vod_without_files_network_or_stored_media(monkeypatch, capsys, vod):
    av, np = libraries(monkeypatch)
    import certifi  # Warm dependency imports before guarding all file opens.
    source = generated(np, frames=30, vod=vod)
    threads_before = set(threading.enumerate())
    with monkeypatch.context() as guarded:
        opened = forbid_rehearsal_outputs(guarded, av)
        worker.run(rehearsal_config(vod=vod), source)
    output = events(capsys)
    ready = next(event for event in output if event["event"] == "ready" and "targetId" not in event)
    stopped = output[-1]
    local = next(event for event in output if event["event"] == "stopped" and event.get("targetId") == "rehearsal-local")
    assert ready["videoEncoderInstances"] == ready["targetMuxerCount"] == 1
    assert ready["audioEncoderCount"] == (2 if vod else 1)
    assert ready["twitchVodWireVerified"] is False
    assert stopped["event"] == "stopped" and stopped["running"] is False
    assert stopped["videoFrames"] == local["videoFrames"] == 30
    assert stopped["audioSamples"] == 48000 and local["audioSamples"] >= 48000
    assert stopped["vodAudioSamples"] == (48000 if vod else 0)
    assert (local["vodAudioSamples"] >= 48000) if vod else local["vodAudioSamples"] == 0
    assert stopped["packets"] == local["packets"] > 30
    assert stopped["bytesMuxed"] == local["bytesMuxed"] > 0
    assert stopped["bytesDiscarded"] == local["bytesDiscarded"] > local["bytesMuxed"]
    assert len(opened) == 2 and all(writer.closed and writer.bytes_written > 0 for writer in opened)
    assert all(event["rehearsal"] and event["localDiscard"] and event["networkVerified"] is False for event in output)
    assert all(not event["platformVerified"] and not event["platformLiveVerified"] and not event["vodPlatformVerified"] for event in output)
    assert set(threading.enumerate()) <= threads_before


@pytest.mark.parametrize("ending", ["eof", "malformed", "missing_vod"])
def test_rehearsal_input_failure_closes_owned_discard_mux_without_success_receipt(monkeypatch, capsys, ending):
    av, np = libraries(monkeypatch)
    import certifi
    source = generated(np, frames=3, vod=ending != "missing_vod").getvalue()
    if ending == "eof": source = source[:-worker.base.HEADER.size]
    if ending == "malformed": source = worker.base.HEADER.pack(ord("X"), 0, 0)
    threads_before = set(threading.enumerate())
    expected = {"eof": "encoder_input_ended", "malformed": "invalid_encoder_packet", "missing_vod": "twitch_vod_audio_missing"}[ending]
    with monkeypatch.context() as guarded:
        opened = forbid_rehearsal_outputs(guarded, av)
        with pytest.raises(worker.base.EncoderError, match=expected):
            worker.run(rehearsal_config(vod=True), BytesIO(source))
    output = events(capsys)
    assert any(event["event"] == "stopped" and event.get("targetId") == "rehearsal-local" for event in output)
    assert not any(event["event"] == "stopped" and "targetId" not in event for event in output)
    assert len(opened) == 2 and all(writer.closed for writer in opened)
    assert set(threading.enumerate()) <= threads_before


def test_rehearsal_mux_failure_is_truthful_redacted_and_does_not_fall_back_to_transport(monkeypatch, capsys):
    av, np = libraries(monkeypatch)
    import certifi
    original = worker.TargetMux.mux_packet
    def failing(self, output, packet, stream):
        if self.counts["packets"] >= 2:
            raise RuntimeError("private synthetic diagnostic")
        return original(self, output, packet, stream)
    with monkeypatch.context() as guarded:
        opened = forbid_rehearsal_outputs(guarded, av)
        guarded.setattr(worker.TargetMux, "mux_packet", failing)
        # Let startup finish before the generated packets reach the mux.
        worker.run(rehearsal_config(), generated(np, frames=20))
    output = events(capsys)
    failed = next(event for event in output if event["event"] == "error")
    stopped = next(event for event in output if event["event"] == "stopped" and "targetId" in event)
    assert failed["targetId"] == "rehearsal-local" and failed["code"] == stopped["code"] == "encoder_failed"
    assert stopped["running"] is False and stopped["packets"] == 2
    assert "private" not in json.dumps(output)
    assert len(opened) == 2 and all(writer.closed for writer in opened)


@pytest.mark.parametrize("spec", [
    {"id": "rehearsal-local", "twitchVod": False, "destination": {}},
    {"id": "rehearsal-local", "twitchVod": False, "rehearsal": True, "testOutput": "forbidden.flv"},
    {"id": "other", "twitchVod": False, "rehearsal": True},
])
def test_mux_boundary_independently_refuses_malformed_rehearsal_spec(spec):
    target = worker.TargetMux(spec, {"rehearsal": True}, {}, None, None, codec="libx264", wire_verified=False)
    target.thread.start()
    target.thread.join(1)
    assert not target.thread.is_alive() and not target.ready.is_set()
    assert target.error == "invalid_encoder_config" and target.relay is None and target.discard is None
