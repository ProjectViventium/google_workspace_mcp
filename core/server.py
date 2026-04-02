import logging
from typing import List, Optional
from importlib import metadata

from fastapi.responses import HTMLResponse, JSONResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.middleware import Middleware

from fastmcp import FastMCP
from auth.oauth21_session_store import get_oauth21_session_store, set_auth_provider
from auth.google_auth import handle_auth_callback, start_auth_flow, check_client_secrets
from auth.mcp_session_middleware import MCPSessionMiddleware
from auth.oauth_responses import create_error_response, create_success_response, create_server_error_response
from auth.auth_info_middleware import AuthInfoMiddleware
from auth.scopes import SCOPES, get_current_scopes # noqa
from auth.persistent_google_provider import PersistentGoogleProvider
from core.config import (
    USER_GOOGLE_EMAIL,
    get_transport_mode,
    set_transport_mode as _set_transport_mode,
    get_oauth_redirect_uri as get_oauth_redirect_uri_for_current_mode,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_auth_provider: Optional[PersistentGoogleProvider] = None
_legacy_callback_registered = False

session_middleware = Middleware(MCPSessionMiddleware)

# ASGI middleware to fix missing client_id in token requests
class TokenClientIdFixMiddleware:
    """
    Raw ASGI middleware that intercepts /token POST requests and adds
    missing client_id before the request reaches the MCP SDK's token handler.
    """
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        from urllib.parse import parse_qs, urlencode
        
        if scope["type"] == "http" and scope["path"] == "/token" and scope["method"] == "POST":
            logger.info("[TokenFix] Intercepting /token request")
            
            # Collect the body
            body_parts = []
            while True:
                message = await receive()
                body_parts.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            
            body = b"".join(body_parts)
            body_str = body.decode('utf-8')
            form_data = parse_qs(body_str)
            
            logger.info(f"[TokenFix] Original fields: {list(form_data.keys())}")
            
            # Get config for fallback values
            from auth.oauth_config import get_oauth_config
            config = get_oauth_config()
            
            # Check if client_id is missing
            if 'client_id' not in form_data or not form_data.get('client_id', [''])[0]:
                logger.info("[TokenFix] client_id is missing")
                
                # Try to get client_id from code data
                code = form_data.get('code', [''])[0]
                client_id_added = False
                
                if code and _auth_provider:
                    code_data = _auth_provider._client_codes.get(code)
                    if code_data and 'client_id' in code_data:
                        form_data['client_id'] = [code_data['client_id']]
                        logger.info(f"[TokenFix] Added client_id from code: {code_data['client_id'][:30]}...")
                        client_id_added = True
                
                # Fallback to config
                if not client_id_added and config.client_id:
                    form_data['client_id'] = [config.client_id]
                    logger.info(f"[TokenFix] Added fallback client_id: {config.client_id[:30]}...")
            
            # Also add client_secret if missing (some OAuth implementations require it)
            if 'client_secret' not in form_data or not form_data.get('client_secret', [''])[0]:
                if config.client_secret:
                    form_data['client_secret'] = [config.client_secret]
                    logger.info("[TokenFix] Added client_secret")
                
                # Rebuild the body
                flat_data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in form_data.items()}
                body = urlencode(flat_data, doseq=True).encode('utf-8')
                logger.info(f"[TokenFix] Modified fields: {list(flat_data.keys())}")
            
            # Update content-length header
            new_headers = []
            for name, value in scope.get('headers', []):
                if name.lower() == b'content-length':
                    new_headers.append((b'content-length', str(len(body)).encode()))
                else:
                    new_headers.append((name, value))
            
            new_scope = dict(scope)
            new_scope['headers'] = new_headers
            
            # Create new receive that returns our modified body
            body_sent = False
            async def new_receive():
                nonlocal body_sent
                if not body_sent:
                    body_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.request", "body": b"", "more_body": False}
            
            await self.app(new_scope, new_receive, send)
        else:
            await self.app(scope, receive, send)


