"""py_mini_racer thread-safety patch — applied and idempotent."""
import pytest

mr = pytest.importorskip("py_mini_racer")

import ashare_mcp.data.akshare_data as ad  # noqa: E402


def test_patch_applied_and_idempotent():
    cls = mr.MiniRacer
    assert getattr(cls, "_ashare_lock_patched", False)
    for name in ("__init__", "eval", "execute", "call"):
        assert getattr(getattr(cls, name), "_ashare_wrapped", False)
    before = {n: getattr(cls, n) for n in ("__init__", "eval", "execute", "call")}
    ad._patch_mini_racer()  # second run must not re-wrap
    after = {n: getattr(cls, n) for n in ("__init__", "eval", "execute", "call")}
    assert before == after


def test_patched_eval_still_works():
    ctx = mr.MiniRacer()
    assert ctx.eval("1 + 1") == 2
