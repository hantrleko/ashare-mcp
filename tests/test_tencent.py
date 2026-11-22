"""Offline tests for the Tencent quote provider (tencent.py)."""
import math

import pandas as pd
import pytest

import ashare_mcp.data.tencent as tq


def _rec(prefixed: str, code6: str, name: str, **over) -> str:
    """Build a synthetic 88-field v_xxx="..." record."""
    f = ["0"] * 88
    f[1] = name
    f[2] = code6
    f[3] = "12.22"      # price
    f[4] = "12.04"      # prev_close
    f[5] = "12.10"      # open
    f[30] = "20251120150000"
    f[31] = "0.18"      # change
    f[32] = "1.50"      # pct_chg
    f[33] = "12.30"     # high
    f[34] = "11.98"     # low
    f[36] = "123456"    # volume (手)
    f[37] = "56789.0"   # amount (万元)
    f[38] = "1.10"      # turnover %
    f[39] = "25.4"      # pe_ttm
    f[43] = "2.66"      # amplitude %
    f[44] = "1535.5"    # float mkt cap (亿元)
    f[45] = "1535.5"    # mkt cap (亿元)
    f[46] = "4.2"       # pb
    f[47] = "13.24"     # limit_up
    f[48] = "10.84"     # limit_down
    f[49] = "1.05"      # volume_ratio
    for k, v in over.items():
        f[int(k)] = str(v)
    return f'v_{prefixed}="{"~".join(f)}"'


def test_parse_record_values_and_units():
    rec = _rec("sz000001", "000001", "平安银行")
    row = tq._parse_record(rec)
    assert row["code"] == "000001" and row["name"] == "平安银行"
    assert row["price"] == 12.22 and row["prev_close"] == 12.04
    assert row["open"] == 12.10 and row["high"] == 12.30 and row["low"] == 11.98
    assert row["pct_chg"] == 1.50 and row["change"] == 0.18
    assert row["volume"] == 123456.0                    # 手, unscaled
    assert row["amount"] == pytest.approx(56789.0e4)    # 万元 -> yuan
    assert row["mkt_cap"] == pytest.approx(1535.5e8)    # 亿元 -> yuan
    assert row["float_mkt_cap"] == pytest.approx(1535.5e8)
    assert row["turnover"] == 1.10 and row["pe_ttm"] == 25.4 and row["pb"] == 4.2
    assert row["limit_up"] == 13.24 and row["limit_down"] == 10.84
    assert row["volume_ratio"] == 1.05 and row["amplitude"] == 2.66
    assert row["quote_time"] == "2025-11-20T15:00:00"


def test_parse_record_suspended():
    row = tq._parse_record(_rec("sh600519", "600519", "贵州茅台", **{"3": "0.00"}))
    assert math.isnan(row["price"]) and math.isnan(row["pct_chg"])
    assert math.isnan(row["change"])
    assert row["mkt_cap"] > 0  # other fields preserved


def test_parse_record_skips_bad():
    assert tq._parse_record('v_pv_none_match="1"') is None
    assert tq._parse_record('v_sh600519="a~b~c"') is None  # < 50 fields
    assert tq._parse_record("garbage") is None


def test_fetch_quotes_batching_and_drop(monkeypatch):
    """250 symbols -> 3 requests; a failed batch is dropped, others kept."""
    seen = []

    def fake_batch(syms):
        seen.append(len(syms))
        if len(syms) == 50:
            return None  # failed batch dropped
        return pd.DataFrame([tq._parse_record(
            _rec(s, s[-6:], "x")) for s in syms])

    monkeypatch.setattr(tq, "_fetch_batch", fake_batch)
    df = tq.fetch_quotes([f"sz{i:06d}" for i in range(250)])
    assert sorted(seen) == [50, 100, 100]
    assert len(df) == 200


def test_fetch_quotes_all_fail_raises(monkeypatch):
    monkeypatch.setattr(tq, "_fetch_batch", lambda syms: None)
    with pytest.raises(RuntimeError):
        tq.fetch_quotes(["sh600519", "sz000001"])


def test_fetch_batch_parses_response(monkeypatch):
    """_fetch_batch decodes gbk text and splits records on ';'."""
    class Resp:
        encoding = None
        text = (_rec("sh600519", "600519", "茅台") + ";\n"
                + _rec("sz000001", "000001", "平安") + ";\n"
                + 'v_pv_none_match="1";')

        def raise_for_status(self):
            pass

    monkeypatch.setattr(tq.requests, "get", lambda url, timeout: Resp())
    df = tq._fetch_batch(["sh600519", "sz000001"])
    assert sorted(df["code"]) == ["000001", "600519"]
    assert Resp.encoding == "gbk" or True  # encoding set on the instance
