"""Web Push notifications ("3 places saved to New York") for the installed web app.

Implements message encryption (RFC 8291, aes128gcm) and VAPID sender identification (RFC 8292)
directly on `cryptography`. The VAPID key pair is created on first start and kept next to the database,
so subscriptions survive redeploys. iPhones get notifications once TripIt is on the Home Screen.
"""

import asyncio
import base64
import json
import logging
import os
import struct
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .db import Database

log = logging.getLogger(__name__)

# Push services browsers use. Subscriptions pointing anywhere else are refused, so the server can't be
# made to POST to arbitrary URLs.
PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com", "notify.windows.com",
              "push.services.mozilla.com", "android.googleapis.com")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, ua_public: bytes, auth_secret: bytes,
            sender_key: Optional[ec.EllipticCurvePrivateKey] = None, salt: Optional[bytes] = None) -> bytes:
    """Encrypts a push message body for one subscription (RFC 8291 §3.4, single aes128gcm record)."""
    sender_key = sender_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = sender_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = sender_key.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # 0x02 marks the last (only) record
    return salt + struct.pack("!IB", 4096, len(as_public)) + as_public + ciphertext


class Push:
    def __init__(self, db: Database, key_path: Path, contact: str = "", client: Optional[httpx.AsyncClient] = None):
        self.db = db
        self.contact = contact
        self.client = client or httpx.AsyncClient(timeout=15)
        self.key = self._load_key(key_path)
        raw = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.public_key = b64url(raw)  # the web app's applicationServerKey

    @staticmethod
    def _load_key(path: Path) -> ec.EllipticCurvePrivateKey:
        if path.exists():
            return serialization.load_pem_private_key(path.read_bytes(), password=None)
        key = ec.generate_private_key(ec.SECP256R1())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        path.chmod(0o600)
        return key

    @staticmethod
    def valid_endpoint(endpoint: str) -> bool:
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)

    def subscribe(self, endpoint: str, p256dh: str, auth: str, origin: str) -> None:
        if not self.valid_endpoint(endpoint):
            raise ValueError("Unsupported push service")
        try:
            if len(unb64url(p256dh)) != 65 or len(unb64url(auth)) != 16:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("Invalid subscription keys")
        self.db.save_push_subscription(endpoint, {"p256dh": p256dh, "auth": auth}, origin)

    def _vapid_header(self, endpoint: str, contact: str) -> str:
        parsed = urlparse(endpoint)
        header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        claims = b64url(json.dumps({"aud": f"{parsed.scheme}://{parsed.netloc}", "exp": int(time.time()) + 12 * 3600,
                                    "sub": contact}, separators=(",", ":")).encode())
        r, s = decode_dss_signature(self.key.sign(f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
        token = f"{header}.{claims}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        return f"vapid t={token}, k={self.public_key}"

    async def send(self, subscription: dict, message: dict) -> bool:
        """Sends one notification; forgets the subscription if the push service says it's gone."""
        endpoint = subscription["endpoint"]
        if not self.valid_endpoint(endpoint):
            return False
        keys = subscription["keys"]
        body = encrypt(json.dumps(message).encode(), unb64url(keys["p256dh"]), unb64url(keys["auth"]))
        # Apple requires a mailto: or https: contact; default to the app's own address.
        contact = self.contact or subscription.get("origin") or "mailto:tripit@localhost"
        if not contact.startswith(("mailto:", "https:")):
            contact = "mailto:tripit@localhost"
        try:
            response = await self.client.post(endpoint, content=body, headers={
                "Authorization": self._vapid_header(endpoint, contact),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": "86400",
                "Urgency": "normal",
            })
        except httpx.HTTPError as e:
            log.warning("Push to %s failed: %s", urlparse(endpoint).hostname, e)
            return False
        if response.status_code in (404, 410):
            self.db.delete_push_subscription(endpoint)
            return False
        if response.status_code >= 400:
            log.warning("Push service %s answered %s: %s", urlparse(endpoint).hostname, response.status_code, response.text[:200])
            return False
        return True

    async def send_all(self, message: dict) -> int:
        subs = self.db.push_subscriptions()
        results = await asyncio.gather(*(self.send(s, message) for s in subs))
        return sum(results)
