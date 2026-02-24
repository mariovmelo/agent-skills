"""
Context Manager — persistent conversation sessions independent of any provider.

Sessions are stored as SQLite databases in ~/.uai/sessions/<name>.db
This allows switching providers mid-conversation without losing history.
"""
from __future__ import annotations
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

from uai.models.context import Message, MessageRole, Session, SessionInfo

if TYPE_CHECKING:
    from uai.providers.base import BaseProvider


# Tokens consumed by injecting the history header text
_HEADER_OVERHEAD_TOKENS = 50


class ContextManager:
    """
    Manages named conversation sessions with persistent SQLite storage.

    Key responsibilities:
    - CRUD for sessions (create, list, delete, export)
    - Add user/assistant messages
    - prepare_context(): select and format history for a target provider
    - Auto-summarization when history approaches provider's context limit
    """

    def __init__(self, sessions_dir: Path) -> None:
        self._dir = sessions_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────
    # Session lifecycle
    # ──────────────────────────────────────────────────────────────────

    def get_session(self, name: str = "default") -> Session:
        """Open or create a named session."""
        db_path = self._db_path(name)
        conn = self._connect(db_path)
        self._ensure_schema(conn)
        conn.close()
        return Session(name=name, db_path=str(db_path))

    def list_sessions(self) -> list[SessionInfo]:
        """Return sessions sorted by last_active descending (most recent first)."""
        infos: list[SessionInfo] = []
        for db_file in self._dir.glob("*.db"):
            name = db_file.stem
            try:
                conn = sqlite3.connect(db_file)
                row = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(COALESCE(tokens,0)),0) FROM messages"
                ).fetchone()
                meta = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
                conn.close()
                infos.append(SessionInfo(
                    name=name,
                    created_at=datetime.fromisoformat(meta.get("created_at", "2026-01-01")),
                    last_active=datetime.fromisoformat(meta.get("last_active", "2026-01-01")),
                    total_messages=row[0],
                    total_tokens=row[1],
                    size_bytes=db_file.stat().st_size,
                ))
            except Exception:
                continue
        # Sort most recent first so list_sessions()[0] is the last active session
        infos.sort(key=lambda s: s.last_active, reverse=True)
        return infos

    def delete_session(self, name: str) -> None:
        db_path = self._db_path(name)
        if db_path.exists():
            db_path.unlink()

    # ──────────────────────────────────────────────────────────────────
    # Message operations
    # ──────────────────────────────────────────────────────────────────

    def add_user_message(self, session: Session, content: str) -> Message:
        tokens = self._estimate_tokens(content)
        with self._connect(session.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO messages (role, content, tokens) VALUES (?, ?, ?)",
                (MessageRole.USER.value, content, tokens),
            )
            msg_id = cur.lastrowid
            self._update_last_active(conn)
        return Message(
            id=msg_id or 0,
            role=MessageRole.USER,
            content=content,
            tokens=tokens,
        )

    def add_assistant_message(
        self,
        session: Session,
        content: str,
        provider: str,
        model: str,
        tokens: int | None = None,
    ) -> Message:
        token_count = tokens or self._estimate_tokens(content)
        with self._connect(session.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO messages (role, content, provider, model, tokens) VALUES (?,?,?,?,?)",
                (MessageRole.ASSISTANT.value, content, provider, model, token_count),
            )
            msg_id = cur.lastrowid
            self._update_last_active(conn)
        return Message(
            id=msg_id or 0,
            role=MessageRole.ASSISTANT,
            content=content,
            provider=provider,
            model=model,
            tokens=token_count,
        )

    def get_messages(self, session: Session, limit: int | None = None) -> list[Message]:
        """Return all (or last N) messages, excluding SUMMARY placeholders."""
        conn = self._connect(session.db_path)
        query = "SELECT id, role, content, provider, model, tokens, timestamp FROM messages ORDER BY id"
        if limit:
            query = (
                "SELECT id, role, content, provider, model, tokens, timestamp "
                "FROM messages ORDER BY id DESC LIMIT ? "
            )
            rows = conn.execute(query, (limit,)).fetchall()
            rows = list(reversed(rows))
        else:
            rows = conn.execute(query).fetchall()
        conn.close()
        return [self._row_to_message(r) for r in rows]

    def clear_messages(self, session: Session) -> None:
        with self._connect(session.db_path) as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM summaries")

    # ──────────────────────────────────────────────────────────────────
    # Context preparation (the core intelligence)
    # ──────────────────────────────────────────────────────────────────

    async def prepare_context(
        self,
        session: Session,
        target_provider: "BaseProvider",
        strategy: Literal["auto", "full", "windowed", "summarized"] = "auto",
        keep_recent_turns: int = 10,
        max_history_tokens: int = 50_000,
    ) -> list[Message]:
        """
        Select and prepare history for injection into a target provider.

        Strategy selection (auto mode):
          - If total tokens <= provider context window * 0.7 → full
          - If total tokens <= max_history_tokens → windowed
          - Otherwise → summarized (auto-compress old turns)
        """
        all_messages = self.get_messages(session)
        if not all_messages:
            return []

        total_tokens = sum(m.tokens or self._estimate_tokens(m.content) for m in all_messages)
        provider_limit = target_provider.context_window_tokens
        budget = min(int(provider_limit * 0.7), max_history_tokens)

        if strategy == "auto":
            if total_tokens <= budget:
                strategy = "full"
            elif len(all_messages) <= keep_recent_turns * 2:
                strategy = "windowed"
            else:
                strategy = "summarized"

        if strategy == "full":
            return all_messages

        if strategy == "windowed":
            # Keep the last N turns (pairs of user+assistant messages)
            return all_messages[-(keep_recent_turns * 2):]

        # strategy == "summarized"
        return await self._summarize_and_trim(
            session, all_messages, keep_recent_turns, budget, target_provider
        )

    def format_for_provider(
        self,
        messages: list[Message],
        provider: "BaseProvider",
    ) -> Any:
        """
        Convert Message list to each provider's native format.

        Returns:
          - Claude/OpenAI-compatible: list[dict]  (role + content)
          - Gemini: list[dict]  (role + parts)
          - CLI providers (codex, qwen): plain text string
        """
        from uai.providers.gemini import GeminiProvider
        from uai.providers.claude import ClaudeProvider
        from uai.providers.codex import CodexProvider
        from uai.providers.qwen import QwenProvider
        from uai.providers.ollama import OllamaProvider
        from uai.providers.deepseek import DeepSeekProvider
        from uai.providers.groq import GroqProvider

        if isinstance(provider, GeminiProvider):
            return self._format_gemini(messages)

        if isinstance(provider, (ClaudeProvider, OllamaProvider, DeepSeekProvider, GroqProvider)):
            return self._format_openai(messages)

        # CLI-based providers — flat text
        return provider.format_history_as_text(messages)

    # ──────────────────────────────────────────────────────────────────
    # Export
    # ──────────────────────────────────────────────────────────────────

    def cleanup_old_sessions(
        self,
        max_count: int = 50,
        max_age_days: int = 90,
    ) -> int:
        """
        Remove sessions older than max_age_days or beyond max_count (keep newest).
        Returns number of sessions deleted.
        """
        from datetime import timedelta
        sessions = self.list_sessions()
        deleted = 0
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)

        # Delete by age first
        for s in sessions:
            if s.last_active < cutoff:
                self.delete_session(s.name)
                deleted += 1

        # Then enforce max_count (keep newest)
        remaining = self.list_sessions()
        # list_sessions returns sorted by file mtime; re-sort by last_active descending
        remaining_sorted = sorted(remaining, key=lambda s: s.last_active, reverse=True)
        for s in remaining_sorted[max_count:]:
            self.delete_session(s.name)
            deleted += 1

        return deleted

    def export_session(self, session: Session, fmt: Literal["json", "markdown"] = "markdown") -> str:
        messages = self.get_messages(session)
        if fmt == "json":
            return json.dumps(
                [
                    {
                        "id": m.id, "role": m.role.value, "content": m.content,
                        "provider": m.provider, "model": m.model,
                        "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                    }
                    for m in messages
                ],
                indent=2,
                ensure_ascii=False,
            )

        # Markdown
        lines: list[str] = [f"# Session: {session.name}\n"]
        for msg in messages:
            if msg.role == MessageRole.USER:
                lines.append(f"**You:** {msg.content}\n")
            elif msg.role == MessageRole.ASSISTANT:
                provider_tag = f"*({msg.provider}/{msg.model})*" if msg.provider else ""
                lines.append(f"**Assistant** {provider_tag}: {msg.content}\n")
            elif msg.role == MessageRole.SUMMARY:
                lines.append(f"> **[Summary]**: {msg.content}\n")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────

    async def _summarize_and_trim(
        self,
        session: Session,
        all_messages: list[Message],
        keep_recent_turns: int,
        budget: int,
        target_provider: "BaseProvider",
    ) -> list[Message]:
        """
        Summarize old messages and return [summary_message] + recent_messages.
        The summary is generated using a free provider (gemini flash or qwen).
        """
        # Split: recent N turns stay intact, older gets summarized
        recent = all_messages[-(keep_recent_turns * 2):]
        older = all_messages[:-(keep_recent_turns * 2)]

        if not older:
            return recent

        # Try to get a free summary using gemini or qwen
        summary_text = await self._generate_summary(older)

        # Store summary in DB
        with self._connect(session.db_path) as conn:
            old_ids = json.dumps([m.id for m in older])
            conn.execute(
                "INSERT INTO summaries (covers_ids, content, provider) VALUES (?,?,?)",
                (old_ids, summary_text, "auto"),
            )

        summary_msg = Message(
            id=-1,
            role=MessageRole.SUMMARY,
            content=f"[Earlier conversation summary]: {summary_text}",
            tokens=self._estimate_tokens(summary_text),
        )
        return [summary_msg] + recent

    async def _generate_summary(self, messages: list[Message]) -> str:
        """Use a free provider to summarize a list of messages."""
        text = "\n".join(f"{m.role.value.upper()}: {m.content}" for m in messages)
        prompt = (
            "Summarize the following conversation concisely, preserving key decisions, "
            "context and information that would be needed to continue the conversation:\n\n"
            f"{text}\n\nProvide a concise summary in the same language as the conversation."
        )

        # Try gemini CLI first (free, no auth needed if CLI installed)
        try:
            import asyncio
            proc = await asyncio.create_subprocess_exec(
                "gemini", "-m", "gemini-2.5-flash-preview-05-20", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0:
                return stdout.decode(errors="replace").strip()
        except Exception:
            pass

        # Try qwen CLI fallback
        try:
            proc = await asyncio.create_subprocess_exec(
                "qwen", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0:
                return stdout.decode(errors="replace").strip()
        except Exception:
            pass

        # Last resort: simple truncation summary
        lines = [f"{m.role.value}: {m.content[:200]}" for m in messages[-10:]]
        return "Previous context:\n" + "\n".join(lines)

    def _format_openai(self, messages: list[Message]) -> list[dict[str, str]]:
        result = []
        for msg in messages:
            if msg.role == MessageRole.SUMMARY:
                result.append({"role": "system", "content": msg.content})
            elif msg.role.value in ("user", "assistant"):
                result.append({"role": msg.role.value, "content": msg.content})
        return result

    def _format_gemini(self, messages: list[Message]) -> list[dict]:
        result = []
        for msg in messages:
            if msg.role == MessageRole.SUMMARY:
                result.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role == MessageRole.USER:
                result.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role == MessageRole.ASSISTANT:
                result.append({"role": "model", "parts": [{"text": msg.content}]})
        return result

    def _estimate_tokens(self, text: str) -> int:
        """Fast approximation: ~4 chars per token."""
        return max(1, len(text) // 4)

    def _db_path(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        return self._dir / f"{safe}.db"

    def _connect(self, path: str | Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                role      TEXT NOT NULL,
                content   TEXT NOT NULL,
                provider  TEXT,
                model     TEXT,
                tokens    INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS summaries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                covers_ids  TEXT,
                content     TEXT NOT NULL,
                provider    TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS metadata (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        # Initialize metadata
        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO metadata (key, value) VALUES ('created_at', ?)", (now,)
        )
        conn.execute(
            "INSERT OR IGNORE INTO metadata (key, value) VALUES ('last_active', ?)", (now,)
        )
        conn.commit()

    def _update_last_active(self, conn: sqlite3.Connection) -> None:
        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_active', ?)", (now,)
        )

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        return Message(
            id=row[0],
            role=MessageRole(row[1]),
            content=row[2],
            provider=row[3],
            model=row[4],
            tokens=row[5],
            timestamp=datetime.fromisoformat(row[6]) if row[6] else datetime.utcnow(),
        )
