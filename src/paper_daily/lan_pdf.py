"""Authenticated read-only PDF chunks for peers enrolled in the same private Drive folder."""

import base64
import hashlib
import ipaddress
import os
import secrets
import socket
import sqlite3
import ssl
import struct
import tempfile
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.x509.oid import NameOID

from paper_daily.drive_sync_files import FILES, MAX_INLINE
from paper_daily.file_change import version

LEASE = 300
PRIVATE = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
REQUEST = struct.Struct("!32sII32s")
PREFIX = b"Paperfact PDF LAN v1\x00"


def home_interface():
    from PySide6.QtNetwork import QNetworkInterface

    physical = (QNetworkInterface.InterfaceType.Wifi, QNetworkInterface.InterfaceType.Ethernet)
    for interface in sorted(QNetworkInterface.allInterfaces(),
                            key=lambda item: item.type() not in physical):
        if not interface.flags() & QNetworkInterface.InterfaceFlag.IsRunning:
            continue
        for entry in interface.addressEntries():
            addr = entry.ip().toString()
            if ":" in addr or entry.prefixLength() <= 0:
                continue
            local = ipaddress.ip_interface(f"{addr}/{entry.prefixLength()}")
            if any(local.ip in block for block in PRIVATE):
                return local
    return None


def exact(stream, length):
    result = bytearray()
    deadline = time.monotonic() + 5
    while len(result) < length:
        if time.monotonic() >= deadline:
            raise TimeoutError("LAN transfer deadline reached")
        piece = stream.recv(min(65536, length - len(result)))
        if not piece:
            raise EOFError()
        result.extend(piece)
    return bytes(result)


