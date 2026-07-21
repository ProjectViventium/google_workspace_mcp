import json
import stat
from types import SimpleNamespace

import pytest
from google.oauth2.credentials import Credentials
from mcp.server.auth.provider import RefreshToken
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull
from pydantic import AnyUrl

from auth.credential_store import (
    CredentialStorageSecurityError,
    LocalDirectoryCredentialStore,
)
from auth.persistent_google_provider import PersistentGoogleProvider
from auth.secure_storage import StorageSecurityError
from core.utils import check_credentials_directory_permissions


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _credentials(token: str = "synthetic-access") -> Credentials:
    return Credentials(
        token=token,
        refresh_token="synthetic-refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="synthetic-client.apps.googleusercontent.com",
        client_secret="synthetic-client-secret",
        scopes=["scope:synthetic"],
    )


def test_local_credential_store_creates_owner_only_directory_and_file(tmp_path):
    credential_dir = tmp_path / "credentials"
    store = LocalDirectoryCredentialStore(str(credential_dir))

    assert store.store_credential("person@example.test", _credentials()) is True

    credential_file = credential_dir / "person@example.test.json"
    assert _mode(credential_dir) == 0o700
    assert _mode(credential_file) == 0o600
    assert store.get_credential("person@example.test").token == "synthetic-access"


def test_local_credential_store_repairs_owned_legacy_modes_before_read(tmp_path):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o755)
    credential_file = credential_dir / "person@example.test.json"
    credential_file.write_text(
        json.dumps(
            {
                "token": "legacy-synthetic-access",
                "refresh_token": "legacy-synthetic-refresh",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "synthetic-client.apps.googleusercontent.com",
                "client_secret": "synthetic-client-secret",
                "scopes": ["scope:synthetic"],
                "expiry": None,
            }
        )
    )
    credential_file.chmod(0o644)

    loaded = LocalDirectoryCredentialStore(str(credential_dir)).get_credential(
        "person@example.test"
    )

    assert loaded is not None
    assert loaded.token == "legacy-synthetic-access"
    assert _mode(credential_dir) == 0o700
    assert _mode(credential_file) == 0o600


def test_local_credential_store_rejects_symlink_directory_without_touching_target(
    tmp_path,
):
    actual_dir = tmp_path / "actual"
    actual_dir.mkdir()
    linked_dir = tmp_path / "credentials"
    linked_dir.symlink_to(actual_dir, target_is_directory=True)

    store = LocalDirectoryCredentialStore(str(linked_dir))

    with pytest.raises(CredentialStorageSecurityError, match="symbolic link"):
        store.store_credential("person@example.test", _credentials())
    assert list(actual_dir.iterdir()) == []


def test_startup_permission_check_rejects_symlink_directory_without_probe_write(
    tmp_path,
):
    actual_dir = tmp_path / "actual"
    actual_dir.mkdir()
    linked_dir = tmp_path / "credentials"
    linked_dir.symlink_to(actual_dir, target_is_directory=True)

    with pytest.raises(StorageSecurityError, match="symbolic link"):
        check_credentials_directory_permissions(str(linked_dir))

    assert list(actual_dir.iterdir()) == []


def test_local_credential_store_rejects_symlink_file_without_touching_target(tmp_path):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    unrelated = tmp_path / "unrelated.json"
    unrelated.write_text("do-not-touch")
    linked_file = credential_dir / "person@example.test.json"
    linked_file.symlink_to(unrelated)

    store = LocalDirectoryCredentialStore(str(credential_dir))

    with pytest.raises(CredentialStorageSecurityError, match="symbolic link"):
        store.store_credential("person@example.test", _credentials())
    assert unrelated.read_text() == "do-not-touch"


def test_atomic_credential_write_preserves_old_state_when_replace_is_interrupted(
    tmp_path, monkeypatch
):
    credential_dir = tmp_path / "credentials"
    store = LocalDirectoryCredentialStore(str(credential_dir))
    assert store.store_credential("person@example.test", _credentials("old")) is True
    credential_file = credential_dir / "person@example.test.json"
    before = credential_file.read_bytes()

    import auth.secure_storage as secure_storage

    def interrupted_replace(*args, **kwargs):
        raise OSError("synthetic interruption before atomic replace")

    monkeypatch.setattr(secure_storage.os, "replace", interrupted_replace)

    assert store.store_credential("person@example.test", _credentials("new")) is False
    assert credential_file.read_bytes() == before
    assert list(credential_dir.glob(".*.tmp-*")) == []


def test_refresh_token_state_is_owner_only_and_atomic(tmp_path, monkeypatch):
    token_dir = tmp_path / "oauth-proxy-tokens"
    token_dir.mkdir(mode=0o755)
    token_file = token_dir / "google_refresh_tokens.json"

    provider = object.__new__(PersistentGoogleProvider)
    provider._refresh_token_state_path = token_file
    provider._refresh_tokens = {
        "synthetic-refresh": RefreshToken(
            token="synthetic-refresh",
            client_id="synthetic-client",
            scopes=["scope:synthetic"],
            expires_at=None,
        )
    }
    provider._persist_refresh_tokens()

    assert _mode(token_dir) == 0o700
    assert _mode(token_file) == 0o600
    before = token_file.read_bytes()

    import auth.secure_storage as secure_storage

    def interrupted_replace(*args, **kwargs):
        raise OSError("synthetic interruption before atomic replace")

    monkeypatch.setattr(secure_storage.os, "replace", interrupted_replace)
    provider._refresh_tokens["second-synthetic-refresh"] = RefreshToken(
        token="second-synthetic-refresh",
        client_id="synthetic-client",
        scopes=["scope:synthetic"],
        expires_at=None,
    )

    with pytest.raises(OSError, match="synthetic interruption"):
        provider._persist_refresh_tokens()
    assert token_file.read_bytes() == before
    assert list(token_dir.glob(".*.tmp-*")) == []


