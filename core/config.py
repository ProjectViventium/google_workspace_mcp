"""
Shared configuration for Google Workspace MCP server.
This module holds configuration values that need to be shared across modules
to avoid circular imports.

NOTE: OAuth configuration has been moved to auth.oauth_config for centralization.
This module now imports from there for backward compatibility.
"""

import os
import ipaddress
from auth.oauth_config import (
    get_oauth_base_url,
    get_oauth_redirect_uri,
    set_transport_mode,
    get_transport_mode,
    is_oauth21_enabled
)

# Server configuration
WORKSPACE_MCP_PORT = int(os.getenv("PORT", os.getenv("WORKSPACE_MCP_PORT", 8000)))
WORKSPACE_MCP_BASE_URI = os.getenv("WORKSPACE_MCP_BASE_URI", "http://localhost")

# Disable USER_GOOGLE_EMAIL in OAuth 2.1 multi-user mode
USER_GOOGLE_EMAIL = None if is_oauth21_enabled() else os.getenv("USER_GOOGLE_EMAIL", None)


def resolve_http_bind_host() -> str:
    """Return a loopback-safe bind host unless remote exposure is explicit."""
    host = os.getenv("WORKSPACE_MCP_BIND_HOST", "127.0.0.1").strip()
    if not host:
        raise ValueError("WORKSPACE_MCP_BIND_HOST must not be empty")

    is_loopback = host.lower() == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False

    remote_opt_in = (
        os.getenv("WORKSPACE_MCP_ALLOW_REMOTE_BIND", "false").strip().lower()
        == "true"
    )
    if not is_loopback and not remote_opt_in:
        raise ValueError(
            "Remote streamable HTTP bind requires "
            "WORKSPACE_MCP_ALLOW_REMOTE_BIND=true"
        )
    return host

# Re-export OAuth functions for backward compatibility
__all__ = [
    'WORKSPACE_MCP_PORT',
    'WORKSPACE_MCP_BASE_URI',
    'USER_GOOGLE_EMAIL',
    'resolve_http_bind_host',
    'get_oauth_base_url',
    'get_oauth_redirect_uri',
    'set_transport_mode',
    'get_transport_mode'
]