def server_context(key):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Paperfact LAN")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=30))
            .sign(key, None))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    with tempfile.TemporaryDirectory() as tmp:
        pem = Path(tmp) / "identity.pem"
        with pem.open("xb") as output:
            output.write(cert.public_bytes(serialization.Encoding.PEM))
            output.write(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        context.load_cert_chain(str(pem))
    return context


class LanPdf:
    def __init__(self, interface):
        self.interface = interface
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes_raw()
        self.tls = server_context(self.key)
        self.socket = socket.socket()
        try:
            self.socket.bind((str(interface.ip), 0))
            self.socket.listen(4)
            self.socket.settimeout(1)
        except OSError:
            self.socket.close()
            raise
        self.port = self.socket.getsockname()[1]
        self.peers = {}
        self.offers = {}
        self.lease = time.monotonic() + LEASE
        self.updated = self.published = 0
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True, name="Paperfact LAN PDF")
        self.thread.start()

    def close(self):
        self.closed.set()
        self.socket.close()
        self.peers = {}
        self.offers.clear()

    def refresh(self, directory, store):
        if time.monotonic() - self.updated < 20 and self.updated:
            return
        self.updated = time.monotonic()
        files = directory.files
        label = "pfl1_" + store.context[:16]
        url = FILES + "/" + directory.folder
        files.owned(directory.folder, directory.key, "directory")
        fields = {"fields": "properties,shared,ownedByMe,trashed"}
        now = int(time.time())
        if self.updated - self.published >= 90 or not self.published:
            key = base64.urlsafe_b64encode(self.public).decode().rstrip("=")
            value = f"{self.interface.ip},{self.port},{key},{now + LEASE}"
            reply = files.request("PATCH", url, params=fields, json={"properties": {label: value}})
            self.published = self.updated
        else:
            reply = files.request("GET", url, params=fields)
        record = files.json(reply)
        if record.get("shared") is not False or record.get("ownedByMe") is not True or record.get(
                "trashed") is not False:
            raise PermissionError("Private Drive library required for LAN")
        peers = {}
        for name, text in record.get("properties", {}).items():
            if not name.startswith("pfl1_") or name == label:
                continue
            try:
                host, port, value, expiry = text.split(",")
                ip = ipaddress.IPv4Address(host)
                public = base64.b64decode(value + "=", altchars=b"-_", validate=True)
                if (len(public) == 32 and ip in self.interface.network
                        and any(ip in block for block in PRIVATE)
                        and 0 < int(port) <= 65535 and now < int(expiry) <= now + LEASE + 60):
                    peers[public] = (str(ip), int(port), int(expiry))
            except (TypeError, ValueError, AttributeError):
                continue
        self.peers = peers
        self.lease = time.monotonic() + LEASE

    def _serve(self):
        while not self.closed.is_set():
            if self.lease <= time.monotonic():
                self.close()
                return
            try:
                client, addr = self.socket.accept()
                with client:
                    if ipaddress.ip_address(addr[0]) not in self.interface.network:
                        continue
                    client.settimeout(2)
                    with self.tls.wrap_socket(client, server_side=True) as stream:
                        self._respond(stream)
            except (OSError, EOFError, ValueError, RuntimeError, InvalidSignature, sqlite3.Error):
                continue

    def _respond(self, stream):
        challenge = secrets.token_bytes(32)
        stream.sendall(challenge)
        client = exact(stream, 32)
        signature = exact(stream, 64)
        request = exact(stream, REQUEST.size)
        peer = self.peers.get(client)
        if not peer or peer[2] <= time.time() or self.lease <= time.monotonic():
            return
        Ed25519PublicKey.from_public_bytes(client).verify(
            signature, PREFIX + self.public + challenge + request)
        digest, offset, length, checksum = REQUEST.unpack(request)
        offer = self.offers.get(digest.hex())
        if not offer or length == 0 or length > MAX_INLINE or offset % MAX_INLINE:
            return
        path, stamp, allowed = offer
        if not allowed() or version(path) != stamp:
            return
        from paper_daily.document_reader import _owned_path

        with _owned_path(path).open("rb") as source:
            if os.fstat(source.fileno()).st_nlink != 1:
                return
            source.seek(offset)
            raw = source.read(length)
        if (len(raw) == length and hashlib.sha256(raw).digest() == checksum
                and version(path) == stamp and not self.closed.is_set() and allowed()):
            stream.sendall(b"1" + raw)

    def fetch(self, digest, offset, ref):
        if self.lease <= time.monotonic() or self.closed.is_set():
            return None
        request = REQUEST.pack(bytes.fromhex(digest), offset, ref["size"],
                               bytes.fromhex(ref["sha256"]))
        for public, (ip, port, expiry) in tuple(self.peers.items()):
            if expiry <= time.time():
                continue
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.minimum_version = ssl.TLSVersion.TLSv1_3
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE  # Pin the enrolled public key below.
                with socket.create_connection((ip, port), timeout=0.45) as sock:
                    sock.settimeout(2)
                    with context.wrap_socket(sock) as stream:
                        cert = x509.load_der_x509_certificate(stream.getpeercert(binary_form=True))
                        key = cert.public_key()
                        if (not isinstance(key, Ed25519PublicKey)
                                or key.public_bytes_raw() != public):
                            continue
                        challenge = exact(stream, 32)
                        sig = self.key.sign(PREFIX + public + challenge + request)
                        stream.sendall(self.public + sig + request)
                        if exact(stream, 1) == b"1":
                            raw = exact(stream, ref["size"])
                            if hashlib.sha256(raw).hexdigest() == ref["sha256"]:
                                return raw
            except EOFError:
                continue
            except (OSError, ValueError):
                # Unreachable peers should not delay every chunk in this pass.
                self.peers.pop(public, None)
        return None


def offer_pdf(lan, store, list_id, revision, grant, local, path, digest):
    stamp = version(path)

    def allowed():
        if store.pdf_grant(list_id, revision) != grant:
            return False
        with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=ro", uri=True,
                                     timeout=0.2)) as conn:
            return bool(conn.execute("SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?",
                                     (list_id, local)).fetchone())

    lan.offers[digest] = (path, stamp, allowed)
