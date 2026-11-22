"""Build the React frontend and stage it inside the package so the wheel
ships it as ashare_mcp/web/static/.

Usage: uv run python scripts/build_web.py   (before `uv build`)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
DIST = WEB / "dist"
TARGET = REPO / "src" / "ashare_mcp" / "web" / "static"


def main() -> None:
    npm = "npm.cmd" if sys.platform.startswith("win") else "npm"
    subprocess.run([npm, "run", "build"], cwd=WEB, check=True)
    if not (DIST / "index.html").is_file():
        raise SystemExit("web/dist/index.html missing after npm build")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(DIST, TARGET)
    print(f"staged {TARGET} ({sum(1 for _ in TARGET.rglob('*'))} entries)")


if __name__ == "__main__":
    main()
