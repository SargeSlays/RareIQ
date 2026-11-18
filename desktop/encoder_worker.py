"""Owned encoder worker. Secrets enter through stdin, never arguments or logs.

Protocol: one JSON line, then <kind:u8,length:u32LE,ptsUs:u64LE> and payload.
V = BGRA, A = interleaved stereo float32/48 kHz, E = explicit drain/stop.
No camera, microphone, desktop capture, automatic reconnect or platform claim.
"""
from __future__ import annotations

from fractions import Fraction
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import socket
import ssl
import struct
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit

HEADER = struct.Struct("<BIQ")
MAX_CONFIG = 16384
MAX_AUDIO_BYTES = 48000 * 2 * 4
MAX_PTS = 7 * 24 * 3600 * 1_000_000


class EncoderError(Exception):
    pass


def fail(code):
    raise EncoderError(code)


def emit(event, **values):
    print(json.dumps({"event": event, **values}, separators=(",", ":")), flush=True)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate_config(value):
    if not isinstance(value, dict):
        fail("invalid_encoder_config")
    width, height, fps = value.get("width"), value.get("height"), value.get("fps", 30)
    bitrate = value.get("bitrate", 6_000_000)
    if (not integer(width, 16, 3840) or not integer(height, 16, 3840) or width * height > 3840 * 2160
            or width % 2 or height % 2 or not integer(fps, 1, 60)
            or not integer(bitrate, 250_000, 40_000_000)
            or value.get("codec", "auto") not in {"auto", "h264_nvenc", "libx264"}):
        fail("invalid_encoder_config")
    return {**value, "width": width, "height": height, "fps": fps, "bitrate": bitrate, "codec": value.get("codec", "auto")}


def test_path(config):
    # Main process must explicitly opt into a synthetic artifact root.
    value, root = config.get("testOutput"), config.get("artifactRoot")
    if not isinstance(value, str) or not isinstance(root, str):
        fail("invalid_test_output")
    target, base = Path(value), Path(root)
    if not target.is_absolute() or not base.is_absolute():
        fail("invalid_test_output")
    target, base = target.resolve(), base.resolve()
    if os.name == "nt" and (base.drive.lower() != "f:" or target.drive.lower() != "f:"):
        fail("invalid_test_output")
    if base not in target.parents or target.suffix.lower() != ".flv" or target.exists():
        fail("invalid_test_output")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def network_target(destination, *, resolver=socket.getaddrinfo, ca_file=None):
    if not isinstance(destination, dict):
        fail("destination_required")
    server, key = destination.get("serverUrl"), destination.get("streamKey")
    if (not isinstance(server, str) or not 1 <= len(server) <= 2048
            or re.search(r"[\s\\\x00-\x1f\x7f?#]", server)
            or not isinstance(key, str) or not 1 <= len(key) <= 4096
            or re.search(r"[\s\x00-\x1f\x7f]", key)):
        fail("invalid_destination")
    try:
        parsed = urlsplit(server)
        hostname, port = (parsed.hostname or "").lower().rstrip("."), parsed.port or 443
    except ValueError:
        fail("invalid_destination")
    if parsed.scheme != "rtmps" or "@" in parsed.netloc or not 1 <= port <= 65535:
        fail("secure_destination_required")
    if (not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}", hostname)
            or hostname.split(".")[-1] in {"localhost", "local", "internal", "intranet", "lan", "home", "corp", "test", "invalid", "example", "onion", "arpa"}):
        fail("nonpublic_destination")
    try:
        answers = resolver(hostname, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
        if not addresses or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast for address in addresses):
            fail("nonpublic_destination")
    except EncoderError:
        raise
    except Exception:
        fail("destination_dns_failed")
    if not ca_file or not Path(ca_file).is_file():
        fail("tls_trust_unavailable")
    address = addresses[0]
    authority = ("[" + address + "]" if ":" in address else address) + ":" + str(port)
    # Pin the checked address, preserving certificate hostname verification.
    # SNI/ingest compatibility must be accepted against an authorized destination.
    target = urlunsplit(("rtmps", authority, parsed.path.rstrip("/") or "/", "", ""))
    options = {"tls_verify": "1", "ca_file": str(ca_file), "verifyhost": hostname,
               "rtmp_tcurl": server, "rtmp_playpath": key, "rtmp_live": "live",
               "rw_timeout": "10000000", "tcp_nodelay": "1", "flvflags": "no_duration_filesize",
               "max_interleave_delta": "1000000"}
    return target, options


