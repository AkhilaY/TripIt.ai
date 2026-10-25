"""Sign in with Apple: the token check, with a local key standing in for Apple's."""

import asyncio
import base64
import hashlib
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from app.apple import AppleError, AppleSignIn


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token(key, claims, kid="k1"):
    head = b64(json.dumps({"alg": "RS256", "kid": kid}).encode())
    body = b64(json.dumps(claims).encode())
    sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64(sig)}"


@pytest.fixture
def apple():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    a = AppleSignIn(["com.example.travel"])
    a._keys, a._keys_at = {"k1": key.public_key()}, time.time()
    return a, key


def claims(**kw):
    return {"iss": "https://appleid.apple.com", "aud": "com.example.travel", "sub": "001.abc", "exp": int(time.time()) + 600,
            "nonce": hashlib.sha256(b"n0nce").hexdigest(), **kw}


def test_a_genuine_token_passes(apple):
    a, key = apple
    out = asyncio.run(a.verify(token(key, claims(email="x@y.com")), nonce="n0nce"))
    assert out["sub"] == "001.abc" and out["email"] == "x@y.com"


@pytest.mark.parametrize("bad", [{"aud": "com.someone.else"}, {"iss": "https://evil.example"}, {"exp": int(time.time()) - 3600}])
def test_tokens_for_other_apps_or_expired_fail(apple, bad):
    a, key = apple
    with pytest.raises(AppleError):
        asyncio.run(a.verify(token(key, claims(**bad)), nonce="n0nce"))


def test_a_wrong_nonce_or_forged_signature_fails(apple):
    a, key = apple
    with pytest.raises(AppleError):
        asyncio.run(a.verify(token(key, claims()), nonce="other"))
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AppleError):
        asyncio.run(a.verify(token(other, claims()), nonce="n0nce"))
    head, body, sig = token(key, claims()).split(".")
    tampered = b64(json.dumps(claims(sub="001.someone-else")).encode())
    with pytest.raises(AppleError):
        asyncio.run(a.verify(f"{head}.{tampered}.{sig}", nonce="n0nce"))


def test_client_secret_is_an_es256_token_apple_can_check():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    a = AppleSignIn(["com.example.travel"], team_id="TEAM123", key_id="KEY456", private_key=pem.replace("\n", "\\n"))
    head, body, sig = a._client_secret("com.example.travel").split(".")
    pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    assert json.loads(pad(head)) == {"alg": "ES256", "kid": "KEY456"}
    assert json.loads(pad(body))["iss"] == "TEAM123" and json.loads(pad(body))["sub"] == "com.example.travel"
    raw = pad(sig)
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if wrong
