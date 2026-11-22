"""Build the bundled industry map (src/ashare_mcp/data/industry.csv).

Source: SW 2021 classification history via ak.stock_industry_clf_hist_sw()
(latest start_date per symbol; level-1 = first 2 digits of industry_code;
legacy SW2014 prefixes are dropped). ~97 s live, one call.

Output columns: code6,industry
Run: .venv\\Scripts\\python.exe scripts\\build_industry.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "src" / "ashare_mcp" / "data" / "industry.csv"


def main() -> None:
    from ashare_mcp.research.industry import _raw_frame, _transform, _LEGACY
    raw = _raw_frame()
    m = _transform(raw)
    df = (pd.DataFrame({"code6": list(m), "industry": list(m.values())})
          .sort_values("code6").reset_index(drop=True))
    df.to_csv(OUT, index=False, encoding="utf-8")
    n = df["industry"].nunique()
    print(f"wrote {len(df)} rows, {n} industries -> {OUT}")

    # coverage vs the bundled stock list
    stocks = pd.read_csv(ROOT / "src" / "ashare_mcp" / "data" / "stock_list.csv",
                         dtype=str)
    cur = set(stocks["code6"].str[-6:])
    mapped = cur & set(m)
    print(f"universe {len(cur)}: mapped {len(mapped)}, "
          f"unclassified {len(cur - mapped)}")
    latest = raw.sort_values("start_date").drop_duplicates("symbol", keep="last")
    latest = latest.assign(code6=latest["symbol"].astype(str).str[-6:])
    cur_rows = latest[latest["code6"].isin(cur)]
    legacy = cur_rows[cur_rows["industry_code"].astype(str).str[:2].isin(_LEGACY)]
    print(f"legacy-prefix codes in current universe: {len(legacy)}")


if __name__ == "__main__":
    main()