def test_preseeded_oauth_client_secret_json_is_exact_owner_only_and_atomic(
    tmp_path, monkeypatch
):
    import fastmcp
    from core.server import _preseed_upstream_client

    monkeypatch.setattr(fastmcp.settings, "home", tmp_path)
    config = SimpleNamespace(
        client_id="synthetic-client.apps.googleusercontent.com",
        client_secret="synthetic-secret",
        redirect_uri="http://127.0.0.1:8000/oauth2callback",
        get_redirect_uris=lambda: [
            "http://127.0.0.1:8000/oauth2callback",
            "https://registered.example.test/oauth2callback",
        ],
    )

    _preseed_upstream_client(object(), config)

    client_dir = tmp_path / "oauth-proxy-clients"
    client_files = list(client_dir.glob("*.json"))
    assert len(client_files) == 1
    assert _mode(client_dir) == 0o700
    assert _mode(client_files[0]) == 0o600
    payload = json.loads(client_files[0].read_text())
    assert payload["data"]["allowed_redirect_uri_patterns"] == [
        "http://127.0.0.1:8000/oauth2callback",
        "https://registered.example.test/oauth2callback",
    ]

    before = client_files[0].read_bytes()
    config.client_secret = "replacement-synthetic-secret"
    import auth.secure_storage as secure_storage

    def interrupted_replace(*args, **kwargs):
        raise OSError("synthetic interruption before atomic replace")

    monkeypatch.setattr(secure_storage.os, "replace", interrupted_replace)
    _preseed_upstream_client(object(), config)
    assert client_files[0].read_bytes() == before
    assert list(client_dir.glob(".*.tmp-*")) == []


def test_preseeded_oauth_client_rejects_symlink_without_touching_target(
    tmp_path, monkeypatch
):
    import fastmcp
    from core.server import _preseed_upstream_client

    monkeypatch.setattr(fastmcp.settings, "home", tmp_path)
    client_dir = tmp_path / "oauth-proxy-clients"
    client_dir.mkdir(mode=0o700)
    outside = tmp_path / "outside.json"
    outside.write_text("do-not-touch")
    unsafe = client_dir / "synthetic-client_apps_googleusercontent_com.json"
    unsafe.symlink_to(outside)
    config = SimpleNamespace(
        client_id="synthetic-client.apps.googleusercontent.com",
        client_secret="synthetic-secret",
        redirect_uri="http://127.0.0.1:8000/oauth2callback",
        get_redirect_uris=lambda: ["http://127.0.0.1:8000/oauth2callback"],
    )

    with pytest.raises(StorageSecurityError, match="symbolic link"):
        _preseed_upstream_client(object(), config)

    assert outside.read_text() == "do-not-touch"


def test_external_client_secret_json_must_be_regular_owner_only_file(tmp_path):
    from auth.google_auth import load_client_secrets

    secret_file = tmp_path / "client_secret.json"
    secret_file.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "synthetic-client",
                    "client_secret": "synthetic-secret",
                }
            }
        )
    )
    secret_file.chmod(0o644)

    with pytest.raises(StorageSecurityError, match="mode 0600"):
        load_client_secrets(str(secret_file))

    secret_file.chmod(0o600)
    assert load_client_secrets(str(secret_file))["client_id"] == "synthetic-client"

    target = tmp_path / "target.json"
    secret_file.rename(target)
    secret_file.symlink_to(target)
    with pytest.raises(StorageSecurityError, match="symbolic link"):
        load_client_secrets(str(secret_file))


def test_credential_filename_cannot_escape_owner_only_directory(tmp_path):
    store = LocalDirectoryCredentialStore(str(tmp_path / "credentials"))

    with pytest.raises(CredentialStorageSecurityError, match="unsafe credential identity"):
        store.store_credential("../escape", _credentials())
    assert not (tmp_path / "escape.json").exists()


@pytest.mark.asyncio
async def test_dynamic_client_registration_uses_private_storage_and_exact_redirects(
    tmp_path, monkeypatch
):
    import fastmcp

    monkeypatch.setattr(fastmcp.settings, "home", tmp_path)
    registered_redirect = "https://registered.example.test/oauth2callback"
    provider = PersistentGoogleProvider(
        client_id="synthetic-upstream-client",
        client_secret="synthetic-upstream-secret",
        base_url="http://127.0.0.1:8000",
        redirect_path="/oauth2callback",
        required_scopes=["openid"],
        allowed_client_redirect_uris=[registered_redirect],
    )
    client = OAuthClientInformationFull(
        client_id="synthetic-downstream-client",
        client_secret="synthetic-downstream-secret",
        redirect_uris=[AnyUrl(registered_redirect)],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="client_secret_post",
    )

    await provider.register_client(client)

    client_dir = tmp_path / "oauth-proxy-clients"
    client_files = list(client_dir.glob("*.json"))
    assert len(client_files) == 1
    assert _mode(client_dir) == 0o700
    assert _mode(client_files[0]) == 0o600
    loaded = await provider.get_client("synthetic-downstream-client")
    assert loaded is not None
    assert loaded.validate_redirect_uri(AnyUrl(registered_redirect)) == AnyUrl(
        registered_redirect
    )
    with pytest.raises(InvalidRedirectUriError, match="not registered"):
        loaded.validate_redirect_uri(
            AnyUrl("https://unregistered.example.test/oauth2callback")
        )
