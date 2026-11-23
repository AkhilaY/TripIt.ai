"""Plus subscriptions bought in the App Store.

The app buys with StoreKit 2 and sends the signed transaction here; Apple also sends App Store Server Notifications
(renewals, expiries, refunds) to /v1/appstore/notifications. Both arrive as JWS signed by Apple: the certificate chain
in the header must end at Apple Root CA - G3 (pinned by its SHA-256 fingerprint), each certificate must be signed by
the next, and the payload by the first. Only then is anything in it believed.

Each account has its own appAccountToken (a UUID made from its id), which the app attaches to the purchase, so a
subscription always belongs to the account that bought it.
"""
import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding

# Apple Root CA - G3 (https://www.apple.com/certificateauthority/), as listed on support.apple.com.
APPLE_ROOT_G3_SHA256 = "63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179"
# Marker extensions Apple puts on the App Store signing certificate and on its intermediate.
LEAF_OID = x509.ObjectIdentifier("1.2.840.113635.100.6.11.1")
INTERMEDIATE_OID = x509.ObjectIdentifier("1.2.840.113635.100.6.2.1")

# Subscription products in App Store Connect (one group, "Plus").
PLUS_PRODUCTS = ("plus.monthly", "plus.yearly")

_TOKEN_NAMESPACE = uuid.UUID("6f1c4d2e-8b0a-4d1b-9a57-2f0e6c3b9d41")


class AppStoreError(Exception):
    pass


def account_token(user_id: str) -> str:
    """The appAccountToken for an account: the same UUID every time, different for every account."""
    return str(uuid.uuid5(_TOKEN_NAMESPACE, user_id))


def _b64url(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _signed_by(cert: x509.Certificate, issuer: x509.Certificate) -> bool:
    key = issuer.public_key()
    if not isinstance(key, ec.EllipticCurvePublicKey) or cert.signature_hash_algorithm is None:
        return False
    try:
        key.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
        return True
    except InvalidSignature:
        return False


def _has(cert: x509.Certificate, oid: x509.ObjectIdentifier) -> bool:
    try:
        cert.extensions.get_extension_for_oid(oid)
        return True
    except x509.ExtensionNotFound:
        return False


def verify_jws(token: str, root_sha256: str = APPLE_ROOT_G3_SHA256) -> dict[str, Any]:
    """The payload of a JWS from the App Store, once its signature and certificate chain check out."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url(header_b64))
        chain = [x509.load_der_x509_certificate(base64.b64decode(c)) for c in header["x5c"]]
    except (ValueError, KeyError, TypeError) as e:
        raise AppStoreError("Not a signed App Store message") from e
    if header.get("alg") != "ES256" or len(chain) != 3:
        raise AppStoreError("Unexpected signature format")
    leaf, intermediate, root = chain
    if hashlib.sha256(root.public_bytes(Encoding.DER)).hexdigest() != root_sha256.lower():
        raise AppStoreError("Not signed by Apple")
    if not (_signed_by(root, root) and _signed_by(intermediate, root) and _signed_by(leaf, intermediate)):
        raise AppStoreError("Broken certificate chain")
    if not (_has(leaf, LEAF_OID) and _has(intermediate, INTERMEDIATE_OID)):
        raise AppStoreError("Not an App Store signing certificate")
    raw = _b64url(signature_b64)
    if len(raw) != 64:
        raise AppStoreError("Unexpected signature format")
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key = leaf.public_key()
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise AppStoreError("Unexpected key")
    try:
        key.verify(der, f"{header_b64}.{payload_b64}".encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as e:
        raise AppStoreError("Bad signature") from e
    return json.loads(_b64url(payload_b64))


def plus_until(tx: dict[str, Any], bundle_ids: list[str], now: Optional[datetime] = None) -> Optional[str]:
    """When Plus from this transaction ends (ISO, UTC), or None if it gives no Plus now (expired, refunded,
    another app's, or not a Plus product)."""
    now = now or datetime.now(timezone.utc)
    if bundle_ids and tx.get("bundleId") not in bundle_ids:
        raise AppStoreError("This purchase is for another app")
    if tx.get("productId") not in PLUS_PRODUCTS or tx.get("revocationDate"):
        return None
    expires_ms = tx.get("expiresDate")
    if not expires_ms:
        return None
    expires = datetime.fromtimestamp(expires_ms / 1000, timezone.utc)
    return expires.isoformat() if expires > now else None