def fixture_transport(config):
    """Explicit synthetic-only localhost transport; no destination credentials."""
    value, root = config.get("testTransport"), config.get("artifactRoot")
    if (not isinstance(value, dict) or set(value) != {"port", "caFile", "serverName"}
            or not integer(value.get("port"), 1024, 65535) or not isinstance(root, str)
            or not isinstance(value.get("caFile"), str) or value.get("serverName") not in {"localhost", "wrong-host.invalid"}):
        fail("invalid_test_transport")
    base, ca = Path(root), Path(value["caFile"])
    if not base.is_absolute() or not ca.is_absolute():
        fail("invalid_test_transport")
    base, ca = base.resolve(), ca.resolve()
    if (base not in ca.parents or not ca.is_file() or ca.suffix != ".pem"
            or os.name == "nt" and base.drive.lower() != "f:"):
        fail("invalid_test_transport")
    authority = "127.0.0.1:" + str(value["port"])
    return "rtmps://" + authority + "/app", {
        "tls_verify": "1", "ca_file": str(ca), "verifyhost": value["serverName"],
        "rtmp_tcurl": "rtmps://" + authority + "/app", "rtmp_playpath": "synthetic-fixture",
        "rw_timeout": "10000000", "tcp_nodelay": "1", "flvflags": "no_duration_filesize", "max_interleave_delta": "1000000"}


def same_process_tcp(peer, local):
    """Verify the connecting socket's IPv4 four-tuple and owner via Windows IP Helper."""
    if os.name != "nt" or peer[0] != "127.0.0.1" or local[0] != "127.0.0.1":
        return False
    import ctypes
    from ctypes import wintypes
    class Row(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in ("state", "local_addr", "local_port", "remote_addr", "remote_port", "pid")]
    try:
        read = ctypes.WinDLL("iphlpapi").GetExtendedTcpTable
        read.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
        read.restype = wintypes.DWORD
        for _ in range(10):
            length = wintypes.DWORD()
            if read(None, ctypes.byref(length), False, socket.AF_INET, 5, 0) not in {0, 122} or not 4 <= length.value <= 8 * 1024 * 1024:
                return False
            table = ctypes.create_string_buffer(length.value)
            result = read(table, ctypes.byref(length), False, socket.AF_INET, 5, 0)
            if result == 122:
                continue
            if result != 0:
                return False
            count = struct.unpack_from("<I", table.raw)[0]
            if count > (length.value - 4) // ctypes.sizeof(Row):
                return False
            for index in range(count):
                row = Row.from_buffer_copy(table, 4 + index * ctypes.sizeof(Row))
                if (socket.inet_ntoa(struct.pack("<I", row.local_addr)) == peer[0]
                        and socket.ntohs(row.local_port & 0xffff) == peer[1]
                        and socket.inet_ntoa(struct.pack("<I", row.remote_addr)) == local[0]
                        and socket.ntohs(row.remote_port & 0xffff) == local[1]):
                    return row.pid == os.getpid()
            time.sleep(.01)
    except Exception:
        pass
    return False


def pump_streams(left, right, closed):
    """Bounded full-duplex forwarding with one owner for each SSL object."""
    left.setblocking(False)
    right.setblocking(False)
    buffers = {left: bytearray(), right: bytearray()}
    wants_write = set()
    ended = set()
    progress = time.monotonic()
    while not closed.is_set():
        reads = [side for side in (left, right) if side not in ended and len(buffers[right if side is left else left]) < 65536]
        writes = [side for side in (left, right) if buffers[side] or side in wants_write]
        readable, writable, _ = select.select(reads, writes, [], .25)
        changed = False
        for source, destination in ((left, right), (right, left)):
            pending = isinstance(source, ssl.SSLSocket) and source.pending() > 0
            if source not in ended and (source in readable or pending or source in wants_write and source in writable):
                room = 65536 - len(buffers[destination])
                if room:
                    try:
                        data = source.recv(room)
                        wants_write.discard(source)
                        if data:
                            buffers[destination].extend(data)
                            changed = True
                        else:
                            ended.add(source)
                    except ssl.SSLWantWriteError:
                        wants_write.add(source)
                    except (BlockingIOError, ssl.SSLWantReadError):
                        pass
        for destination in (left, right):
            if buffers[destination] and (destination in writable or destination in readable):
                try:
                    sent = destination.send(buffers[destination])
                    if sent:
                        del buffers[destination][:sent]
                        changed = True
                except ssl.SSLWantWriteError:
                    wants_write.add(destination)
                except (BlockingIOError, ssl.SSLWantReadError):
                    pass
        if changed:
            progress = time.monotonic()
        if ended and not buffers[left] and not buffers[right]:
            return
        if (buffers[left] or buffers[right]) and time.monotonic() - progress > 10:
            raise TimeoutError("bounded_transport_timeout")


