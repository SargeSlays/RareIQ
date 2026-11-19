"""One owned encode pipeline, bounded independent mux queues; secrets use stdin.

V/A/B use encoder_worker framing. T carries JSON {id} (<=128 bytes, pts0);
E drains shared codecs and all remaining targets. No devices or implicit retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from fractions import Fraction
from io import BytesIO, RawIOBase
from pathlib import Path
import json
import os
import queue
import re
import shutil
import stat
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
    "invalid_recording_file", "recording_file_exists", "recording_storage_unavailable",
    "insufficient_recording_space", "recording_finalize_failed",
    "replay_buffer_empty", "replay_save_busy", "replay_save_failed", "replay_cancelled",
})


def emit(event, **values):
    with _PRINT_LOCK:
        base.emit(event, **values, platformVerified=False)


def safe_code(error):
    value = str(error) if isinstance(error, base.EncoderError) else None
    return value if value in SAFE_CODES else "encoder_failed"


def validate_config(value):
    allowed = {"width", "height", "fps", "bitrate", "codec", "audioBitrateKbps", "keyframeSeconds",
               "twitchVod", "targets", "artifactRoot", "rehearsal", "recordingFile", "replay"}
    if not isinstance(value, dict) or set(value) - allowed:
        base.fail("invalid_encoder_config")
    if "rehearsal" in value and value["rehearsal"] is not True:
        base.fail("invalid_encoder_config")
    config = base.validate_config(value)
    rehearsal = value.get("rehearsal") is True
    recording = "recordingFile" in value
    replay = "replay" in value
    if replay:
        ring = value["replay"]
        if (recording or rehearsal or "artifactRoot" in value or config["twitchVod"] or not isinstance(ring, dict)
                or set(ring) != {"seconds", "maximumBytes"} or type(ring["seconds"]) is not int or ring["seconds"] not in {15, 30, 60}
                or type(ring["maximumBytes"]) is not int or not 1024 ** 2 <= ring["maximumBytes"] <= 128 * 1024 ** 2):
            base.fail("invalid_encoder_config")
    if recording:
        file = value["recordingFile"]
        if (rehearsal or "artifactRoot" in value or config["twitchVod"]
                or not isinstance(file, dict) or set(file) != {"path", "minimumFreeBytes"}
                or not isinstance(file["path"], str) or not 1 <= len(file["path"]) <= 2048
                or not Path(file["path"]).is_absolute() or Path(file["path"]).suffix.lower() != ".mkv"
                or type(file["minimumFreeBytes"]) is not int or not 256 * 1024 ** 2 <= file["minimumFreeBytes"] <= 2 ** 53 - 1):
            base.fail("invalid_recording_file")
    targets = value.get("targets")
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS:
        base.fail("invalid_encoder_config")
    if recording and targets != [{"id": "recording-local", "recording": True, "twitchVod": False}]:
        base.fail("invalid_encoder_config")
    if replay and targets != [{"id": "replay-local", "replay": True, "twitchVod": False}]:
        base.fail("invalid_encoder_config")
    if rehearsal and (len(targets) != 1 or "artifactRoot" in value):
        base.fail("invalid_encoder_config")
    seen, normalized = set(), []
    for target in targets:
        allowed_target = {"id", "replay", "twitchVod"} if replay else {"id", "recording", "twitchVod"} if recording else {"id", "rehearsal", "twitchVod"} if rehearsal else {"id", "destination", "testOutput", "testTransport", "twitchVod"}
        if (not isinstance(target, dict) or set(target) - allowed_target
                or not isinstance(target.get("id"), str) or not _ID.fullmatch(target["id"]) or target["id"] in seen
                or type(target.get("twitchVod", False)) is not bool):
            base.fail("invalid_encoder_config")
        seen.add(target["id"])
        if recording or replay:
            normalized.append(dict(target))
            continue
        if rehearsal:
            if target["id"] != "rehearsal-local" or target.get("rehearsal") is not True:
                base.fail("invalid_encoder_config")
            normalized.append({"id": target["id"], "rehearsal": True, "twitchVod": target.get("twitchVod", False)})
            continue
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
    return {**config, "targets": normalized, **({"recordingFile": dict(value["recordingFile"])} if recording else {}), **({"replay": dict(value["replay"])} if replay else {})}


class RecordingWriter(RawIOBase):
    """Exclusive Main-selected local file; no provider or synthetic fallback."""
    def __init__(self, spec):
        super().__init__()
        self.path = Path(os.path.abspath(spec["path"]))
        self.minimum = spec["minimumFreeBytes"]
        self.handle = None
        self.checked_at = 0.0
        if "\x00" in str(self.path) or self.path.suffix.lower() != ".mkv":
            base.fail("invalid_recording_file")
        parents = [self.path.parent, *self.path.parent.parents]
        try:
            pinned = []
            for parent in parents:
                info = parent.lstat()
                if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                        or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                    base.fail("invalid_recording_file")
                pinned.append((parent, info.st_dev, info.st_ino))
            self.check_space()
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
            self.handle = os.fdopen(descriptor, "w+b", buffering=0)
            for parent, device, inode in pinned:
                info = parent.lstat()
                if (info.st_dev, info.st_ino) != (device, inode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    base.fail("invalid_recording_file")
            self.verify_identity()
            if os.name == "nt":
                import ctypes
                import msvcrt
                from ctypes import wintypes
                resolved = ctypes.create_unicode_buffer(32768)
                query = ctypes.windll.kernel32.GetFinalPathNameByHandleW
                query.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
                query.restype = wintypes.DWORD
                size = query(msvcrt.get_osfhandle(self.handle.fileno()), resolved, len(resolved), 0)
                actual = resolved.value.removeprefix("\\\\?\\")
                if not size or size >= len(resolved) or os.path.normcase(actual) != os.path.normcase(str(self.path)):
                    base.fail("invalid_recording_file")
        except FileExistsError:
            base.fail("recording_file_exists")
        except base.EncoderError:
            if self.handle:
                self.handle.close()
            raise
        except OSError:
            if self.handle:
                self.handle.close()
            base.fail("recording_storage_unavailable")

    def check_space(self):
        if shutil.disk_usage(self.path.parent).free < self.minimum:
            base.fail("insufficient_recording_space")
        self.checked_at = time.monotonic()

    def verify_identity(self):
        current, opened = self.path.lstat(), os.fstat(self.handle.fileno())
        if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or opened.st_nlink != 1
                or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
                or getattr(current, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            base.fail("invalid_recording_file")

    def writable(self): return True
    def seekable(self): return True
    def tell(self): return self.handle.tell()
    def seek(self, offset, whence=0): return self.handle.seek(offset, whence)

    def write(self, value):
        try:
            if time.monotonic() - self.checked_at >= 1:
                self.check_space()
                self.verify_identity()
            size = self.handle.write(value)
            if size != len(value):
                base.fail("recording_storage_unavailable")
            return size
        except OSError:
            base.fail("recording_storage_unavailable")

    def finalize(self):
        try:
            self.verify_identity()
            self.handle.flush()
            os.fsync(self.handle.fileno())
            return os.fstat(self.handle.fileno()).st_size
        except OSError:
            base.fail("recording_finalize_failed")

    def close(self):
        if self.handle and not self.handle.closed:
            self.handle.close()
        super().close()


class DiscardWriter(RawIOBase):
    """Non-seekable mux destination retaining only a bounded byte counter."""
    def __init__(self):
        super().__init__()
        self.bytes_written = 0

    def writable(self):
        return True

    def write(self, value):
        if self.closed:
            raise ValueError("discard_writer_closed")
        size = len(value)
        if size > (2 ** 53 - 1) - self.bytes_written:
            base.fail("encoder_failed")
        self.bytes_written += size
        return size


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
        self.discard = None
        self.recording_finalized = False
        self.recording_bytes = 0
        self.interrupted = self.error_reported = self.closed_reported = False
        self.counts = {"videoFrames": 0, "audioSamples": 0, "vodAudioSamples": 0, "packets": 0, "bytesMuxed": 0}
        self.thread = threading.Thread(target=self.run, daemon=True, name="shared-target-mux")

    def public(self):
        return {**self.counts, "twitchVodWireVerified": self.spec["twitchVod"] and self.wire_verified,
                **({"rehearsal": True, "localDiscard": True, "networkVerified": False,
                    "bytesDiscarded": self.discard.bytes_written if self.discard else 0}
                   if self.spec.get("rehearsal") is True else {}),
                **({"recording": True, "recordingFinalized": self.recording_finalized,
                    "recordingBytes": self.recording_bytes} if self.spec.get("recording") is True else {})}

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
            if self.spec.get("recording") is True:
                if self.spec != {"id": "recording-local", "recording": True, "twitchVod": False} or "recordingFile" not in self.config:
                    base.fail("invalid_encoder_config")
                handle = RecordingWriter(self.config["recordingFile"])
                output = self.av.open(handle, "w", format="matroska")
            elif self.config.get("rehearsal") is True or "rehearsal" in self.spec:
                # Validate again at the output selection boundary: never let a
                # malformed target silently choose the credential/network path.
                if (self.config.get("rehearsal") is not True or self.spec.get("rehearsal") is not True
                        or set(self.spec) != {"id", "rehearsal", "twitchVod"}
                        or self.spec["id"] != "rehearsal-local" or "artifactRoot" in self.config):
                    base.fail("invalid_encoder_config")
                handle = self.discard = DiscardWriter()
                output = self.av.open(handle, "w", format="flv", options={"flvflags": "no_duration_filesize"})
            elif "testOutput" in self.spec:
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
            if handle is not None:
                if isinstance(handle, RecordingWriter):
                    try:
                        self.recording_bytes = handle.finalize()
                        self.recording_finalized = bool(not self.error and not self.abort.is_set() and self.counts["videoFrames"] and self.counts["audioSamples"] and self.recording_bytes)
                    except Exception as error:
                        self.error = safe_code(error)
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


class ReplayRing:
    """Encoded payload capped at 128 MiB; one retained snapshot has the same cap."""
    def __init__(self, seconds, maximum_bytes):
        self.seconds, self.maximum_bytes = seconds, maximum_bytes
        self.packets, self.bytes = deque(), 0
        self.end = Fraction(0)
        self.lock = threading.RLock()

    @staticmethod
    def stamp(packet):
        return Fraction(packet.dts if packet.dts is not None else packet.pts or 0) * packet.time_base

    def append(self, packet):
        with self.lock:
            if packet.kind == "V": self.end = max(self.end, self.stamp(packet))
            self.packets.append(packet)
            self.bytes += len(packet.data)
            cutoff = self.end - self.seconds
            while self.packets and (self.bytes > self.maximum_bytes or len(self.packets) > 20000 or self.stamp(self.packets[0]) < cutoff):
                self.bytes -= len(self.packets.popleft().data)

    def snapshot(self):
        with self.lock:
            cutoff = self.end - self.seconds
            key = next((packet for packet in self.packets if packet.kind == "V" and packet.keyframe and self.stamp(packet) >= cutoff), None)
            if key is None: base.fail("replay_buffer_empty")
            origin = self.stamp(key)
            selected = tuple(packet for packet in self.packets if origin <= self.stamp(packet) <= self.end)
            if self.end - origin < Fraction(1, 4) or sum(packet.kind == "A" for packet in selected) < 2:
                base.fail("replay_buffer_empty")
            return origin, selected

    def public(self):
        with self.lock:
            try:
                origin, _packets = self.snapshot()
                ready, duration = True, max(0, round(float(self.end - origin) * 1000))
            except base.EncoderError:
                ready, duration = False, 0
            return {"replay": True, "replayReady": ready, "bufferedMs": duration, "bufferBytes": self.bytes}


class ReplayMux(TargetMux):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ring = ReplayRing(self.config["replay"]["seconds"], self.config["replay"]["maximumBytes"])
        self.saver, self.save_lock = None, threading.Lock()
        self.save_receipts = {}

    def public(self):
        return {**super().public(), **self.ring.public()}

    def run(self):
        self.ready.set()
        emit("ready", targetId=self.spec["id"], running=True, **self.public())
        report_at = 0.0
        try:
            while not self.abort.is_set():
                try: packet = self.queue.get(timeout=.05)
                except queue.Empty:
                    if self.drain.is_set(): break
                    continue
                with self.lock: self.queue_bytes -= len(packet.data)
                self.ring.append(packet)
                self.counts["packets"] += 1
                self.counts["bytesMuxed"] += len(packet.data)
                if packet.kind == "V": self.counts["videoFrames"] += 1
                else: self.counts["audioSamples"] += packet.duration
                if time.monotonic() - report_at >= 1:
                    emit("stats", targetId=self.spec["id"], running=True, **self.public())
                    report_at = time.monotonic()
        except Exception as error:
            self.error = safe_code(error)
        finally:
            if self.saver: self.saver.join(STOP_TIMEOUT_SECONDS)
            if self.saver and self.saver.is_alive(): self.error = "shared_encoder_shutdown_unconfirmed"
            with self.ring.lock:
                self.ring.packets.clear()
                self.ring.bytes = 0

    def save(self, value):
        identifier = value["requestId"]
        fingerprint = json.dumps(value, sort_keys=True, separators=(",", ":"))
        with self.save_lock:
            previous = self.save_receipts.get(identifier)
            if previous:
                emit("replaySaved", requestId=identifier, **(previous[1] if previous[0] == fingerprint else {"ok": False, "code": "replay_save_failed"}))
                return
            if self.saver and self.saver.is_alive():
                emit("replaySaved", requestId=identifier, ok=False, code="replay_save_busy")
                return
            try: origin, packets = self.ring.snapshot()
            except Exception as error:
                emit("replaySaved", requestId=identifier, ok=False, code=safe_code(error))
                return
            def write_snapshot():
                output = handle = None
                result = {"ok": False, "code": "replay_save_failed"}
                try:
                    handle = RecordingWriter(value["recordingFile"])
                    output = self.av.open(handle, "w", format="matroska")
                    streams = {kind: output.add_stream_from_template(template, opaque=True) for kind, template in self.templates.items()}
                    output.start_encoding()
                    video, audio, duration = 0, 0, Fraction(0)
                    for packet in sorted(packets, key=lambda item: (self.ring.stamp(item), item.kind != "V")):
                        current = packet.rematerialize(self.av, streams[packet.kind])
                        offset = round(origin / packet.time_base)
                        if current.pts is not None: current.pts -= offset
                        if current.dts is not None: current.dts -= offset
                        output.mux(current)
                        duration = max(duration, self.ring.stamp(packet) + packet.duration * packet.time_base - origin)
                        if packet.kind == "V": video += 1
                        else: audio += packet.duration
                    output.close(); output = None
                    size = handle.finalize()
                    if not video or not audio or not size: base.fail("replay_buffer_empty")
                    result = {"ok": True, "finalized": True, "savedBytes": size, "durationMs": round(float(duration) * 1000), "videoFrames": video, "audioSamples": audio}
                except Exception as error:
                    result = {"ok": False, "code": safe_code(error)}
                finally:
                    if output:
                        try: output.close()
                        except Exception: pass
                    if handle: handle.close()
                    with self.save_lock:
                        self.save_receipts[identifier] = (fingerprint, result)
                        if len(self.save_receipts) > 32: self.save_receipts.pop(next(iter(self.save_receipts)))
                    emit("replaySaved", requestId=identifier, **result)
            self.saver = threading.Thread(target=write_snapshot, daemon=True, name="replay-save")
            self.saver.start()


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


def validate_replay_save(value):
    if (not isinstance(value, dict) or set(value) != {"requestId", "recordingFile"}
            or not isinstance(value["requestId"], str) or not _ID.fullmatch(value["requestId"])):
        base.fail("invalid_encoder_packet")
    validate_config({"width": 64, "height": 64, "fps": 30, "bitrate": 500000, "codec": "libx264",
                     "audioBitrateKbps": 96, "keyframeSeconds": 1, "twitchVod": False,
                     "recordingFile": value["recordingFile"],
                     "targets": [{"id": "recording-local", "recording": True, "twitchVod": False}]})
    return value


def run(value, stream):
    import av
    import certifi
    import numpy as np
    av.logging.set_level(av.logging.PANIC)
    config = validate_config(value)
    for key in list(os.environ):
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            os.environ.pop(key, None)
    rehearsal = config.get("rehearsal") is True
    # The existing wire probe stores its synthetic output for inspection. A
    # rehearsal only discards mux bytes and therefore makes no wire claim.
    wire_verified = base.probe_twitch_vod_mux(av, np) if config["twitchVod"] and not rehearsal else False
    codec = base.select_codec(av, np, config)
    template_handle = DiscardWriter() if rehearsal else BytesIO()
    template = av.open(template_handle, "w", format="flv", options={"flvflags": "no_duration_filesize"} if rehearsal else {})
    templates = {"V": template.add_stream(codec, rate=config["fps"]), "A": template.add_stream("aac", rate=48000)}
    base.configure_video(templates["V"], config, codec)
    base.configure_audio(templates["A"], config["audioBitrateKbps"])
    if config["twitchVod"]:
        templates["B"] = template.add_stream("aac", rate=48000)
        base.configure_audio(templates["B"], config["audioBitrateKbps"])
    targets, monitor, monitor_stop = {}, None, threading.Event()
    counts = {"videoFrames": 0, "audioSamples": 0, "audioSilenceSamples": 0,
              "vodAudioSamples": 0, "vodAudioSilenceSamples": 0, "packets": 0, "bytesMuxed": 0}
    def local_stats():
        return (targets["replay-local"].ring.public() if "replay" in config and targets else {"replay": True, "replayReady": False, "bufferedMs": 0, "bufferBytes": 0} if "replay" in config else {"recording": True, "recordingFinalized": bool(targets) and all(target.recording_finalized for target in targets.values()),
                 "recordingBytes": sum(target.recording_bytes for target in targets.values())}
                if "recordingFile" in config else {"rehearsal": True, "localDiscard": True, "networkVerified": False,
                 "bytesDiscarded": sum(target.discard.bytes_written for target in targets.values() if target.discard)}
                if rehearsal else {})
    def dispatch(kind, packets):
        for packet in packets:
            frozen = EncodedPacket.capture(kind, packet)
            counts["packets"] += 1
            counts["bytesMuxed"] += len(frozen.data)
            for target in targets.values():
                target.enqueue(frozen)
    try:
        template.start_encoding()
        targets = {spec["id"]: (ReplayMux if "replay" in config else TargetMux)(spec, config, templates, av, None if rehearsal else certifi.where(), codec=codec, wire_verified=wire_verified)
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
             videoEncoderInstances=encoder_count, audioEncoderCount=len(templates) - 1, targetMuxerCount=len(targets), **local_stats(), **counts)
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
            if kind == "S":
                if "replay" not in config or pts != 0 or not 1 <= length <= 8192:
                    base.fail("invalid_encoder_packet")
                try: command = validate_replay_save(json.loads(base.read_exact(stream, length)))
                except (ValueError, TypeError): base.fail("invalid_encoder_packet")
                targets["replay-local"].save(command)
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
                emit("stats", running=True, **local_stats(), **counts)
                last_report = time.monotonic()
        for kind, encoder in templates.items():
            dispatch(kind, encoder.encode(None))
        stop_targets(targets, drain=True)
        monitor.join(STOP_TIMEOUT_SECONDS)
        if monitor.is_alive():
            base.fail("shared_encoder_shutdown_unconfirmed")
        emit("stopped", running=False, **local_stats(), **counts)
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
            template_handle.close()


def main():
    try:
        raw = sys.stdin.buffer.readline(MAX_CONFIG + 1)
        if len(raw) > MAX_CONFIG or not raw.endswith(b"\n"):
            base.fail("invalid_encoder_config")
        value = json.loads(raw)
        if isinstance(value, dict) and value.get("rehearsal") is True:
            # No media-file handle, even a null-device file, is needed here.
            # Native diagnostics remain on the parent's drained stderr pipe.
            run(value, sys.stdin.buffer)
        else:
            with open(os.devnull, "w") as null:
                os.dup2(null.fileno(), 2)
            run(value, sys.stdin.buffer)
        return 0
    except ModuleNotFoundError:
        emit("error", code="encoder_dependency_missing", running=False)
    except Exception as error:
        emit("error", code=safe_code(error), running=False)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
