"""Build the desktop exe: web frontend -> staged static -> PyInstaller onedir.

Usage:
    uv run --extra desktop --group build python scripts/build_desktop.py
    uv run --extra desktop --group build python scripts/build_desktop.py --data-dir E:\\market

Output: dist/desktop/ashare-desktop/  (+ ashare-desktop.json next to the exe)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "packaging" / "ashare-desktop.spec"
OUT = REPO / "dist" / "desktop"
DEFAULT_DATA_DIR = "F:\\Hermes\\data"


def _folder_size(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                    help="data dir written to ashare-desktop.json next to the exe")
    ap.add_argument("--skip-web", action="store_true",
                    help="skip the npm build/static staging step")
    args = ap.parse_args()

    t0 = time.time()
    if not args.skip_web:
        print("== building web frontend ==")
        subprocess.run([sys.executable, str(REPO / "scripts" / "build_web.py")],
                       cwd=REPO, check=True)

    print("== pyinstaller ==")
    if not (REPO / "packaging" / "ashare.ico").exists():
        subprocess.run([sys.executable, str(REPO / "scripts" / "make_icon.py")],
                       cwd=REPO, check=True)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--workpath", str(REPO / "build" / "desktop"),
         "--distpath", str(OUT), str(SPEC)],
        cwd=SPEC.parent, check=True)

    exe_dir = OUT / "ashare-desktop"
    cfg = {"data_dir": args.data_dir}
    (exe_dir / "ashare-desktop.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done in {time.time() - t0:.0f}s -> {exe_dir}")
    print(f"folder size: {_folder_size(exe_dir):.0f} MB")
    print(f"data_dir: {args.data_dir}")


if __name__ == "__main__":
    main()
