"""Authenticating as a GitHub App installation."""

import base64
import json
import time
from typing import Any

import pytest
from observe_github.app import AppAuth, _normalize
from observe_github.sink import GitHubSink

cryptography = pytest.importorskip("cryptography")


@pytest.fixture
def pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def unpack(segment: str) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    )
    return decoded


class TestJwt:
    def test_is_signed_with_rs256(self, pem: str):
        header, _, _ = AppAuth("1", pem, "o/r")._jwt().split(".")
        assert unpack(header) == {"alg": "RS256", "typ": "JWT"}

    def test_the_signature_verifies_against_the_key(self, pem: str):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        header, claims, signature = AppAuth("1", pem, "o/r")._jwt().split(".")
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        assert isinstance(key, rsa.RSAPrivateKey)
        key.public_key().verify(
            base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
            f"{header}.{claims}".encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

    def test_stays_inside_the_ten_minute_cap(self, pem: str):
        """GitHub rejects anything longer, measured from `iat`."""
        _, claims, _ = AppAuth("1", pem, "o/r")._jwt().split(".")
        payload = unpack(claims)
        assert payload["exp"] - payload["iat"] <= 600

    def test_is_backdated_against_clock_drift(self, pem: str):
        _, claims, _ = AppAuth("1", pem, "o/r")._jwt().split(".")
        assert unpack(claims)["iat"] < time.time()

    def test_is_issued_by_the_app(self, pem: str):
        _, claims, _ = AppAuth("99", pem, "o/r")._jwt().split(".")
        assert unpack(claims)["iss"] == "99"


class TestKeyFormats:
    """A PEM survives however a secret store mangles it."""

    def test_plain(self, pem: str):
        assert _normalize(pem) == pem.strip()

    def test_newlines_flattened_to_escapes(self, pem: str):
        assert _normalize(pem.replace("\n", "\\n")) == pem.strip()

    def test_wrapped_in_base64(self, pem: str):
        assert _normalize(base64.b64encode(pem.encode()).decode()) == pem.strip()


class TestTokenReuse:
    def test_a_live_token_is_not_minted_again(self, pem: str):
        auth = AppAuth("1", pem, "o/r")
        auth._token = "ghs_live"
        auth._expires = time.time() + 3600
        assert auth.token() == "ghs_live"

    def test_a_token_near_expiry_is_replaced(self, pem: str, monkeypatch):
        auth = AppAuth("1", pem, "o/r")
        auth._token = "ghs_stale"
        auth._expires = time.time() + 10
        auth._installation = 7
        monkeypatch.setattr(
            AppAuth, "_post", lambda *a, **k: {"token": "ghs_fresh", "expires_at": ""}
        )
        assert auth.token() == "ghs_fresh"


class TestSinkCredentials:
    def test_an_app_is_used_when_no_token_is_set(self, pem: str, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_APP_ID", "1")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", pem)
        assert GitHubSink(repo="o/r")._app is not None

    def test_an_explicit_token_wins(self, pem: str, monkeypatch):
        monkeypatch.setenv("GITHUB_APP_ID", "1")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", pem)
        sink = GitHubSink(token="ghp_explicit", repo="o/r")
        assert sink._app is None
        assert sink._token == "ghp_explicit"

    def test_neither_configured_is_not_an_error(self, monkeypatch):
        for name in ("GITHUB_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY"):
            monkeypatch.delenv(name, raising=False)
        sink = GitHubSink(repo="o/r")
        assert sink._token == ""

    def test_a_failure_to_mint_does_not_raise(self, pem: str, monkeypatch):
        """Feedback is best-effort; a credential problem must not crash a push."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_APP_ID", "1")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", pem)
        sink = GitHubSink(repo="o/r")
        monkeypatch.setattr(AppAuth, "token", lambda self: (_ for _ in ()).throw(OSError("no")))
        assert sink._token == ""
