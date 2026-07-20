"""Unit tests for thin harness auth ([4.2], issue #24)."""

import pytest
from flask import Flask, jsonify

from mas.core.harness_auth import (
    AllowAllAuthorizer,
    Authorizer,
    K8sTokenReviewAuthenticator,
    Principal,
    StaticBearerAuthenticator,
)
from inbound.flask.harness_auth_mw import install_harness_auth


# ── authenticators ───────────────────────────────────────────────────

@pytest.mark.unit
def test_static_bearer_accepts_and_rejects():
    auth = StaticBearerAuthenticator("s3cret", subject="svc")
    ok = auth.authenticate("s3cret")
    assert ok is not None and ok.subject == "svc" and ok.method == "bearer"
    assert auth.authenticate("wrong") is None
    assert auth.authenticate("") is None


@pytest.mark.unit
def test_empty_configured_token_rejects_all():
    auth = StaticBearerAuthenticator("")
    assert auth.authenticate("") is None
    assert auth.authenticate("anything") is None


@pytest.mark.unit
def test_k8s_tokenreview_fails_closed_on_error(monkeypatch):
    auth = K8sTokenReviewAuthenticator("https://k8s.local")

    import httpx

    def boom(*a, **k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "post", boom)
    assert auth.authenticate("sa-token") is None


@pytest.mark.unit
def test_k8s_tokenreview_parses_authenticated(monkeypatch):
    auth = K8sTokenReviewAuthenticator("https://k8s.local")
    import httpx

    class Resp:
        def json(self):
            return {"status": {"authenticated": True,
                               "user": {"username": "system:serviceaccount:ns:sa",
                                        "groups": ["g1"]}}}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    p = auth.authenticate("sa-token")
    assert p.subject == "system:serviceaccount:ns:sa"
    assert p.groups == ["g1"] and p.method == "k8s"


# ── middleware ───────────────────────────────────────────────────────

def _app(authenticator, authorizer=None, exempt=("/api/health",)):
    app = Flask(__name__)
    install_harness_auth(app, authenticator, authorizer or AllowAllAuthorizer(),
                         exempt_prefixes=exempt)

    @app.route("/api/health/")
    def health():
        return jsonify({"ok": True})

    @app.route("/api/sessions/x")
    def protected():
        return jsonify({"ok": True})

    return app


@pytest.mark.unit
def test_middleware_rejects_without_token():
    client = _app(StaticBearerAuthenticator("tok")).test_client()
    assert client.get("/api/sessions/x").status_code == 401


@pytest.mark.unit
def test_middleware_rejects_bad_token():
    client = _app(StaticBearerAuthenticator("tok")).test_client()
    r = client.get("/api/sessions/x", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


@pytest.mark.unit
def test_middleware_allows_valid_token():
    client = _app(StaticBearerAuthenticator("tok")).test_client()
    r = client.get("/api/sessions/x", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200


@pytest.mark.unit
def test_health_is_exempt():
    client = _app(StaticBearerAuthenticator("tok")).test_client()
    assert client.get("/api/health/").status_code == 200  # no token needed


@pytest.mark.unit
def test_authorizer_can_forbid():
    class DenyAll(Authorizer):
        def authorize(self, principal, method, path):
            return False

    client = _app(StaticBearerAuthenticator("tok"), authorizer=DenyAll()).test_client()
    r = client.get("/api/sessions/x", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 403
