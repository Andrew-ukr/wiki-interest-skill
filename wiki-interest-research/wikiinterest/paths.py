"""Filesystem locations. Nothing is written inside the skill directory except .venv."""
from __future__ import annotations

import os
from pathlib import Path


def cache_dir() -> Path:
    path = Path(os.environ.get("WIKI_INTEREST_CACHE", Path.home() / ".cache" / "wiki-interest-research"))
    path = path.expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dir() -> Path:
    """Runs (analysis.json, charts, PDFs) go to ./wiki-reports of the caller by default."""
    path = Path(os.environ.get("WIKI_INTEREST_OUT", Path.cwd() / "wiki-reports")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def font_path(bold: bool = False) -> Path:
    """DejaVu Sans ships with matplotlib and covers Cyrillic, Polish, Czech, etc."""
    import matplotlib

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name
