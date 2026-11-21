"""Build the bundled A-share stock-list snapshot (src/ashare_mcp/data/stock_list.csv).

Sources, in order:
1. ak.stock_info_a_code_name()             (all exchanges, one call)
2. per-exchange lists: stock_info_sh_name_code / stock_info_sz_name_code /
   stock_info_bj_name_code
3. For any exchange still missing: Sina full-market snapshot
   ak.stock_zh_a_spot_sina() (~1-2.5 min), filtered to A-share codes.

Output columns: code6,name,market  (code6 zero-padded str, market sh|sz|bj)

Run: .venv\\Scripts\\python.exe scripts\\build_stock_list.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ashare_mcp.utils import _market_of  # noqa: E402

OUT = ROOT / "src" / "ashare_mcp" / "data" / "stock_list.csv"

# A-share code prefixes worth keeping from the Sina spot snapshot
_PREFIX = ("sh60", "sh68", "sz00", "sz30", "bj43", "bj83", "bj87", "bj88", "bj92")


def _digits(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\D", "", regex=True).str[-6:]


def try_a_code_name() -> pd.DataFrame | None:
    df = ak.stock_info_a_code_name()
    code_col = next((c for c in ("A股代码", "证券代码", "代码") if c in df.columns), None)
    name_col = next((c for c in ("A股简称", "证券简称", "名称") if c in df.columns), None)
    if not (code_col and name_col):
        return None
    if "A股代码" in df.columns:
        df = df[df["A股代码"].notna()]
        code_col, name_col = "A股代码", "A股简称"
    out = pd.DataFrame({"code6": _digits(df[code_col]), "name": df[name_col].astype(str)})
    out["market"] = out["code6"].map(_market_of)
    return out.dropna()


def per_exchange() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for fn, c_col, n_col, mkt in (
        ("stock_info_sh_name_code", "证券代码", "证券简称", "sh"),
        ("stock_info_sz_name_code", "A股代码", "A股简称", "sz"),
        ("stock_info_bj_name_code", "证券代码", "证券简称", "bj"),
    ):
        try:
            d = getattr(ak, fn)()
            if c_col in d.columns and n_col in d.columns:
                out[mkt] = pd.DataFrame({
                    "code6": _digits(d[c_col]),
                    "name": d[n_col].astype(str),
                    "market": mkt,
                })
                print(f"  {fn}: {len(out[mkt])} rows")
        except Exception as e:
            print(f"  {fn}: FAILED {type(e).__name__}: {e}")
    return out


def sina_fallback(mkts: set[str]) -> pd.DataFrame:
    """Sina spot snapshot -> rows for the missing markets only."""
    print("  fetching ak.stock_zh_a_spot_sina() (slow, 1-2.5 min)…")
    df = ak.stock_zh_a_spot_sina()
    codes = df["代码"].astype(str)
    rows = []
    for mkt in mkts:
        sel = codes[codes.str.startswith(tuple(p for p in _PREFIX if p.startswith(mkt)))]
        sub = df.loc[sel.index]
        rows.append(pd.DataFrame({
            "code6": _digits(sub["代码"]),
            "name": sub["名称"].astype(str),
            "market": mkt,
        }))
        print(f"  sina spot: {len(rows[-1])} {mkt} rows")
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def main() -> None:
    frames: list[pd.DataFrame] = []
    print("trying stock_info_a_code_name…")
    try:
        df = try_a_code_name()
        if df is not None and len(df):
            frames.append(df)
            print(f"  got {len(df)} rows")
    except Exception as e:
        print(f"  FAILED {type(e).__name__}: {e}")

    have = set()
    if frames:
        have = set(frames[0]["market"].unique())
    missing = {"sh", "sz", "bj"} - have
    if missing:
        print(f"missing markets {sorted(missing)}; trying per-exchange lists…")
        pe = per_exchange()
        for mkt, d in pe.items():
            frames.append(d)
            have.add(mkt)

    missing = {"sh", "sz", "bj"} - have
    if missing:
        frames.append(sina_fallback(missing))
        have |= missing

    all_df = pd.concat(frames, ignore_index=True).dropna(subset=["code6", "name"])
    all_df = all_df[all_df["code6"].str.len() == 6]
    all_df["market"] = all_df["code6"].map(_market_of)
    all_df = all_df.drop_duplicates("code6").sort_values("code6").reset_index(drop=True)

    all_df.to_csv(OUT, index=False, encoding="utf-8")
    print(f"wrote {len(all_df)} rows -> {OUT}")
    print(all_df["market"].value_counts().to_dict())
    probe = all_df[all_df["code6"] == "600519"]
    print("600519:", probe.to_dict("records"))


if __name__ == "__main__":
    main()
