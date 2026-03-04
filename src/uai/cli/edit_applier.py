"""
Parse unified diffs from AI responses and either display or apply them.

Supported diff block formats in AI responses:
  1. Fenced code block with "diff" language tag:
       ```diff
       --- a/path/to/file.py
       +++ b/path/to/file.py
       @@ ... @@
        ...
       ```
  2. Fenced code block with a file-path comment header (GitHub Copilot style):
       ```python
       # path/to/file.py
       ...full file content...
       ```
       These are shown as a full-file replace suggestion (not applied automatically).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FilePatch:
    """A single unified diff targeting one file."""
    path: str               # relative path extracted from --- / +++ header
    raw_diff: str           # complete diff text (including headers)
    hunks: list[str] = field(default_factory=list)


@dataclass
class EditPlan:
    """All file patches extracted from an AI response."""
    patches: list[FilePatch] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return len(self.patches) == 0


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_DIFF_FENCE = re.compile(
    r"```diff\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_DIFF_PATH = re.compile(r"^\+\+\+\s+(?:b/)?(.+)$", re.MULTILINE)


def parse_edit_plan(text: str) -> EditPlan:
    """Extract all ```diff ``` blocks from *text* and build an EditPlan."""
    patches: list[FilePatch] = []

    for m in _DIFF_FENCE.finditer(text):
        diff_body = m.group(1)

        # Find target file path from the +++ header
        path_match = _DIFF_PATH.search(diff_body)
        if not path_match:
            continue  # malformed diff — skip

        path = path_match.group(1).strip()
        # Strip git "b/" prefix
        if path.startswith("b/"):
            path = path[2:]

        hunks = _split_hunks(diff_body)
        patches.append(FilePatch(path=path, raw_diff=diff_body, hunks=hunks))

    return EditPlan(patches=patches)


def _split_hunks(diff_body: str) -> list[str]:
    """Split a diff body into individual @@ hunk strings."""
    lines = diff_body.splitlines(keepends=True)
    hunks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("@@") and current:
            hunks.append("".join(current))
            current = []
        current.append(line)
    if current:
        hunks.append("".join(current))
    return hunks


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def show_edit_plan(plan: EditPlan, console: Console) -> None:
    """Render all patches as syntax-highlighted diffs in the terminal."""
    if plan.is_empty:
        return

    console.print()
    for patch in plan.patches:
        console.print(
            Text.from_markup(f"[bold yellow]── diff:[/bold yellow] [cyan]{patch.path}[/cyan]")
        )
        console.print(
            Syntax(
                patch.raw_diff.rstrip(),
                "diff",
                theme="ansi_dark",
                line_numbers=False,
                word_wrap=True,
            )
        )
        console.print()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def apply_edit_plan(
    plan: EditPlan,
    console: Console,
    base_dir: Path | None = None,
    confirm: bool = True,
) -> list[str]:
    """
    Apply all patches to disk.

    Returns a list of file paths that were modified.
    Skips patches where the target file does not exist.
    If *confirm* is True, ask the user before each file write.
    """
    if plan.is_empty:
        return []

    base = base_dir or Path.cwd()
    modified: list[str] = []

    for patch in plan.patches:
        target = base / patch.path
        if not target.exists():
            console.print(
                Text.from_markup(
                    f"[yellow]  ⚠ skip[/yellow] {patch.path} — file not found"
                )
            )
            continue

        # Show the diff so the user can see what will change
        console.print(
            Text.from_markup(f"[bold yellow]── diff:[/bold yellow] [cyan]{patch.path}[/cyan]")
        )
        console.print(
            Syntax(
                patch.raw_diff.rstrip(),
                "diff",
                theme="ansi_dark",
                line_numbers=False,
                word_wrap=True,
            )
        )

        if confirm:
            console.print(
                Text.from_markup(
                    f"  Apply to [cyan]{patch.path}[/cyan]? \\[y/N] "
                ),
                end="",
            )
            try:
                answer = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer not in ("y", "yes"):
                console.print(Text.from_markup("[dim]  skipped[/dim]"))
                continue

        try:
            _apply_patch(target, patch.raw_diff)
            console.print(
                Text.from_markup(f"  [green]✓ applied[/green] {patch.path}")
            )
            modified.append(str(patch.path))
        except Exception as exc:
            console.print(
                Text.from_markup(
                    f"  [red]✗ failed[/red] {patch.path}: {exc}"
                )
            )

    return modified


def _apply_patch(target: Path, raw_diff: str) -> None:
    """Apply a unified diff to *target* using Python's difflib patch logic."""
    import subprocess
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".patch", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(raw_diff)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["patch", "--quiet", "--forward", str(target), tmp_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    finally:
        os.unlink(tmp_path)
