"""Multi-account storage for paper trading — SQLite, optimistic rev check.

``data_dir()/paper.db`` is user state (NOT disposable). Each account's full
state dict is serialized into ``state_json``; concurrent writers are
rejected via a monotonically increasing ``rev``.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
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
CREATE TABLE IF NOT EXISTS api_keys(
  key_hash TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  label TEXT DEFAULT '',
  created_at TEXT,
  revoked INTEGER NOT NULL DEFAULT 0);
"""

# columns added after the initial schema — migrated idempotently
_NEW_COLS = {
    "kind": "TEXT NOT NULL DEFAULT 'manual'",   # manual | agent
    "model": "TEXT NOT NULL DEFAULT ''",
    "arena": "INTEGER NOT NULL DEFAULT 0",
}


def _migrate_cols(c: sqlite3.Connection) -> None:
    have = {r[1] for r in c.execute("PRAGMA table_info(accounts)")}
    for col, ddl in _NEW_COLS.items():
        if col not in have:
            c.execute(f"ALTER TABLE accounts ADD COLUMN {col} {ddl}")


def _conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_DDL)
    _migrate_cols(conn)
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
                "INSERT INTO accounts(id, name, created_at, updated_at,"
                " rev, state_json) VALUES (?,?,?,?,?,?)",
                ("default", "默认账户", now, now, 0, json.dumps(state,
                                                              ensure_ascii=False)))
        legacy.rename(legacy.with_suffix(".json.migrated"))

    # ---------- CRUD ----------

    def list(self) -> list[dict[str, Any]]:
        with _conn(self.path) as c:
            rows = c.execute(
                "SELECT id, name, created_at, updated_at, state_json, "
                "kind, model, arena "
                "FROM accounts ORDER BY created_at, id").fetchall()
        out = []
        for aid, name, created, updated, sj, kind, model, arena in rows:
            st = json.loads(sj)
            hist = st.get("history") or []
            out.append({
                "id": aid, "name": name,
                "created_at": created, "updated_at": updated,
                "kind": kind, "model": model, "arena": arena,
                "initial_capital": st.get("initial_capital"),
                "cash": st.get("cash"),
                "last_equity": hist[-1].get("equity") if hist else None,
                "position_count": len(st.get("positions") or {}),
            })
        return out



    def meta(self, account_id: str) -> dict[str, Any]:
        with _conn(self.path) as c:
            row = c.execute(
                "SELECT id, name, created_at, kind, model, arena "
                "FROM accounts WHERE id=?", (account_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown account {account_id!r}")
        return {"id": row[0], "name": row[1], "created_at": row[2],
                "kind": row[3], "model": row[4], "arena": row[5]}

    def is_arena(self, account_id: str) -> bool:
        try:
            return bool(self.meta(account_id)["arena"])
        except KeyError:
            return False

    def create(self, name: str, capital: float = 1_000_000.0,
               account_id: str | None = None, kind: str = "manual",
               model: str = "", arena: bool = False) -> dict[str, Any]:
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
                    "INSERT INTO accounts(id, name, created_at, updated_at,"
                    " rev, state_json, kind, model, arena)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (aid, name.strip(), now, now, 0,
                     json.dumps(state, ensure_ascii=False),
                     kind, model.strip(), int(bool(arena))))
        except sqlite3.IntegrityError:
            raise ValueError(f"account id {aid!r} already exists")
        return {"id": aid, "name": name.strip(), "created_at": now,
                "updated_at": now, "kind": kind, "model": model.strip(),
                "arena": int(bool(arena)),
                "initial_capital": float(capital),
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
            c.execute("DELETE FROM api_keys WHERE account_id=?",
                      (account_id,))
        if not n:
            raise KeyError(f"unknown account {account_id!r}")
        return {"deleted": account_id}

    # ---------- api keys ----------

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    def create_key(self, account_id: str, label: str = "") -> dict[str, Any]:
        """Issue ``ak_…`` — raw key returned ONCE; only sha256 is stored."""
        if not self.exists(account_id):
            raise KeyError(f"unknown account {account_id!r}")
        raw = "ak_" + secrets.token_urlsafe(24)
        now = datetime.now().isoformat(timespec="seconds")
        with _conn(self.path) as c:
            c.execute("INSERT INTO api_keys VALUES (?,?,?,?,0)",
                      (self._hash(raw), account_id, label, now))
        return {"api_key": raw, "prefix": raw[:10],
                "account_id": account_id, "label": label,
                "created_at": now}

    def verify_key(self, raw: str) -> str | None:
        """Raw key -> account_id, or None when unknown/revoked."""
        if not raw:
            return None
        with _conn(self.path) as c:
            row = c.execute(
                "SELECT account_id FROM api_keys "
                "WHERE key_hash=? AND revoked=0",
                (self._hash(raw),)).fetchone()
        return row[0] if row else None

    def revoke_keys(self, account_id: str) -> int:
        with _conn(self.path) as c:
            return c.execute(
                "UPDATE api_keys SET revoked=1 WHERE account_id=?",
                (account_id,)).rowcount

    def list_keys(self, account_id: str) -> list[dict[str, Any]]:
        with _conn(self.path) as c:
            rows = c.execute(
                "SELECT key_hash, label, created_at, revoked FROM api_keys "
                "WHERE account_id=? ORDER BY created_at",
                (account_id,)).fetchall()
        return [{"prefix": "ak_" + h[:8] + "…", "label": l,
                 "created_at": ca, "revoked": bool(r)}
                for h, l, ca, r in rows]

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
