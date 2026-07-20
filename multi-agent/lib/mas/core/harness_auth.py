"""
Thin harness authentication + authorization ([4.2], issue #24).

Replaces the platform Keycloak identity service for headless
deployments. Two authenticator strategies:

  - **bearer**: a shared static token (simplest on-prem / Podman)
  - **k8s**: a Kubernetes ServiceAccount token validated via the
    TokenReview API (in-cluster)

Plus a pluggable ``Authorizer`` (RBAC) that fails **closed** when
enabled. All endpoints require a valid principal when auth is enabled;
exempt paths (health) are configurable.
"""

from __future__ import annotations

import hmac
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Principal:
    """An authenticated caller."""
    subject: str
    groups: List[str] = field(default_factory=list)
    method: str = ""


class Authenticator(ABC):
    @abstractmethod
    def authenticate(self, token: str) -> Optional[Principal]:
        """Return a Principal for a valid token, else None."""
        ...


class StaticBearerAuthenticator(Authenticator):
    """Constant-time comparison against a configured shared secret."""

    def __init__(self, token: str, subject: str = "harness-client") -> None:
        self._token = token
        self._subject = subject

    def authenticate(self, token: str) -> Optional[Principal]:
        if self._token and hmac.compare_digest(token, self._token):
            return Principal(subject=self._subject, method="bearer")
        return None


class K8sTokenReviewAuthenticator(Authenticator):
    """Validate a ServiceAccount token via the Kubernetes TokenReview API."""

    def __init__(self, api_server: str, ca_cert: str = "",
                 reviewer_token: str = "", verify: bool = True) -> None:
        self._api = api_server.rstrip("/")
        self._ca = ca_cert
        self._reviewer_token = reviewer_token
        self._verify = verify

    def authenticate(self, token: str) -> Optional[Principal]:
        try:
            import httpx
        except ImportError:  # pragma: no cover
            logger.error("httpx required for K8s TokenReview")
            return None
        body = {
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenReview",
            "spec": {"token": token},
        }
        headers = {"Content-Type": "application/json"}
        if self._reviewer_token:
            headers["Authorization"] = f"Bearer {self._reviewer_token}"
        verify = self._ca or self._verify
        try:
            resp = httpx.post(
                f"{self._api}/apis/authentication.k8s.io/v1/tokenreviews",
                json=body, headers=headers, verify=verify, timeout=5.0)
            status = resp.json().get("status", {})
            if status.get("authenticated"):
                user = status.get("user", {})
                return Principal(subject=user.get("username", "unknown"),
                                 groups=user.get("groups", []), method="k8s")
        except Exception:  # noqa: BLE001 — fail closed on any error
            logger.warning("TokenReview call failed", exc_info=True)
        return None


class Authorizer(ABC):
    @abstractmethod
    def authorize(self, principal: Principal, method: str, path: str) -> bool:
        ...


class AllowAllAuthorizer(Authorizer):
    """Authenticated == authorized. The default when no RBAC is wired."""

    def authorize(self, principal: Principal, method: str, path: str) -> bool:
        return True


def build_authenticator(cfg) -> Optional[Authenticator]:
    mode = getattr(cfg, "harness_auth_mode", "bearer")
    if mode == "k8s":
        return K8sTokenReviewAuthenticator(
            api_server=getattr(cfg, "k8s_api_server", "https://kubernetes.default.svc"),
            ca_cert=getattr(cfg, "k8s_ca_cert", ""),
            reviewer_token=getattr(cfg, "k8s_reviewer_token", ""),
        )
    token = getattr(cfg, "harness_auth_bearer_token", "")
    if not token:
        logger.warning("harness auth enabled but no bearer token set; "
                       "all requests will be rejected (fail-closed)")
    return StaticBearerAuthenticator(token)
