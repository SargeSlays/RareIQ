"""Pure encoder protocol/policy checks. No network or physical media."""
import importlib.util
from pathlib import Path
import socket
import os
import subprocess
import sys
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("encoder_worker", Path(__file__).parents[1] / "encoder_worker.py")
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


@pytest.mark.parametrize("change", [{"width": 1}, {"width": 1919}, {"height": 3842}, {"width": 3840, "height": 3840}, {"fps": 0}, {"fps": 61}, {"bitrate": 100}, {"codec": "shell"}, {"width": True}])
def test_invalid_config_fails_closed(change):
    with pytest.raises(worker.EncoderError, match="invalid_encoder_config"):
        worker.validate_config({"width": 1920, "height": 1080, **change})


def answers(address):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]


def test_network_target_pins_public_address_and_keeps_key_out_of_url(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("synthetic trust fixture")
    target, options = worker.network_target({"serverUrl": "rtmps://ingest.provider.com/app", "streamKey": "synthetic-key"}, resolver=lambda *args, **kwargs: answers("8.8.8.8"), ca_file=ca)
    assert target == "rtmps://8.8.8.8:443/app"
    assert "synthetic-key" not in target
    assert options["tls_verify"] == "1" and options["verifyhost"] == "ingest.provider.com"
    assert options["ca_file"] == str(ca) and options["rtmp_playpath"] == "synthetic-key"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "::1", "fc00::1", "0.0.0.0", "100.64.0.1", "224.0.0.1", "ff0e::1"])
def test_private_dns_answers_cannot_start_network(address, tmp_path):
    ca = tmp_path / "ca.pem"
    ca.touch()
    with pytest.raises(worker.EncoderError, match="nonpublic_destination"):
        worker.network_target({"serverUrl": "rtmps://ingest.provider.com/app", "streamKey": "synthetic-key"}, resolver=lambda *args, **kwargs: answers(address), ca_file=ca)


@pytest.mark.parametrize("server", ["rtmp://ingest.provider.com/app", "rtmps://localhost/app", "rtmps://127.0.0.1/app", "rtmps://user:password@ingest.provider.com/app", "rtmps://ingest.provider.com/app?key=secret"])
def test_invalid_address_never_resolves(server):
    def forbidden(*args, **kwargs):
        pytest.fail("Rejected addresses must never resolve")
    with pytest.raises(worker.EncoderError):
        worker.network_target({"serverUrl": server, "streamKey": "synthetic-key"}, resolver=forbidden)


def test_truncated_packet_is_sanitized():
    from io import BytesIO
    with pytest.raises(worker.EncoderError, match="encoder_input_ended"):
        worker.read_exact(BytesIO(b"short"), 13)


def test_artifact_cannot_escape_root(tmp_path):
    with pytest.raises(worker.EncoderError, match="invalid_test_output"):
        worker.test_path({"testOutput": str(tmp_path / "outside.flv"), "artifactRoot": str(tmp_path / "inside")})


