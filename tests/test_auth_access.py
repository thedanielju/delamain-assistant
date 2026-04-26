from __future__ import annotations

import json
import time
from dataclasses import replace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from delamain_backend.config import AuthConfig
from delamain_backend.main import create_app


def test_access_required_rejects_missing_cloudflare_jwt(test_config, tmp_path):
    app = create_app(_access_config(test_config, tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 401
        detail = response.json()["detail"]
        assert detail["code"] == "auth_required"
        assert detail["redirect_url"].startswith(
            "https://danielju.cloudflareaccess.com/cdn-cgi/access/login"
        )


def test_access_required_accepts_valid_cloudflare_jwt(test_config, tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    jwks_path = tmp_path / "jwks.json"
    jwks_path.write_text(json.dumps({"keys": [public_jwk]}), encoding="utf-8")
    config = _access_config(test_config, tmp_path, jwks_url=jwks_path.as_uri())
    token = jwt.encode(
        {
            "aud": config.auth.cloudflare_access_audience,
            "email": config.auth.allowed_email,
            "iss": config.auth.issuer,
            "sub": "daniel",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    app = create_app(config)
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"Cf-Access-Jwt-Assertion": token})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_access_required_returns_auth_response_when_jwks_fetch_fails(
    test_config, tmp_path, monkeypatch
):
    def fail_urlopen(*args, **kwargs):
        raise OSError("jwks unavailable")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    app = create_app(_access_config(test_config, tmp_path, jwks_url="https://example.test/jwks"))
    token = jwt.encode({"sub": "daniel"}, "secret", algorithm="HS256", headers={"kid": "test-key"})
    with TestClient(app) as client:
        response = client.get(
            "/api/health",
            headers={"Cf-Access-Jwt-Assertion": token},
        )
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "auth_required"


def _access_config(test_config, tmp_path, jwks_url: str | None = None):
    if jwks_url is None:
        jwks_path = tmp_path / "jwks.json"
        jwks_path.write_text(json.dumps({"keys": []}), encoding="utf-8")
        jwks_url = jwks_path.as_uri()
    return replace(
        test_config,
        auth=AuthConfig(
            mode="access_required",
            allowed_email="daniel@example.test",
            cloudflare_access_team_domain="https://danielju.cloudflareaccess.com",
            cloudflare_access_audience="test-audience",
            cloudflare_access_jwks_url=jwks_url,
        ),
    )
