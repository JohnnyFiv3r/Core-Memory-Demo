from __future__ import annotations

from functools import lru_cache
from typing import Any

import jwt
from fastapi import Header, HTTPException, Request, status

from app.core.config import settings


def auth_meta_payload() -> dict[str, Any]:
    return {
        "enabled": bool(settings.demo_auth_enabled),
        "domain": str(settings.demo_auth0_domain or "").strip(),
        "audience": str(settings.demo_auth0_audience or "").strip(),
        "client_id": str(settings.demo_auth0_client_id or "").strip(),
    }


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    issuer = str(settings.auth0_issuer or "").strip()
    if not issuer:
        raise RuntimeError("auth0_issuer_missing")
    return jwt.PyJWKClient(f"{issuer}.well-known/jwks.json")


def _extract_bearer(authorization: str | None) -> str:
    raw = str(authorization or "").strip()
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_authorization")
    parts = raw.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_authorization_header")
    return parts[1].strip()


def _validate_admin_claims(claims: dict[str, Any]) -> dict[str, Any]:
    email = str(claims.get("email") or "").strip().lower()
    if bool(settings.demo_auth_require_verified_email) and not bool(claims.get("email_verified")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="email_not_verified")

    allowlist = settings.admin_emails
    if not allowlist:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="admin_allowlist_empty")
    if not email or email not in allowlist:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_email_not_allowed")

    return {
        "sub": str(claims.get("sub") or ""),
        "email": email,
        "name": str(claims.get("name") or email or "admin"),
    }


def _decode_token(token: str) -> dict[str, Any]:
    issuer = str(settings.auth0_issuer or "").strip()
    audience = str(settings.demo_auth0_audience or "").strip()
    if not issuer or not audience or not str(settings.demo_auth0_domain or "").strip():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="auth0_not_configured")

    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            leeway=max(0, int(settings.demo_auth_jwt_leeway_seconds)),
        )
        return dict(claims or {})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid_token:{exc}")


async def require_admin(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not bool(settings.demo_auth_enabled):
        principal = {"sub": "dev-anon", "email": "", "name": "dev"}
        request.state.principal = principal
        return principal

    token = _extract_bearer(authorization)
    claims = _decode_token(token)
    principal = _validate_admin_claims(claims)
    request.state.principal = principal
    return principal
