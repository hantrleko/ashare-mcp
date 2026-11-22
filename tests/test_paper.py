"""Offline tests for PaperAccount — quote feed is stubbed, state in tmp dir."""
import pytest

from ashare_mcp.trading.accounts import AccountStore
from ashare_mcp.trading.paper import PaperAccount


@pytest.fixture
def acct(tmp_path, monkeypatch):
    a = PaperAccount(store=AccountStore(tmp_path / "paper.db"))
    a.reset(1_000_000.0)
    monkeypatch.setattr(a, "_quote",
                        lambda s: (10.0, 10.0, "测试股"))
    return a


def test_buy_lot_and_fees(acct):
    r = acct.buy("600519", 100)
    # amount 1000; fee = max(1000*0.00025, 5) + 1000*0.00001 = 5.01
    assert r["status"] == "filled"
    assert r["fee"] == pytest.approx(5.01, abs=0.01)
    assert acct.state["cash"] == pytest.approx(1_000_000 - 1005.01, abs=0.01)
    pos = acct.state["positions"]["600519"]
    assert pos["shares"] == 100 and pos["available"] == 0  # T+1


def test_buy_rejects_bad_lot(acct):
    with pytest.raises(ValueError):
        acct.buy("600519", 50)


def test_buy_insufficient_cash(acct):
    with pytest.raises(RuntimeError, match="insufficient"):
        acct.buy("600519", 9_999_900)


def test_t1_sell_block_then_rollover(acct):
    acct.buy("600519", 200)
    with pytest.raises(RuntimeError, match="T\\+1|sellable"):
        acct.sell("600519", 100)
    # simulate next trading day
    acct.state["last_date"] = "2000-01-01"
    acct._save()
    r = acct.sell("600519", 100)
    assert r["status"] == "filled"
    pos = acct.state["positions"]["600519"]
    assert pos["shares"] == 100 and pos["available"] == 100


def test_price_limit_block(acct, monkeypatch):
    # prev_close 10 -> limit-up 11 for a 10% board
    monkeypatch.setattr(acct, "_quote",
                        lambda s: (11.0, 10.0, "测试股"))
    with pytest.raises(RuntimeError, match="涨停"):
        acct.buy("600519", 100)


def test_sell_requires_position(acct):
    with pytest.raises(RuntimeError, match="no position"):
        acct.sell("600519", 100)


def test_trigger_fills_and_lists(acct, monkeypatch):
    acct.add_trigger("600519", "buy", 100, 9.5, "<=")
    assert acct.triggers()[0]["status"] == "pending"
    # price drops below trigger -> fills on check
    monkeypatch.setattr(acct, "_quote", lambda s: (9.4, 10.0, "测试股"))
    res = acct.check_triggers()
    t = res["triggers"][0]
    assert t["status"] == "filled" and t["filled_price"] == 9.4
    assert acct.state["positions"]["600519"]["shares"] == 100


def test_trigger_cancel(acct):
    t = acct.add_trigger("600519", "buy", 100, 9.0, "<=")
    done = acct.cancel_trigger(t["id"])
    assert done["status"] == "cancelled"
    with pytest.raises(KeyError):
        acct.cancel_trigger("nope")


def test_trigger_validation(acct):
    with pytest.raises(ValueError):
        acct.add_trigger("600519", "buy", 50, 9.0, "<=")
    with pytest.raises(ValueError):
        acct.add_trigger("600519", "hold", 100, 9.0, "<=")


def test_reset_clears(acct):
    acct.buy("600519", 100)
    acct.reset(500_000.0)
    assert acct.state["cash"] == 500_000.0
    assert acct.state["positions"] == {}
    assert acct.state["orders"] == []
    assert acct.state["triggers"] == []


def test_equity_history_upsert(acct):
    acct.buy("600519", 100)
    st = acct.status()
    hist = acct.history()
    assert len(hist) == 1
    assert hist[0]["equity"] == st["equity"]
    # second status() on the same day replaces, not appends
    acct.status()
    assert len(acct.history()) == 1
    # a new day appends
    acct.state["history"][0]["date"] = "2000-01-01"
    acct._save()
    acct.status()
    assert len(acct.history()) == 2


