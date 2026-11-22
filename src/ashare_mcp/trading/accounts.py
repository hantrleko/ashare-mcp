"""Multi-account storage for paper trading — SQLite, optimistic rev check.

``data_dir()/paper.db`` is user state (NOT disposable). Each account's full
state dict is serialized into ``state_json``; concurrent writers are
rejected via a monotonically increasing ``rev``.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..config import data_dir

_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
LEGACY_JSON = "paper_account.json"

_DDL = """
CREATE TABLE IF NOT EXISTS accounts(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT,
  updated_at TEXT,
  rev INTEGER NOT NULL DEFAULT 0,
  state_json TEXT NOT NULL);
"""


def _conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_DDL)
    return conn


class AccountStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else data_dir() / "paper.db"
        self._migrate()

    # ---------- schema / migration ----------

    def _migrate(self) -> None:
        legacy = data_dir() / LEGACY_JSON
        with _conn(self.path) as c:
            has_default = c.execute(
                "SELECT 1 FROM accounts WHERE id='default'").fetchone()
        if has_default or not legacy.exists():
            return
        try:
            state = json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            return
        now = datetime.now().isoformat(timespec="seconds")
        with _conn(self.path) as c:
            c.execute(
                "INSERT INTO accounts VALUES (?,?,?,?,?,?)",
                ("default", "默认账户", now, now, 0, json.dumps(state,
                                                              ensure_ascii=False)))
        legacy.rename(legacy.with_suffix(".json.migrated"))

    # ---------- CRUD ----------

    def list(self) -> list[dict[str, Any]]:
        with _conn(self.path) as c:
            rows = c.execute(
                "SELECT id, name, created_at, updated_at, state_json "
                "FROM accounts ORDER BY created_at, id").fetchall()
        out = []
        for aid, name, created, updated, sj in rows:
            st = json.loads(sj)
            hist = st.get("history") or []
            out.append({
                "id": aid, "name": name,
                "created_at": created, "updated_at": updated,
                "initial_capital": st.get("initial_capital"),
                "cash": st.get("cash"),
                "last_equity": hist[-1].get("equity") if hist else None,
                "position_count": len(st.get("positions") or {}),
            })
        return out

    def create(self, name: str, capital: float = 1_000_000.0,
               account_id: str | None = None) -> dict[str, Any]:
        aid = account_id or uuid.uuid4().hex[:8]
        if not _ID_RE.match(aid):
            raise ValueError(f"invalid account id {aid!r} (a-z0-9_- max 32)")
        if not str(name).strip():
            raise ValueError("name is required")
        if float(capital) <= 0:
            raise ValueError("capital must be positive")
        state = _fresh_state(float(capital))
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with _conn(self.path) as c:
                c.execute(
                    "INSERT INTO accounts VALUES (?,?,?,?,?,?)",
                    (aid, name.strip(), now, now, 0,
                     json.dumps(state, ensure_ascii=False)))
        except sqlite3.IntegrityError:
            raise ValueError(f"account id {aid!r} already exists")
        return {"id": aid, "name": name.strip(), "created_at": now,
                "updated_at": now, "initial_capital": float(capital),
                "cash": float(capital), "last_equity": None,
                "position_count": 0}

    def rename(self, account_id: str, name: str) -> dict[str, Any]:
        if not str(name).strip():
            raise ValueError("name is required")
        now = datetime.now().isoformat(timespec="seconds")
        with _conn(self.path) as c:
            n = c.execute(
                "UPDATE accounts SET name=?, updated_at=? WHERE id=?",
                (name.strip(), now, account_id)).rowcount
        if not n:
            raise KeyError(f"unknown account {account_id!r}")
        return {"id": account_id, "name": name.strip(), "updated_at": now}

    def delete(self, account_id: str) -> dict[str, Any]:
        if account_id == "default":
            raise ValueError("cannot delete the default account")
        with _conn(self.path) as c:
            n = c.execute("DELETE FROM accounts WHERE id=?",
                          (account_id,)).rowcount
        if not n:
            raise KeyError(f"unknown account {account_id!r}")
        return {"deleted": account_id}

    def exists(self, account_id: str) -> bool:
        with _conn(self.path) as c:
            return bool(c.execute("SELECT 1 FROM accounts WHERE id=?",
                                  (account_id,)).fetchone())

    # ---------- state load/save ----------

    def load(self, account_id: str) -> tuple[dict[str, Any], int]:
        with _conn(self.path) as c:
            row = c.execute("SELECT state_json, rev FROM accounts WHERE id=?",
                            (account_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown account {account_id!r}")
        return json.loads(row[0]), row[1]

    def create_default(self) -> None:
        """Lazily create the 'default' account with 1e6 capital."""
        if not self.exists("default"):
            self.create("默认账户", 1_000_000.0, account_id="default")

    def save(self, account_id: str, state: dict[str, Any],
             expected_rev: int) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        new_rev = expected_rev + 1
        with _conn(self.path) as c:
            n = c.execute(
                "UPDATE accounts SET state_json=?, rev=?, updated_at=? "
                "WHERE id=? AND rev=?",
                (json.dumps(state, ensure_ascii=False), new_rev, now,
                 account_id, expected_rev)).rowcount
        if not n:
            raise RuntimeError(
                "账户已被其他进程修改，请重试 / account modified concurrently, retry")
        return new_rev


def _fresh_state(capital: float) -> dict[str, Any]:
    return {
        "version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "initial_capital": capital,
        "cash": capital,
        "last_date": date.today().isoformat(),
        "positions": {},
        "orders": [],
        "triggers": [],
        "history": [],
    }