# Custom FastMCP that adds secure middleware stack and token fix for OAuth 2.1
class SecureFastMCP(FastMCP):
    def http_app(self, path=None, middleware=None, json_response=None, stateless_http=None, transport="http"):
        """Override to wrap the app with our ASGI middleware."""
        # Call parent to create the base app
        app = super().http_app(
            path=path,
            middleware=middleware,
            json_response=json_response,
            stateless_http=stateless_http,
            transport=transport
        )

        # Add session middleware
        app.user_middleware.insert(0, session_middleware)
        app.middleware_stack = app.build_middleware_stack()
        
        # Wrap the entire app with our ASGI middleware
        wrapped_app = TokenClientIdFixMiddleware(app)
        
        # Return a wrapper that looks like a Starlette app
        class WrappedStarletteApp:
            def __init__(self, middleware_app, original_app):
                self._middleware_app = middleware_app
                self._original_app = original_app
                # Copy attributes from original app for compatibility
                for attr in ['routes', 'state', 'debug', 'middleware_stack', 'exception_handlers', 'on_startup', 'on_shutdown']:
                    if hasattr(original_app, attr):
                        setattr(self, attr, getattr(original_app, attr))
            
            async def __call__(self, scope, receive, send):
                await self._middleware_app(scope, receive, send)
        
        logger.info("[TokenFix] Added TokenClientIdFix ASGI middleware wrapper")
        return WrappedStarletteApp(wrapped_app, app)


async def _auto_register_upstream_client_impl() -> None:
    """
    Auto-register the upstream Google client_id as a valid DCR client.
    
    This allows LibreChat (and other MCP clients) to use the Google client_id
    directly in the /authorize request without needing to do DCR first.
    """
    global _auth_provider
    
    logger.info("=== Auto-register upstream client starting ===")
    
    if _auth_provider is None:
        logger.warning("No auth provider configured, skipping upstream client auto-registration")
        return
    
    logger.info(f"Auth provider is configured: {type(_auth_provider).__name__}")
    
    try:
        from auth.oauth_config import get_oauth_config
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyUrl
        
        config = get_oauth_config()
        logger.info(f"OAuth config loaded, client_id present: {bool(config.client_id)}")
        
        if not config.client_id:
            logger.warning("No Google client_id configured, skipping auto-registration")
            return
        
        logger.info(f"Will register client_id: {config.client_id[:30]}...")
        
        # Check if already registered
        existing = await _auth_provider.get_client(config.client_id)
        if existing:
            logger.info(f"Upstream Google client already registered: {config.client_id[:30]}...")
            return
        
        logger.info("Client not found, proceeding with registration...")
        
        redirect_uris = config.get_redirect_uris() if hasattr(config, "get_redirect_uris") else []
        if not redirect_uris:
            redirect_uris = [config.redirect_uri]

        # Create client info with the Google client_id
        client_info = OAuthClientInformationFull(
            client_id=config.client_id,
            client_secret=config.client_secret,
            redirect_uris=[AnyUrl(uri) for uri in redirect_uris],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name="LibreChat-Google-Workspace",
            token_endpoint_auth_method="client_secret_post",
        )
        
        logger.info("Calling register_client...")
        await _auth_provider.register_client(client_info)
        logger.info(f"=== Auto-registered upstream Google client: {config.client_id[:30]}... ===")
        
        # Verify registration
        verify = await _auth_provider.get_client(config.client_id)
        logger.info(f"Verification after registration: client found = {verify is not None}")
        
    except Exception as e:
        logger.error(f"Failed to auto-register upstream client: {e}", exc_info=True)

server = SecureFastMCP(
    name="google_workspace",
    auth=None,
)

# Add the AuthInfo middleware to inject authentication into FastMCP context
auth_info_middleware = AuthInfoMiddleware()
server.add_middleware(auth_info_middleware)


def set_transport_mode(mode: str):
    """Sets the transport mode for the server."""
    _set_transport_mode(mode)
    logger.info(f"Transport: {mode}")


def _ensure_legacy_callback_route() -> None:
    global _legacy_callback_registered
    if _legacy_callback_registered:
        return
    server.custom_route("/oauth2callback", methods=["GET"])(legacy_oauth2_callback)
    _legacy_callback_registered = True

