import asyncio
import logging

from core.server import TokenClientIdFixMiddleware


def test_token_middleware_logs_only_safe_oauth_error_fields(caplog):
    async def failing_token_app(scope, receive, send):
        await receive()
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": (
                    b'{"error":"invalid_grant",'
                    b'"error_description":"incorrect code_verifier",'
                    b'"access_token":"must-not-be-logged"}'
                ),
                "more_body": False,
            }
        )

    middleware = TokenClientIdFixMiddleware(failing_token_app)
    sent = []
    request_delivered = False

    async def receive():
        nonlocal request_delivered
        if request_delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        request_delivered = True
        return {
            "type": "http.request",
            "body": (
                b"grant_type=authorization_code&code=opaque&code_verifier=verifier"
                b"&redirect_uri=http%3A%2F%2Flocalhost%2Fcallback"
                b"&client_id=client&client_secret=secret"
            ),
            "more_body": False,
        }

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "path": "/token",
        "method": "POST",
        "headers": [(b"content-length", b"173")],
    }

    with caplog.at_level(logging.WARNING, logger="core.server"):
        asyncio.run(middleware(scope, receive, send))

    assert [message["type"] for message in sent] == [
        "http.response.start",
        "http.response.body",
    ]
    assert "oauth_token_exchange_failed" in caplog.text
    assert "error=invalid_grant" in caplog.text
    assert "description=incorrect code_verifier" in caplog.text
    assert "must-not-be-logged" not in caplog.text


def test_token_middleware_diagnostics_never_log_code_or_client(caplog):
    async def rejecting_app(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error":"invalid_grant"}',
                "more_body": False,
            }
        )

    middleware = TokenClientIdFixMiddleware(rejecting_app)
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {
            "type": "http.request",
            "body": (
                b"grant_type=authorization_code&code=private-code-value"
                b"&code_verifier=private-verifier&client_id=private-client-value"
            ),
            "more_body": False,
        }

    async def send(_message):
        return None

    scope = {
        "type": "http",
        "path": "/token",
        "method": "POST",
        "headers": [],
    }

    with caplog.at_level(logging.INFO, logger="core.server"):
        asyncio.run(middleware(scope, receive, send))

    assert "Authorization code registered=False client_match=False" in caplog.text
    assert "private-code-value" not in caplog.text
    assert "private-client-value" not in caplog.text
    assert "private-verifier" not in caplog.text
