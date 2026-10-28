#!/usr/bin/env python3
"""Build a Cardputer game into a self-contained MicroPython app .bin (engine + game frozen in).

  python build.py games/demo                # -> dist/demo.bin
  python build.py games/demo --stage-only   # just prepare the freeze folder, no Docker

Needs Docker running on this PC. The first build creates a build image (clones MicroPython,
downloads ESP-IDF, does a warm build) which takes a while; later builds reuse it.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Pinned versions. Bump here (and use --rebuild-image) to move to a newer MicroPython.
MPY_TAG = "v1.29.0"
IDF_TAG = "v5.5.2"          # ESP-IDF that MicroPython v1.29.0 builds against
DEFAULT_BOARD = "ESP32_GENERIC_S3"
IMAGE = "cardputer-engine-build"

MAIN_PY = "import engine\nimport game\nengine.run(game.Game())\n"
MANIFEST_PY = 'include("$(PORT_DIR)/boards/manifest.py")\nfreeze("/stage/frozen")\n'


def stage(game_dir, stage_dir):
    """Lay out the freeze folder: frozen/{engine,game,main.py} + manifest.py."""
    game_dir = Path(game_dir)
    if not (game_dir / "__init__.py").is_file():
        raise SystemExit("%s has no __init__.py (it must define class Game)" % game_dir)
    stage_dir = Path(stage_dir)
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    frozen = stage_dir / "frozen"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    shutil.copytree(ROOT / "engine", frozen / "engine", ignore=ignore)
    shutil.copytree(game_dir, frozen / "game", ignore=ignore)
    (frozen / "main.py").write_text(MAIN_PY)
    (stage_dir / "manifest.py").write_text(MANIFEST_PY)
    return stage_dir


def run(cmd, dry_run=False, **kw):
    print("$ " + " ".join(str(c) for c in cmd))
    if dry_run:
        return 0
    return subprocess.run([str(c) for c in cmd], **kw).returncode


def image_exists():
    r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    return r.returncode == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game", help="game package directory (needs __init__.py defining class Game)")
    ap.add_argument("--board", default=DEFAULT_BOARD)
    ap.add_argument("--out", help="output .bin (default: dist/<game>.bin)")
    ap.add_argument("--stage-only", action="store_true", help="only prepare build/stage, skip Docker")
    ap.add_argument("--rebuild-image", action="store_true", help="rebuild the Docker build image")
    ap.add_argument("--dry-run", action="store_true", help="print the Docker commands without running them")
    args = ap.parse_args(argv)

    game = Path(args.game).resolve()
    stage_dir = stage(game, ROOT / "build" / "stage")
    print("staged %s -> %s" % (game.name, stage_dir))
    if args.stage_only:
        return 0

    if not args.dry_run:
        if shutil.which("docker") is None or subprocess.run(["docker", "info"], capture_output=True).returncode:
            raise SystemExit("Docker isn't available/running. Start Docker Desktop (or the daemon) and retry.")

    out = Path(args.out).resolve() if args.out else ROOT / "dist" / (game.name + ".bin")
    out_dir = ROOT / "build" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run or args.rebuild_image or not image_exists():
        print("building the build image (slow the first time)...")
        rc = run(["docker", "build", "-t", IMAGE,
                  "--build-arg", "IDF_TAG=" + IDF_TAG,
                  "--build-arg", "MPY_TAG=" + MPY_TAG,
                  "--build-arg", "BOARD=" + args.board,
                  str(ROOT / "docker")], dry_run=args.dry_run)
        if rc:
            return rc

    rc = run(["docker", "run", "--rm",
              "-v", "%s:/stage:ro" % stage_dir,
              "-v", "%s:/out" % out_dir,
              IMAGE, args.board], dry_run=args.dry_run)
    if rc:
        return rc
    if not args.dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_dir / "micropython.bin", out)
        print("wrote %s (%d bytes)" % (out, out.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
