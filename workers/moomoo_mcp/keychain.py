from __future__ import annotations

import uuid

from workers.portfolio.keychain import (
    KeychainBackend,
    MacOSKeychainBackend,
    MoomooKeychainError,
)


MCP_KEYCHAIN_SERVICE = "dev.slated.iros.moomoo.mcp"


class MoomooMcpTokenKeychain:
    """Separate macOS Keychain custody for MCP OAuth refresh tokens."""

    def __init__(
        self,
        *,
        operator_id: str,
        backend: KeychainBackend | None = None,
    ) -> None:
        normalized_operator_id = str(uuid.UUID(operator_id))
        self.account = f"{normalized_operator_id}:refresh_token"
        self.backend = backend if backend is not None else MacOSKeychainBackend()

    def store_refresh_token(self, refresh_token: str) -> None:
        if not refresh_token or "\n" in refresh_token or "\r" in refresh_token:
            raise ValueError("Moomoo MCP refresh token is invalid")
        self.backend.store(
            service=MCP_KEYCHAIN_SERVICE,
            account=self.account,
            secret=refresh_token,
        )

    def read_refresh_token(self) -> str:
        token = self.backend.read(
            service=MCP_KEYCHAIN_SERVICE,
            account=self.account,
        )
        if token is None or not token:
            raise MoomooKeychainError("Moomoo MCP refresh token is unavailable")
        return token

    def delete_refresh_token(self) -> None:
        self.backend.delete(
            service=MCP_KEYCHAIN_SERVICE,
            account=self.account,
        )