class VerifiedTlsRelay:
    """One owned-process RTMP connection transported through verified stdlib TLS.

    FFmpeg's Windows SChannel ignores an explicit CA file. The relay leaves RTMP
    untouched while enforcing the chosen CA, hostname and pinned public address.
    """
    def __init__(self, target, options):
        self.target, self.options = urlsplit(target), options
        self.error, self.tls_verified = None, False
        self._closed = threading.Event()
        self._sockets = []
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1) if os.name == "nt" else None
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(10)
        self.local_url = "rtmp://127.0.0.1:" + str(self._listener.getsockname()[1]) + (self.target.path or "/")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            client, _ = self._listener.accept()
            self._listener.close()  # Exactly one connection; no later local client.
            self._sockets.append(client)
            client.settimeout(10)
            if not same_process_tcp(client.getpeername(), client.getsockname()):
                self.error = "encoder_transport_ownership_unavailable"
                return
            context = ssl.create_default_context(cafile=self.options["ca_file"])
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            # target.hostname is already a checked numeric IP: never resolve again.
            remote = socket.create_connection((self.target.hostname, self.target.port or 443), timeout=10)
            self._sockets.append(remote)
            secure = context.wrap_socket(remote, server_hostname=self.options["verifyhost"])
            self._sockets.remove(remote)
            self._sockets.append(secure)
            self.tls_verified = True
            pump_streams(client, secure, self._closed)
        except ssl.SSLCertVerificationError:
            self.error = "tls_verification_failed"
        except (OSError, ssl.SSLError):
            if not self._closed.is_set():
                self.error = "tls_connection_failed"
        finally:
            self._shutdown()

    def _shutdown(self):
        self._closed.set()
        try:
            self._listener.close()
        except OSError:
            pass
        for connection in list(self._sockets):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass

    def close(self):
        self._shutdown()
        self._thread.join(timeout=1)


def configure_video(stream, config, codec):
    stream.width, stream.height = config["width"], config["height"]
    stream.pix_fmt = "yuv420p"
    stream.bit_rate = config["bitrate"]
    stream.codec_context.time_base = Fraction(1, config["fps"])
    stream.codec_context.framerate = Fraction(config["fps"], 1)
    stream.codec_context.gop_size = config["fps"] * 2
    stream.codec_context.max_b_frames = 0
    stream.options = ({"preset": "p4", "tune": "ll", "rc": "cbr", "bf": "0"} if codec == "h264_nvenc"
                      else {"preset": "veryfast", "tune": "zerolatency", "bf": "0"})


def select_codec(av, np, config):
    # Actual generated-frame encode, not an advertised-codec availability check.
    choices = ["h264_nvenc", "libx264"] if config["codec"] == "auto" else [config["codec"]]
    for codec in choices:
        try:
            context = av.CodecContext.create(codec, "w")
            context.width, context.height = 64, 64
            context.pix_fmt, context.time_base, context.framerate = "yuv420p", Fraction(1, 30), Fraction(30, 1)
            context.bit_rate = 500_000
            context.options = {"preset": "p4", "tune": "ll"} if codec == "h264_nvenc" else {"preset": "ultrafast", "tune": "zerolatency"}
            context.open()
            frame = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), dtype=np.uint8), format="rgb24").reformat(format="yuv420p")
            frame.pts = 0
            if list(context.encode(frame)) + list(context.encode(None)):
                return codec
        except Exception:
            pass
    fail("video_encoder_unavailable")


def read_exact(stream, count):
    parts = bytearray()
    while len(parts) < count:
        chunk = stream.read(count - len(parts))
        if not chunk:
            fail("encoder_input_ended")
        parts.extend(chunk)
    return bytes(parts)


def audio_timing(pts_us, next_sample):
    start = round(pts_us * 48000 / 1_000_000)
    if next_sample is None:
        return start, 0
    gap = start - next_sample
    if gap < -1 or gap > 48000:
        fail("audio_timeline_discontinuity")
    return (next_sample, 0) if abs(gap) <= 1 else (start, gap)


