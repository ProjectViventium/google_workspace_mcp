import pytest
from pathlib import Path

from core.config import resolve_http_bind_host


@pytest.fixture(autouse=True)
def clear_bind_environment(monkeypatch):
    monkeypatch.delenv("WORKSPACE_MCP_BIND_HOST", raising=False)
    monkeypatch.delenv("WORKSPACE_MCP_ALLOW_REMOTE_BIND", raising=False)


def test_streamable_http_defaults_to_ipv4_loopback():
    assert resolve_http_bind_host() == "127.0.0.1"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.42.0.1", "::1"])
def test_loopback_bind_does_not_need_remote_opt_in(monkeypatch, host):
    monkeypatch.setenv("WORKSPACE_MCP_BIND_HOST", host)

    assert resolve_http_bind_host() == host


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.10", "mcp.example.test"])
def test_remote_bind_is_rejected_without_explicit_opt_in(monkeypatch, host):
    monkeypatch.setenv("WORKSPACE_MCP_BIND_HOST", host)

    with pytest.raises(ValueError, match="WORKSPACE_MCP_ALLOW_REMOTE_BIND=true"):
        resolve_http_bind_host()


def test_remote_bind_is_allowed_only_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("WORKSPACE_MCP_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("WORKSPACE_MCP_ALLOW_REMOTE_BIND", "true")

    assert resolve_http_bind_host() == "0.0.0.0"


def test_supported_container_deployments_explicitly_opt_into_remote_bind():
    root = Path(__file__).resolve().parents[1]
    deployment_files = [
        root / "Dockerfile",
        root / "docker-compose.yml",
        root / "helm-chart/workspace-mcp/values.yaml",
        root / "smithery.yaml",
    ]

    for deployment_file in deployment_files:
        content = deployment_file.read_text()
        assert "WORKSPACE_MCP_BIND_HOST" in content, deployment_file
        assert "WORKSPACE_MCP_ALLOW_REMOTE_BIND" in content, deployment_file


def test_main_passes_safe_default_bind_to_streamable_http_server(
    tmp_path, monkeypatch
):
    import main as entrypoint

    captured = {}
    monkeypatch.setenv("GOOGLE_MCP_CREDENTIALS_DIR", str(tmp_path / "credentials"))
    monkeypatch.setattr(
        entrypoint.server,
        "run",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        ["workspace-mcp", "--transport", "streamable-http", "--tools"],
    )

    entrypoint.main()

    assert captured == {
        "transport": "streamable-http",
        "host": "127.0.0.1",
        "port": 8000,
    }
