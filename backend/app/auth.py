"""Accounts: email + password sign-in, sessions, invite codes and personal keys for the share Shortcut.

Passwords are hashed with scrypt (standard library). Sessions, invite codes and keys are random strings of which
only a SHA-256 hash is stored, so a copy of the database can't be used to sign in. The web app keeps its session in
an HttpOnly cookie; the iOS app sends it as a Bearer token.

Before any account exists the server runs as before: the shared APP_API_KEY opens everything. The first account is
created with that key as its invite code; it becomes the admin and takes over all existing data. After that the key
still works (for the owner's Shortcut and phone) but only ever as the owner.
"""

import base64
import hashlib
import hmac
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import OWNED_TABLES, USER_SETTINGS, Database

SESSION_DAYS = 90
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(ValueError):
    pass


@dataclass
class User:
    id: str
    email: str
    name: str
    is_admin: bool
    created_at: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        expect = base64.b64decode(digest)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=2**14, r=8, p=1, dklen=len(expect))
        return hmac.compare_digest(got, expect)
    except (ValueError, TypeError):
        return False


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def clean_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def valid_password(password: str) -> None:
    if len(password) < 8:
        raise AuthError("Use at least 8 characters for your password")
    if len(password) > 200:
        raise AuthError("That password is too long")


class Accounts:
    def __init__(self, db: Database, app_api_key: str = "", open_signup: bool = False):
        self.db = db
        self.app_api_key = app_api_key
        self.open_signup = open_signup  # anyone can make an account; otherwise new accounts need an invite
        self._failures: dict[str, list[float]] = {}  # email -> recent failed sign-in times

    # ---------- Users ----------

    def _user(self, row) -> User:
        return User(id=row["id"], email=row["email"], name=row["name"], is_admin=bool(row["is_admin"]), created_at=row["created_at"])

    def get_user(self, user_id: str) -> Optional[User]:
        rows = self.db._rows("SELECT * FROM users WHERE id = ?", (user_id,))
        return self._user(rows[0]) if rows else None

    def by_email(self, email: str) -> Optional[User]:
        rows = self.db._rows("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
        return self._user(rows[0]) if rows else None

    def owner(self) -> Optional[User]:
        rows = self.db._rows("SELECT * FROM users WHERE is_admin = 1 ORDER BY created_at LIMIT 1")
        return self._user(rows[0]) if rows else None

    def list_users(self) -> list[User]:
        return [self._user(r) for r in self.db._rows("SELECT * FROM users ORDER BY created_at")]

    def sign_up(self, email: str, password: str, invite: str, name: str = "") -> User:
        email = email.strip().lower()
        if not EMAIL.match(email) or len(email) > 200:
            raise AuthError("Enter a valid email address")
        valid_password(password)
        if self.by_email(email):
            raise AuthError("There's already an account with that email. Sign in instead.")
        first = self.owner() is None
        invite_row = None
        if first:
            if not self.app_api_key or not hmac.compare_digest(invite.strip(), self.app_api_key):
                raise AuthError("The first account needs the server key as its invite code")
        elif invite.strip() or not self.open_signup:
            invite_row = self.db._rows("SELECT * FROM invites WHERE code_hash = ? AND used_by IS NULL", (_hash(clean_code(invite)),))
            if not invite_row:
                raise AuthError("That invite code isn't valid or has been used")
        user_id = uuid.uuid4().hex[:16]
        self.db._exec("INSERT INTO users (id, email, name, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                      (user_id, email, " ".join(name.split())[:80], hash_password(password), int(first), _now().isoformat()))
        if first:
            self._claim_existing(user_id)
        elif invite_row:
            self.db._exec("UPDATE invites SET used_by = ?, used_at = ? WHERE code_hash = ?",
                          (user_id, _now().isoformat(), _hash(clean_code(invite))))
        return self.get_user(user_id)

    # ---------- Sign in with Apple ----------

    def by_apple(self, sub: str) -> Optional[User]:
        rows = self.db._rows("SELECT * FROM users WHERE apple_sub = ?", (sub,))
        return self._user(rows[0]) if rows else None

    def apple_user(self, sub: str, email: Optional[str], email_verified: bool, name: str = "") -> tuple[User, bool]:
        """The account for an Apple ID: the one already linked, else the account with Apple's verified email (now
        linked), else a new one. Returns (user, created)."""
        user = self.by_apple(sub)
        if user:
            if name and not user.name:
                self.db._exec("UPDATE users SET name = ? WHERE id = ?", (" ".join(name.split())[:80], user.id))
                user = self.get_user(user.id)
            return user, False
        email = (email or "").strip().lower()
        existing = self.by_email(email) if email and email_verified else None
        if existing:
            self.db._exec("UPDATE users SET apple_sub = ? WHERE id = ?", (sub, existing.id))
            if name and not existing.name:
                self.db._exec("UPDATE users SET name = ? WHERE id = ?", (" ".join(name.split())[:80], existing.id))
            return self.get_user(existing.id), False
        if self.owner() is None:
            raise AuthError("Set up the first account with the server key before signing in with Apple")
        if not self.open_signup:
            raise AuthError("The Travel Edit is invite-only for now. Create an account with your invite code first.")
        user_id = uuid.uuid4().hex[:16]
        # Apple may hide the email (a private relay address), or not share one: the account still works without it.
        address = email if email and not self.by_email(email) else f"apple-{sub[:12].replace('.', '')}@users.traveledit.invalid"
        self.db._exec("INSERT INTO users (id, email, name, password_hash, is_admin, created_at, apple_sub) VALUES (?, ?, ?, '', 0, ?, ?)",
                      (user_id, address, " ".join(name.split())[:80], _now().isoformat(), sub))
        return self.get_user(user_id), True

    def set_apple_token(self, user: User, token: Optional[str]) -> None:
        self.db._exec("UPDATE users SET apple_token = ? WHERE id = ?", (token, user.id))

    def apple_token(self, user: User) -> Optional[str]:
        rows = self.db._rows("SELECT apple_token FROM users WHERE id = ?", (user.id,))
        return rows[0]["apple_token"] if rows else None

    def has_password(self, user: User) -> bool:
        rows = self.db._rows("SELECT password_hash FROM users WHERE id = ?", (user.id,))
        return bool(rows and rows[0]["password_hash"])

    def _claim_existing(self, user_id: str) -> None:
        """The owner's first account takes over everything saved before accounts existed."""
        for table in OWNED_TABLES:
            self.db._exec(f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (user_id,))
        for key in USER_SETTINGS:
            self.db._exec("UPDATE OR REPLACE settings SET key = ? WHERE key = ?", (f"{key}@{user_id}", key))

    def sign_in(self, email: str, password: str) -> User:
        key = email.strip().lower()
        recent = [t for t in self._failures.get(key, []) if time.time() - t < 600]
        if len(recent) >= 8:
            raise AuthError("Too many attempts. Wait a few minutes and try again.")
        user = self.by_email(key)
        rows = self.db._rows("SELECT password_hash FROM users WHERE email = ?", (key,)) if user else []
        if not rows or not check_password(password, rows[0]["password_hash"]):
            self._failures[key] = recent + [time.time()]
            raise AuthError("That email and password don't match")
        self._failures.pop(key, None)
        return user

    def set_name(self, user: User, name: str) -> User:
        self.db._exec("UPDATE users SET name = ? WHERE id = ?", (" ".join(name.split())[:80], user.id))
        return self.get_user(user.id)

    def change_password(self, user: User, current: str, new: str) -> None:
        rows = self.db._rows("SELECT password_hash FROM users WHERE id = ?", (user.id,))
        if not rows or not check_password(current, rows[0]["password_hash"]):
            raise AuthError("Your current password isn't right")
        valid_password(new)
        self.db._exec("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), user.id))

    def reset_password(self, user_id: str) -> str:
        """For the admin to pass on: a temporary password that signs the person in (they can change it after)."""
        temp = f"{new_code()}-{new_code()}"
        self.db._exec("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(temp), user_id))
        self.db._exec("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return temp

    def delete_user(self, user: User) -> None:
        """Removes the account and everything in it."""
        self.db._exec("DELETE FROM trips WHERE user_id = ?", (user.id,))
        self.db._exec("DELETE FROM places WHERE user_id = ?", (user.id,))
        for table in ("folders", "reels", "jobs", "push_subscriptions", "feedback"):
            self.db._exec(f"DELETE FROM {table} WHERE user_id = ?", (user.id,))
        self.db._exec("DELETE FROM settings WHERE key LIKE ?", (f"%@{user.id}",))
        self.db._exec("DELETE FROM users WHERE id = ?", (user.id,))

    # ---------- Sessions ----------

    def new_session(self, user: User, device: str = "") -> str:
        token = secrets.token_urlsafe(32)
        self.db._exec("INSERT INTO sessions (token_hash, user_id, device, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                      (_hash(token), user.id, device[:120], _now().isoformat(), (_now() + timedelta(days=SESSION_DAYS)).isoformat()))
        return token

    def session_user(self, token: str) -> Optional[User]:
        if not token:
            return None
        rows = self.db._rows("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (_hash(token),))
        if not rows or datetime.fromisoformat(rows[0]["expires_at"]) < _now():
            return None
        return self.get_user(rows[0]["user_id"])

    def end_session(self, token: str) -> None:
        self.db._exec("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))

    # ---------- Invites ----------

    def create_invite(self, admin: User, note: str = "") -> str:
        code = new_code()
        self.db._exec("INSERT INTO invites (code_hash, hint, note, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                      (_hash(clean_code(code)), code[-4:], " ".join(note.split())[:80], admin.id, _now().isoformat()))
        return code

    def list_invites(self) -> list[dict]:
        rows = self.db._rows("SELECT i.*, u.email AS used_email FROM invites i LEFT JOIN users u ON u.id = i.used_by ORDER BY i.created_at DESC")
        return [{"id": r["code_hash"][:16], "hint": r["hint"], "note": r["note"], "created_at": r["created_at"],
                 "used_by": r["used_email"], "used_at": r["used_at"]} for r in rows]

    def delete_invite(self, invite_id: str) -> None:
        self.db._exec("DELETE FROM invites WHERE substr(code_hash, 1, 16) = ? AND used_by IS NULL", (invite_id,))

    # ---------- Personal keys (for the iPhone share Shortcut) ----------

    def new_import_key(self, user: User) -> str:
        """A key that can only send links and screenshots to import. Making a new one turns the old one off."""
        token = "tpk_" + secrets.token_urlsafe(24)
        self.db._exec("DELETE FROM api_tokens WHERE user_id = ? AND scope = 'import'", (user.id,))
        self.db._exec("INSERT INTO api_tokens (token_hash, user_id, scope, created_at) VALUES (?, ?, 'import', ?)",
                      (_hash(token), user.id, _now().isoformat()))
        return token

    def has_import_key(self, user: User) -> bool:
        return bool(self.db._rows("SELECT 1 FROM api_tokens WHERE user_id = ? AND scope = 'import'", (user.id,)))

    def key_user(self, token: str) -> Optional[tuple[User, str]]:
        rows = self.db._rows("SELECT user_id, scope FROM api_tokens WHERE token_hash = ?", (_hash(token),))
        if not rows:
            return None
        self.db._exec("UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ?", (_now().isoformat(), _hash(token)))
        user = self.get_user(rows[0]["user_id"])
        return (user, rows[0]["scope"]) if user else None