def test_history_survives_old_state_file(acct, tmp_path):
    # state files written before the history feature lack the key
    del acct.state["history"]
    acct._save()
    st = acct.status()  # setdefault path, must not raise
    assert acct.history()[-1]["equity"] == st["equity"]


# ---------- multi-account ----------

def test_two_accounts_isolated(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "paper.db")
    store.create("账户B", 500_000.0, account_id="acct2")
    a1 = PaperAccount("default", store)
    a2 = PaperAccount("acct2", store)
    for a in (a1, a2):
        monkeypatch.setattr(a, "_quote", lambda s: (10.0, 10.0, "T"))
    a1.buy("600519", 100)
    assert a1.positions()[0]["code"] == "600519"
    assert a2.positions() == []
    assert a2.status()["cash"] == 500_000.0


def test_reload_sees_other_instance_writes(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "paper.db")
    a1 = PaperAccount("default", store)
    monkeypatch.setattr(a1, "_quote", lambda s: (10.0, 10.0, "T"))
    a1.buy("600519", 100)
    a2 = PaperAccount("default", store)
    monkeypatch.setattr(PaperAccount, "_quote", lambda self, s: (10.0, 10.0, "T"))
    assert a2.positions()[0]["shares"] == 100


def test_concurrent_modification_raises(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "paper.db")
    a1 = PaperAccount("default", store)
    a2 = PaperAccount("default", store)
    for a in (a1, a2):
        monkeypatch.setattr(a, "_quote", lambda s: (10.0, 10.0, "T"))
    a1.buy("600519", 100)          # rev -> 2
    a2.state["cash"] -= 1.0        # a2 holds stale rev 1
    with pytest.raises(RuntimeError, match="concurrently|修改"):
        a2._save()


def test_trigger_fill_persisted(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "paper.db")
    a = PaperAccount("default", store)
    monkeypatch.setattr(a, "_quote", lambda s: (10.0, 10.0, "T"))
    a.add_trigger("600519", "buy", 100, 9.5, "<=")
    monkeypatch.setattr(a, "_quote", lambda s: (9.4, 10.0, "T"))
    res = a.check_triggers()
    assert res["triggers"][0]["status"] == "filled"
    fresh = PaperAccount("default", store)
    monkeypatch.setattr(PaperAccount, "_quote", lambda self, s: (9.4, 10.0, "T"))
    assert fresh.triggers()[0]["status"] == "filled"
    assert fresh.state["positions"]["600519"]["shares"] == 100


def test_unknown_account_raises(tmp_path):
    store = AccountStore(tmp_path / "paper.db")
    with pytest.raises(KeyError):
        PaperAccount("nope", store)


def test_delete_default_refused(tmp_path):
    store = AccountStore(tmp_path / "paper.db")
    store.create_default()
    with pytest.raises(ValueError):
        store.delete("default")
    with pytest.raises(KeyError):
        store.delete("ghost")


def test_legacy_json_migrated(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_DATA_DIR", str(tmp_path))
    legacy = tmp_path / "paper_account.json"
    legacy.write_text('{"cash": 777.0, "initial_capital": 1000.0,'
                      ' "positions": {}, "orders": [], "triggers": [],'
                      ' "history": [], "last_date": "2025-01-01"}',
                      encoding="utf-8")
    store = AccountStore(tmp_path / "paper.db")
    state, _ = store.load("default")
    assert state["cash"] == 777.0
    assert not legacy.exists()
    assert (tmp_path / "paper_account.json.migrated").exists()


def test_store_create_validation(tmp_path):
    store = AccountStore(tmp_path / "paper.db")
    store.create("A", account_id="dup1")
    with pytest.raises(ValueError):
        store.create("B", account_id="dup1")
    with pytest.raises(ValueError):
        store.create("B", account_id="Bad Id!")
    lst = store.list()
    assert any(a["id"] == "dup1" and a["cash"] == 1_000_000.0 for a in lst)
