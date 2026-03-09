"""prompt_toolkit-based input handler for the UAI chat REPL."""
from __future__ import annotations
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings


class SlashCompleter(Completer):
    """Autocomplete /commands when the user starts typing a /."""

    def __init__(self, extra_commands: list[str] | None = None) -> None:
        self._commands: list[str] = extra_commands or []

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        word = text  # full text including "/"
        for cmd in self._commands:
            if cmd.startswith(word) and cmd != word:
                yield Completion(cmd, start_position=-len(word))


def make_prompt_session(
    history_path: Path,
    extra_commands: list[str] | None = None,
) -> PromptSession:
    """
    Build a configured PromptSession for the UAI chat REPL.

    Features:
    - Persistent history stored at history_path
    - /command autocomplete
    - Inline history suggestions (grey ghost text)
    - Shift+Enter (or Alt+Enter) inserts a newline without submitting
    - Ctrl+R enables reverse history search
    """
    history_path.parent.mkdir(parents=True, exist_ok=True)

    # Key bindings: Shift+Enter / Alt+Enter for multi-line input
    kb = KeyBindings()

    @kb.add("escape", "enter")   # Alt+Enter (terminal fallback)
    def _alt_enter(event):
        event.current_buffer.insert_text("\n")

    # Note: "s-return" (Shift+Enter) support depends on the terminal emulator.
    # We bind escape+enter as the universal fallback.
    @kb.add("c-j")               # Ctrl+J = LF, another common multi-line shortcut
    def _ctrl_j(event):
        event.current_buffer.insert_text("\n")

    return PromptSession(
        history=FileHistory(str(history_path)),
        completer=SlashCompleter(extra_commands=extra_commands),
        auto_suggest=AutoSuggestFromHistory(),
        key_bindings=kb,
        multiline=False,
        enable_history_search=True,   # Ctrl+R reverse search
        vi_mode=False,
        mouse_support=False,
    )


async def get_user_input(session: PromptSession, provider_name: str) -> str:
    """
    Async prompt that shows the current provider name in the prompt string.

    Returns the stripped input text.
    Raises EOFError on Ctrl+D and KeyboardInterrupt on Ctrl+C.
    """
    prompt_text = HTML(
        f"<ansigreen><b>You</b></ansigreen> "
        f"<ansiyellow>({provider_name})</ansiyellow> "
        f"<ansiblue>&gt;</ansiblue> "
    )
    result = await session.prompt_async(prompt_text)
    return result.strip()
