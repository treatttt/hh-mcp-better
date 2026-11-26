"""Secure persistence for OAuth token pairs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Protocol


KEYRING_SERVICE = "headhunter-mcp-server"
KEYRING_ACCOUNT = "oauth-token-pair"


class TokenStorageError(RuntimeError):
    """Raised when OAuth tokens cannot be loaded or persisted safely."""


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_at: float


class TokenStore(Protocol):
    def load(self) -> OAuthTokens | None: ...

    def save(self, tokens: OAuthTokens) -> None: ...


class KeyringTokenStore:
    """Store the complete token pair as one Credential Manager entry."""

    def _keyring(self):
        try:
            import keyring
        except ImportError as error:
            raise TokenStorageError(
                "Secure token storage is unavailable; install project dependencies"
            ) from error
        return keyring

    def load(self) -> OAuthTokens | None:
        try:
            payload = self._keyring().get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        except Exception as error:
            raise TokenStorageError("Could not read OAuth tokens securely") from error
        if payload is None:
            return None
        try:
            data = json.loads(payload)
            return OAuthTokens(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=float(data["expires_at"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise TokenStorageError("Stored OAuth token data is invalid") from error

    def save(self, tokens: OAuthTokens) -> None:
        payload = json.dumps(asdict(tokens), separators=(",", ":"))
        try:
            self._keyring().set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, payload)
        except Exception as error:
            raise TokenStorageError("Could not save OAuth tokens securely") from error


class EnvironmentTokenStore:
    """Explicit development-only token storage in the process environment."""

    def load(self) -> OAuthTokens | None:
        access_token = os.getenv("HH_ACCESS_TOKEN")
        refresh_token = os.getenv("HH_REFRESH_TOKEN")
        expires_at = os.getenv("HH_TOKEN_EXPIRES_AT")
        if not access_token or not refresh_token or not expires_at:
            return None
        try:
            return OAuthTokens(access_token, refresh_token, float(expires_at))
        except ValueError as error:
            raise TokenStorageError("HH_TOKEN_EXPIRES_AT must be a timestamp") from error

    def save(self, tokens: OAuthTokens) -> None:
        os.environ["HH_ACCESS_TOKEN"] = tokens.access_token
        os.environ["HH_REFRESH_TOKEN"] = tokens.refresh_token
        os.environ["HH_TOKEN_EXPIRES_AT"] = str(tokens.expires_at)


def build_token_store() -> TokenStore:
    if os.getenv("HH_ALLOW_ENV_TOKENS", "").lower() == "true":
        return EnvironmentTokenStore()
    return KeyringTokenStore()
