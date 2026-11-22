"""MCP-over-HTTP account resolution, /mcp auth gate, allowed hosts."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ashare_mcp import auth, server
from ashare_mcp.trading.accounts import AccountStore


class _Req:
    def __init__(self, authz=""):
        self.headers = {"authorization": authz} if authz else {}


class _Ctx:
    def __init__(self, req):
        self.request_context = type("RC", (), {"request": req})()


def _ctx(req):
    return _Ctx(req)


def _pub(tmp_path, monkeypatch, admin="adm-secret"):
    store = AccountStore(tmp_path / "paper.db")
    store.create("甲", 1e6, account_id="agent1")
    key = store.create_key("agent1")["api_key"]
    monkeypatch.setattr(auth, "PUBLIC", True)
    monkeypatch.setattr(auth, "ADMIN_KEY", admin)
    monkeypatch.setattr(server, "_store_instance", store)
    return key


def test_resolve_stdio_no_context(monkeypatch):
    monkeypatch.setattr(server.mcp, "get_context",
                        lambda: (_ for _ in ()).throw(LookupError))
    assert server._resolve_account("whatever") == "whatever"


def test_resolve_local_http_unchanged(tmp_path, monkeypatch):
    _pub(tmp_path, monkeypatch)
    monkeypatch.setattr(auth, "PUBLIC", False)
    monkeypatch.setattr(server.mcp, "get_context",
                        lambda: _ctx(_Req()))
    assert server._resolve_account("other") == "other"


def test_resolve_public_matrix(tmp_path, monkeypatch):
    key = _pub(tmp_path, monkeypatch)
    # admin: unrestricted
    monkeypatch.setattr(server.mcp, "get_context",
                        lambda: _ctx(_Req("Bearer adm-secret")))
    assert server._resolve_account("other") == "other"
    assert server._resolve_account("x", admin_only=True) == "x"
    # agent: defaults map to own account; others forbidden
    monkeypatch.setattr(server.mcp, "get_context",
                        lambda: _ctx(_Req(f"Bearer {key}")))
    assert server._resolve_account("") == "agent1"
    assert server._resolve_account("default") == "agent1"
    assert server._resolve_account("agent1") == "agent1"
    with pytest.raises(PermissionError):
        server._resolve_account("other")
    with pytest.raises(PermissionError):
        server._resolve_account("agent1", admin_only=True)
    # anonymous in public: rejected
    monkeypatch.setattr(server.mcp, "get_context",
                        lambda: _ctx(_Req()))
    with pytest.raises(PermissionError):
        server._resolve_account("default")


def test_allowed_hosts_env(monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_ALLOWED_HOSTS",
                       "example.com, example.com:*")
    hosts = server._allowed_hosts()
    assert "example.com" in hosts and "example.com:*" in hosts
    assert "127.0.0.1:*" in hosts


def test_mcp_401_public(monkeypatch):
    monkeypatch.setattr("ashare_mcp.web.api.PUBLIC", True)
    monkeypatch.setattr("ashare_mcp.web.api._ADMIN_KEY", "adm-secret")
    c = TestClient(server.__dict__ and __import__(
        "ashare_mcp.web.api", fromlist=["app"]).app)
    r = c.post("/mcp/", json={"jsonrpc": "2.0", "id": 1,
                              "method": "tools/list", "params": {}})
    assert r.status_code == 401
