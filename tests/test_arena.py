"""Arena: migration, api keys, reasons, leaderboard, auth, rate limits.
All offline — provider calls stubbed."""
import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import ashare_mcp.web.api as api  # noqa: E402
from ashare_mcp.data.facade import market_data  # noqa: E402
from ashare_mcp.trading.accounts import AccountStore  # noqa: E402
from ashare_mcp.trading.paper import PaperAccount  # noqa: E402
from ashare_mcp.trading import arena  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return AccountStore(tmp_path / "paper.db")


@pytest.fixture
def quiet_quote(monkeypatch):
    monkeypatch.setattr(PaperAccount, "_quote",
                        lambda self, s: (10.0, 10.0, "测试股"))


# ---------- migration ----------

def test_migration_idempotent_and_defaults(store):
    s = AccountStore(store.path)  # second open re-runs migration
    s.create("旧账户", 1000, account_id="old1")
    s2 = AccountStore(store.path)  # again — no error
    row = next(a for a in s2.list() if a["id"] == "old1")
    assert row["kind"] == "manual" and row["arena"] == 0
    assert row["model"] == "" and row["created_at"]


def test_api_key_lifecycle(store):
    store.create("bot", 1e6, account_id="bot1", kind="agent",
                 model="gpt-x", arena=True)
    k = store.create_key("bot1", label="first")
    raw = k["api_key"]
    assert raw.startswith("ak_") and len(raw) > 20
    assert store.verify_key(raw) == "bot1"
    assert store.verify_key(raw + "x") is None
    # only the hash is stored
    import sqlite3
    with sqlite3.connect(store.path) as c:
        hashes = c.execute("SELECT key_hash FROM api_keys").fetchall()
    assert raw not in [h[0] for h in hashes]
    assert store.revoke_keys("bot1") >= 1
    assert store.verify_key(raw) is None
    with pytest.raises(KeyError):
        store.create_key("nope")


# ---------- reasons ----------

def test_reason_persisted_and_truncated(store, quiet_quote):
    store.create("r", 1e6, account_id="r1")
    acct = PaperAccount("r1", store)
    long_reason = "  " + "看多逻辑" * 200 + "  "
    acct.buy("600519", 100, 10.0, reason=long_reason)
    o = acct.orders()[0]
    assert o["reason"] == "看多逻辑" * 125  # trimmed to 500 chars
    assert len(o["reason"]) == 500


def test_trigger_reason_carries_to_fill(store, quiet_quote):
    store.create("r", 1e6, account_id="r2")
    acct = PaperAccount("r2", store)
    acct.add_trigger("600519", "buy", 100, 10.0, ">=",
                     reason="突破买入")
    res = acct.check_triggers()
    assert res["pending"] == 0                       # trigger fired
    assert acct.orders()[0]["reason"] == "突破买入"
    acct.add_trigger("600519", "buy", 100, 99.0, ">=")
    assert acct.triggers()[0]["reason"] == ""        # newest first, default ""


def test_arena_reset_refused(store, quiet_quote):
    store.create("bot", 1e6, account_id="ar1", kind="agent", arena=True)
    acct = PaperAccount("ar1", store)
    with pytest.raises(ValueError, match="竞技场账户不可重置"):
        acct.reset()
    # manual account still resets
    store.create("m", 1e6, account_id="m1")
    PaperAccount("m1", store).reset(50000)


# ---------- leaderboard ----------

@pytest.fixture
def two_agents(store, quiet_quote, monkeypatch):
    store.create("Alpha", 1e6, account_id="aa", kind="agent",
                 model="claude", arena=True)
    store.create("Beta", 1e6, account_id="bb", kind="agent",
                 model="gpt", arena=True)
    a = PaperAccount("aa", store)
    a.buy("600519", 100, 10.0, reason="buy A")
    a.state["positions"]["600519"]["available"] = 100  # simulate T+1
    a.state["positions"]["600519"]["today_bought"] = 0
    a._save()
    a.sell("600519", 100, 10.0, reason="sell A")  # realized loss via fees
    b = PaperAccount("bb", store)
    b.buy("000001", 100, 10.0, reason="buy B")
    # live quotes: 600519->11 (aa flat anyway), 000001->12
    df = pd.DataFrame({"code": ["600519", "000001"], "price": [11.0, 12.0]})
    monkeypatch.setattr(arena.tencent, "fetch_quotes", lambda syms: df)
    from datetime import date, timedelta
    # backdate both accounts 10 days so the benchmark window exists
    for aid in ("aa", "bb"):
        ac = PaperAccount(aid, store)
        ac.state["created_at"] = (
            date.today() - timedelta(days=10)).isoformat()
        ac._save()
    yest = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    bench = [{"date": "2019-12-31", "close": 3700.0},   # pre-anchor, trimmed
             {"date": "2020-01-02", "close": 3800.0},   # anchor (last ≤ created)
             {"date": yest, "close": 4000.0},
             {"date": today, "close": 4200.0}]
    monkeypatch.setattr(market_data, "call",
                        lambda n, *a, **k: (bench, "fake"))
    return store


