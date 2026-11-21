"""Offline unit tests for utils.py — no network required."""
import pandas as pd
import pytest

from ashare_mcp.utils import (
    limit_pct_for,
    normalize_date,
    normalize_symbol,
    resample_ohlcv,
)


@pytest.mark.parametrize("inp,expected", [
    ("600519", ("600519", "sh")),
    ("sh600519", ("600519", "sh")),
    ("SH600519", ("600519", "sh")),
    ("000001", ("000001", "sz")),
    ("sz000001", ("000001", "sz")),
    ("000001.SZ", ("000001", "sz")),
    ("300750", ("300750", "sz")),
    ("920001", ("920001", "bj")),
    ("430047", ("430047", "bj")),
    ("510300", ("510300", "sh")),
])
def test_normalize_symbol(inp, expected):
    assert normalize_symbol(inp) == expected


def test_normalize_symbol_invalid():
    with pytest.raises(ValueError):
        normalize_symbol("")
    with pytest.raises(ValueError):
        normalize_symbol("abc")


@pytest.mark.parametrize("inp,default,expected", [
    ("2024-01-05", None, "20240105"),
    ("20240105", None, "20240105"),
    ("2024-01", None, "20240101"),
    ("", "20200101", "20200101"),
    (None, "20200101", "20200101"),
])
def test_normalize_date(inp, default, expected):
    assert normalize_date(inp, default) == expected


def test_normalize_date_invalid():
    with pytest.raises(ValueError):
        normalize_date("2024", None)


@pytest.mark.parametrize("code,name,expected", [
    ("600519", "", 0.10),
    ("300750", "", 0.20),
    ("688981", "", 0.20),
    ("830799", "", 0.30),
    ("920001", "", 0.30),
    ("600001", "ST测试", 0.05),
    ("600001", "*ST股", 0.05),
    ("600001", "退市股", 0.05),
])
def test_limit_pct(code, name, expected):
    assert limit_pct_for(code, name) == expected


def test_resample_weekly():
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=14).strftime("%Y-%m-%d"),
        "open": range(14), "high": [x + 1 for x in range(14)],
        "low": range(14), "close": [x + 0.5 for x in range(14)],
        "volume": 100, "amount": 1000.0,
    })
    wk = resample_ohlcv(df, "weekly")
    assert len(wk) < len(df)
    # 2024-01-01 is Monday; W-FRI buckets the first week as Jan 1-5
    assert wk["high"].iloc[0] == df["high"].iloc[:5].max()
    assert wk["open"].iloc[0] == df["open"].iloc[0]


def test_resample_daily_passthrough():
    df = pd.DataFrame({"date": ["2024-01-02"], "close": [1.0]})
    assert len(resample_ohlcv(df, "daily")) == 1
