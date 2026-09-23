#!/usr/bin/env python3
"""Entry point of the wiki-interest-research skill.

On first run it creates an isolated virtualenv next to the skill (``.venv``),
installs the pinned dependencies from ``requirements.txt`` and then forwards all
arguments to ``python -m wikiinterest``. Later runs start instantly.

Usage:  python3 scripts/wiki.py <command> [options]      (see --help)
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REQUIREMENTS = SKILL_DIR / "requirements.txt"
MIN_PY = (3, 10)


def _venv_dir() -> Path:
    override = os.environ.get("WIKI_INTEREST_VENV")
    if override:
        return Path(override).expanduser()
    if os.access(SKILL_DIR, os.W_OK):
        return SKILL_DIR / ".venv"
    # Skill installed read-only: keep the environment in the user cache instead.
    return Path.home() / ".cache" / "wiki-interest-research" / "venv"


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()[:16]


def _log(msg: str) -> None:
    print(f"[wiki-interest setup] {msg}", file=sys.stderr, flush=True)


def _create_venv(venv: Path) -> None:
    uv = shutil.which("uv")
    if sys.version_info < MIN_PY and not uv:
        sys.exit(
            f"Python {MIN_PY[0]}.{MIN_PY[1]}+ is required (found {sys.version.split()[0]}). "
            "Install a newer Python (https://www.python.org/downloads/) or uv "
            "(https://docs.astral.sh/uv/) and run the command again."
        )
    if venv.exists():
        shutil.rmtree(venv)
    venv.parent.mkdir(parents=True, exist_ok=True)
    py = _venv_python(venv)
    if uv:
        _log("creating virtualenv with uv ...")
        cmd = [uv, "venv", "--quiet", str(venv)]
        if sys.version_info < MIN_PY:
            cmd += ["--python", "3.12"]  # uv downloads a suitable interpreter
        else:
            cmd += ["--python", sys.executable]
        subprocess.check_call(cmd)
        _log("installing pinned dependencies (one-time, ~30 s) ...")
        subprocess.check_call([uv, "pip", "install", "--quiet", "--python", str(py), "-r", str(REQUIREMENTS)])
    else:
        _log("creating virtualenv ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
        _log("installing pinned dependencies (one-time, ~30-60 s) ...")
        subprocess.check_call(
            [str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(REQUIREMENTS)]
        )


def ensure_env() -> Path:
    venv = _venv_dir()
    marker = venv / ".wiki-interest-installed"
    wanted = _requirements_hash()
    py = _venv_python(venv)
    if py.exists() and marker.exists() and marker.read_text().strip() == wanted:
        return py
    try:
        _create_venv(venv)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"Dependency installation failed ({exc}). Check internet access and retry.")
    marker.write_text(wanted)
    _log("environment ready")
    return py


def main() -> None:
    py = ensure_env()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SKILL_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    args = [str(py), "-m", "wikiinterest", *sys.argv[1:]]
    if os.name == "nt":
        sys.exit(subprocess.call(args, env=env))
    os.execve(str(py), args, env)


if __name__ == "__main__":
    main()
