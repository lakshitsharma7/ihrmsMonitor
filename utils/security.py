"""Security helpers for password hashing and verification."""

from __future__ import annotations

import hashlib
import secrets


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2 with SHA-256 and a random salt."""
    salt = secrets.token_hex(16)
    iterations = 100_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a PBKDF2 hash."""
    try:
        method, iterations_str, salt, hash_hex = hashed.split("$")
        if method != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return secrets.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False
