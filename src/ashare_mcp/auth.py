"""Shared auth helpers for the web API and the MCP-over-HTTP transport.

Public mode (``ASHARE_WEB_PUBLIC=1``) requires ``ASHARE_ADMIN_KEY`` and
turns every mutating call into a Bearer-key-gated operation.  Both
`web.api` (HTTP endpoints) and `server` (MCP tools over streamable
HTTP) resolve the caller's role through this module so the rules stay
identical on either transport.
"""
from __future__ import annotations

import hmac
import os

PUBLIC = os.environ.get("ASHARE_WEB_PUBLIC") == "1"
ADMIN_KEY = os.environ.get("ASHARE_ADMIN_KEY", "")


def bearer_token(authorization_header: str) -> str:
    """Extract the token from an ``Authorization`` header value."""
    h = authorization_header or ""
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def resolve_role(raw: str, admin_key: str,
                 store=None) -> tuple[str, str | None]:
    """(role, account_id) — admin | agent | anonymous.

    ``store`` must provide ``verify_key(raw) -> account_id | None`` and
    is only consulted for non-empty, non-admin tokens.
    """
    if not raw:
        return "anonymous", None
    if admin_key and hmac.compare_digest(raw, admin_key):
        return "admin", None
    acct = store.verify_key(raw) if store is not None else None
    return ("agent", acct) if acct else ("anonymous", None)
