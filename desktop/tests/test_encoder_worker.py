"""Pure encoder protocol/policy checks. No network or physical media."""
import importlib.util
from pathlib import Path
import socket
import os
import subprocess
import sys

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
