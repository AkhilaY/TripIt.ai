"""Web Push notifications ("3 places saved to New York") for the installed web app.

Implements message encryption (RFC 8291, aes128gcm) and VAPID sender identification (RFC 8292)
directly on `cryptography`. The VAPID key pair is created on first start and kept next to the database,
so subscriptions survive redeploys. iPhones get notifications once TripIt is on the Home Screen.

The native iOS app registers its device token instead (stored as an "apns:<environment>:<token>" subscription)
and gets notifications through Apple's push service, signed with the team's .p8 key (token-based auth).
"""

import asyncio
import base64
import json
import logging
import os
import struct
import time
from dataclasses import dataclass
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


APNS_HOSTS = {"production": "https://api.push.apple.com", "sandbox": "https://api.sandbox.push.apple.com"}


@dataclass
class ApnsConfig:
    key_pem: str  # the .p8 file's contents
    key_id: str
    team_id: str
    topic: str  # the app's bundle ID

    @classmethod
    def from_settings(cls, settings) -> Optional["ApnsConfig"]:
        values = (settings.apns_key, settings.apns_key_id, settings.apns_team_id, settings.apns_topic)
        if not all(v.strip() for v in values):
            return None
        pem = settings.apns_key.strip().replace("\\n", "\n")  # a key pasted into one line of a secret
        return cls(pem, settings.apns_key_id.strip(), settings.apns_team_id.strip(), settings.apns_topic.strip())


def apns_endpoint(token: str, environment: str) -> str:
    return f"apns:{environment}:{token}"


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
    def __init__(self, db: Database, key_path: Path, contact: str = "", client: Optional[httpx.AsyncClient] = None,
                 apns: Optional[ApnsConfig] = None, apns_client: Optional[httpx.AsyncClient] = None):
        self.db = db
        self.contact = contact
        self.client = client or httpx.AsyncClient(timeout=15)
        self.apns = apns
        self.apns_key = serialization.load_pem_private_key(apns.key_pem.encode(), password=None) if apns else None
        self._apns_client = apns_client
        self._apns_token: tuple[float, str] = (0.0, "")
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

    def subscribe_apns(self, token: str, environment: str) -> None:
        token = token.strip().lower()
        if environment not in APNS_HOSTS or not (32 <= len(token) <= 200) or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Invalid device token")
        for env in APNS_HOSTS:  # one row per device, whichever build registered it last
            self.db.delete_push_subscription(apns_endpoint(token, env))
        self.db.save_push_subscription(apns_endpoint(token, environment), {}, "ios")

    def unsubscribe_apns(self, token: str) -> None:
        for env in APNS_HOSTS:
            self.db.delete_push_subscription(apns_endpoint(token.strip().lower(), env))

    def _apns_jwt(self) -> str:
        """Apple wants a fresh provider token at most hourly and no more than every 20 minutes: reuse for 40."""
        made, token = self._apns_token
        if token and time.time() - made < 40 * 60:
            return token
        header = b64url(json.dumps({"alg": "ES256", "kid": self.apns.key_id}, separators=(",", ":")).encode())
        claims = b64url(json.dumps({"iss": self.apns.team_id, "iat": int(time.time())}, separators=(",", ":")).encode())
        r, s = decode_dss_signature(self.apns_key.sign(f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
        token = f"{header}.{claims}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        self._apns_token = (time.time(), token)
        return token

    async def send_apns(self, endpoint: str, message: dict) -> bool:
        _, environment, token = endpoint.split(":", 2)
        if not self.apns or environment not in APNS_HOSTS:
            return False
        if self._apns_client is None:
            self._apns_client = httpx.AsyncClient(http2=True, timeout=15)
        alert = {"title": message.get("title", "The Travel Edit"), "body": message.get("body", "")}
        aps: dict = {"alert": alert, "sound": "default"}
        if message.get("tag"):
            aps["thread-id"] = str(message["tag"])
        try:
            response = await self._apns_client.post(f"{APNS_HOSTS[environment]}/3/device/{token}", json={"aps": aps, "url": message.get("url", "/")}, headers={
                "authorization": f"bearer {self._apns_jwt()}",
                "apns-topic": self.apns.topic,
                "apns-push-type": "alert",
                "apns-priority": "10",
            })
        except httpx.HTTPError as e:
            log.warning("APNs push failed: %s", e)
            return False
        if response.status_code == 410 or (response.status_code == 400 and "BadDeviceToken" in response.text):
            self.db.delete_push_subscription(endpoint)
            return False
        if response.status_code >= 400:
            log.warning("APNs answered %s: %s", response.status_code, response.text[:200])
            return False
        return True

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
        if endpoint.startswith("apns:"):
            return await self.send_apns(endpoint, message)
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