def _preseed_upstream_client(provider: PersistentGoogleProvider, config) -> None:
    """
    Pre-seed the upstream Google client_id into the provider's client storage.
    
    This writes directly to the JSON file storage to ensure the client is
    available immediately when the server starts, without needing async.
    """
    import json
    from pathlib import Path
    from datetime import datetime
    import fastmcp
    
    try:
        # Get the client storage directory
        cache_dir = fastmcp.settings.home / "oauth-proxy-clients"
        cache_dir.mkdir(exist_ok=True, parents=True)
        
        # Create safe filename from client_id
        safe_key = config.client_id
        for char in [".", "/", "\\", ":", "*", "?", '"', "<", ">", "|", " "]:
            safe_key = safe_key.replace(char, "_")
        while "__" in safe_key:
            safe_key = safe_key.replace("__", "_")
        safe_key = safe_key.strip("_")
        
        file_path = cache_dir / f"{safe_key}.json"
        
        redirect_uris = config.get_redirect_uris() if hasattr(config, "get_redirect_uris") else []
        if not redirect_uris:
            redirect_uris = [config.redirect_uri]

        # Get the configured scopes
        from auth.scopes import get_current_scopes
        scopes = get_current_scopes()
        scope_string = " ".join(sorted(scopes)) if scopes else None

        # === VIVENTIUM START ===
        # Feature: Refresh stale pre-seeded OAuth client files when runtime redirects drift.
        # Purpose: Prevent isolated local runs from reusing old cloud/compat callback URIs.
        # === VIVENTIUM END ===
        if file_path.exists():
            try:
                existing_wrapper = json.loads(file_path.read_text())
                existing_client = existing_wrapper.get("data", {}).get("client", {})
                existing_redirects = existing_client.get("redirect_uris") or []
                if (
                    existing_client.get("client_id") == config.client_id and
                    existing_client.get("client_secret") == config.client_secret and
                    existing_client.get("scope") == scope_string and
                    existing_redirects == redirect_uris
                ):
                    logger.info(f"Client already pre-seeded: {config.client_id[:30]}...")
                    return
                logger.info(
                    f"Refreshing pre-seeded client for {config.client_id[:30]}... due to redirect/scope drift"
                )
            except Exception as e:
                logger.warning(f"Failed reading existing pre-seeded client file {file_path}: {e}")

        # Create the client data structure expected by get_client()
        client_data = {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": scope_string,
            "token_endpoint_auth_method": "none",
            "client_name": "LibreChat-Google-Workspace",
        }
        
        storage_data = {
            "client": client_data,
            "allowed_redirect_uri_patterns": ["*"],  # Allow any redirect URI
        }
        
        # Wrap with metadata as expected by JSONFileStorage
        wrapper = {
            "data": storage_data,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Write to file
        file_path.write_text(json.dumps(wrapper, indent=2))
        logger.info(f"Pre-seeded upstream client: {config.client_id[:30]}... at {file_path}")
        
    except Exception as e:
        logger.error(f"Failed to pre-seed upstream client: {e}", exc_info=True)


def configure_server_for_http():
    """
    Configures the authentication provider for HTTP transport.
    This must be called BEFORE server.run().
    """
    global _auth_provider

    transport_mode = get_transport_mode()

    if transport_mode != "streamable-http":
        return

    # Use centralized OAuth configuration
    from auth.oauth_config import get_oauth_config
    config = get_oauth_config()

    # Check if OAuth 2.1 is enabled via centralized config
    oauth21_enabled = config.is_oauth21_enabled()

    if oauth21_enabled:
        if not config.is_configured():
            logger.warning("OAuth 2.1 enabled but OAuth credentials not configured")
            return

        try:
            required_scopes: List[str] = sorted(get_current_scopes())
            provider = PersistentGoogleProvider(
                client_id=config.client_id,
                client_secret=config.client_secret,
                base_url=config.get_oauth_base_url(),
                redirect_path=config.redirect_path,
                required_scopes=required_scopes,
            )
            # VIVENTIUM: Google must be forced into offline consent or local MCP auth
            # only receives short-lived access tokens and breaks again on expiry.
            extra_authorize_params = getattr(provider, "_extra_authorize_params", None)
            if isinstance(extra_authorize_params, dict):
                extra_authorize_params["access_type"] = "offline"
                extra_authorize_params["prompt"] = "consent"
            server.auth = provider
            set_auth_provider(provider)
            logger.info("OAuth 2.1 enabled using FastMCP GoogleProvider")
            _auth_provider = provider
            
            # Pre-seed the upstream client into storage synchronously
            _preseed_upstream_client(provider, config)
        except Exception as exc:
            logger.error("Failed to initialize FastMCP GoogleProvider: %s", exc, exc_info=True)
            raise
    else:
        logger.info("OAuth 2.0 mode - Server will use legacy authentication.")
        server.auth = None
        _auth_provider = None
        set_auth_provider(None)
        _ensure_legacy_callback_route()


def get_auth_provider() -> Optional[PersistentGoogleProvider]:
    """Gets the global authentication provider instance."""
    return _auth_provider

@server.custom_route("/health", methods=["GET"])
async def health_check(request: Request):
    try:
        version = metadata.version("workspace-mcp")
    except metadata.PackageNotFoundError:
        version = "dev"
    return JSONResponse({
        "status": "healthy",
        "service": "workspace-mcp",
        "version": version,
        "transport": get_transport_mode()
    })

@server.custom_route("/debug/register-upstream", methods=["POST"])
async def debug_register_upstream(request: Request):
    """Debug endpoint to manually trigger upstream client registration."""
    try:
        await _auto_register_upstream_client_impl()
        return JSONResponse({
            "status": "success",
            "message": "Upstream client registration triggered"
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)

async def legacy_oauth2_callback(request: Request) -> HTMLResponse:
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        msg = f"Authentication failed: Google returned an error: {error}. State: {state}."
        logger.error(msg)
        return create_error_response(msg)

    if not code:
        msg = "Authentication failed: No authorization code received from Google."
        logger.error(msg)
        return create_error_response(msg)

    try:
        error_message = check_client_secrets()
        if error_message:
            return create_server_error_response(error_message)

        logger.info(f"OAuth callback: Received code (state: {state}).")

        mcp_session_id = None
        if hasattr(request, 'state') and hasattr(request.state, 'session_id'):
            mcp_session_id = request.state.session_id

        verified_user_id, credentials = handle_auth_callback(
            scopes=get_current_scopes(),
            authorization_response=str(request.url),
            redirect_uri=get_oauth_redirect_uri_for_current_mode(),
            session_id=mcp_session_id
        )

        logger.info(f"OAuth callback: Successfully authenticated user: {verified_user_id}.")

        try:
            store = get_oauth21_session_store()

            store.store_session(
                user_email=verified_user_id,
                access_token=credentials.token,
                refresh_token=credentials.refresh_token,
                token_uri=credentials.token_uri,
                client_id=credentials.client_id,
                client_secret=credentials.client_secret,
                scopes=credentials.scopes,
                expiry=credentials.expiry,
                session_id=f"google-{state}",
                mcp_session_id=mcp_session_id,
            )
            logger.info(f"Stored Google credentials in OAuth 2.1 session store for {verified_user_id}")
        except Exception as e:
            logger.error(f"Failed to store credentials in OAuth 2.1 store: {e}")

        return create_success_response(verified_user_id)
    except Exception as e:
        logger.error(f"Error processing OAuth callback: {str(e)}", exc_info=True)
        return create_server_error_response(str(e))

@server.tool()
async def start_google_auth(service_name: str, user_google_email: str = USER_GOOGLE_EMAIL) -> str:
    """
    Manually initiate Google OAuth authentication flow.

    NOTE: This tool should typically NOT be called directly. The authentication system
    automatically handles credential checks and prompts for authentication when needed.
    Only use this tool if:
    1. You need to re-authenticate with different credentials
    2. You want to proactively authenticate before using other tools
    3. The automatic authentication flow failed and you need to retry

    In most cases, simply try calling the Google Workspace tool you need - it will
    automatically handle authentication if required.
    """
    if not user_google_email:
        raise ValueError("user_google_email must be provided.")

    # Check if this is a service account
    if user_google_email.endswith('.gserviceaccount.com'):
        return (
            f"**Service Account Detected:** {user_google_email}\n\n"
            f"Service accounts authenticate automatically using their JSON key file. "
            f"No manual authentication needed - just use the Google Workspace tools directly!"
        )

    error_message = check_client_secrets()
    if error_message:
        return f"**Authentication Error:** {error_message}"

    try:
        auth_message = await start_auth_flow(
            user_google_email=user_google_email,
            service_name=service_name,
            redirect_uri=get_oauth_redirect_uri_for_current_mode()
        )
        return auth_message
    except Exception as e:
        logger.error(f"Failed to start Google authentication flow: {e}", exc_info=True)
        return f"**Error:** An unexpected error occurred: {e}"
