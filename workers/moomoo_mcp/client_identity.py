"""Durable, non-secret custody for this desktop app's MCP OAuth client ID.

A `client_id` for a public, PKCE-only, loopback-redirect OAuth client is a
public identifier, not a secret: it identifies which application is asking
for authorization, and it is exposed anyway in the browser-visible
authorization URL. It is safe to persist as a plain (not Keychain-custodied)
JSON file, but it must remain bound to the exact resource and redirect URI it
was registered for, so a future resource change cannot silently reuse a
stale registration.

This store never persists a `client_secret` or a registration access token;
dynamic registration for a public client returns no secret, and this module
has no field to carry one even if a server returned it unexpectedly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MAX_IDENTITY_FILE_BYTES = 4_096


@dataclass(frozen=True, slots=True)
class MoomooMcpClientIdentity:
    client_id: str
    resource: str
    redirect_uri: str


class MoomooMcpClientIdentityStore:
    """Desktop-local JSON file custody for one registered public client ID."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self, *, resource: str, redirect_uri: str) -> str | None:
        """Return a usable client ID, or None if none is bound and valid.

        Fails closed (returns None, never raises) on a missing, oversized,
        malformed, or resource/redirect-mismatched file, so a stale or
        tampered identity file cannot silently authorize under the wrong
        binding: the caller falls back to fresh dynamic registration.
        """

        try:
            raw = self._path.read_bytes()
        except OSError:
            return None
        if len(raw) > MAX_IDENTITY_FILE_BYTES:
            return None
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        client_id = payload.get("client_id")
        stored_resource = payload.get("resource")
        stored_redirect_uri = payload.get("redirect_uri")
        if (
            not isinstance(client_id, str)
            or not client_id.strip()
            or stored_resource != resource
            or stored_redirect_uri != redirect_uri
        ):
            return None
        return client_id

    def load_any(self, *, resource: str) -> str | None:
        """Return the persisted client ID bound to `resource`, ignoring redirect URI.

        Used only for token refresh, which never redirects a browser and so
        has no redirect URI to bind against; `load()` (which does check the
        redirect URI) remains the gate for building a fresh authorization
        URL.
        """

        try:
            raw = self._path.read_bytes()
        except OSError:
            return None
        if len(raw) > MAX_IDENTITY_FILE_BYTES:
            return None
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        client_id = payload.get("client_id")
        if (
            not isinstance(client_id, str)
            or not client_id.strip()
            or payload.get("resource") != resource
        ):
            return None
        return client_id

    def save(self, identity: MoomooMcpClientIdentity) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "client_id": identity.client_id,
                "resource": identity.resource,
                "redirect_uri": identity.redirect_uri,
            },
            sort_keys=True,
        )
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self._path)

    def clear(self) -> None:
        """Remove this app's persisted public MCP client identity only."""

        try:
            self._path.unlink()
        except FileNotFoundError:
            return


__all__ = ["MoomooMcpClientIdentity", "MoomooMcpClientIdentityStore"]
