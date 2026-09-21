"""Authenticating as a GitHub App installation.

An App is the right shape for a service that opens issues on its own: the
grant is scoped to the repositories it is installed on, it is not tied to a
person, and it can be revoked without touching anyone's account.

Installation tokens last an hour, so they are minted on demand and reused
until shortly before they expire.

Signing the App JWT needs RSA, which the standard library cannot do, so this
module is behind the ``app`` extra and imported only when App credentials are
actually configured.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

API = "https://api.github.com"
TIMEOUT = 30
#: GitHub rejects a JWT claiming more than ten minutes, counted from `iat`.
#: Backdating costs a minute of that, so this leaves a margin under the cap.
JWT_LIFETIME = 480
#: Renew before expiry rather than on it, so a slow request cannot outlive
#: the token it started with.
RENEW_MARGIN = 300


class AppAuth:
    """Mints and caches installation tokens for one repository."""

    def __init__(self, app_id: str, private_key: str, repo: str) -> None:
        self.app_id = app_id
        self.private_key = _normalize(private_key)
        self.repo = repo
        self._token = ""
        self._expires = 0.0
        self._installation = 0

    def token(self) -> str:
        """A valid installation token, minting a new one when needed."""
        if self._token and time.time() < self._expires - RENEW_MARGIN:
            return self._token

        jwt = self._jwt()
        if not self._installation:
            found = self._get(f"/repos/{self.repo}/installation", jwt)
            self._installation = int(found["id"])

        issued = self._post(f"/app/installations/{self._installation}/access_tokens", jwt)
        self._token = str(issued["token"])
        self._expires = _timestamp(str(issued.get("expires_at", "")))
        log.info("github app: token for %s valid until %s", self.repo, issued.get("expires_at"))
        return self._token

    def _jwt(self) -> str:
        now = int(time.time())
        # Backdated by a minute: GitHub rejects a JWT issued in its future,
        # and clocks drift.
        claims = {"iat": now - 60, "exp": now + JWT_LIFETIME, "iss": self.app_id}
        signing_input = b".".join(
            _b64(json.dumps(part, separators=(",", ":")).encode())
            for part in ({"alg": "RS256", "typ": "JWT"}, claims)
        )
        return b".".join((signing_input, _b64(self._sign(signing_input)))).decode()

    def _sign(self, payload: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        key = serialization.load_pem_private_key(self.private_key.encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise TypeError("a GitHub App private key is RSA")
        return key.sign(payload, padding.PKCS1v15(), hashes.SHA256())

    def _get(self, path: str, jwt: str) -> dict[str, Any]:
        return self._call(path, jwt, method="GET")

    def _post(self, path: str, jwt: str) -> dict[str, Any]:
        return self._call(path, jwt, method="POST")

    @staticmethod
    def _call(path: str, jwt: str, *, method: str) -> dict[str, Any]:
        request = urllib.request.Request(
            API + path,
            headers={
                "Authorization": f"Bearer {jwt}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "observe-github-sink/1.0",
            },
            method=method,
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            parsed: dict[str, Any] = json.loads(resp.read())
            return parsed


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _normalize(key: str) -> str:
    """Accept a PEM however a secret store hands it over.

    Vaults and CI variables routinely flatten the newlines a PEM needs, as
    literal ``\\n`` or by base64-ing the whole thing.
    """
    key = key.strip()
    if "BEGIN" in key:
        return key.replace("\\n", "\n").strip()
    try:
        return base64.b64decode(key).decode().strip()
    except (ValueError, UnicodeDecodeError):
        return key


def _timestamp(iso: str) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        # Unparseable expiry: treat the token as good for the documented
        # hour rather than never refreshing it.
        return time.time() + 3600