def test_local_transport_requires_explicit_artifact_ca_and_fixed_host(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.touch()
    for transport in [{"port": 19000, "caFile": str(ca), "serverName": "external.provider.com"},
                      {"port": 19000, "caFile": str(ca), "serverName": "localhost", "target": "10.0.0.1"}]:
        with pytest.raises(worker.EncoderError, match="invalid_test_transport"):
            worker.fixture_transport({"testTransport": transport, "artifactRoot": str(tmp_path)})


def test_audio_timestamp_gaps_are_silence_not_compressed_time():
    assert worker.audio_timing(10000, None) == (480, 0)
    assert worker.audio_timing(30000, 480) == (1440, 960)
    assert worker.audio_timing(10000, 481) == (481, 0)
    with pytest.raises(worker.EncoderError, match="audio_timeline_discontinuity"):
        worker.audio_timing(0, 480)
    with pytest.raises(worker.EncoderError, match="audio_timeline_discontinuity"):
        worker.audio_timing(2_000_000, 0)


@pytest.mark.parametrize("change", [{"fps": 0}, {"fps": 61}, {"fps": 29.97}, {"fps": True}, {"audioBitrateKbps": 63}, {"audioBitrateKbps": 321},
    {"audioBitrateKbps": True}, {"keyframeSeconds": 0}, {"keyframeSeconds": 11}, {"keyframeSeconds": 1.5},
    {"twitchVod": 1}, {"twitchVod": None}])
def test_extended_output_profile_validation(change):
    with pytest.raises(worker.EncoderError, match="invalid_encoder_config"):
        worker.validate_config({"width": 64, "height": 64, **change})


@pytest.mark.parametrize("codec", ["libx264", "h264_nvenc"])
def test_video_profile_applies_keyframes_and_bounded_rate_control(codec):
    config = worker.validate_config({"width": 64, "height": 64, "fps": 60, "bitrate": 4000000, "keyframeSeconds": 3})
    stream = SimpleNamespace(codec_context=SimpleNamespace())
    worker.configure_video(stream, config, codec)
    assert stream.codec_context.gop_size == 180 and stream.codec_context.max_b_frames == 0
    assert stream.bit_rate == 4000000 and stream.options["maxrate"] == stream.options["minrate"] == "4000000"
    assert stream.options["bufsize"] == "8000000"
    if codec == "libx264":
        assert "nal-hrd=cbr" in stream.options["x264-params"] and "scenecut=0" in stream.options["x264-params"]
    else:
        assert stream.options["rc"] == "cbr" and stream.options["preset"] == "p4"


def test_existing_integer_frame_rate_contract_includes_pal_and_low_rate_inputs():
    for fps in (1, 10, 25, 30, 60):
        assert worker.validate_config({"width": 64, "height": 64, "fps": fps})["fps"] == fps


@pytest.mark.parametrize("width,height,expected", [(320, 180, "h264_nvenc"), (1280, 720, "h264_nvenc"), (64, 64, "libx264")])
def test_codec_probe_uses_actual_output_size_and_keeps_small_size_fallback(width, height, expected):
    # Models the measured runtime behavior: 64x64 fails NVENC, production-sized
    # generated frames succeed. No GPU is required by the regression itself.
    opened, frame_shapes = [], []
    class Context:
        def __init__(self, codec):
            self.codec = codec
        def open(self):
            opened.append((self.codec, self.width, self.height))
            if self.codec == "h264_nvenc" and self.width == 64 and self.height == 64:
                raise ValueError("synthetic unsupported dimensions")
        def encode(self, frame):
            return [] if frame is None else [b"synthetic-h264-packet"]
    class Frame:
        @staticmethod
        def from_ndarray(shape, *, format):
            frame_shapes.append(shape)
            return Frame()
        def reformat(self, *, format):
            return self
    av = SimpleNamespace(CodecContext=SimpleNamespace(create=lambda codec, mode: Context(codec)), VideoFrame=Frame)
    np = SimpleNamespace(zeros=lambda shape, dtype: shape, uint8="synthetic-u8")
    config = worker.validate_config({"width": width, "height": height, "codec": "auto"})
    assert worker.select_codec(av, np, config) == expected
    assert all((seen_width, seen_height) == (width, height) for _, seen_width, seen_height in opened)
    assert frame_shapes == [(height, width, 3)]
    if expected == "h264_nvenc":
        assert opened == [("h264_nvenc", width, height)]
    else:
        assert [codec for codec, _, _ in opened] == ["h264_nvenc", "libx264"]


def flv_tag(kind, body):
    return bytes([kind]) + len(body).to_bytes(3, "big") + bytes(7) + body + (len(body) + 11).to_bytes(4, "big")


def enhanced_vod_fixture(*, secondary=b"\x95\x00mp4a\x01\x11\x90", config=b"\x95\x04mp4a\x01\x01\x02\x00\x00\x00\x03"):
    # OBS30.2.3 AAC header/framing, plus Enhanced RTMP v2 native stereo config.
    tags = [flv_tag(18, b"\x02\x00\x0aonMetaData audiocodecid audiosamplerate stereo"),
            flv_tag(8, b"\xaf\x00\x11\x90"), flv_tag(8, secondary), flv_tag(8, config),
            flv_tag(8, b"\xaf\x01generated-primary"), flv_tag(8, b"\x95\x01mp4a\x01generated-archive")]
    return b"FLV\x01\x04\x00\x00\x00\x09\x00\x00\x00\x00" + b"".join(tags)


def test_obs_equivalent_wire_and_stereo_multichannel_tag_are_explicitly_verified():
    assert worker.verify_twitch_vod_wire(enhanced_vod_fixture()) is True
    for body in [b"\x95\x00mp4a\x02\x11\x90", b"\x95\x00Opus\x01\x11\x90", b"\x95\x00mp4a\x01\x11\x88"]:
        with pytest.raises(worker.EncoderError, match="twitch_vod_unavailable"):
            worker.verify_twitch_vod_wire(enhanced_vod_fixture(secondary=body))
    for body in [b"\x95\x04mp4a\x01\x01\x01\x00\x00\x00\x01", b"\x95\x07mp4a\x01", b"\xaf\x02unknown"]:
        with pytest.raises(worker.EncoderError, match="twitch_vod_unavailable"):
            worker.verify_twitch_vod_wire(enhanced_vod_fixture(config=body))
    for data in [b"corrupt", enhanced_vod_fixture()[:-1], enhanced_vod_fixture() + flv_tag(31, b"unknown")]:
        with pytest.raises(worker.EncoderError, match="twitch_vod_unavailable"):
            worker.verify_twitch_vod_wire(data)


def test_archive_input_must_arrive_and_keep_up_without_live_audio_substitution():
    assert worker.check_vod_input(1000000, 0, None) is None
    assert worker.check_vod_input(1000000, 0, 0) is None
    for stamp, first, latest, reason in [(1000001, 0, None, "twitch_vod_audio_missing"),
        (1000001, 0, 0, "twitch_vod_audio_late"), (0, 0, 1000001, "vod_audio_timeline_discontinuity")]:
        with pytest.raises(worker.EncoderError, match=reason):
            worker.check_vod_input(stamp, first, latest)


def libraries(monkeypatch):
    # Optional encoder wheels are already bundled here by the desktop build.
    cached = Path("F:/Caches/ProducerPlease/python-packages")
    if importlib.util.find_spec("av") is None and cached.is_dir():
        monkeypatch.syspath_prepend(str(cached))
    return pytest.importorskip("av"), pytest.importorskip("numpy")


def test_actual_installed_mux_is_probed_and_unsupported_dependencies_fail_closed(monkeypatch):
    av, np = libraries(monkeypatch)
    assert worker.probe_twitch_vod_mux(av, np) is True
    unsupported = SimpleNamespace(open=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private dependency detail")))
    with pytest.raises(worker.EncoderError, match="^twitch_vod_unavailable$"):
        worker.probe_twitch_vod_mux(unsupported, np)


def generated_inputs(np, *, vod, frames=60, omit_vod_index=10):
    data = BytesIO()
    for index in range(frames):
        pts = round(index * 1000000 / 30)
        video = np.zeros((64, 64, 4), dtype=np.uint8)
        video[:, :, 0], video[:, :, 3] = index * 3, 255
        data.write(worker.HEADER.pack(ord("V"), video.nbytes, pts))
        data.write(video.tobytes())
        for kind, frequency in (("A", 440), ("B", 880)) if vod else (("A", 440),):
            if kind == "B" and index == omit_vod_index:
                continue
            samples = np.arange(index * 1600, (index + 1) * 1600, dtype=np.float64)
            mono = (.15 * np.sin(samples * (2 * np.pi * frequency / 48000))).astype("<f4")
            audio = np.column_stack((mono, mono)).tobytes()
            data.write(worker.HEADER.pack(ord(kind), len(audio), pts))
            data.write(audio)
    data.write(worker.HEADER.pack(ord("E"), 0, 0))
    data.seek(0)
    return data


def amplitude(np, samples, frequency):
    samples = samples[12000:-12000]
    timebase = np.arange(len(samples)) / 48000
    return float(2 * abs(np.sum(samples * np.exp(-2j * np.pi * frequency * timebase))) / len(samples))


def test_generated_dual_bus_file_matches_obs_wire_and_decodes_independent_audio(tmp_path, monkeypatch, capsys):
    av, np = libraries(monkeypatch)
    target = tmp_path / "generated-dual-audio.flv"
    worker.run({"width": 64, "height": 64, "fps": 30, "bitrate": 500000, "codec": "libx264",
                "audioBitrateKbps": 96, "keyframeSeconds": 1, "twitchVod": True,
                "testOutput": str(target), "artifactRoot": str(tmp_path)}, generated_inputs(np, vod=True))
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0]["event"] == "ready" and events[0]["twitchVodWireVerified"] is True
    assert all(event["platformLiveVerified"] is False and event["vodPlatformVerified"] is False for event in events)
    assert events[-1]["event"] == "stopped" and events[-1]["audioSamples"] == 96000
    assert events[-1]["vodAudioSamples"] == 94400 and events[-1]["vodAudioSilenceSamples"] == 1600
    assert events[-1]["audioSilenceSamples"] == 0 and worker.verify_twitch_vod_wire(target.read_bytes()) is True
    decoded = []
    for index in (0, 1):
        with av.open(str(target)) as media:
            assert len(media.streams.audio) == 2
            frames = [frame.to_ndarray() for frame in media.decode(audio=index)]
            decoded.append(np.concatenate(frames, axis=1)[0])
    assert amplitude(np, decoded[0], 440) > .1 and amplitude(np, decoded[0], 880) < .01
    assert amplitude(np, decoded[1], 880) > .1 and amplitude(np, decoded[1], 440) < .01
    with av.open(str(target)) as media:
        keyframes = [float(frame.pts * frame.time_base) for frame in media.decode(video=0) if frame.key_frame]
        assert len(keyframes) == 2 and abs(keyframes[1] - keyframes[0] - 1) < .04


def test_ordinary_output_contains_only_live_audio_and_missing_vod_input_fails(tmp_path, monkeypatch, capsys):
    av, np = libraries(monkeypatch)
    config = {"width": 64, "height": 64, "fps": 30, "bitrate": 500000, "codec": "libx264",
              "testOutput": str(tmp_path / "generated-live.flv"), "artifactRoot": str(tmp_path)}
    worker.run(config, generated_inputs(np, vod=False, frames=5))
    with av.open(config["testOutput"]) as media:
        assert len(media.streams.audio) == 1
    with pytest.raises(worker.EncoderError, match="twitch_vod_audio_missing"):
        worker.run({**config, "testOutput": str(tmp_path / "generated-missing-vod.flv"), "twitchVod": True},
                   generated_inputs(np, vod=False, frames=5))
    capsys.readouterr()


def test_cancel_before_any_media_is_a_clean_stop_without_audio_substitution(tmp_path, monkeypatch, capsys):
    libraries(monkeypatch)
    worker.run({"width": 64, "height": 64, "fps": 30, "codec": "libx264", "twitchVod": True,
                "testOutput": str(tmp_path / "generated-empty-stop.flv"), "artifactRoot": str(tmp_path)},
               BytesIO(worker.HEADER.pack(ord("E"), 0, 0)))
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["event"] == "stopped"
    assert events[-1]["audioSamples"] == events[-1]["vodAudioSamples"] == events[-1]["videoFrames"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows socket owner guard")
def test_loopback_relay_checks_exact_client_process():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(2)
        server.settimeout(3)
        with socket.create_connection(server.getsockname(), timeout=3) as own:
            accepted, _ = server.accept()
            with accepted:
                assert worker.same_process_tcp(accepted.getpeername(), accepted.getsockname())
        child = subprocess.Popen([sys.executable, "-B", "-c", "import socket,sys; s=socket.create_connection(('127.0.0.1',int(sys.argv[1]))); sys.stdin.buffer.read(1)", str(server.getsockname()[1])], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            accepted, _ = server.accept()
            with accepted:
                assert not worker.same_process_tcp(accepted.getpeername(), accepted.getsockname())
        finally:
            child.communicate(b"x", timeout=3)
