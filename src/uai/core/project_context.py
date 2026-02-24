"""Load UAI.md / .uai/instructions.md project context files.

Inspired by Gemini CLI's GEMINI.md auto-loading. UAI searches upward
from the current working directory for a UAI.md or .uai/instructions.md
file and returns its content as a system prompt addition.
"""
from __future__ import annotations
from pathlib import Path


_CANDIDATES = ["UAI.md", ".uai/instructions.md"]


def find_project_instructions(cwd: Path | None = None) -> str | None:
    """
    Search upward from `cwd` for UAI.md or .uai/instructions.md.

    Stops at the user's home directory or filesystem root.
    Returns file content (str) if found, None otherwise.
    """
    cwd = cwd or Path.cwd()
    home = Path.home()

    for parent in [cwd, *cwd.parents]:
        for name in _CANDIDATES:
            path = parent / name
            if path.exists() and path.is_file():
                try:
                    return path.read_text(errors="replace")
                except OSError:
                    return None
        # Stop at home directory or filesystem root
        if parent == home or parent == parent.parent:
            break

    return None


def find_project_config(cwd: Path | None = None) -> Path | None:
    """
    Search upward from `cwd` for .uai/config.yaml (project-level config).

    Returns the Path if found, None otherwise.
    """
    cwd = cwd or Path.cwd()
    home = Path.home()

    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".uai" / "config.yaml"
        if candidate.exists():
            return candidate
        if parent == home or parent == parent.parent:
            break

    return None