def run(config, stream):
    import av
    import certifi
    import numpy as np
    av.logging.set_level(av.logging.PANIC)
    config = validate_config(config)
    codec = select_codec(av, np, config)
    synthetic = config.get("testOutput") is not None or config.get("testTransport") is not None
    if config.get("testOutput") is not None and config.get("testTransport") is not None:
        fail("invalid_test_transport")
    handle, relay = None, None
    if config.get("testOutput") is not None:
        target = test_path(config)
        handle = target.open("xb")
        output = av.open(handle, "w", format="flv")
    else:
        target, options = (fixture_transport(config) if config.get("testTransport") is not None
                           else network_target(config.get("destination"), ca_file=certifi.where()))
        # Do not allow proxy environment to redirect the pinned public transport.
        for key in list(os.environ):
            if key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
                os.environ.pop(key, None)
        relay = VerifiedTlsRelay(target, options)
        # No credential-bearing address is exposed in the local socket URL.
        mux_options = {key: value for key, value in options.items() if key not in {"tls_verify", "ca_file", "verifyhost"}}
        output = av.open(relay.local_url, "w", format="flv", options=mux_options, timeout=(10.0, 10.0))
    video = output.add_stream(codec, rate=config["fps"])
    configure_video(video, config, codec)
    audio = output.add_stream("aac", rate=48000)
    audio.layout, audio.bit_rate = "stereo", 192000
    audio.codec_context.time_base = Fraction(1, 48000)
    counts = {"videoFrames": 0, "audioSamples": 0, "audioSilenceSamples": 0, "packets": 0, "bytesMuxed": 0}
    next_audio_sample = None
    last = {ord("V"): -1, ord("A"): -1}
    last_report, active = 0.0, False
    try:
        output.start_encoding()
        emit("ready", state="starting", codec=codec, hardwareVerified=codec == "h264_nvenc", synthetic=synthetic, tlsVerified=bool(relay and relay.tls_verified), platformVerified=False)
        while True:
            kind, length, pts = HEADER.unpack(read_exact(stream, HEADER.size))
            if kind == ord("E") and length == 0:
                break
            if kind not in last or not 0 <= pts <= MAX_PTS or pts <= last[kind]:
                fail("invalid_encoder_packet")
            if ((kind == ord("V") and length != config["width"] * config["height"] * 4)
                    or (kind == ord("A") and (not 8 <= length <= MAX_AUDIO_BYTES or length % 8))):
                fail("invalid_encoder_packet")
            data = read_exact(stream, length)
            last[kind] = pts
            if kind == ord("V"):
                frame = av.VideoFrame.from_ndarray(np.frombuffer(data, np.uint8).reshape(config["height"], config["width"], 4), format="bgra")
                frame.pts, frame.time_base = pts, Fraction(1, 1_000_000)
                packets = video.encode(frame)
                counts["videoFrames"] += 1
            else:
                samples = np.frombuffer(data, dtype="<f4").reshape(-1, 2)
                if not np.isfinite(samples).all():
                    fail("invalid_audio_samples")
                samples = np.ascontiguousarray(np.clip(samples, -1, 1).T)
                start_sample, gap = audio_timing(pts, next_audio_sample)
                packets = []
                if gap:
                    silence = av.AudioFrame.from_ndarray(np.zeros((2, gap), dtype=np.float32), format="fltp", layout="stereo")
                    silence.sample_rate, silence.time_base, silence.pts = 48000, Fraction(1, 48000), next_audio_sample
                    packets.extend(audio.encode(silence))
                    counts["audioSilenceSamples"] += gap
                frame = av.AudioFrame.from_ndarray(samples, format="fltp", layout="stereo")
                frame.sample_rate, frame.time_base = 48000, Fraction(1, 48000)
                frame.pts = start_sample
                next_audio_sample = start_sample + frame.samples
                packets.extend(audio.encode(frame))
                counts["audioSamples"] += frame.samples
            for packet in packets:
                counts["bytesMuxed"] += packet.size
                output.mux(packet)
                counts["packets"] += 1
            if counts["packets"] and not active:
                active = True
                emit("active", state="active", **counts, platformVerified=False)
            now = time.monotonic()
            if now - last_report >= 1:
                emit("stats", state="active" if active else "starting", **counts, platformVerified=False)
                last_report = now
        for channel in (video, audio):
            for packet in channel.encode(None):
                counts["bytesMuxed"] += packet.size
                output.mux(packet)
                counts["packets"] += 1
        output.close()
        emit("stopped", state="stopped", **counts, platformVerified=False, synthetic=synthetic)
    except Exception:
        if relay and relay.error:
            fail(relay.error)
        raise
    finally:
        try:
            output.close()
        except Exception:
            pass
        if handle:
            handle.close()
        if relay:
            relay.close()


def main():
    # Suppress native FFmpeg errors too; they can contain private ingest addresses.
    with open(os.devnull, "w") as null:
        os.dup2(null.fileno(), 2)
    try:
        raw = sys.stdin.buffer.readline(MAX_CONFIG + 1)
        if len(raw) > MAX_CONFIG or not raw.endswith(b"\n"):
            fail("invalid_encoder_config")
        run(json.loads(raw), sys.stdin.buffer)
        return 0
    except EncoderError as error:
        emit("error", state="failed", code=str(error), platformVerified=False)
    except ModuleNotFoundError:
        emit("error", state="failed", code="encoder_dependency_missing", platformVerified=False)
    except Exception:
        emit("error", state="failed", code="encoder_failed", platformVerified=False)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
