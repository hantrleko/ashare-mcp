"""Offline tests for the FastAPI web layer — data facade is stubbed."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import ashare_mcp.web.api as api  # noqa: E402
from ashare_mcp.data.facade import market_data  # noqa: E402
from ashare_mcp.trading.paper import PaperAccount  # noqa: E402


def _fake_bars(n=60, price=10.0):
    return [
        {"date": f"2024-01-{(i % 28) + 1:02d}", "open": price, "high": price + 1,
         "low": price - 1, "close": price + 0.5, "volume": 1_000_000,
         "amount": 1e7}
        for i in range(n)
    ]


def _fake_call(name, *args, **kwargs):
    if name == "search_stock":
        return [{"code": "600519", "name": "贵州茅台", "market": "sh"}], "fake"
    if name == "get_quote":
        return {"code": "600519", "name": "贵州茅台", "price": 1700.0,
                "prev_close": 1690.0, "pct_chg": 0.59}, "fake"
    if name == "get_quotes":
        return [{"code": s, "price": 10.0} for s in args[0]], "fake"
    if name == "get_kline":
        return _fake_bars(), "fake"
    if name == "get_index_quote":
        return {"symbol": args[0], "price": 3000.0, "pct_chg": 0.1}, "fake"
    raise RuntimeError(f"unstubbed call {name}")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "call", _fake_call)
    acct = PaperAccount()
    acct.path = tmp_path / "paper.json"
    acct.reset(1_000_000.0)
    monkeypatch.setattr(acct, "_quote", lambda s: (10.0, 10.0, "测试股"))
    monkeypatch.setattr(api, "_acct", acct)
    api._cache._store.clear()
    return TestClient(api.app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_search_and_quote(client):
    r = client.get("/api/search", params={"q": "茅台"})
    assert r.status_code == 200
    assert r.json()["data"][0]["code"] == "600519"
    assert r.json()["source"] == "fake"
    r = client.get("/api/quote/600519")
    assert r.json()["data"]["price"] == 1700.0


def test_kline_and_indices(client):
    r = client.get("/api/kline/600519", params={"start": "20240101"})
    assert r.status_code == 200 and len(r.json()["data"]) == 60
    r = client.get("/api/indices")
    assert r.status_code == 200 and len(r.json()["data"]) == 9


def test_paper_buy_then_status_positions_history(client):
    r = client.post("/api/paper/buy", json={"symbol": "600519", "shares": 100})
    assert r.status_code == 200 and r.json()["status"] == "filled"
    st = client.get("/api/paper/status").json()
    assert st["position_count"] == 1
    pos = client.get("/api/paper/positions").json()["data"]
    assert pos[0]["code"] == "600519"
    hist = client.get("/api/paper/history").json()["data"]
    assert hist and hist[-1]["equity"] == st["equity"]


def test_trigger_create_and_delete(client):
    r = client.post("/api/paper/triggers", json={
        "symbol": "600519", "side": "buy", "shares": 100,
        "trigger_price": 9.0, "condition": "<=", "note": "t"})
    assert r.status_code == 200
    tid = r.json()["id"]
    r = client.delete(f"/api/paper/triggers/{tid}")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_backtest_returns_benchmark(client):
    r = client.post("/api/backtest", json={
        "symbol": "000001", "strategy": "ma_cross",
        "params": {"fast": 5, "slow": 20},
        "start": "20240101", "end": "20241231", "capital": 100000})
    assert r.status_code == 200
    body = r.json()
    assert body["equity_curve"] and body["benchmark"]
    assert "sharpe" in body


def test_bad_input_400(client):
    r = client.post("/api/paper/buy", json={"symbol": "600519", "shares": 50})
    assert r.status_code == 400
    assert "detail" in r.json()


def test_unknown_symbol_502(client, monkeypatch):
    def boom(name, *a, **k):
        raise RuntimeError("all providers failed — x")
    monkeypatch.setattr(market_data, "call", boom)
    api._cache._store.clear()
    r = client.get("/api/quote/999999")
    assert r.status_code == 502
