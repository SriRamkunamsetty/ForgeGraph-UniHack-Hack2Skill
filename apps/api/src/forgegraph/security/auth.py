from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException
from forgegraph.core.settings import Settings


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    scopes: frozenset[str]


def authenticate(
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
    settings: Settings | None = None,
) -> Principal:
    runtime_settings = settings
    if runtime_settings is None:
        from forgegraph.core.settings import get_settings

        runtime_settings = get_settings()
    if not runtime_settings.auth_enabled:
        return Principal(
            subject="local", tenant_id=(x_tenant_id or "local"), scopes=frozenset({"*"})
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer authentication is required.")
    if not runtime_settings.jwt_jwks_url or not runtime_settings.jwt_issuer:
        raise HTTPException(status_code=503, detail="OIDC authentication is not configured.")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        jwt = importlib.import_module("jwt")

        key = jwt.PyJWKClient(runtime_settings.jwt_jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            issuer=runtime_settings.jwt_issuer,
            audience=runtime_settings.jwt_audience,
            options={"require": ["sub", "iss"]},
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid access token.") from exc
    subject = str(claims["sub"])
    tenant_id = str(claims.get("tenant_id") or claims.get("org_id") or x_tenant_id or "")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Token does not identify a tenant.")
    raw_scopes = claims.get("scope", "")
    scopes = frozenset(str(raw_scopes).split())
    return Principal(subject=subject, tenant_id=tenant_id, scopes=scopes)
