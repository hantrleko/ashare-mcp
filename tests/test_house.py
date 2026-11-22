"""Built-in arena agents: universe, strategies, plan timing, execution."""
from datetime import date

import pandas as pd
import pytest

from ashare_mcp.trading import house
from ashare_mcp.trading.accounts import AccountStore
from ashare_mcp.trading.paper import PaperAccount


def _spot(n=12):
    rows = []
    for i in range(n):
        rows.append(dict(code6=f"60{i:04d}", name=f"S{i}",
                         price=10.0, pct_chg=0.0,
                         pe_ttm=10.0 + i, pb=1.0 + i * 0.1,
                         mkt_cap=(100 - i) * 1e8, turnover=1.0))
    rows[1]["pe_ttm"] = 16.0          # excluded by value filter
    rows[2]["pb"] = 2.0               # excluded by value filter
    rows[3]["name"] = "ST坏股"         # excluded from universe
    rows[4]["price"] = 0.0            # suspended
    return pd.DataFrame(rows)


@pytest.fixture
def store(tmp_path):
    return AccountStore(tmp_path / "paper.db")


def test_universe_excludes_st_and_suspended(monkeypatch):
    monkeypatch.setattr(house.ad, "_spot_df", _spot)
    u = house._universe()
    assert "ST坏股" not in set(u["name"])
    assert f"60{4:04d}" not in set(u["code6"])
    assert len(u) == 10


def test_value_targets(monkeypatch):
    monkeypatch.setattr(house.ad, "_spot_df", _spot)
    t = house._value_targets(house._universe())
    codes = {x["code"] for x in t}
    assert f"60{1:04d}" not in codes and f"60{2:04d}" not in codes
    assert t[0]["rank"] == 1 and "低估值" in t[0]["note"]
    assert all(x["metrics"]["pe_ttm"] <= 15 for x in t)


def _clines():
    # 61 bars; code A trending, code B flat (fails trend filter)
    up = [10 + i * 0.1 for i in range(61)]
    flat = [10.0] * 61
    return {"600111": up, "600222": flat}


def test_trend_and_momentum_targets():
    names = {"600111": "A", "600222": "B"}
    t = house._trend_targets(_clines(), names)
    assert [x["code"] for x in t] == ["600111"]
    assert t[0]["metrics"]["ret20"] > 0 and "趋势跟踪" in t[0]["note"]
    m = house._momentum_targets(_clines(), names)
    assert m[0]["code"] == "600111" and "动量" in m[0]["note"]


def test_plan_due_calendar(monkeypatch):
    days = ["2026-11-20", "2026-11-23", "2026-11-30", "2026-12-01"]
    monkeypatch.setattr(house.cal, "_days", lambda: days)
    # Fri 2026-11-20 -> next trading Mon 11-23, new ISO week -> due
    assert house.plan_due("W", date(2026, 11, 20)) is True
    # Mon 11-30 -> next Tue 12-01, same ISO week -> not due
    assert house.plan_due("W", date(2026, 11, 30)) is False
    # 11-20 monthly: next 11-23 same month -> no; fake month boundary:
    days2 = ["2026-11-27", "2026-12-01"]
    monkeypatch.setattr(house.cal, "_days", lambda: days2)
    assert house.plan_due("M", date(2026, 11, 27)) is True


def test_plan_due_fallback(monkeypatch):
    monkeypatch.setattr(house.cal, "_days", lambda: None)
    assert house.plan_due("W", date(2026, 11, 20)) is True   # Friday
    assert house.plan_due("W", date(2026, 11, 19)) is False
    assert house.plan_due("M", date(2026, 11, 30)) is True   # Mon is Dec
    assert house.plan_due("M", date(2026, 11, 15)) is False


def test_enable_creates_three_once(store, monkeypatch):
    monkeypatch.setattr(house.ad, "_spot_df", _spot)
    monkeypatch.setattr(house, "fetch_closes", lambda codes: _clines())
    r = house.enable(store, today=date(2026, 11, 20))
    assert set(r["created"]) == set(house.AGENTS)
    r2 = house.enable(store, today=date(2026, 11, 20))
    assert r2["created"] == []
    kinds = {a["id"]: a["kind"] for a in store.list()}
    assert all(kinds[a] == "house" for a in house.AGENTS)
    assert all(store.meta(a)["arena"] for a in house.AGENTS)


def _mk_acct(store, aid, monkeypatch, prices):
    acct = PaperAccount(aid, store)
    monkeypatch.setattr(PaperAccount, "_quote",
                        lambda self, s: (prices.get(s, 10.0), 10.0, "N"))
    return acct


