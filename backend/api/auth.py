"""
PowerSync auth: RS256 JWT + JWKS endpoint.

The web client calls POST /api/auth/token to get a token; PowerSync trusts
those tokens because its `client_auth.jwks_uri` points at GET /api/auth/keys.
"""
import base64
import logging
import os
import time
import uuid

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from fastapi import APIRouter, HTTPException

log = logging.getLogger("auth")
router = APIRouter()

# loaded once at startup by main.py via load_keys()
_private_key: RSAPrivateKey | None = None
_public_key: RSAPublicKey | None = None
_kid = os.environ.get("JWT_KID", "retail-key-1")
_alg = os.environ.get("JWT_ALGORITHM", "RS256")
_audience = os.environ.get("PS_JWT_AUDIENCE", "powersync")
_issuer = os.environ.get("PS_JWT_ISSUER", "retail-stock-take")
_token_ttl_seconds = int(os.environ.get("JWT_TTL_SECONDS", "3600"))


def load_keys() -> None:
    """Load PEM keys from disk; called once at startup."""
    global _private_key, _public_key

    priv_path = os.environ["JWT_PRIVATE_KEY_PATH"]
    pub_path = os.environ["JWT_PUBLIC_KEY_PATH"]

    with open(priv_path, "rb") as f:
        _private_key = serialization.load_pem_private_key(f.read(), password=None)
    with open(pub_path, "rb") as f:
        _public_key = serialization.load_pem_public_key(f.read())

    if not isinstance(_private_key, RSAPrivateKey) or not isinstance(_public_key, RSAPublicKey):
        raise RuntimeError("JWT keys must be RSA for RS256")

    log.info("loaded RS256 keypair: kid=%s alg=%s", _kid, _alg)


def _b64url_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@router.get("/api/auth/keys")
async def jwks():
    if _public_key is None:
        raise HTTPException(503, "keys not loaded")
    numbers = _public_key.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "alg": _alg,
                "use": "sig",
                "kid": _kid,
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }


@router.post("/api/auth/token")
async def issue_token():
    """
    Issue a short-lived JWT for the PowerSync client.

    Phase 1: anonymous demo — a stable demo operator user.
    Phase 2: this will read a real session/credentials and set per-user claims.
    """
    if _private_key is None:
        raise HTTPException(503, "keys not loaded")

    now = int(time.time())
    operator = os.environ.get("DEMO_OPERATOR", "demo-operator")

    payload = {
        "sub": operator,
        "iat": now,
        "exp": now + _token_ttl_seconds,
        "aud": _audience,
        "iss": _issuer,
        "jti": str(uuid.uuid4()),
    }

    token = jwt.encode(
        payload,
        _private_key,
        algorithm=_alg,
        headers={"kid": _kid, "alg": _alg, "typ": "JWT"},
    )

    return {
        "token": token,
        # Browser-facing PowerSync WebSocket URL, delivered at runtime so the
        # frontend image carries no environment-specific build-time config.
        "powersync_url": os.environ.get("POWERSYNC_PUBLIC_URL", "http://localhost:8080"),
        "user_id": operator,
        "expires_at": payload["exp"],
    }
