"""One owned encode pipeline, bounded independent mux queues; secrets use stdin.

V/A/B use encoder_worker framing. T carries JSON {id} (<=128 bytes, pts0);
E drains shared codecs and all remaining targets. No devices or implicit retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from io import BytesIO
import json
import os
import queue
import re
import sys
import threading
import time

import encoder_worker as base


MAX_CONFIG = 65536
MAX_TARGETS = 8
MAX_QUEUE_BYTES = 8 * 1024 * 1024
MAX_QUEUE_PACKETS = 256
START_TIMEOUT_SECONDS = 25
STOP_TIMEOUT_SECONDS = 12
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_PRINT_LOCK = threading.Lock()
SAFE_CODES = frozenset({
    "invalid_encoder_config", "invalid_test_output", "invalid_test_transport", "destination_required",
    "invalid_destination", "secure_destination_required", "nonpublic_destination", "destination_dns_failed",
    "tls_trust_unavailable", "tls_verification_failed", "tls_connection_failed", "encoder_transport_ownership_unavailable",
    "encoder_transport_interrupted", "video_encoder_unavailable", "encoder_input_ended", "invalid_encoder_packet",
    "invalid_audio_samples", "audio_timeline_discontinuity", "vod_audio_timeline_discontinuity",
    "twitch_vod_unavailable", "twitch_vod_audio_missing", "twitch_vod_audio_late", "encoder_dependency_missing",
    "encoder_failed", "encoder_backpressure", "shared_mux_unavailable", "shared_encoder_start_failed",
    "shared_encoder_shutdown_unconfirmed",
})


def emit(event, **values):
    with _PRINT_LOCK:
        base.emit(event, **values, platformVerified=False)


def safe_code(error):
    value = str(error) if isinstance(error, base.EncoderError) else None
    return value if value in SAFE_CODES else "encoder_failed"


def validate_config(value):
    allowed = {"width", "height", "fps", "bitrate", "codec", "audioBitrateKbps", "keyframeSeconds",
               "twitchVod", "targets", "artifactRoot"}
    if not isinstance(value, dict) or set(value) - allowed:
        base.fail("invalid_encoder_config")
    config = base.validate_config(value)
    targets = value.get("targets")
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS:
        base.fail("invalid_encoder_config")
    seen, normalized = set(), []
    for target in targets:
        if (not isinstance(target, dict) or set(target) - {"id", "destination", "testOutput", "testTransport", "twitchVod"}
                or not isinstance(target.get("id"), str) or not _ID.fullmatch(target["id"]) or target["id"] in seen
                or type(target.get("twitchVod", False)) is not bool):
            base.fail("invalid_encoder_config")
        seen.add(target["id"])
        modes = set(target) & {"destination", "testOutput", "testTransport"}
        if len(modes) != 1:
            base.fail("invalid_encoder_config")
        if "destination" in target:
            destination = target["destination"]
            if (not isinstance(destination, dict) or set(destination) - {"serverUrl", "streamKey", "platform"}
                    or not isinstance(destination.get("serverUrl"), str) or not 1 <= len(destination["serverUrl"]) <= 2048
                    or not isinstance(destination.get("streamKey"), str) or not 1 <= len(destination["streamKey"]) <= 4096
                    or target.get("twitchVod", False) and destination.get("platform") != "twitch"):
                base.fail("invalid_encoder_config")
        elif not isinstance(value.get("artifactRoot"), str):
            base.fail("invalid_test_output")
        normalized.append({**target, "twitchVod": target.get("twitchVod", False)})
    if config["twitchVod"] != any(target["twitchVod"] for target in normalized):
        base.fail("invalid_encoder_config")
    return {**config, "targets": normalized}


@dataclass(frozen=True, repr=False)
class EncodedPacket:
    kind: str
    data: bytes
    pts: int | None
    dts: int | None
    duration: int
    time_base: Fraction
    keyframe: bool

    @classmethod
    def capture(cls, kind, packet):
        return cls(kind, bytes(packet), packet.pts, packet.dts, packet.duration or 0,
                   Fraction(packet.time_base), bool(packet.is_keyframe))

    def rematerialize(self, av, stream):
        packet = av.Packet(self.data)
        packet.pts, packet.dts, packet.duration = self.pts, self.dts, self.duration
        packet.time_base, packet.is_keyframe, packet.stream = self.time_base, self.keyframe, stream
        return packet


class TargetMux:
    def __init__(self, spec, config, templates, av, ca_file, *, codec, wire_verified):
        self.spec, self.config, self.templates = spec, config, templates
        self.av, self.ca_file, self.codec, self.wire_verified = av, ca_file, codec, wire_verified
        self.queue = queue.Queue(MAX_QUEUE_PACKETS)
        self.lock = threading.Lock()
        self.queue_bytes = 0
        self.ready, self.abort, self.drain = threading.Event(), threading.Event(), threading.Event()
        self.error = None
        self.relay = None
        self.interrupted = self.error_reported = self.closed_reported = False
        self.counts = {"videoFrames": 0, "audioSamples": 0, "vodAudioSamples": 0, "packets": 0, "bytesMuxed": 0}
        self.thread = threading.Thread(target=self.run, daemon=True, name="shared-target-mux")

    def public(self):
        return {**self.counts, "twitchVodWireVerified": self.spec["twitchVod"] and self.wire_verified}

    def enqueue(self, packet):
        if packet.kind == "B" and not self.spec["twitchVod"]:
            return True
        with self.lock:
            if self.abort.is_set() or self.drain.is_set() or self.closed_reported:
                return False
            if len(packet.data) > MAX_QUEUE_BYTES - self.queue_bytes:
                self.error = "encoder_backpressure"
                self.abort.set()
                return False
            try:
                self.queue.put_nowait(packet)
            except queue.Full:
                self.error = "encoder_backpressure"
                self.abort.set()
                return False
            self.queue_bytes += len(packet.data)
            return True

    def request_stop(self):
        self.abort.set()

    def interrupt(self):
        if self.abort.is_set() and self.relay is not None and not self.interrupted:
            self.interrupted = True
            self.relay.close()

    def mux_packet(self, output, packet, stream):
        output.mux(packet.rematerialize(self.av, stream))

    def run(self):
        output = handle = None
        try:
            if "testOutput" in self.spec:
                target = base.test_path({**self.spec, "artifactRoot": self.config["artifactRoot"]})
                handle = target.open("xb")
                output = self.av.open(handle, "w", format="flv")
            else:
                target, options = (base.fixture_transport({**self.spec, "artifactRoot": self.config.get("artifactRoot")})
                                   if "testTransport" in self.spec else base.network_target(self.spec["destination"], ca_file=self.ca_file))
                self.relay = base.VerifiedTlsRelay(target, options)
                mux_options = {key: value for key, value in options.items() if key not in {"tls_verify", "ca_file", "verifyhost"}}
                output = self.av.open(self.relay.local_url, "w", format="flv", options=mux_options, timeout=(10.0, 10.0))
            streams = {kind: output.add_stream_from_template(template, opaque=True)
                       for kind, template in self.templates.items() if kind != "B" or self.spec["twitchVod"]}
            output.start_encoding()
            if any(stream.codec_context.is_open for stream in streams.values()):
                base.fail("shared_mux_unavailable")
            self.ready.set()
            emit("ready", targetId=self.spec["id"], running=True, **self.public())
            active, last_report = False, 0.0
            while not self.abort.is_set():
                try:
                    packet = self.queue.get(timeout=.05)
                except queue.Empty:
                    if self.drain.is_set():
                        break
                    continue
                with self.lock:
                    self.queue_bytes -= len(packet.data)
                self.mux_packet(output, packet, streams[packet.kind])
                self.counts["packets"] += 1
                self.counts["bytesMuxed"] += len(packet.data)
                if packet.kind == "V":
                    self.counts["videoFrames"] += 1
                else:
                    self.counts["audioSamples" if packet.kind == "A" else "vodAudioSamples"] += packet.duration
                if not active:
                    active = True
                    emit("active", targetId=self.spec["id"], running=True, **self.public())
                if time.monotonic() - last_report >= 1:
                    emit("stats", targetId=self.spec["id"], running=True, **self.public())
                    last_report = time.monotonic()
            if any(stream.codec_context.is_open for stream in streams.values()):
                base.fail("shared_mux_unavailable")
        except Exception as error:
            if self.error is None and not self.abort.is_set():
                self.error = self.relay.error if self.relay and self.relay.error in SAFE_CODES else safe_code(error)
        finally:
            if output is not None:
                try:
                    output.close()
                except Exception:
                    if not self.abort.is_set() and self.error is None:
                        self.error = "encoder_failed"
            if handle:
                handle.close()
            if self.relay:
                self.relay.close()
            with self.lock:
                while True:
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        break
                self.queue_bytes = 0


def monitor_targets(targets, stop):
    while not stop.is_set():
        all_closed = True
        for target in targets.values():
            target.interrupt()
            if target.error and not target.error_reported:
                emit("error", targetId=target.spec["id"], running=True, code=target.error, **target.public())
                target.error_reported = True
            if target.thread.is_alive():
                all_closed = False
            elif not target.closed_reported:
                target.thread.join(0)
                target.closed_reported = True
                emit("stopped", targetId=target.spec["id"], running=False,
                     **({"code": target.error} if target.error else {}), **target.public())
        if all_closed:
            return
        stop.wait(.02)


def stop_targets(targets, *, drain):
    for target in targets.values():
        target.drain.set() if drain and not target.abort.is_set() else target.request_stop()
    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    for target in targets.values():
        target.interrupt()
        target.thread.join(max(0, deadline - time.monotonic()))
    if any(target.thread.is_alive() for target in targets.values()):
        base.fail("shared_encoder_shutdown_unconfirmed")


def run(value, stream):
    import av
    import certifi
    import numpy as np
    av.logging.set_level(av.logging.PANIC)
    config = validate_config(value)
    for key in list(os.environ):
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            os.environ.pop(key, None)
    wire_verified = base.probe_twitch_vod_mux(av, np) if config["twitchVod"] else False
    codec = base.select_codec(av, np, config)
    template = av.open(BytesIO(), "w", format="flv")
    templates = {"V": template.add_stream(codec, rate=config["fps"]), "A": template.add_stream("aac", rate=48000)}
    base.configure_video(templates["V"], config, codec)
    base.configure_audio(templates["A"], config["audioBitrateKbps"])
    if config["twitchVod"]:
        templates["B"] = template.add_stream("aac", rate=48000)
        base.configure_audio(templates["B"], config["audioBitrateKbps"])
    targets, monitor, monitor_stop = {}, None, threading.Event()
    counts = {"videoFrames": 0, "audioSamples": 0, "audioSilenceSamples": 0,
              "vodAudioSamples": 0, "vodAudioSilenceSamples": 0, "packets": 0, "bytesMuxed": 0}
    def dispatch(kind, packets):
        for packet in packets:
            frozen = EncodedPacket.capture(kind, packet)
            counts["packets"] += 1
            counts["bytesMuxed"] += len(frozen.data)
            for target in targets.values():
                target.enqueue(frozen)
    try:
        template.start_encoding()
        targets = {spec["id"]: TargetMux(spec, config, templates, av, certifi.where(), codec=codec, wire_verified=wire_verified)
                   for spec in config["targets"]}
        for target in targets.values():
            target.thread.start()
        monitor = threading.Thread(target=monitor_targets, args=(targets, monitor_stop), daemon=True, name="shared-target-monitor")
        monitor.start()
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while not all(target.ready.is_set() for target in targets.values()):
            if any(target.error or target.closed_reported for target in targets.values()) or time.monotonic() > deadline:
                base.fail("shared_encoder_start_failed")
            time.sleep(.01)
        if any(target.error or not target.thread.is_alive() for target in targets.values()):
            base.fail("shared_encoder_start_failed")
        encoder_count = sum(encoder.codec_context.is_open for kind, encoder in templates.items() if kind == "V")
        if encoder_count != 1:
            base.fail("shared_mux_unavailable")
        emit("ready", running=True, codec=codec, hardwareVerified=codec == "h264_nvenc", twitchVodWireVerified=wire_verified,
             videoEncoderInstances=encoder_count, audioEncoderCount=len(templates) - 1, targetMuxerCount=len(targets), **counts)
        last = {kind: -1 for kind in templates}
        next_sample = {kind: None for kind in templates if kind != "V"}
        first_pts, last_report = None, 0.0
        while True:
            kind, length, pts = base.HEADER.unpack(base.read_exact(stream, base.HEADER.size))
            kind = chr(kind)
            if kind == "E" and length == 0:
                active_vod = any(target.spec["twitchVod"] and not target.abort.is_set() and not target.closed_reported for target in targets.values())
                if active_vod and not counts["vodAudioSamples"] and (counts["videoFrames"] or counts["audioSamples"]):
                    base.fail("twitch_vod_audio_missing")
                break
            if kind == "T":
                if pts != 0 or not 1 <= length <= 128:
                    base.fail("invalid_encoder_packet")
                try:
                    control = json.loads(base.read_exact(stream, length))
                    if not isinstance(control, dict) or set(control) != {"id"} or not isinstance(control["id"], str) or control["id"] not in targets:
                        raise ValueError()
                except (ValueError, TypeError):
                    base.fail("invalid_encoder_packet")
                targets[control["id"]].request_stop()
                continue
            if (kind not in last or not 0 <= pts <= base.MAX_PTS or pts <= last[kind]
                    or kind == "V" and length != config["width"] * config["height"] * 4
                    or kind != "V" and (not 8 <= length <= base.MAX_AUDIO_BYTES or length % 8)):
                base.fail("invalid_encoder_packet")
            first_pts = pts if first_pts is None else first_pts
            vod_targets = any(target.spec["twitchVod"] and not target.abort.is_set() and not target.closed_reported for target in targets.values())
            if vod_targets and kind != "B":
                base.check_vod_input(pts, first_pts, None if last.get("B", -1) < 0 else last["B"])
            data, last[kind] = base.read_exact(stream, length), pts
            if kind == "V":
                frame = av.VideoFrame.from_ndarray(np.frombuffer(data, np.uint8).reshape(config["height"], config["width"], 4), format="bgra")
                frame.pts, frame.time_base = pts, Fraction(1, 1000000)
                dispatch(kind, templates[kind].encode(frame))
                counts["videoFrames"] += 1
            else:
                samples = np.frombuffer(data, dtype="<f4").reshape(-1, 2)
                if not np.isfinite(samples).all():
                    base.fail("invalid_audio_samples")
                try:
                    start, gap = base.audio_timing(pts, next_sample[kind])
                except base.EncoderError:
                    base.fail("vod_audio_timeline_discontinuity" if kind == "B" else "audio_timeline_discontinuity")
                if gap:
                    silence = av.AudioFrame.from_ndarray(np.zeros((2, gap), dtype=np.float32), format="fltp", layout="stereo")
                    silence.sample_rate, silence.time_base, silence.pts = 48000, Fraction(1, 48000), next_sample[kind]
                    dispatch(kind, templates[kind].encode(silence))
                    counts["vodAudioSilenceSamples" if kind == "B" else "audioSilenceSamples"] += gap
                frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(np.clip(samples, -1, 1).T), format="fltp", layout="stereo")
                frame.sample_rate, frame.time_base, frame.pts = 48000, Fraction(1, 48000), start
                next_sample[kind] = start + frame.samples
                dispatch(kind, templates[kind].encode(frame))
                counts["vodAudioSamples" if kind == "B" else "audioSamples"] += frame.samples
            if time.monotonic() - last_report >= 1:
                emit("stats", running=True, **counts)
                last_report = time.monotonic()
        for kind, encoder in templates.items():
            dispatch(kind, encoder.encode(None))
        stop_targets(targets, drain=True)
        monitor.join(STOP_TIMEOUT_SECONDS)
        if monitor.is_alive():
            base.fail("shared_encoder_shutdown_unconfirmed")
        emit("stopped", running=False, **counts)
    finally:
        try:
            if targets:
                stop_targets(targets, drain=False)
        finally:
            # The monitor emits targetstopped only after join confirms exit;
            # let it observe fatal-input cleanup before ending the monitor.
            if monitor:
                monitor.join(STOP_TIMEOUT_SECONDS)
            monitor_stop.set()
            template.close()


def main():
    with open(os.devnull, "w") as null:
        os.dup2(null.fileno(), 2)
    try:
        raw = sys.stdin.buffer.readline(MAX_CONFIG + 1)
        if len(raw) > MAX_CONFIG or not raw.endswith(b"\n"):
            base.fail("invalid_encoder_config")
        run(json.loads(raw), sys.stdin.buffer)
        return 0
    except ModuleNotFoundError:
        emit("error", code="encoder_dependency_missing", running=False)
    except Exception as error:
        emit("error", code=safe_code(error), running=False)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