def test_execution_sells_then_buys(store, monkeypatch):
    monkeypatch.setattr(house.ad, "_spot_df", _spot)
    monkeypatch.setattr(house.cal, "_days", lambda: None)
    store.create("趋势跟踪", 1e6, account_id="house_trend",
                 kind="house", model="规则策略", arena=True)
    acct = _mk_acct(store, "house_trend", monkeypatch,
                    {"600111": 10.0, "600999": 10.0})
    # seed an off-target position (rolled to be sellable)
    acct.buy("600999", 100)
    st, rev = store.load("house_trend")
    st["last_date"] = "2000-01-01"      # force rollover -> available
    store.save("house_trend", st, rev)
    acct = PaperAccount("house_trend", store)

    closes = {c: [10 + i * 0.1 for i in range(61)] for c in
              ["600111", "600222", "600333"]}
    plan = house.run_plan("house_trend", date(2026, 11, 20),
                          store=store, closes=closes,
                          spot=_spot())
    assert plan["status"] == "planned"
    assert plan["exec_date"] == "2026-11-23"   # next weekday
    res = house.run_execute("house_trend", date(2026, 11, 23),
                            store=store, acct=acct)
    assert res["status"] == "executed"
    logs = res["log"]
    acts = [(l["action"], l["code"]) for l in logs]
    assert ("sell", "600999") in acts                # sells happen
    buys = [l for l in logs if l["action"] == "buy" and l.get("ok")]
    assert buys                                   # buys after sells
    assert all(l["shares"] % 100 == 0 for l in buys)
    # reasons attached to orders
    orders = acct.state["orders"]
    assert any(o["reason"].startswith("周度调仓") for o in orders)
    assert any(o["reason"].startswith("调出") for o in orders)


def test_execute_failure_logged_not_raised(store, monkeypatch):
    store.create("趋势跟踪", 1e6, account_id="house_trend",
                 kind="house", arena=True)
    acct = PaperAccount("house_trend", store)
    monkeypatch.setattr(house.ad, "_spot_df", _spot)
    monkeypatch.setattr(house.cal, "_days", lambda: None)

    monkeypatch.setattr(PaperAccount, "_quote",
                        lambda self, s: (10.0, 10.0, "涨停股"))
    closes = {c: [10 + i * 0.1 for i in range(61)] for c in ["BAD", "600222"]}
    house.run_plan("house_trend", date(2026, 11, 20),
                   store=store, closes=closes, spot=_spot())
    orig = PaperAccount._check_limit

    def _chk(self, c6, n, side, px, prev):
        if c6 == "BAD" and side == "buy":
            raise RuntimeError("涨停无法买入")
        return orig(self, c6, n, side, px, prev)
    monkeypatch.setattr(PaperAccount, "_check_limit", _chk)
    res = house.run_execute("house_trend", date(2026, 11, 23),
                            store=store, acct=acct)
    assert res is not None
    errs = [l for l in res["log"] if "error" in l]
    assert any("BAD" in l["code"] for l in errs)


def test_plan_and_execute_idempotent(store, monkeypatch):
    monkeypatch.setattr(house.ad, "_spot_df", _spot)
    monkeypatch.setattr(house.cal, "_days", lambda: None)
    store.create("动量", 1e6, account_id="house_momentum",
                 kind="house", arena=True)
    closes = {"600111": [10 + i * 0.1 for i in range(61)]}
    p1 = house.run_plan("house_momentum", date(2026, 11, 20),
                        store=store, closes=closes, spot=_spot())
    p2 = house.run_plan("house_momentum", date(2026, 11, 20),
                        store=store, closes={}, spot=_spot())
    assert p1["targets"] == p2["targets"]          # re-run returns stored
    monkeypatch.setattr(PaperAccount, "_quote",
                        lambda self, s: (10.0, 10.0, "N"))
    acct = PaperAccount("house_momentum", store)
    assert house.run_execute("house_momentum", date(2026, 11, 23),
                             store=store, acct=acct) is not None
    assert house.run_execute("house_momentum", date(2026, 11, 23),
                             store=store, acct=acct) is None  # done


def test_plans_for(store, monkeypatch):
    monkeypatch.setattr(house.ad, "_spot_df", _spot)
    monkeypatch.setattr(house.cal, "_days", lambda: None)
    store.create("动量", 1e6, account_id="house_momentum",
                 kind="house", arena=True)
    house.run_plan("house_momentum", date(2026, 11, 20), store=store,
                   closes={"600111": [10 + i * 0.1 for i in range(61)]},
                   spot=_spot())
    ps = house.plans_for(store, "house_momentum")
    assert len(ps) == 1 and ps[0]["status"] == "planned"
    assert ps[0]["targets"][0]["code"] == "600111"
