"""
Expand @file and !shell references in user input before sending to a provider.

Inspired by the Gemini CLI's @path and !command syntax.

Examples:
  "Review @src/main.py for security issues"
  "What does !git log --oneline -10 show about recent changes?"
  "Compare @old.py and @new.py"
"""
from __future__ import annotations
import asyncio
import re
from pathlib import Path


_FILE_PATTERN = re.compile(r"@([\w./\-]+)")
_SHELL_PATTERN = re.compile(r"!([\w\s./\-|&<>\"'`]+?)(?=\s*(?:@|\Z|$))")

MAX_FILE_BYTES = 100_000    # 100 KB guard
MAX_SHELL_OUTPUT = 10_000   # 10 KB guard
SHELL_TIMEOUT = 30          # seconds


async def expand_input(
    text: str,
    cwd: Path | None = None,
) -> tuple[str, list[str]]:
    """
    Expand @file and !cmd references in the input text.

    Returns:
        (expanded_text, list_of_warnings)
    """
    warnings: list[str] = []
    cwd = cwd or Path.cwd()

    # Expand @file references
    file_matches = list(_FILE_PATTERN.finditer(text))
    for match in reversed(file_matches):   # reversed so offsets stay valid
        raw_path = match.group(1)
        file_path = (cwd / raw_path).resolve()

        if not file_path.exists():
            warnings.append(f"File not found: {raw_path}")
            continue

        if not file_path.is_file():
            warnings.append(f"Not a file: {raw_path}")
            continue

        size = file_path.stat().st_size
        if size > MAX_FILE_BYTES:
            warnings.append(
                f"File too large ({size // 1024}KB > {MAX_FILE_BYTES // 1024}KB): {raw_path}"
            )
            continue

        try:
            content = file_path.read_text(errors="replace")
        except OSError as exc:
            warnings.append(f"Cannot read {raw_path}: {exc}")
            continue

        # Detect language for syntax highlighting
        suffix = file_path.suffix.lstrip(".") or "text"
        replacement = f"\n```{suffix}\n# {raw_path}\n{content}\n```\n"
        text = text[: match.start()] + replacement + text[match.end():]

    # Expand !shell references
    shell_matches = list(_SHELL_PATTERN.finditer(text))
    for match in reversed(shell_matches):
        raw_cmd = match.group(1).strip()
        if not raw_cmd:
            continue

        try:
            proc = await asyncio.create_subprocess_shell(
                raw_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(cwd),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=SHELL_TIMEOUT)
            output = stdout.decode(errors="replace")
            if len(output) > MAX_SHELL_OUTPUT:
                output = output[:MAX_SHELL_OUTPUT] + "\n... [truncated]"
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            warnings.append(f"Shell command timed out ({SHELL_TIMEOUT}s): {raw_cmd}")
            continue
        except Exception as exc:
            warnings.append(f"Shell command failed ({raw_cmd}): {exc}")
            continue

        replacement = f"\n```\n$ {raw_cmd}\n{output}\n```\n"
        text = text[: match.start()] + replacement + text[match.end():]

    return text, warnings
