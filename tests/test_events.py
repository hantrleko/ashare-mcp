"""GET /api/events: trigger fill/fail events across accounts."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient  # noqa

import ashare_mcp.web.api as api
from ashare_mcp.trading.accounts import AccountStore
from ashare_mcp.trading.paper import PaperAccount


@pytest.fixture
def client(tmp_path):
    api._store = AccountStore(tmp_path / "paper.db")
    c = TestClient(api.app)
    yield c
    api._store = None
    api._accts.clear()
    api._locks.clear()


def _inject(client, account="default", **kw):
    """Write a trigger record straight into the account state."""
    store = api._account_store()
    store.create_default()
    st, rev = store.load(account)
    trig = {
        "id": kw.get("id", "t0000001"), "symbol": kw.get("symbol", "600519"),
        "side": kw.get("side", "buy"), "shares": kw.get("shares", 100),
        "condition": ">=", "trigger_price": 1.0, "note": "",
        "created_at": "2026-11-23T09:30:00", "status": "pending",
    }
    trig.update(kw)
    st.setdefault("triggers", []).append(trig)
    store.save(account, st, rev)
    return trig


def test_filled_event(client):
    _inject(client, status="filled", filled_at="2026-11-23T10:00:00",
            filled_price=1485.0)
    r = client.get("/api/events", params={"since": "2026-11-23T00:00:00"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 1
    e = body["data"][0]
    assert e["kind"] == "trigger_filled" and e["symbol"] == "600519"
    assert e["price"] == 1485.0 and e["at"] == "2026-11-23T10:00:00"
    assert e["account_id"] == "default"
    assert body["now"] >= "2026-11-23"


def test_failed_event(client):
    _inject(client, status="failed", failed_at="2026-11-23T10:05:00",
            error="买入金额超出可用现金", side="sell")
    r = client.get("/api/events", params={"since": "2026-11-23T00:00:00"})
    e = r.json()["data"][0]
    assert e["kind"] == "trigger_failed" and e["side"] == "sell"
    assert e["error"] == "买入金额超出可用现金"


def test_since_filter(client):
    _inject(client, id="old", status="filled",
            filled_at="2026-11-20T10:00:00")
    _inject(client, id="new", status="filled",
            filled_at="2026-11-23T10:00:00")
    _inject(client, id="pend")  # pending: no event
    r = client.get("/api/events", params={"since": "2026-11-21T00:00:00"})
    ids = [e["id"] for e in r.json()["data"]]
    assert ids == ["new"]


def test_real_fill_via_check(client, monkeypatch):
    """A real _eval_triggers fill records filled_at and shows up."""
    monkeypatch.setattr(PaperAccount, "_quote",
                        lambda self, s: (10.0, 10.0, "测试股"))
    client.post("/api/paper/triggers",
                json={"symbol": "600519", "side": "buy", "shares": 100,
                      "trigger_price": 10.0, "condition": "<="},
                params={"account": "default"})
    client.post("/api/paper/check", params={"account": "default"})
    r = client.get("/api/events", params={"since": "2000-01-01"})
    data = r.json()["data"]
    assert len(data) == 1 and data[0]["kind"] == "trigger_filled"
    assert data[0]["price"] == 10.0


def test_real_fail_via_check(client, monkeypatch):
    """Insufficient cash -> status failed with failed_at."""
    monkeypatch.setattr(PaperAccount, "_quote",
                        lambda self, s: (1e6, 1e6, "测试股"))
    client.post("/api/paper/triggers",
                json={"symbol": "600519", "side": "buy", "shares": 100,
                      "trigger_price": 2e6, "condition": "<="},
                params={"account": "default"})
    client.post("/api/paper/check", params={"account": "default"})
    r = client.get("/api/events", params={"since": "2000-01-01"})
    data = r.json()["data"]
    assert len(data) == 1 and data[0]["kind"] == "trigger_failed"
    assert data[0]["error"]
    # failed_at is stamped in the stored trigger
    st, _ = api._account_store().load("default")
    assert st["triggers"][0]["failed_at"]


def test_events_public_requires_admin(client, monkeypatch):
    monkeypatch.setattr(api, "PUBLIC", True)
    r = client.get("/api/events")
    assert r.status_code == 403
    r = client.get("/api/events",
                   headers={"Authorization": "Bearer x"})
    assert r.status_code == 403
    monkeypatch.setattr(api, "_ADMIN_KEY", "adm")
    r = client.get("/api/events",
                   headers={"Authorization": "Bearer adm"})
    assert r.status_code == 200
