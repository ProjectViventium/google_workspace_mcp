from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import fastmcp
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.utilities.storage import JSONFileStorage
from mcp.server.auth.provider import RefreshToken

from auth.secure_storage import (
    StorageSecurityError,
    atomic_write_private_json,
    ensure_private_directory,
    list_private_json_files,
    read_private_json,
    remove_private_file,
)

logger = logging.getLogger(__name__)


class SecureJSONFileStorage(JSONFileStorage):
    """FastMCP-compatible client registration storage with private atomic files."""

    def __init__(self, cache_dir: Path):
        ensure_private_directory(cache_dir)
        super().__init__(cache_dir)
        ensure_private_directory(cache_dir)

    async def get(self, key: str) -> dict[str, Any] | None:
        path = self._get_file_path(key)
        try:
            wrapper = read_private_json(path, repair_mode=True)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
            logger.warning("Failed to load OAuth client %r: %s", key, exc)
            return None
        if not isinstance(wrapper, dict) or "data" not in wrapper:
            logger.warning("Invalid OAuth client storage format for key %r", key)
            return None
        return wrapper["data"]

    async def set(self, key: str, value: dict[str, Any]) -> None:
        wrapper = {"data": value, "timestamp": time.time()}
        atomic_write_private_json(self._get_file_path(key), wrapper, indent=None)

    async def delete(self, key: str) -> None:
        remove_private_file(self._get_file_path(key))

    async def cleanup_old_entries(
        self,
        max_age_seconds: int = 30 * 24 * 60 * 60,
    ) -> int:
        current_time = time.time()
        removed_count = 0
        for json_file in list_private_json_files(
            self.cache_dir, repair_mode=True
        ):
            try:
                wrapper = read_private_json(json_file, repair_mode=True)
                timestamp = wrapper.get("timestamp") if isinstance(wrapper, dict) else None
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp).timestamp()
                if not isinstance(timestamp, (int, float)):
                    continue
                if current_time - timestamp > max_age_seconds:
                    remove_private_file(json_file)
                    removed_count += 1
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return removed_count


class PersistentGoogleProvider(GoogleProvider):
    # === VIVENTIUM START ===
    # Feature: Persist Google OAuth refresh tokens across local MCP restarts.
    # Purpose: FastMCP persists OAuth client registrations but keeps refresh-token
    # state in memory by default, which causes LibreChat's stored local Google
    # tokens to become invalid after each Google MCP restart.
    # === VIVENTIUM END ===
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        client_dir = fastmcp.settings.home / "oauth-proxy-clients"
        ensure_private_directory(client_dir)
        kwargs.setdefault("client_storage", SecureJSONFileStorage(client_dir))
        super().__init__(*args, **kwargs)
        token_dir = fastmcp.settings.home / "oauth-proxy-tokens"
        ensure_private_directory(token_dir)
        self._refresh_token_state_path = token_dir / "google_refresh_tokens.json"
        self._load_persisted_refresh_tokens()

    def _serialize_refresh_token(self, refresh_token: RefreshToken) -> dict[str, Any]:
        return {
            "token": refresh_token.token,
            "client_id": refresh_token.client_id,
            "scopes": list(refresh_token.scopes),
            "expires_at": refresh_token.expires_at,
        }

    def _load_persisted_refresh_tokens(self) -> None:
        if not self._refresh_token_state_path.exists():
            return

        try:
            payload = read_private_json(
                self._refresh_token_state_path, repair_mode=True
            )
        except StorageSecurityError:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to read persisted Google refresh-token state from %s: %s",
                self._refresh_token_state_path,
                exc,
            )
            return

        stored_tokens = payload.get("refresh_tokens", [])
        if not isinstance(stored_tokens, list):
            logger.warning(
                "Ignoring invalid Google refresh-token state file %s",
                self._refresh_token_state_path,
            )
            return

        loaded_count = 0
        for entry in stored_tokens:
            if not isinstance(entry, dict):
                continue
            try:
                refresh_token = RefreshToken(**entry)
            except Exception as exc:
                logger.warning("Skipping invalid persisted Google refresh token: %s", exc)
                continue
            self._refresh_tokens[refresh_token.token] = refresh_token
            loaded_count += 1

        if loaded_count:
            logger.info(
                "Loaded %s persisted Google refresh token(s) from %s",
                loaded_count,
                self._refresh_token_state_path,
            )

    def _persist_refresh_tokens(self) -> None:
        refresh_tokens = sorted(
            (
                self._serialize_refresh_token(refresh_token)
                for refresh_token in self._refresh_tokens.values()
            ),
            key=lambda token: (token["client_id"], token["token"]),
        )

        if not refresh_tokens:
            remove_private_file(self._refresh_token_state_path)
            return

        payload = {
            "refresh_tokens": refresh_tokens,
            "updated_at": int(time.time()),
        }
        atomic_write_private_json(self._refresh_token_state_path, payload, indent=2)

    def persist_refresh_token_for_access_token(self, access_token: str) -> bool:
        # === VIVENTIUM START ===
        # Feature: Persist refresh-token state after a successful bearer-token tool call.
        # Purpose: Some local auth flows prove Google auth via a live bearer token before the
        # persisted refresh-token file exists. If the access token already maps to a refresh
        # token in provider memory, flush it now so the next local restart keeps working.
        # === VIVENTIUM END ===
        refresh_token_value = self._access_to_refresh.get(access_token)
        if not refresh_token_value:
            return False

        refresh_token = self._refresh_tokens.get(refresh_token_value)
        if refresh_token is None:
            return False

        self._persist_refresh_tokens()
        return True

    async def load_refresh_token(
        self,
        client,
        refresh_token: str,
    ) -> RefreshToken | None:
        token = self._refresh_tokens.get(refresh_token)
        if token is None:
            self._load_persisted_refresh_tokens()
            token = self._refresh_tokens.get(refresh_token)

        if token is None:
            # === VIVENTIUM START ===
            # Feature: Bootstrap local Google refresh-token state from LibreChat's stored token.
            # Purpose: On a fresh local machine or after a local MCP restart, LibreChat may still
            # hold the valid Google refresh token even when the MCP's in-memory cache was lost.
            # Accepting that presented refresh token for the active client lets local isolated
            # reconnect recover without another manual Google auth cycle.
            # === VIVENTIUM END ===
            client_scopes = getattr(client, "scope", None)
            if isinstance(client_scopes, str):
                scopes = [scope for scope in client_scopes.split() if scope]
            else:
                scopes = list(getattr(client, "scopes", []) or [])

            token = RefreshToken(
                token=refresh_token,
                client_id=client.client_id,
                scopes=scopes,
                expires_at=None,
            )
            self._refresh_tokens[refresh_token] = token
            self._persist_refresh_tokens()
            logger.info(
                "Bootstrapped persisted Google refresh token for client_id %s from client-presented token",
                client.client_id,
            )
            return token

        if token.client_id != client.client_id:
            logger.warning(
                "Discarding persisted Google refresh token for mismatched client_id %s",
                token.client_id,
            )
            return None

        return token

    async def exchange_authorization_code(self, client, authorization_code):
        tokens = await super().exchange_authorization_code(client, authorization_code)
        self._persist_refresh_tokens()
        return tokens

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        tokens = await super().exchange_refresh_token(client, refresh_token, scopes)
        self._persist_refresh_tokens()
        return tokens

    async def revoke_token(self, token) -> None:
        await super().revoke_token(token)
        self._persist_refresh_tokens()
