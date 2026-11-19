"""Full Program encoded A/V RAM replay. Generated pixels/tone only."""
from dataclasses import replace
from fractions import Fraction
from io import BytesIO
import json
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import shared_encoder_worker as worker


def libraries(monkeypatch):
    monkeypatch.syspath_prepend("F:/Caches/ProducerPlease/python-packages")
    return pytest.importorskip("av"), pytest.importorskip("numpy")


def config(seconds=15):
    return {"width": 64, "height": 64, "fps": 30, "codec": "libx264", "bitrate": 500000,
            "audioBitrateKbps": 96, "keyframeSeconds": 1, "twitchVod": False,
            "replay": {"seconds": seconds, "maximumBytes": 8 * 1024 ** 2},
            "targets": [{"id": "replay-local", "replay": True, "twitchVod": False}]}


@pytest.mark.parametrize("seconds", [15, 30, 60])
def test_replay_modes_remain_ram_only_and_exclusive(seconds):
    value = config(seconds)
    assert worker.validate_config(value)["replay"] == value["replay"]
    for change in [{"artifactRoot": "F:/private"}, {"rehearsal": True}, {"recordingFile": {}},
                   {"replay": {"seconds": 14, "maximumBytes": 1024 ** 2}},
                   {"targets": [{"id": "replay-local", "replay": True, "twitchVod": False, "testOutput": "F:/private.flv"}]}]:
        with pytest.raises(worker.base.EncoderError): worker.validate_config({**value, **change})


def test_encoded_ring_is_bounded_and_requires_a_keyframe_plus_audio():
    ring = worker.ReplayRing(15, 1000)
    video = worker.EncodedPacket("V", b"v" * 80, 0, 0, 1, Fraction(1, 30), True)
    audio = worker.EncodedPacket("A", b"a" * 40, 0, 0, 1024, Fraction(1, 48000), False)
    ring.append(video)
    with pytest.raises(worker.base.EncoderError, match="replay_buffer_empty"): ring.snapshot()
    ring.append(audio)
    ring.append(replace(audio, pts=1024, dts=1024))
    ring.append(replace(video, pts=10, dts=10, keyframe=False))
    assert ring.snapshot()[0] == 0
    for index in range(1000):
        ring.append(replace(video, pts=index, dts=index, keyframe=index % 30 == 0))
        ring.append(replace(audio, pts=index * 1600, dts=index * 1600))
        assert ring.bytes <= 1000
    ring.append(replace(video, data=b"large" * 1000))
    assert ring.bytes == 0


def command(identifier, file, minimum=256 * 1024 ** 2):
    data = json.dumps({"requestId": identifier, "recordingFile": {"path": str(file), "minimumFreeBytes": minimum}}).encode()
    return worker.base.HEADER.pack(ord("S"), len(data), 0) + data


def generated(np, tmp_path, *, failure=None):
    class Input(BytesIO):
        def read(self, count=-1):
            if count == worker.base.HEADER.size and self.getbuffer()[self.tell():self.tell() + 1] == b"S":
                # Ensure the independently bounded mux queue has consumed input.
                time.sleep(.15)
                if failure != "exists": assert not list(tmp_path.iterdir()), "RAM replay wrote a file before explicit Save"
            return super().read(count)
    data = Input()
    for index in range(600):
        image = np.zeros((64, 64, 4), dtype=np.uint8)
        image[:, :, 0], image[:, :, 3] = index % 256, 255
        pts = round(index * 1000000 / 30)
        mono = (.15 * np.sin(np.arange(index * 1600, (index + 1) * 1600) * 2 * np.pi * 440 / 48000)).astype("<f4")
        pcm = np.column_stack((mono, mono)).tobytes()
        for kind, payload in (("V", image.tobytes()), ("A", pcm)):
            data.write(worker.base.HEADER.pack(ord(kind), len(payload), pts)); data.write(payload)
    data.write(command("save-one", tmp_path / "program.mkv", 2 ** 53 - 1 if failure == "space" else 256 * 1024 ** 2))
    data.write(worker.base.HEADER.pack(ord("E"), 0, 0)); data.seek(0)
    return data


def test_full_program_replay_decodes_keyframe_aligned_live_audio_with_rebased_timestamps(tmp_path, monkeypatch, capsys):
    av, np = libraries(monkeypatch)
    worker.run(config(), generated(np, tmp_path))
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    receipt = next(item for item in output if item["event"] == "replaySaved")
    assert receipt["ok"] and receipt["finalized"] and receipt["savedBytes"] == (tmp_path / "program.mkv").stat().st_size
    assert 14000 <= receipt["durationMs"] <= 15100
    assert str(tmp_path) not in json.dumps(output)
    with av.open(str(tmp_path / "program.mkv")) as media:
        frames = list(media.decode(video=0))
        assert 420 <= len(frames) <= 450
        assert frames[0].key_frame and abs(float(frames[0].time)) < .002
    with av.open(str(tmp_path / "program.mkv")) as media:
        first_packet = next(packet for packet in media.demux(audio=0) if packet.size)
        assert 0 <= float(first_packet.pts * first_packet.time_base) <= .025
    with av.open(str(tmp_path / "program.mkv")) as media:
        frames = list(media.decode(audio=0))
        # AAC decode priming can discard one 1024-sample packet at the clip edge.
        assert 0 <= float(frames[0].time) <= .05
        samples = np.concatenate([frame.to_ndarray().reshape(-1) for frame in frames])
        assert float(np.sqrt(np.mean(samples ** 2))) > .05
    assert output[-1]["event"] == "stopped"


@pytest.mark.parametrize("failure,code", [("exists", "recording_file_exists"), ("space", "insufficient_recording_space")])
def test_failed_replay_save_preserves_buffer_and_existing_file(tmp_path, monkeypatch, capsys, failure, code):
    _av, np = libraries(monkeypatch)
    if failure == "exists": (tmp_path / "program.mkv").write_bytes(b"owner evidence")
    worker.run(config(), generated(np, tmp_path, failure=failure))
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    receipt = next(item for item in output if item["event"] == "replaySaved")
    assert not receipt["ok"] and receipt["code"] == code
    assert output[-1]["event"] == "stopped" and output[-1]["videoFrames"] == 600
    if failure == "exists": assert (tmp_path / "program.mkv").read_bytes() == b"owner evidence"
    else: assert not (tmp_path / "program.mkv").exists()
