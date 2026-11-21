"""Run the web API + static frontend with uvicorn.

    python -m ashare_mcp.web
Env: ASHARE_WEB_HOST (default 127.0.0.1), ASHARE_WEB_PORT (default 8600).
"""
from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("ASHARE_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("ASHARE_WEB_PORT", "8600"))
    uvicorn.run("ashare_mcp.web.api:app", host=host, port=port)


if __name__ == "__main__":
    main()
