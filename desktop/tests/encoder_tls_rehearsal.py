"""Explicit localhost-only synthetic RTMPS rehearsal; never platform credentials."""
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import time
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

sys.path.insert(0, str(Path(__file__).parents[1]))
from encoder_worker import pump_streams


def certificates(root):
    now = datetime.now(timezone.utc)
    ca_key, server_key = (rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2))
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic local encoder fixture CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True).sign(ca_key, hashes.SHA256()))
    server = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
              .issuer_name(ca_name).public_key(server_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
              .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True, data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
              .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
              .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False).sign(ca_key, hashes.SHA256()))
    (root / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (root / "server.pem").write_bytes(server.public_bytes(serialization.Encoding.PEM))
    (root / "fixture-key.pem").write_bytes(server_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def run_case(root, *, hostname="localhost", case_name=None):
    ffmpeg = shutil.which("ffmpeg")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        plain_port = reservation.getsockname()[1]
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.listen(1)
    listener.settimeout(12)
    transport = {"accepted": False, "tlsEstablished": False}
    sockets = []
    def forward_tls():
        try:
            peer, _ = listener.accept()
            peer.settimeout(12)
            transport["accepted"] = True
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(root / "server.pem"), str(root / "fixture-key.pem"))
            secure = context.wrap_socket(peer, server_side=True)
            transport["tlsEstablished"] = True
            plain = socket.create_connection(("127.0.0.1", plain_port), timeout=12)
            sockets.extend([secure, plain])
            pump_streams(plain, secure, threading.Event())
        except (OSError, ssl.SSLError) as error:
            transport["handshakeRejected"] = True
            transport["failureClass"] = type(error).__name__
            transport["tlsReason"] = getattr(error, "reason", None)
        finally:
            for connection in sockets:
                connection.close()
    received = root / ((case_name + ".flv") if case_name else "received.flv" if hostname == "localhost" else "rejected-host.flv")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-listen", "1", "-timeout", "10",
               "-i", f"rtmp://127.0.0.1:{plain_port}/app/synthetic-fixture", "-map", "0", "-c", "copy", "-f", "flv", "-n", str(received)]
    receiver = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        time.sleep(.3)
        bridge = threading.Thread(target=forward_tls, daemon=True)
        bridge.start()
        env = {**os.environ, "PRODUCER_ENCODER_TEST_PORT": str(port), "PRODUCER_ENCODER_TEST_HOST": hostname}
        client = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("encoder-synthetic.cjs")), str(root)], env=env,
                                capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            _, errors = receiver.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            receiver.terminate()
            _, errors = receiver.communicate(timeout=3)
        result = {"clientExit": client.returncode, "receiverExit": receiver.returncode,
                  "receivedBytes": received.stat().st_size if received.exists() else 0,
                  "hostname": hostname, "transport": transport, "receiverError": errors.decode(errors="replace")[:2000]}
        if client.returncode == 0:
            result["client"] = json.loads(client.stdout.strip().splitlines()[-1])
        return result, received
    finally:
        listener.close()
        for connection in sockets:
            connection.close()
        if receiver.poll() is None:
            receiver.kill()
            receiver.wait(timeout=3)


def main():
    root = Path(sys.argv[1]).resolve()
    if os.name == "nt" and root.drive.lower() != "f:":
        raise SystemExit("Synthetic artifacts require F:")
    root.mkdir(parents=True, exist_ok=False)
    certificates(root)
    good, received = run_case(root)
    result = {"localOnly": True, "syntheticMedia": True, "validCertificate": good}
    if good["clientExit"] == 0 and good["receivedBytes"]:
        probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-count_frames", "-show_entries", "stream=codec_name,codec_type,width,height,sample_rate,channels,nb_read_frames", "-of", "json", str(received)], capture_output=True, text=True, check=True)
        result["probe"] = json.loads(probe.stdout)
        decode = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(received), "-f", "null", "-"], capture_output=True, check=False)
        result["decodeExit"] = decode.returncode
        wrong, _ = run_case(root, hostname="wrong-host.invalid")
        result["wrongHostname"] = wrong
        untrusted = root / "untrusted-ca"
        untrusted.mkdir()
        certificates(untrusted)
        (root / "ca.pem").write_bytes((untrusted / "ca.pem").read_bytes())
        rejected, _ = run_case(root, case_name="rejected-ca")
        result["wrongCertificateAuthority"] = rejected
    (root / "tls-results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    return 0 if result.get("decodeExit") == 0 and result.get("wrongHostname", {}).get("clientExit") != 0 and result.get("wrongCertificateAuthority", {}).get("clientExit") != 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
