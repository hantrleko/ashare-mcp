"""Run the web API + static frontend with uvicorn.

    python -m ashare_mcp.web
Env: ASHARE_WEB_HOST (default 127.0.0.1), ASHARE_WEB_PORT (default 8600).
"""
from __future__ import annotations

import os


def main() -> None:
    import argparse

    import uvicorn

    p = argparse.ArgumentParser(prog="ashare-web")
    p.add_argument("--host", default=os.environ.get("ASHARE_WEB_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("ASHARE_WEB_PORT", "8600")))
    args = p.parse_args()
    uvicorn.run("ashare_mcp.web.api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
