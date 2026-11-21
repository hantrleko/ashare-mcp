"""Paper-trading engine for A-shares with JSON persistence.

Rules modeled after mainland China A-share trading:
- lot size 100 shares (1 手)
- T+1 settlement (shares bought today cannot be sold today)
- price limits: ±10% main board, ±20% ChiNext/STAR, ±30% BSE, ±5% ST
- fees: commission 0.025% (min 5 CNY), stamp tax 0.05% on sells,
  transfer fee 0.001%
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..config import data_dir
from ..data.facade import market_data
from ..utils import limit_pct_for, normalize_symbol

COMMISSION_RATE = 0.00025
COMMISSION_MIN = 5.0
STAMP_TAX_SELL = 0.0005   # 0.05% since 2023-08-28
TRANSFER_FEE = 0.00001    # 0.001%
LOT = 100
MAX_ORDERS = 500

_STATE_PATH = data_dir() / "paper_account.json"


def _buy_fee(amount: float) -> float:
    return max(amount * COMMISSION_RATE, COMMISSION_MIN) + amount * TRANSFER_FEE


def _sell_fee(amount: float) -> float:
    return (max(amount * COMMISSION_RATE, COMMISSION_MIN)
            + amount * (STAMP_TAX_SELL + TRANSFER_FEE))


class PaperAccount:
    def __init__(self) -> None:
        self.path = _STATE_PATH
        self.state = self._load() or self._fresh(1_000_000.0)

    # ---------- persistence ----------

    def _fresh(self, capital: float) -> dict[str, Any]:
        return {
            "version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "initial_capital": float(capital),
            "cash": float(capital),
            "last_date": date.today().isoformat(),
            "positions": {},
            "orders": [],
            "triggers": [],
        }

    def _load(self) -> dict[str, Any] | None:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        for _ in range(5):  # Windows: Defender can briefly hold the file
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.05)
        os.replace(tmp, self.path)

    # ---------- helpers ----------

    def _rollover(self) -> None:
        """T+1: on a new trading day, yesterday's buys become sellable."""
        today = date.today().isoformat()
        if self.state["last_date"] == today:
            return
        for pos in self.state["positions"].values():
            pos["available"] += pos.get("today_bought", 0)
            pos["today_bought"] = 0
        self.state["last_date"] = today

    def _quote(self, symbol: str) -> tuple[float, float, str]:
        """Return (latest_price, prev_close, name); fall back to last close."""
        try:
            q, _ = market_data.call("get_quote", symbol)
            price = float(q.get("price") or 0)
            prev = float(q.get("prev_close") or 0)
            if price > 0:
                return price, prev, str(q.get("name") or "")
        except Exception:
            pass
        try:
            bars, _ = market_data.call(
                "get_kline", symbol, period="daily",
                start_date="", end_date="", adjust="")
            if bars:
                last = bars[-1]
                prev = float(bars[-2]["close"]) if len(bars) > 1 else float(last["close"])
                return float(last["close"]), prev, ""
        except Exception:
            pass
        raise RuntimeError(f"cannot get price for {symbol}")

    def _check_limit(self, code6: str, name: str, side: str,
                     price: float, prev_close: float) -> None:
        if prev_close <= 0:
            return
        pct = limit_pct_for(code6, name)
        upper = round(prev_close * (1 + pct), 2)
        lower = round(prev_close * (1 - pct), 2)
        if side == "buy" and price >= upper - 0.001:
            raise RuntimeError(f"涨停无法买入 (limit-up {upper})")
        if side == "sell" and price <= lower + 0.001:
            raise RuntimeError(f"跌停无法卖出 (limit-down {lower})")

    def _record_order(self, **kw: Any) -> None:
        order = {
            "id": uuid.uuid4().hex[:12],
            "time": datetime.now().isoformat(timespec="seconds"),
            **kw,
        }
        self.state["orders"].append(order)
        if len(self.state["orders"]) > MAX_ORDERS:
            self.state["orders"] = self.state["orders"][-MAX_ORDERS:]

    # ---------- conditional (trigger) orders ----------

    def _eval_triggers(self) -> None:
        """Fill pending triggers whose price condition is met.

        Marked 'filling' before executing so a nested buy/sell re-entering
        this loop cannot fire the same trigger twice.
        """
        for t in self.state.get("triggers", []):
            if t.get("status") != "pending":
                continue
            try:
                px, _, _ = self._quote(t["symbol"])
            except Exception:
                continue
            hit = px >= t["trigger_price"] if t["condition"] == ">=" \
                else px <= t["trigger_price"]
            if not hit:
                continue
            t["status"] = "filling"
            try:
                fn = self.buy if t["side"] == "buy" else self.sell
                res = fn(t["symbol"], t["shares"])
                t["status"] = "filled"
                t["filled_price"] = res["price"]
                t["filled_at"] = datetime.now().isoformat(timespec="seconds")
            except Exception as e:
                t["status"] = "failed"
                t["error"] = str(e)
        if self.state.get("triggers"):
            self._save()

    def add_trigger(self, symbol: str, side: str, shares: int,
                    trigger_price: float, condition: str = ">=",
                    note: str = "") -> dict[str, Any]:
        self._rollover()
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy|sell")
        if condition not in (">=", "<="):
            raise ValueError("condition must be '>=' or '<='")
        shares = int(shares)
        if shares <= 0 or shares % LOT != 0:
            raise ValueError("shares must be a positive multiple of 100")
        if float(trigger_price) <= 0:
            raise ValueError("trigger_price must be positive")
        code6, _ = normalize_symbol(symbol)
        trig = {
            "id": uuid.uuid4().hex[:8],
            "symbol": code6,
            "side": side,
            "shares": shares,
            "condition": condition,
            "trigger_price": float(trigger_price),
            "note": note,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "status": "pending",
        }
        self.state.setdefault("triggers", []).append(trig)
        self._save()
        return trig

    def cancel_trigger(self, trigger_id: str) -> dict[str, Any]:
        for t in self.state.get("triggers", []):
            if t["id"] == trigger_id:
                if t["status"] != "pending":
                    raise RuntimeError(
                        f"trigger {trigger_id} is {t['status']}, not pending")
                t["status"] = "cancelled"
                self._save()
                return t
        raise KeyError(f"no pending trigger {trigger_id}")

    def triggers(self) -> list[dict[str, Any]]:
        return list(reversed(self.state.get("triggers", [])))

    def check_triggers(self) -> dict[str, Any]:
        self._rollover()
        self._eval_triggers()
        pending = sum(1 for t in self.state.get("triggers", [])
                      if t["status"] == "pending")
        return {"triggers": self.triggers(), "pending": pending}

    # ---------- account ----------

    def reset(self, capital: float = 1_000_000.0) -> dict[str, Any]:
        self.state = self._fresh(capital)
        self._save()
        return {"status": "reset", "initial_capital": capital}

    def buy(self, symbol: str, shares: int,
            price: float | None = None) -> dict[str, Any]:
        self._rollover()
        code6, mkt = normalize_symbol(symbol)
        shares = int(shares)
        if shares <= 0 or shares % LOT != 0:
            raise ValueError("shares must be a positive multiple of 100")

        fill, prev_close, name = self._quote(symbol)
        px = float(price) if price else fill
        if px <= 0:
            raise ValueError("invalid price")
        self._check_limit(code6, name, "buy", px, prev_close)

        amount = round(px * shares, 2)
        fee = round(_buy_fee(amount), 2)
        total = round(amount + fee, 2)
        if total > self.state["cash"] + 1e-6:
            raise RuntimeError(
                f"insufficient cash: need {total:.2f}, have {self.state['cash']:.2f}")

        pos = self.state["positions"].get(code6)
        if pos is None:
            pos = {"name": name or code6, "market": mkt,
                   "shares": 0, "available": 0, "today_bought": 0,
                   "avg_cost": 0.0}
            self.state["positions"][code6] = pos
        new_qty = pos["shares"] + shares
        pos["avg_cost"] = round(
            (pos["avg_cost"] * pos["shares"] + total) / new_qty, 4)
        pos["shares"] = new_qty
        pos["today_bought"] += shares
        self.state["cash"] = round(self.state["cash"] - total, 2)

        self._record_order(symbol=code6, name=pos["name"], side="buy",
                           shares=shares, price=px, amount=amount, fee=fee,
                           status="filled")
        self._save()
        return {"status": "filled", "side": "buy", "code": code6,
                "shares": shares, "price": px, "amount": amount, "fee": fee,
                "cash": self.state["cash"]}

    def sell(self, symbol: str, shares: int,
             price: float | None = None) -> dict[str, Any]:
        self._rollover()
        code6, _ = normalize_symbol(symbol)
        shares = int(shares)
        pos = self.state["positions"].get(code6)
        if pos is None or pos["shares"] <= 0:
            raise RuntimeError(f"no position in {code6}")
        if shares <= 0:
            raise ValueError("shares must be positive")
        if shares > pos["available"]:
            raise RuntimeError(
                f"only {pos['available']} shares sellable (T+1); "
                f"{pos['today_bought']} bought today are locked")
        if shares % LOT != 0 and shares != pos["shares"]:
            raise ValueError("sell in lots of 100 unless closing the position")

        fill, prev_close, name = self._quote(symbol)
        px = float(price) if price else fill
        if px <= 0:
            raise ValueError("invalid price")
        self._check_limit(code6, name or pos.get("name", ""), "sell", px, prev_close)

        amount = round(px * shares, 2)
        fee = round(_sell_fee(amount), 2)
        proceeds = round(amount - fee, 2)

        pos["shares"] -= shares
        pos["available"] -= shares
        realized = round((px - pos["avg_cost"]) * shares - fee, 2)
        self.state["cash"] = round(self.state["cash"] + proceeds, 2)

        self._record_order(symbol=code6, name=pos.get("name", ""), side="sell",
                           shares=shares, price=px, amount=amount, fee=fee,
                           realized_pnl=realized, status="filled")
        if pos["shares"] <= 0:
            del self.state["positions"][code6]
        self._save()
        return {"status": "filled", "side": "sell", "code": code6,
                "shares": shares, "price": px, "amount": amount, "fee": fee,
                "realized_pnl": realized, "cash": self.state["cash"]}

    def _mark_positions(self) -> tuple[list[dict[str, Any]], float]:
        total = 0.0
        rows = []
        for code6, pos in self.state["positions"].items():
            try:
                px, _, _ = self._quote(code6)
            except Exception:
                px = pos["avg_cost"]
            mv = round(px * pos["shares"], 2)
            cost = round(pos["avg_cost"] * pos["shares"], 2)
            total += mv
            rows.append({
                "code": code6, "name": pos.get("name", ""),
                "shares": pos["shares"], "available": pos["available"],
                "today_bought": pos.get("today_bought", 0),
                "avg_cost": pos["avg_cost"], "last_price": px,
                "market_value": mv, "pnl": round(mv - cost, 2),
            })
        return rows, total

    def status(self) -> dict[str, Any]:
        self._rollover()
        self._eval_triggers()
        rows, mv = self._mark_positions()
        equity = round(self.state["cash"] + mv, 2)
        init = self.state["initial_capital"]
        return {
            "cash": self.state["cash"],
            "market_value": mv,
            "equity": equity,
            "initial_capital": init,
            "total_pnl": round(equity - init, 2),
            "total_return_pct": round((equity / init - 1) * 100, 2) if init else None,
            "position_count": len(rows),
        }

    def positions(self) -> list[dict[str, Any]]:
        self._rollover()
        self._eval_triggers()
        rows, _ = self._mark_positions()
        return rows

    def orders(self, limit: int = 50) -> list[dict[str, Any]]:
        orders = self.state["orders"][-max(1, min(int(limit), MAX_ORDERS)):]
        return list(reversed(orders))
