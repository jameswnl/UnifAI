"""Unit tests for sandbox security: TLS, redaction, tool scoping."""

import pytest

from mas.sandbox.tls import (
    TLSMode,
    get_tls_mode,
    generate_ephemeral_certs,
    EphemeralCerts,
)
from mas.sandbox.security import redact_secrets, validate_tool_scoping


class TestTLSMode:
    def test_get_tls_mode_disabled(self):
        assert get_tls_mode("") == TLSMode.DISABLED
        assert get_tls_mode("disabled") == TLSMode.DISABLED
        assert get_tls_mode("  ") == TLSMode.DISABLED

    def test_get_tls_mode_app(self):
        assert get_tls_mode("app") == TLSMode.APP
        assert get_tls_mode("APP") == TLSMode.APP

    def test_get_tls_mode_mesh(self):
        assert get_tls_mode("mesh") == TLSMode.MESH


class TestEphemeralCerts:
    def test_generate_certs(self):
        certs = generate_ephemeral_certs("sb-test", valid_seconds=300)
        assert isinstance(certs, EphemeralCerts)
        assert b"CERTIFICATE" in certs.ca_cert_pem
        assert b"CERTIFICATE" in certs.server_cert_pem
        assert len(certs.server_key_pem) > 100
        assert certs.valid_seconds == 300

    def test_generate_certs_with_san(self):
        certs = generate_ephemeral_certs(
            "sb-test",
            san_dns=["sb-test.default.svc", "sb-test.default.svc.cluster.local"],
        )
        assert certs.ca_cert_pem != certs.server_cert_pem

    def test_certs_are_unique(self):
        a = generate_ephemeral_certs("sb-a")
        b = generate_ephemeral_certs("sb-b")
        assert a.ca_cert_pem != b.ca_cert_pem
        assert a.server_cert_pem != b.server_cert_pem


class TestRedactSecrets:
    def test_redacts_known_values(self):
        text = "Error: token abc123 is invalid"
        result = redact_secrets(text, ["abc123"])
        assert result == "Error: token ***REDACTED*** is invalid"

    def test_redacts_multiple(self):
        text = "key=secret1 and key2=secret2"
        result = redact_secrets(text, ["secret1", "secret2"])
        assert "secret1" not in result
        assert "secret2" not in result

    def test_longest_first(self):
        text = "my-secret-key-long"
        result = redact_secrets(text, ["my-secret", "my-secret-key-long"])
        assert result == "***REDACTED***"

    def test_empty_inputs(self):
        assert redact_secrets("", ["secret"]) == ""
        assert redact_secrets("text", []) == "text"
        assert redact_secrets("text", None) == "text"

    def test_no_match(self):
        assert redact_secrets("safe text", ["missing"]) == "safe text"


class TestValidateToolScoping:
    def test_no_restrictions(self):
        result = validate_tool_scoping(requested=["kubectl", "ls", "cat"])
        assert result == ["kubectl", "ls", "cat"]

    def test_allowlist(self):
        result = validate_tool_scoping(
            allowed=["kubectl", "ls"],
            requested=["kubectl", "ls", "rm"],
        )
        assert result == ["kubectl", "ls"]

    def test_denylist(self):
        result = validate_tool_scoping(
            denied=["rm", "dd"],
            requested=["kubectl", "ls", "rm"],
        )
        assert result == ["kubectl", "ls"]

    def test_both_allow_and_deny(self):
        result = validate_tool_scoping(
            allowed=["kubectl", "ls", "cat"],
            denied=["cat"],
            requested=["kubectl", "ls", "cat", "rm"],
        )
        assert result == ["kubectl", "ls"]

    def test_none_requested(self):
        assert validate_tool_scoping(allowed=["x"]) == []

    def test_empty_requested(self):
        assert validate_tool_scoping(requested=[]) == []