def test_leaderboard_metrics(two_agents):
    lb = arena.leaderboard("sh000300", two_agents)
    rows = {r["id"]: r for r in lb["agents"]}
    assert set(rows) == {"aa", "bb"}
    # bb: cash 999kish + 100*12 = 1.0012m → return > aa's (which lost fees)
    assert rows["bb"]["return"] > rows["aa"]["return"]
    assert lb["agents"][0]["id"] == "bb" and lb["agents"][0]["rank"] == 1
    assert rows["bb"]["sharpe"] is None          # <10 equity points
    assert rows["aa"]["num_trades"] == 2
    assert rows["aa"]["win_rate"] == 0.0          # one sell, pnl<0 (fees)
    assert rows["bb"]["position_count"] == 1
    assert rows["bb"]["turnover"] > 0
    assert "as_of" in lb and lb["benchmark"] == "sh000300"
    # anchor = close on/before created (2020-01-02: 3800) → bench +10.5%
    assert abs(rows["bb"]["excess"]
               - (rows["bb"]["return"] - (4200 / 3800 - 1))) < 1e-4
    # bench_series trimmed to earliest anchor — the 2019 point is gone
    assert lb["bench_series"][0]["date"] == "2020-01-02"


def test_agent_detail(two_agents):
    d = arena.agent_detail("bb", "sh000300", two_agents)
    assert d["name"] == "Beta" and d["model"] == "gpt"
    assert d["positions"][0]["code"] == "000001"
    assert d["positions"][0]["last_price"] == 12.0
    assert d["trades"][0]["reason"] == "buy B"
    assert d["series"] and "benchmark" in d["series"][0]
    with pytest.raises(KeyError):
        arena.agent_detail("nope", store=two_agents)


def test_detail_anchor_normalization(two_agents):
    d = arena.agent_detail("bb", "sh000300", two_agents)
    # series starts at creation date, flat at initial capital
    from datetime import date, timedelta
    created = (date.today() - timedelta(days=10)).isoformat()
    assert d["series"][0]["date"] == created
    assert d["series"][0]["equity"] == pytest.approx(d["initial_capital"])
    # benchmark normalized to initial capital at the anchor —
    # the first point is exactly initial capital, nothing before anchor
    assert d["series"][0]["benchmark"] == pytest.approx(
        d["initial_capital"])
    anchor = "2020-01-02"
    assert all(pt["date"] >= anchor for pt in d["series"])
    # leaderboard excess uses the same anchor (bench 3800→4200 = +10.5%)
    lb = arena.leaderboard("sh000300", two_agents)
    row = next(r for r in lb["agents"] if r["id"] == "bb")
    assert row["excess"] == pytest.approx(d["excess"], abs=1e-6)


# ---------- public-mode auth + rate limits ----------

@pytest.fixture
def pub_client(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "call",
                        lambda n, *a, **k: ([{"date": "2020-01-02",
                                              "close": 4000.0}], "fake"))
    monkeypatch.setattr(PaperAccount, "_quote",
                        lambda self, s: (10.0, 10.0, "测试股"))
    monkeypatch.setattr(arena.tencent, "fetch_quotes",
                        lambda syms: pd.DataFrame())
    api._store = AccountStore(tmp_path / "paper.db")
    api._accts.clear(); api._locks.clear(); api._cache._store.clear()
    monkeypatch.setattr(api, "PUBLIC", True)
    monkeypatch.setattr(api, "_ADMIN_KEY", "admin-secret")
    c = TestClient(api.app)
    yield c
    api._store = None; api._accts.clear(); api._locks.clear()
    api._buckets.clear()


def _reg(c, name="bot"):
    r = c.post("/api/arena/agents",
               json={"name": name, "model": "m"},
               headers={"Authorization": "Bearer admin-secret"})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["account"]["id"], body["api_key"]


