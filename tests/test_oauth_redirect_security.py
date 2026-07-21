import pytest

from auth.oauth_config import OAuthConfig


@pytest.fixture(autouse=True)
def clear_oauth_environment(monkeypatch):
    for key in (
        "GOOGLE_OAUTH_REDIRECT_URI",
        "OAUTH_CUSTOM_REDIRECT_URIS",
        "WORKSPACE_EXTERNAL_URL",
        "WORKSPACE_MCP_BASE_URI",
        "PORT",
        "WORKSPACE_MCP_PORT",
        "MCP_ENABLE_OAUTH21",
        "WORKSPACE_MCP_STATELESS_MODE",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "*",
        "https://*.example.test/oauth2callback",
        "https://example.test/*",
    ],
)
def test_wildcard_redirect_configuration_is_rejected(monkeypatch, redirect_uri):
    monkeypatch.setenv("OAUTH_CUSTOM_REDIRECT_URIS", redirect_uri)

    with pytest.raises(ValueError, match="wildcard"):
        OAuthConfig()


def test_external_redirect_must_be_https(monkeypatch):
    monkeypatch.setenv(
        "OAUTH_CUSTOM_REDIRECT_URIS", "http://external.example.test/oauth2callback"
    )

    with pytest.raises(ValueError, match="HTTPS"):
        OAuthConfig()


def test_redirect_validation_uses_exact_registered_uris(monkeypatch):
    registered = "https://registered.example.test/oauth2callback"
    monkeypatch.setenv("OAUTH_CUSTOM_REDIRECT_URIS", registered)
    config = OAuthConfig()

    assert config.validate_redirect_uri(registered) is True
    assert (
        config.validate_redirect_uri("https://unregistered.example.test/oauth2callback")
        is False
    )
    assert config.validate_redirect_uri(f"{registered}/extra") is False


def test_loopback_http_redirects_remain_supported(monkeypatch):
    monkeypatch.setenv(
        "OAUTH_CUSTOM_REDIRECT_URIS",
        "http://127.0.0.1:19090/oauth2callback,http://[::1]:19091/oauth2callback",
    )
    config = OAuthConfig()

    assert config.validate_redirect_uri("http://127.0.0.1:19090/oauth2callback")
    assert config.validate_redirect_uri("http://[::1]:19091/oauth2callback")
