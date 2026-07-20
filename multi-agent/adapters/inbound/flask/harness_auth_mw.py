"""
Harness auth Flask middleware ([4.2], issue #24).

A ``before_request`` hook that enforces bearer/K8s authentication (and
pluggable authorization) on every API route when enabled. Fails closed:
a missing/invalid token → 401; an unauthorized principal → 403. Exempt
paths (health, and CORS preflight OPTIONS) bypass the check.
"""

from __future__ import annotations

import logging

from flask import g, jsonify, request

logger = logging.getLogger(__name__)


def install_harness_auth(app, authenticator, authorizer, exempt_prefixes):
    exempt = tuple(exempt_prefixes)

    @app.before_request
    def _enforce_auth():  # noqa: ANN202
        if request.method == "OPTIONS":
            return None
        path = request.path
        if any(path.startswith(p) for p in exempt):
            return None

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "missing bearer token"}), 401
        token = auth[len("Bearer "):].strip()

        principal = authenticator.authenticate(token)
        if principal is None:
            return jsonify({"error": "invalid token"}), 401

        if not authorizer.authorize(principal, request.method, path):
            return jsonify({"error": "forbidden"}), 403

        g.harness_principal = principal
        return None

    logger.info("harness auth enabled (exempt: %s)", ", ".join(exempt))