def test_public_auth_matrix(pub_client):
    # GET open
    assert pub_client.get("/api/health").status_code == 200
    assert pub_client.get("/api/accounts").status_code == 200
    # mutation without key → 401
    assert pub_client.post("/api/paper/buy",
                           json={"symbol": "600519", "shares": 100}
                           ).status_code == 401
    # invalid key → 401
    assert pub_client.post("/api/paper/buy",
                           json={"symbol": "600519", "shares": 100},
                           headers={"Authorization": "Bearer ak_bad"}
                           ).status_code == 401
    # admin registers agent
    acct, key = _reg(pub_client)
    # agent on own account → 200
    h = {"Authorization": f"Bearer {key}"}
    r = pub_client.post(f"/api/paper/buy?account={acct}",
                        json={"symbol": "600519", "shares": 100,
                              "reason": "t"}, headers=h)
    assert r.status_code == 200, r.text
    # agent on another account → 403
    assert pub_client.post("/api/paper/buy?account=default",
                           json={"symbol": "600519", "shares": 100},
                           headers=h).status_code == 403
    # agent cannot create accounts/keys → 403
    assert pub_client.post("/api/accounts", json={"name": "x"},
                           headers=h).status_code == 403
    assert pub_client.post(f"/api/arena/agents/{acct}/keys",
                           headers=h).status_code == 403
    # admin can
    assert pub_client.post(f"/api/arena/agents/{acct}/keys",
                           headers={"Authorization": "Bearer admin-secret"}
                           ).status_code == 200
    n = pub_client.post(f"/api/arena/agents/{acct}/keys/revoke",
                        headers={"Authorization": "Bearer admin-secret"})
    assert n.status_code == 200 and n.json()["revoked"] >= 1
    # revoked key no longer works
    assert pub_client.post(f"/api/paper/buy?account={acct}",
                           json={"symbol": "600519", "shares": 100},
                           headers=h).status_code == 401


def test_arena_register_local_open(tmp_path, monkeypatch):
    """Local mode: no key needed."""
    api._store = AccountStore(tmp_path / "paper.db")
    api._accts.clear(); api._locks.clear()
    monkeypatch.setattr(api, "PUBLIC", False)
    c = TestClient(api.app)
    try:
        r = c.post("/api/arena/agents",
                   json={"name": "bot", "model": "m", "id": "bot1"})
        assert r.status_code == 200
        assert r.json()["account"]["id"] == "bot1"
        # and arena reset → 400 via API
        assert c.post("/api/paper/reset?account=bot1",
                      json={"capital": 1e6}).status_code == 400
    finally:
        api._store = None; api._accts.clear(); api._locks.clear()


def test_auth_me(pub_client, tmp_path, monkeypatch):
    r = pub_client.get("/api/auth/me").json()
    assert r == {"public": True, "role": "anonymous", "account": None}
    assert pub_client.get("/api/auth/me", headers={
        "Authorization": "Bearer admin-secret"}).json()["role"] == "admin"
    acct, key = _reg(pub_client)
    me = pub_client.get("/api/auth/me",
                        headers={"Authorization": f"Bearer {key}"}).json()
    assert me["role"] == "agent" and me["account"] == acct


def test_auth_me_local(tmp_path, monkeypatch):
    api._store = AccountStore(tmp_path / "paper.db")
    monkeypatch.setattr(api, "PUBLIC", False)
    c = TestClient(api.app)
    try:
        r = c.get("/api/auth/me").json()
        assert r["public"] is False and r["role"] == "anonymous"
    finally:
        api._store = None


def test_rate_limit(pub_client, monkeypatch):
    monkeypatch.setattr(api, "RATE_GET", 3)
    for _ in range(3):
        assert pub_client.get("/api/health").status_code == 200
    r = pub_client.get("/api/health")
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    # different bucket: mutations still counted separately
    api._buckets.clear()
    monkeypatch.setattr(api, "RATE_MUT", 2)
    for _ in range(2):
        pub_client.post("/api/paper/buy",
                        json={"symbol": "x", "shares": 1})
    r = pub_client.post("/api/paper/buy",
                        json={"symbol": "x", "shares": 1})
    assert r.status_code == 429


def test_rate_limit_heavy_post_and_fake_keys(pub_client, monkeypatch):
    api._buckets.clear()
    monkeypatch.setattr(api, "RATE_HEAVY", 2)
    for _ in range(2):
        pub_client.post("/api/backtest", json={"symbol": "x"})
    assert pub_client.post("/api/backtest",
                           json={"symbol": "x"}).status_code == 429
    # rotating invalid bearer keys must not escape the per-IP mutation bucket
    api._buckets.clear()
    monkeypatch.setattr(api, "RATE_MUT", 2)
    codes = [pub_client.post("/api/paper/buy", json={"symbol": "x", "shares": 1},
                             headers={"Authorization": f"Bearer fake{i}"}).status_code
             for i in range(3)]
    assert codes[-1] == 429


def test_public_requires_admin_key(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "PUBLIC", True)
    monkeypatch.setattr(api, "_ADMIN_KEY", "")
    api._store = AccountStore(tmp_path / "paper.db")
    try:
        with pytest.raises(RuntimeError, match="ASHARE_ADMIN_KEY"):
            with TestClient(api.app):
                pass
    finally:
        api._store = None
