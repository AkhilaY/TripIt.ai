#!/usr/bin/env python3
"""Signing for TestFlight uploads from GitHub Actions, with no Mac and nothing stored between runs.

Each run makes a fresh Apple Distribution certificate and App Store provisioning profiles through the
App Store Connect API, signs and uploads with them, then revokes them. Apps already uploaded to
TestFlight or the App Store keep working after their certificate is revoked.

  asc_signing.py setup    makes the certificate and profiles, installs them, writes settings to $GITHUB_ENV
  asc_signing.py cleanup  revokes the certificate and deletes the profiles from this run

Needs ASC_KEY_ID, ASC_ISSUER_ID and ASC_KEY_P8 (an App Store Connect API key with the Admin role,
which may create certificates), TRIPIT_BUNDLE_ID, and RUNNER_TEMP for its working files.
"""

import base64
import json
import os
import plistlib
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

API = "https://api.appstoreconnect.apple.com/v1"
WORK = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "asc-signing"
STATE = WORK / "state.json"
KEYCHAIN = "tripit-signing.keychain-db"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token() -> str:
    key = serialization.load_pem_private_key(os.environ["ASC_KEY_P8"].strip().replace("\\n", "\n").encode(), password=None)
    header = b64url(json.dumps({"alg": "ES256", "kid": os.environ["ASC_KEY_ID"].strip(), "typ": "JWT"}).encode())
    now = int(time.time())
    claims = b64url(json.dumps({"iss": os.environ["ASC_ISSUER_ID"].strip(), "iat": now, "exp": now + 15 * 60,
                                "aud": "appstoreconnect-v1"}).encode())
    r, s = decode_dss_signature(key.sign(f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{header}.{claims}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def call(method: str, path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None, headers={
        "Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read()
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            errors = json.loads(detail).get("errors", [])
            detail = "; ".join(f"{x.get('title')}: {x.get('detail')}" for x in errors) or detail
        except ValueError:
            pass
        raise SystemExit(f"App Store Connect said {e.code} to {method} {path}: {detail}")


def bundle_id(identifier: str) -> str:
    query = urllib.parse.urlencode({"filter[identifier]": identifier, "filter[platform]": "IOS", "limit": 200})
    for item in call("GET", f"/bundleIds?{query}")["data"]:
        if item["attributes"]["identifier"] == identifier:
            return item["id"]
    raise SystemExit(
        f"The bundle ID {identifier} isn't registered yet. In developer.apple.com → Certificates, IDs & Profiles → "
        "Identifiers, add it as an App ID with App Groups ticked (see the README's TestFlight steps).")


def enable_sign_in_with_apple(bundle: str) -> None:
    """Turns on Sign in with Apple for the app's ID (once; it stays on). Profiles made after include it."""
    caps = call("GET", f"/bundleIds/{bundle}/bundleIdCapabilities")["data"]
    if any(c["attributes"].get("capabilityType") == "APPLE_ID_AUTH" for c in caps):
        return
    call("POST", "/bundleIdCapabilities", {"data": {
        "type": "bundleIdCapabilities",
        "attributes": {"capabilityType": "APPLE_ID_AUTH",
                       "settings": [{"key": "APPLE_ID_AUTH_APP_CONSENT", "options": [{"key": "PRIMARY_APP_CONSENT"}]}]},
        "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bundle}}},
    }})
    print("Turned on Sign in with Apple for the app's ID")


def make_profile(name: str, bundle: str, certificate: str) -> dict:
    data = call("POST", "/profiles", {"data": {
        "type": "profiles",
        "attributes": {"name": name, "profileType": "IOS_APP_STORE"},
        "relationships": {
            "bundleId": {"data": {"type": "bundleIds", "id": bundle}},
            "certificates": {"data": [{"type": "certificates", "id": certificate}]},
        },
    }})["data"]
    content = base64.b64decode(data["attributes"]["profileContent"])
    uuid = data["attributes"]["uuid"]
    # The profile is a signed plist; read its entitlements from the embedded XML.
    start, end = content.find(b"<?xml"), content.rfind(b"</plist>")
    entitlements = plistlib.loads(content[start:end + len(b"</plist>")]).get("Entitlements", {}) if start >= 0 else {}
    for folder in (Path.home() / "Library/MobileDevice/Provisioning Profiles",
                   Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{uuid}.mobileprovision").write_bytes(content)
    return {"id": data["id"], "name": name, "uuid": uuid,
            "groups": list(entitlements.get("com.apple.security.application-groups", [])),
            "apple_sign_in": "com.apple.developer.applesignin" in entitlements}


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def setup() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    app_identifier = os.environ["TRIPIT_BUNDLE_ID"].strip()
    run_id = os.environ.get("GITHUB_RUN_ID", str(int(time.time())))
    # Look up the identifiers first, so a missing one fails before anything is made.
    app_bundle = bundle_id(app_identifier)
    share_bundle = bundle_id(app_identifier + ".share")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TripIt CI"),
                                    x509.NameAttribute(NameOID.EMAIL_ADDRESS, "ci@tripit.invalid")]))
           .sign(key, hashes.SHA256()))
    data = call("POST", "/certificates", {"data": {"type": "certificates", "attributes": {
        "certificateType": "DISTRIBUTION", "csrContent": csr.public_bytes(serialization.Encoding.PEM).decode()}}})["data"]
    state = {"certificate": data["id"], "profiles": []}
    STATE.write_text(json.dumps(state))
    certificate = x509.load_der_x509_certificate(base64.b64decode(data["attributes"]["certificateContent"]))

    # A temporary keychain holding the certificate and its key, for codesign. macOS's importer wants the
    # older PKCS#12 encryption.
    password = secrets.token_urlsafe(24)
    p12 = pkcs12.serialize_key_and_certificates(
        b"TripIt CI", key, certificate, None,
        serialization.PrivateFormat.PKCS12.encryption_builder()
        .kdf_rounds(50000).key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC).hmac_hash(hashes.SHA1())
        .build(password.encode()))
    (WORK / "signing.p12").write_bytes(p12)
    keychain_password = secrets.token_urlsafe(24)
    run("security", "create-keychain", "-p", keychain_password, KEYCHAIN)
    run("security", "set-keychain-settings", "-lut", "21600", KEYCHAIN)
    run("security", "unlock-keychain", "-p", keychain_password, KEYCHAIN)
    run("security", "import", str(WORK / "signing.p12"), "-k", KEYCHAIN, "-P", password, "-T", "/usr/bin/codesign", "-T", "/usr/bin/security")
    run("security", "set-key-partition-list", "-S", "apple-tool:,apple:", "-s", "-k", keychain_password, KEYCHAIN)
    existing = subprocess.run(["security", "list-keychains", "-d", "user"], capture_output=True, text=True).stdout.split()
    run("security", "list-keychains", "-d", "user", "-s", KEYCHAIN, *[k.strip('"') for k in existing])
    (WORK / "signing.p12").unlink()

    enable_sign_in_with_apple(app_bundle)
    app_profile = make_profile(f"TripIt CI {run_id}", app_bundle, state["certificate"])
    state["profiles"].append(app_profile["id"])
    STATE.write_text(json.dumps(state))
    share_profile = make_profile(f"TripIt Share CI {run_id}", share_bundle, state["certificate"])
    state["profiles"].append(share_profile["id"])
    STATE.write_text(json.dumps(state))

    if not app_profile["apple_sign_in"]:
        raise SystemExit(f"The App ID {app_identifier} doesn't have Sign in with Apple. In developer.apple.com → Identifiers, "
                         "open it, tick Sign In with Apple, and Save; then run this again.")

    # The app and its share extension share sign-in through an App Group. Use the one registered for them.
    print("App Groups in the profiles:", app_profile["groups"], share_profile["groups"])
    for profile, identifier in ((app_profile, app_identifier), (share_profile, app_identifier + ".share")):
        if not profile["groups"]:
            raise SystemExit(
                f"The App ID {identifier} has no App Group chosen. In developer.apple.com → Identifiers, open it, "
                "tick App Groups, click Configure, choose your group (e.g. group." + app_identifier + "), and Save.")
    shared = [g for g in app_profile["groups"] if g in share_profile["groups"]]
    if not shared:
        raise SystemExit(f"The app ({app_profile['groups']}) and the share extension ({share_profile['groups']}) "
                         "need the same App Group. Choose the same group for both App IDs in developer.apple.com.")
    group = f"group.{app_identifier}" if f"group.{app_identifier}" in shared else shared[0]

    env = os.environ.get("GITHUB_ENV")
    lines = [f"TRIPIT_APP_PROFILE={app_profile['name']}", f"TRIPIT_SHARE_PROFILE={share_profile['name']}",
             f"TRIPIT_APP_GROUP={group}"]
    if env:
        with open(env, "a") as f:
            f.write("\n".join(lines) + "\n")
    print("Signing ready:", ", ".join(lines))


def cleanup() -> None:
    if not STATE.exists():
        return
    state = json.loads(STATE.read_text())
    for profile in state.get("profiles", []):
        try:
            call("DELETE", f"/profiles/{profile}")
        except SystemExit as e:
            print(e)
    if state.get("certificate"):
        try:
            call("DELETE", f"/certificates/{state['certificate']}")
            print("Revoked this run's signing certificate")
        except SystemExit as e:
            print(e)
    subprocess.run(["security", "delete-keychain", KEYCHAIN])
    STATE.unlink()


if __name__ == "__main__":
    {"setup": setup, "cleanup": cleanup}[sys.argv[1]]()
