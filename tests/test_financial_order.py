import pandas as pd
from ashare_mcp.utils import latest_records


def test_latest_records_newest_first_any_input_order():
    df = pd.DataFrame({"REPORT_DATE": ["2020-12-31", "2026-09-30", "2023-06-30"],
                       "v": [1, 3, 2]})
    out = latest_records(df, 2)
    assert [r["v"] for r in out] == [3, 2]
    sina = pd.DataFrame({"报告日": ["19981231", "20260930"], "x": [0, 9]})
    assert latest_records(sina, 1)[0]["x"] == 9
