"""Offline tests for the FastAPI web layer — data facade is stubbed."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import ashare_mcp.web.api as api  # noqa: E402
from ashare_mcp.data.facade import market_data  # noqa: E402
from ashare_mcp.trading.accounts import AccountStore  # noqa: E402
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
    monkeypatch.setattr("ashare_mcp.backtest.engine._name_of",
                        lambda c: "")
    monkeypatch.setattr(PaperAccount, "_quote",
                        lambda self, s: (10.0, 10.0, "测试股"))
    api._store = AccountStore(tmp_path / "paper.db")
    api._accts.clear()
    api._locks.clear()
    api._cache._store.clear()
    c = TestClient(api.app)
    yield c
    api._store = None
    api._accts.clear()
    api._locks.clear()


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


# ---------- multi-account + scheduler ----------

def test_accounts_crud(client):
    r = client.get("/api/accounts")
    assert r.status_code == 200
    ids = [a["id"] for a in r.json()["data"]]
    assert "default" in ids

    r = client.post("/api/accounts", json={"name": "test1", "capital": 50000,
                                           "id": "test1"})
    assert r.status_code == 200 and r.json()["id"] == "test1"

    r = client.patch("/api/accounts/test1", json={"name": "改名"})
    assert r.status_code == 200
    names = {a["id"]: a["name"] for a in
             client.get("/api/accounts").json()["data"]}
    assert names["test1"] == "改名"

    r = client.delete("/api/accounts/test1")
    assert r.status_code == 200
    ids = [a["id"] for a in client.get("/api/accounts").json()["data"]]
    assert "test1" not in ids

    r = client.delete("/api/accounts/nope")
    assert r.status_code == 404
    r = client.delete("/api/accounts/default")
    assert r.status_code == 400
    r = client.post("/api/accounts", json={"name": "x", "id": "BAD ID!"})
    assert r.status_code == 400


def test_paper_unknown_account_404(client):
    r = client.get("/api/paper/status?account=nope")
    assert r.status_code == 404
    client.post("/api/accounts", json={"name": "x", "id": "x1"})
    client.delete("/api/accounts/x1")
    r = client.get("/api/paper/status?account=x1")
    assert r.status_code == 404


def test_bad_capital_400(client):
    r = client.post("/api/accounts",
                    json={"name": "x", "capital": 0, "id": "x1"})
    assert r.status_code == 400
    r = client.post("/api/paper/reset", json={"capital": -1})
    assert r.status_code == 400


def test_paper_account_isolation(client):
    client.post("/api/accounts", json={"name": "t", "id": "test1"})
    r = client.post("/api/paper/buy?account=test1",
                    json={"symbol": "600519", "shares": 100})
    assert r.status_code == 200
    st = client.get("/api/paper/status?account=test1").json()
    assert st["position_count"] == 1
    st = client.get("/api/paper/status").json()  # default unaffected
    assert st["position_count"] == 0
    pos = client.get("/api/paper/positions?account=test1").json()["data"]
    assert pos[0]["code"] == "600519"


def test_intraday(client, monkeypatch):
    def fake(name, *a, **k):
        if name == "get_intraday":
            return {"symbol": "600519", "mode": "intraday",
                    "prev_close": 1700.0,
                    "points": [{"time": "09:30", "price": 1701.0, "volume": 1e4}]}, "fake"
        return _fake_call(name, *a, **k)
    monkeypatch.setattr(market_data, "call", fake)
    api._cache._store.clear()
    r = client.get("/api/intraday/600519")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["mode"] == "intraday" and body["prev_close"] == 1700.0
    assert body["points"][0]["time"] == "09:30"


def test_scheduler_endpoint(client):
    r = client.get("/api/scheduler")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False  # ASHARE_WEB_SCHEDULER=0 in conftest
    assert "last_settlement_date" in body


def test_trigger_tick_and_settle(client, monkeypatch):
    from ashare_mcp.data import calendar as cal
    from ashare_mcp.web import scheduler

    # neutral calendar: unknown → scheduler falls back to its index check
    monkeypatch.setattr(cal, "is_trading_day", lambda d: None)
    client.get("/api/paper/status")  # lazily create the default account
    # trigger check: account with a pending trigger gets checked
    client.post("/api/accounts", json={"name": "t", "id": "test1"})
    r = client.post("/api/paper/triggers?account=test1", json={
        "symbol": "600519", "side": "buy", "shares": 100,
        "trigger_price": 20.0, "condition": "<=", "note": ""})
    assert r.status_code == 200
    n = scheduler.trigger_tick()
    assert n == 1
    trig = client.get("/api/paper/triggers?account=test1").json()["data"]
    assert trig[0]["status"] == "filled"  # price 10 <= 20 → fired

    # settle: holiday check (get_index_kline stub says last bar != today)
    today = scheduler._now().date().isoformat()
    not_today = lambda *a, **k: ([{"date": "2000-01-01"}], "fake")
    res = scheduler.settle_tick(get_index_kline=not_today)
    assert res["skipped"] == "not a trading day"

    traded = lambda *a, **k: ([{"date": today}], "fake")
    warmed = {"n": 0}
    def fake_kline(*a, **k):
        warmed["n"] += 1
        return ([], "fake")
    monkeypatch.setattr(scheduler.time, "sleep", lambda s: None)
    scheduler._state["last_settlement_date"] = None
    res = scheduler.settle_tick(force=True, get_index_kline=traded,
                                get_kline=fake_kline)
    assert len(res["accounts"]) >= 2
    assert scheduler._state["last_settlement_date"] == today


def test_market_clock(client, monkeypatch):
    from ashare_mcp.data import calendar as cal
    monkeypatch.setattr(cal, "is_trading_day", lambda d: True)
    r = client.get("/api/market-clock")
    assert r.status_code == 200
    j = r.json()
    assert j["is_trading_day"] is True
    assert "date" in j and "server_time" in j
    assert j["date"] in j["server_time"]  # server_time is China-time ISO


def test_resolve_dist_prefers_repo_dist(tmp_path, monkeypatch):
    """Dev order: repo web/dist beats the packaged static dir."""
    pkg = tmp_path / "ashare_mcp" / "web"
    (pkg / "static").mkdir(parents=True)
    (pkg / "static" / "index.html").write_text("<html/>")
    repo_dist = tmp_path / "web" / "dist"
    repo_dist.mkdir(parents=True)
    (repo_dist / "index.html").write_text("<html/>")
    monkeypatch.delenv("ASHARE_WEB_DIST", raising=False)
    monkeypatch.setattr(api, "__file__", str(pkg / "api.py"))
    monkeypatch.setattr(api, "REPO_ROOT", tmp_path)
    assert api._resolve_dist() == repo_dist


def test_resolve_dist_wheel_falls_back_to_package_static(tmp_path,
                                                         monkeypatch):
    """Installed wheel: no repo web/dist -> packaged static."""
    pkg = tmp_path / "site" / "ashare_mcp" / "web"
    (pkg / "static").mkdir(parents=True)
    (pkg / "static" / "index.html").write_text("<html/>")
    monkeypatch.delenv("ASHARE_WEB_DIST", raising=False)
    monkeypatch.setattr(api, "__file__", str(pkg / "api.py"))
    # REPO_ROOT points somewhere without web/dist
    monkeypatch.setattr(api, "REPO_ROOT", tmp_path / "nowhere")
    assert api._resolve_dist() == pkg / "static"


def test_resolve_dist_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_WEB_DIST", str(tmp_path))
    assert api._resolve_dist() == tmp_path


def test_screen_endpoint(client, monkeypatch):
    import pandas as pd
    import ashare_mcp.data.akshare_data as ad
    import ashare_mcp.research.screener as scr
    monkeypatch.setattr(ad, "_spot_df", lambda: pd.DataFrame([
        {"code6": "600519", "name": "贵州茅台", "price": 1700.0,
         "pct_chg": 1.2, "turnover": 0.4, "pe_ttm": 30.0, "pb": 10.0,
         "mkt_cap": 2.1e12, "float_mkt_cap": 2.1e12, "amount": 5e9,
         "volume_ratio": 1.1, "amplitude": 2.0},
        {"code6": "000001", "name": "平安银行", "price": 12.0,
         "pct_chg": -0.5, "turnover": 1.0, "pe_ttm": 5.0, "pb": 0.6,
         "mkt_cap": 2.3e11, "float_mkt_cap": 2.0e11, "amount": 1e9,
         "volume_ratio": 0.9, "amplitude": 1.0},
    ]))
    monkeypatch.setattr(scr, "industry_map", lambda: {})
    r = client.post("/api/screen", json={"ranges": {"pe_ttm": [0, 10]}})
    assert r.status_code == 200
    j = r.json()
    assert j["total_universe"] == 2 and j["matched"] == 1
    assert j["rows"][0]["code"] == "000001"

    r = client.post("/api/screen", json={"ranges": {"nope": [0, 1]}})
    assert r.status_code == 400


def test_industries_endpoint(client, monkeypatch):
    import ashare_mcp.research.industry as ind
    monkeypatch.setattr(ind, "list_industries",
                        lambda: [{"name": "白酒行业", "count": 20}])
    r = client.get("/api/industries")
    assert r.status_code == 200
    assert r.json()["data"][0]["name"] == "白酒行业"


def test_portfolio_and_scan_endpoints(client, monkeypatch):
    import ashare_mcp.backtest.portfolio as pf
    import ashare_mcp.backtest.engine as eng
    def _fake_pf(*a, **k):
        if len(a[0]) < 2:
            raise ValueError("need >=2 symbols")
        return {"symbols": a[0], "total_return": 0.1}
    monkeypatch.setattr(pf, "run_portfolio_backtest", _fake_pf)
    monkeypatch.setattr(eng, "scan_backtest",
                        lambda *a, **k: {"results": [], "best_is": {}})
    r = client.post("/api/backtest/portfolio", json={
        "symbols": ["600001", "000002"]})
    assert r.status_code == 200 and r.json()["total_return"] == 0.1
    r = client.post("/api/backtest/scan", json={
        "symbol": "000001", "strategy": "ma_cross",
        "grid": {"fast": [5], "slow": [20]}})
    assert r.status_code == 200
    r = client.post("/api/backtest/portfolio", json={"symbols": ["600001"]})
    assert r.status_code == 400
