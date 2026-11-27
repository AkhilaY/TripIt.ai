"""Sign in with Apple.

The iPhone app sends the identity token Apple gave it. We check it ourselves: Apple's signature (RS256, against the
public keys Apple publishes), that it was issued by Apple for our app (the bundle ID), that it hasn't expired, and that
its nonce matches the one the app generated. The token's "sub" is the person's stable Apple ID for our app.

Apple also asks apps to revoke a person's tokens when they delete their account. That needs a Sign in with Apple key
(a .p8 from developer.apple.com): with one configured we exchange the app's one-time authorization code for a refresh
token when they sign in, and revoke it when they delete their account. Without one, sign-in still works.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from typing import Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

log = logging.getLogger(__name__)

ISSUER = "https://appleid.apple.com"
KEYS_URL = "https://appleid.apple.com/auth/keys"
TOKEN_URL = "https://appleid.apple.com/auth/token"
REVOKE_URL = "https://appleid.apple.com/auth/revoke"


class AppleError(Exception):
    pass


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class AppleSignIn:
    def __init__(self, client_ids: list[str], team_id: str = "", key_id: str = "", private_key: str = ""):
        self.client_ids = [c for c in client_ids if c]
        self.team_id, self.key_id = team_id, key_id
        self.private_key = private_key.replace("\\n", "\n").strip()
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._keys_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.client_ids)

    @property
    def can_revoke(self) -> bool:
        return bool(self.team_id and self.key_id and self.private_key and self.client_ids)

    async def _public_key(self, kid: str) -> rsa.RSAPublicKey:
        if kid not in self._keys or time.time() - self._keys_at > 86400:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(KEYS_URL)
            r.raise_for_status()
            keys = {}
            for k in r.json().get("keys", []):
                if k.get("kty") == "RSA":
                    numbers = rsa.RSAPublicNumbers(int.from_bytes(_b64(k["e"]), "big"), int.from_bytes(_b64(k["n"]), "big"))
                    keys[k["kid"]] = numbers.public_key()
            self._keys, self._keys_at = keys, time.time()
        if kid not in self._keys:
            raise AppleError("Unknown Apple signing key")
        return self._keys[kid]

    async def verify(self, identity_token: str, nonce: Optional[str] = None) -> dict:
        """The token's claims, once it's checked. Raises AppleError if anything doesn't hold."""
        if not self.enabled:
            raise AppleError("Sign in with Apple isn't set up on the server")
        try:
            head_b64, body_b64, sig_b64 = identity_token.split(".")
            header, claims = json.loads(_b64(head_b64)), json.loads(_b64(body_b64))
        except (ValueError, json.JSONDecodeError) as e:
            raise AppleError("That isn't an Apple sign-in token") from e
        if header.get("alg") != "RS256":
            raise AppleError("Unexpected token type")
        try:
            key = await self._public_key(header.get("kid", ""))
        except httpx.HTTPError as e:
            raise AppleError("Couldn't reach Apple to check the sign-in") from e
        try:
            key.verify(_b64(sig_b64), f"{head_b64}.{body_b64}".encode(), padding.PKCS1v15(), hashes.SHA256())
        except Exception as e:  # noqa: BLE001 - any failure means the signature isn't Apple's
            raise AppleError("The sign-in token's signature isn't valid") from e
        if claims.get("iss") != ISSUER or claims.get("aud") not in self.client_ids:
            raise AppleError("This sign-in token isn't for The Travel Edit")
        if int(claims.get("exp", 0)) < time.time() - 30:
            raise AppleError("The Apple sign-in expired. Try again.")
        if nonce is not None and claims.get("nonce") != hashlib.sha256(nonce.encode()).hexdigest():
            raise AppleError("The sign-in didn't match this request. Try again.")
        if not claims.get("sub"):
            raise AppleError("The sign-in token has no Apple ID")
        return claims

    def _client_secret(self, client_id: str) -> str:
        """A short-lived ES256 token proving we're the app (Apple's 'client secret')."""
        key = serialization.load_pem_private_key(self.private_key.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise AppleError("The Sign in with Apple key isn't an Apple .p8 key")
        now = int(time.time())
        header = _b64url(json.dumps({"alg": "ES256", "kid": self.key_id}).encode())
        body = _b64url(json.dumps({"iss": self.team_id, "iat": now, "exp": now + 300, "aud": ISSUER, "sub": client_id}).encode())
        der = key.sign(f"{header}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return f"{header}.{body}.{_b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"

    async def refresh_token(self, code: str, client_id: str) -> Optional[str]:
        """Swaps the app's one-time authorization code for a refresh token (kept only to revoke it later)."""
        if not self.can_revoke or not code:
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(TOKEN_URL, data={"client_id": client_id, "client_secret": self._client_secret(client_id),
                                                       "code": code, "grant_type": "authorization_code"})
            return r.json().get("refresh_token") if r.status_code == 200 else None
        except (httpx.HTTPError, AppleError, ValueError) as e:
            log.warning("Couldn't exchange the Apple authorization code: %s", e)
            return None

    async def revoke(self, token: str, client_id: str) -> bool:
        if not self.can_revoke or not token:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(REVOKE_URL, data={"client_id": client_id, "client_secret": self._client_secret(client_id),
                                                        "token": token, "token_type_hint": "refresh_token"})
            return r.status_code == 200
        except (httpx.HTTPError, AppleError) as e:
            log.warning("Couldn't revoke the Apple token: %s", e)
            return False
