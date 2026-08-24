from __future__ import annotations

import uuid

from workers.moomoo_mcp.oauth import MOOMOO_MCP_RESOURCE
from workers.portfolio.keychain import (
    KeychainBackend,
    MacOSKeychainBackend,
    MoomooKeychainError,
)


MCP_KEYCHAIN_SERVICE = "dev.slated.iros.moomoo.mcp"
"""Legacy service name: operator-only identity, no client/resource binding.

Kept read-only for detection purposes so a pre-existing entry is never
silently deleted or silently trusted — see `MoomooMcpTokenKeychain` below.
"""

MCP_KEYCHAIN_SERVICE_V2 = "dev.slated.iros.moomoo.mcp.v2"
"""Resource-bound service name: operator + OAuth client ID + MCP resource."""


class MoomooMcpCredentialError(MoomooKeychainError):
    """Raised with one bounded reason code instead of a generic message."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MoomooMcpTokenKeychain:
    """Resource-bound macOS Keychain custody for MCP OAuth refresh tokens.

    Storage identity binds the canonical operator ID, the MCP OAuth client
    ID, and the canonical MCP resource URI, so a token issued for one client
    or resource can never be read back and refreshed under another. A
    pre-existing operator-only entry (`MCP_KEYCHAIN_SERVICE`, written before
    this binding existed) is never auto-migrated or exposed: `read_refresh_token`
    distinguishes "nothing stored yet" (`credential_missing`) from "a legacy
    unbound entry exists but its binding cannot be verified"
    (`credential_binding_mismatch`), which requires one fresh operator OAuth
    consent to populate the new resource-bound entry safely.
    """

    def __init__(
        self,
        *,
        operator_id: str,
        client_id: str,
        resource: str = MOOMOO_MCP_RESOURCE,
        backend: KeychainBackend | None = None,
    ) -> None:
        normalized_operator_id = str(uuid.UUID(operator_id))
        if not isinstance(client_id, str) or not client_id.strip():
            raise ValueError("Moomoo MCP OAuth client ID is required")
        if not isinstance(resource, str) or not resource.startswith("https://"):
            raise ValueError("Moomoo MCP resource identifier is invalid")
        self._legacy_account = f"{normalized_operator_id}:refresh_token"
        self.account = f"{normalized_operator_id}:{client_id.strip()}:{resource}:refresh_token"
        self.backend = backend if backend is not None else MacOSKeychainBackend()

    def store_refresh_token(self, refresh_token: str) -> None:
        if not refresh_token or "\n" in refresh_token or "\r" in refresh_token:
            raise ValueError("Moomoo MCP refresh token is invalid")
        self.backend.store(
            service=MCP_KEYCHAIN_SERVICE_V2,
            account=self.account,
            secret=refresh_token,
        )

    def read_refresh_token(self) -> str:
        token = self.backend.read(
            service=MCP_KEYCHAIN_SERVICE_V2,
            account=self.account,
        )
        if token:
            return token
        legacy_token = self.backend.read(
            service=MCP_KEYCHAIN_SERVICE,
            account=self._legacy_account,
        )
        if legacy_token:
            raise MoomooMcpCredentialError("credential_binding_mismatch")
        raise MoomooMcpCredentialError("credential_missing")

    def delete_refresh_token(self) -> None:
        self.backend.delete(
            service=MCP_KEYCHAIN_SERVICE_V2,
            account=self.account,
        )

    def clear_all_local_tokens(self) -> None:
        """Explicit full-clear path for bound and pre-v2 local credentials."""

        self.delete_refresh_token()
        self.backend.delete(
            service=MCP_KEYCHAIN_SERVICE,
            account=self._legacy_account,
        )
