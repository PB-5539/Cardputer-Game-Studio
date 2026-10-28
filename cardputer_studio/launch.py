#!/usr/bin/env python3
"""One-step launcher: sets up a private virtual environment on first run, then starts the IDE.

    python launch.py              start Cardputer Studio (installs what it needs the first time)
    python launch.py --setup      only set up the environment
    python launch.py --reset      delete the environment and set it up again
    python launch.py --check      print what it would do, change nothing

Only the standard library is used here. Everything it installs goes into ./.venv, so nothing
touches your system Python.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import venv

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(ROOT, ".venv")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
STAMP = os.path.join(VENV, ".requirements.sha256")
MIN_PYTHON = (3, 9)


def venv_python() -> str:
    sub = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    return os.path.join(VENV, *sub)


def requirements_hash() -> str:
    with open(REQUIREMENTS, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def env_is_ready() -> bool:
    if not os.path.isfile(venv_python()) or not os.path.isfile(STAMP):
        return False
    with open(STAMP) as f:
        return f.read().strip() == requirements_hash()


def plan() -> list[str]:
    steps = []
    if not os.path.isfile(venv_python()):
        steps.append("create virtual environment in %s" % VENV)
    if not env_is_ready():
        steps.append("pip install -r requirements.txt")
    steps.append("start: %s -m cpg_studio" % venv_python())
    return steps


def setup() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit("Python %d.%d or newer is required (this is %d.%d)." % (MIN_PYTHON + sys.version_info[:2]))
    if not os.path.isfile(venv_python()):
        print("Creating virtual environment (first run only)...")
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
    if not env_is_ready():
        print("Installing PySide6 and friends (this can take a minute)...")
        code = subprocess.call([venv_python(), "-m", "pip", "install", "--disable-pip-version-check",
                                "-r", REQUIREMENTS])
        if code != 0:
            raise SystemExit("pip install failed (exit code %d). Check your internet connection and try again; "
                            "`python launch.py --reset` starts clean." % code)
        with open(STAMP, "w") as f:
            f.write(requirements_hash())


def main(argv: list[str]) -> int:
    if "--check" in argv:
        for step in plan():
            print("-", step)
        return 0
    if "--reset" in argv and os.path.isdir(VENV):
        shutil.rmtree(VENV)
    setup()
    if "--setup" in argv:
        print("Environment ready.")
        return 0
    extra = [a for a in argv if not a.startswith("--")]
    # A child process (not exec) behaves the same on Windows, macOS and Linux.
    return subprocess.call([venv_python(), "-m", "cpg_studio", *extra], cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
