from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from jwt import InvalidTokenError

from delamain_backend.config import AuthConfig


class AuthError(Exception):
    code = "AUTH_REQUIRED"


@dataclass(frozen=True)
class AuthIdentity:
    email: str
    subject: str


class CloudflareAccessValidator:
    def __init__(self, config: AuthConfig, *, jwks_ttl_seconds: int = 3600):
        self.config = config
        self.jwks_ttl_seconds = jwks_ttl_seconds
        self._jwks: dict[str, Any] | None = None
        self._jwks_expires_at = 0.0

    def validate(self, token: str) -> AuthIdentity:
        self._ensure_configured()
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise AuthError("Missing JWT key id")
        key = self._key_for_kid(str(kid))
        payload = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=self.config.cloudflare_access_audience,
            issuer=self.config.issuer,
        )
        email = str(payload.get("email") or "")
        if not email:
            raise AuthError("Cloudflare Access JWT did not include an email")
        if email.lower() != self.config.allowed_email.lower():
            raise AuthError("Cloudflare Access user is not allowed")
        return AuthIdentity(email=email, subject=str(payload.get("sub") or ""))

    def _ensure_configured(self) -> None:
        if not self.config.allowed_email:
            raise AuthError("Auth allowed email is not configured")
        if not self.config.issuer:
            raise AuthError("Cloudflare Access team domain is not configured")
        if not self.config.cloudflare_access_audience:
            raise AuthError("Cloudflare Access audience is not configured")
        if not self.config.jwks_url:
            raise AuthError("Cloudflare Access JWKS URL is not configured")

    def _key_for_kid(self, kid: str) -> Any:
        jwks = self._get_jwks()
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
        self._jwks = None
        jwks = self._get_jwks()
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
        raise AuthError("Cloudflare Access signing key was not found")

    def _get_jwks(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._jwks is not None and now < self._jwks_expires_at:
            return self._jwks
        try:
            with urllib.request.urlopen(self.config.jwks_url, timeout=10) as response:
                loaded = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise AuthError("Cloudflare Access JWKS could not be loaded") from exc
        if not isinstance(loaded, dict) or not isinstance(loaded.get("keys"), list):
            raise AuthError("Cloudflare Access JWKS response is invalid")
        self._jwks = loaded
        self._jwks_expires_at = now + self.jwks_ttl_seconds
        return loaded


def install_auth_middleware(app, validator: CloudflareAccessValidator) -> None:
    @app.middleware("http")
    async def cloudflare_access_auth(request: Request, call_next):
        config = request.app.state.config.auth
        if config.mode == "dev_local":
            return await call_next(request)
        if config.mode != "access_required":
            return JSONResponse(
                status_code=500,
                content={"detail": {"code": "CONFIG_ERROR", "message": "Invalid auth mode"}},
            )
        token = request.headers.get("cf-access-jwt-assertion")
        if not token:
            return _auth_response("Missing Cloudflare Access JWT", request)
        try:
            identity = validator.validate(token)
        except (AuthError, InvalidTokenError) as exc:
            return _auth_response(str(exc), request)
        request.state.auth_identity = identity
        return await call_next(request)


def _auth_response(message: str, request: Request) -> JSONResponse:
    issuer = request.app.state.config.auth.issuer
    redirect_url = None
    if issuer:
        redirect_url = f"{issuer}/cdn-cgi/access/login?redirect_url={quote(str(request.url), safe='')}"
    return JSONResponse(
        status_code=401,
        content={
            "detail": {
                "code": "auth_required",
                "message": message,
                "redirect_url": redirect_url,
            }
        },
    )
