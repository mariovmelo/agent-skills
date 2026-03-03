"""
Context Manager — persistent conversation sessions independent of any provider.

Sessions are stored as SQLite databases in ~/.uai/sessions/<name>.db
This allows switching providers mid-conversation without losing history.

3-Layer Intelligent Memory Architecture:
  Layer 1 — Adaptive Window (JetBrains Research / SWE-bench validated)
    Keep last 10 turns verbatim; summarize when total exceeds 21 turns.
    Goal-aware summarization prompt preserves goals, file paths, decisions.
    Ref: https://arxiv.org/abs/2402.01467

  Layer 2 — FTS5 Recall Index (MemGPT / Letta pattern)
    SQLite FTS5 virtual table with BM25 search over full message history.
    Retrieves relevant older turns outside the sliding window.
    Ref: https://research.memgpt.ai/

  Layer 3 — Core Memory (mem0 extract-then-store pattern)
    Per-session structured facts (goal/preference/project/general) extracted
    by a lightweight LLM after each exchange and injected as a system message.
    Always ≤ 500 tokens; survives summarization.
    Ref: https://github.com/mem0ai/mem0
"""
from __future__ import annotations
import asyncio
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

from uai.models.context import Message, MessageRole, Session, SessionInfo

if TYPE_CHECKING:
    from uai.providers.base import BaseProvider


# ── Constants ──────────────────────────────────────────────────────────────────
_HEADER_OVERHEAD_TOKENS = 50
_KEEP_RECENT_TURNS = 10       # JetBrains: keep last N turns verbatim
_SUMMARIZE_THRESHOLD = 21     # Summarize when total turns exceed this
_SUMMARIZE_CHUNK = 11         # Compress chunks of this size
_CORE_MEMORY_MAX_TOKENS = 500 # Max tokens injected via core memory block
_RECALL_RESULTS = 5           # FTS5 recall: max turns retrieved

# ── Prompts ────────────────────────────────────────────────────────────────────
_GOAL_AWARE_SUMMARY_PROMPT = """\
You are condensing a conversation to preserve essential context.

MUST PRESERVE (never omit):
- Primary goals and objectives stated by the user
- Key decisions made (tech choices, architectural decisions, rejected approaches)
- Specific file paths, function names, class names mentioned
- Errors encountered and their resolutions
- Current progress state ("we just finished X, next step is Y")
- Any explicit constraints or requirements

CONDENSE FREELY:
- Repetitive exchanges
- Exploratory discussions that led nowhere
- Verbose explanations already understood

Conversation to summarize:
{conversation}

Write a concise but complete summary in the SAME LANGUAGE as the conversation.
Focus on what someone needs to know to continue this work effectively."""

_FACT_EXTRACTION_PROMPT = """\
Extract structured facts from this conversation exchange.

USER MESSAGE: {user_msg}
ASSISTANT RESPONSE: {assistant_msg}

Return ONLY a JSON array (no other text) of fact objects:
[
  {{"category": "goal", "fact": "..."}},
  {{"category": "preference", "fact": "..."}},
  {{"category": "project", "fact": "..."}},
  {{"category": "general", "fact": "..."}}
]

Categories:
- goal: what the user is trying to accomplish
- preference: how the user likes things done (language, style, tools)
- project: specific project details (name, tech stack, file paths)
- general: other persistent facts worth remembering

Only include facts that are GENUINELY USEFUL for future context.
Return [] if there are no meaningful facts to extract.
Respond ONLY with the JSON array."""


class ContextManager:
    """
    Manages named conversation sessions with persistent SQLite storage.

    Key responsibilities:
    - CRUD for sessions (create, list, delete, export)
    - Add user/assistant messages with FTS5 indexing
    - prepare_context(): 3-layer memory assembly for a target provider
    - Auto-summarization when history approaches provider's context limit
    - Core memory: background fact extraction per session
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
            msg_id = cur.lastrowid or 0
            # Index in FTS5 for recall search
            try:
                conn.execute(
                    "INSERT INTO message_fts (rowid, content) VALUES (?, ?)",
                    (msg_id, content),
                )
            except Exception:
                pass
            self._update_last_active(conn)
        return Message(
            id=msg_id,
            role=MessageRole.USER,
            content=content,
            tokens=tokens,
        )

    def update_message_tokens(self, session: Session, message_id: int, tokens: int) -> None:
        """Update the stored token count for a message (e.g. replace estimate with API value)."""
        if message_id <= 0 or tokens <= 0:
            return
        with self._connect(session.db_path) as conn:
            conn.execute(
                "UPDATE messages SET tokens = ? WHERE id = ?",
                (tokens, message_id),
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
            msg_id = cur.lastrowid or 0
            # Index in FTS5 for recall search
            try:
                conn.execute(
                    "INSERT INTO message_fts (rowid, content) VALUES (?, ?)",
                    (msg_id, content),
                )
            except Exception:
                pass
            self._update_last_active(conn)
        return Message(
            id=msg_id,
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
            try:
                conn.execute("DELETE FROM message_fts")
            except Exception:
                pass
            try:
                conn.execute("DELETE FROM core_memory")
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────
    # Layer 2: FTS5 Recall Search (MemGPT pattern)
    # ──────────────────────────────────────────────────────────────────

    def search_messages(
        self, session: Session, query: str, limit: int = _RECALL_RESULTS
    ) -> list[Message]:
        """
        BM25 full-text search over all messages in the session.
        Returns the top-N most relevant messages ranked by FTS5 BM25 score.
        Useful for surfacing older turns outside the sliding window.
        """
        if not query or not query.strip():
            return []
        # Sanitize query for FTS5 (escape special chars, limit length)
        safe_query = re.sub(r'[^\w\s]', ' ', query)[:500].strip()
        if not safe_query:
            return []

        try:
            conn = self._connect(session.db_path)
            rows = conn.execute(
                """
                SELECT m.id, m.role, m.content, m.provider, m.model, m.tokens, m.timestamp
                FROM message_fts f
                JOIN messages m ON m.id = f.rowid
                WHERE message_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, limit),
            ).fetchall()
            conn.close()
            return [self._row_to_message(r) for r in rows]
        except Exception:
            return []

    # ──────────────────────────────────────────────────────────────────
    # Layer 3: Core Memory (mem0 extract-then-store pattern)
    # ──────────────────────────────────────────────────────────────────

    def get_core_memory_block(self, session: Session) -> Message | None:
        """
        Return a SYSTEM Message containing the structured facts for this session,
        or None if no facts have been extracted yet.
        Always-injected into context; ≤ _CORE_MEMORY_MAX_TOKENS tokens.
        """
        try:
            conn = self._connect(session.db_path)
            rows = conn.execute(
                "SELECT category, fact FROM core_memory ORDER BY category, updated_at DESC"
            ).fetchall()
            conn.close()
        except Exception:
            return None

        if not rows:
            return None

        by_category: dict[str, list[str]] = {}
        for row in rows:
            cat, fact = row[0], row[1]
            by_category.setdefault(cat, []).append(fact)

        lines = ["[Session Memory]"]
        order = ["goal", "project", "preference", "general"]
        for cat in order:
            facts = by_category.get(cat, [])
            if facts:
                lines.append(f"{cat.upper()}:")
                for f in facts[:5]:  # cap per category
                    lines.append(f"  - {f}")

        block = "\n".join(lines)
        tokens = self._estimate_tokens(block)
        if tokens > _CORE_MEMORY_MAX_TOKENS:
            # Truncate to budget
            allowed_chars = _CORE_MEMORY_MAX_TOKENS * 4
            block = block[:allowed_chars]

        return Message(
            id=-2,
            role=MessageRole.SYSTEM,
            content=block,
            tokens=self._estimate_tokens(block),
        )

    async def update_core_memory(
        self, session: Session, user_msg: str, assistant_msg: str
    ) -> None:
        """
        Extract structured facts from the latest exchange and upsert into core_memory.
        Called as a background task (asyncio.create_task) after each successful response.
        Silently ignores all errors — must never block the main request path.
        """
        try:
            prompt = _FACT_EXTRACTION_PROMPT.format(
                user_msg=user_msg[:2000],
                assistant_msg=assistant_msg[:2000],
            )
            result = await self._call_lightweight_llm(prompt)
            if not result:
                return

            # Parse JSON array
            # Strip markdown code fences if present
            cleaned = re.sub(r'```(?:json)?\s*|\s*```', '', result).strip()
            facts = json.loads(cleaned)
            if not isinstance(facts, list):
                return

            now = datetime.utcnow().isoformat()
            with self._connect(session.db_path) as conn:
                for item in facts:
                    if not isinstance(item, dict):
                        continue
                    cat = str(item.get("category", "general")).lower()
                    fact = str(item.get("fact", "")).strip()
                    if not fact or cat not in ("goal", "preference", "project", "general"):
                        continue
                    # Upsert: if a fact with the same category+content exists, update timestamp
                    conn.execute(
                        """
                        INSERT INTO core_memory (category, fact, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(category, fact) DO UPDATE SET updated_at = excluded.updated_at
                        """,
                        (cat, fact, now),
                    )
        except Exception:
            pass  # Best-effort; never raise

    # ──────────────────────────────────────────────────────────────────
    # Context preparation (3-layer memory assembly)
    # ──────────────────────────────────────────────────────────────────

    async def prepare_context(
        self,
        session: Session,
        target_provider: "BaseProvider",
        strategy: Literal["auto", "full", "windowed", "summarized"] = "auto",
        keep_recent_turns: int = _KEEP_RECENT_TURNS,
        max_history_tokens: int = 50_000,
        current_prompt: str | None = None,
    ) -> list[Message]:
        """
        Assemble context using 3-layer intelligent memory:

        Layer 1 — Adaptive Window: keep last N turns verbatim; summarize old turns
        Layer 2 — FTS5 Recall: retrieve relevant older turns via BM25 search
        Layer 3 — Core Memory: inject session facts as system message

        Final assembly: [core_memory] + [FTS5 recall] + [adaptive window]
        All layers respect the token budget: min(provider_limit * 0.7, max_history_tokens)
        """
        all_messages = self.get_messages(session)
        if not all_messages:
            return []

        total_tokens = sum(
            m.tokens if m.tokens is not None else self._estimate_tokens(m.content)
            for m in all_messages
        )
        provider_limit = target_provider.context_window_tokens
        budget = min(int(provider_limit * 0.7), max_history_tokens)

        # ── Layer 1: Adaptive window ────────────────────────────────────
        if strategy == "auto":
            turn_count = len(all_messages)
            if total_tokens <= budget:
                strategy = "full"
            elif turn_count <= keep_recent_turns * 2:
                strategy = "windowed"
            else:
                strategy = "summarized"

        if strategy == "full":
            window = all_messages
        elif strategy == "windowed":
            window = all_messages[-(keep_recent_turns * 2):]
        else:  # summarized
            window = await self._summarize_and_trim(
                session, all_messages, keep_recent_turns, budget, target_provider
            )

        # ── 3-layer assembly ────────────────────────────────────────────
        return await self._assemble(session, window, current_prompt, budget)

    async def _assemble(
        self,
        session: Session,
        window: list[Message],
        current_prompt: str | None,
        budget: int,
    ) -> list[Message]:
        """
        Combine [core_memory] + [FTS5 recall] + [window] within token budget.
        Deduplicates recall results that are already in the window.
        """
        result: list[Message] = []
        used_tokens = 0
        window_ids = {m.id for m in window}

        # Layer 3: Core memory (always first, if it fits)
        core_block = self.get_core_memory_block(session)
        if core_block:
            core_tokens = core_block.tokens or self._estimate_tokens(core_block.content)
            if used_tokens + core_tokens <= budget:
                result.append(core_block)
                used_tokens += core_tokens

        # Layer 2: FTS5 recall — retrieve relevant older turns
        if current_prompt:
            recall_msgs = self.search_messages(session, current_prompt, limit=_RECALL_RESULTS)
            recall_budget = budget // 5  # max 20% of budget for recall
            for msg in recall_msgs:
                if msg.id in window_ids:
                    continue  # already in window, skip
                msg_tokens = msg.tokens if msg.tokens is not None else self._estimate_tokens(msg.content)
                if used_tokens + msg_tokens <= used_tokens + recall_budget:
                    result.append(msg)
                    used_tokens += msg_tokens

        # Layer 1: Adaptive window (most recent turns)
        window_tokens = sum(
            m.tokens if m.tokens is not None else self._estimate_tokens(m.content)
            for m in window
        )
        remaining = budget - used_tokens
        if window_tokens <= remaining:
            result.extend(window)
        else:
            # Trim window from the front to fit budget
            trimmed = []
            acc = 0
            for msg in reversed(window):
                t = msg.tokens if msg.tokens is not None else self._estimate_tokens(msg.content)
                if acc + t <= remaining:
                    trimmed.append(msg)
                    acc += t
                else:
                    break
            result.extend(reversed(trimmed))

        return result

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
        from uai.providers.deepseek import DeepSeekProvider
        from uai.providers.groq import GroqProvider

        if isinstance(provider, GeminiProvider):
            return self._format_gemini(messages)

        if isinstance(provider, (ClaudeProvider, DeepSeekProvider, GroqProvider)):
            return self._format_openai(messages)

        # CLI-based providers — flat text
        return provider.format_history_as_text(messages)

    # ──────────────────────────────────────────────────────────────────
    # Export / cleanup
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

        for s in sessions:
            if s.last_active < cutoff:
                self.delete_session(s.name)
                deleted += 1

        remaining = self.list_sessions()
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

        lines: list[str] = [f"# Session: {session.name}\n"]
        for msg in messages:
            if msg.role == MessageRole.USER:
                lines.append(f"**You:** {msg.content}\n")
            elif msg.role == MessageRole.ASSISTANT:
                provider_tag = f"*({msg.provider}/{msg.model})*" if msg.provider else ""
                lines.append(f"**Assistant** {provider_tag}: {msg.content}\n")
            elif msg.role in (MessageRole.SUMMARY, MessageRole.SYSTEM):
                lines.append(f"> **[{msg.role.value.title()}]**: {msg.content}\n")
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
        Uses goal-aware summarization prompt (OpenHands pattern).
        """
        recent = all_messages[-(keep_recent_turns * 2):]
        older = all_messages[:-(keep_recent_turns * 2)]

        if not older:
            return recent

        summary_text = await self._generate_summary(older)

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
        """Generate a goal-aware summary using a free provider."""
        conversation = "\n".join(
            f"{m.role.value.upper()}: {m.content}" for m in messages
        )
        prompt = _GOAL_AWARE_SUMMARY_PROMPT.format(conversation=conversation)

        result = await self._call_lightweight_llm(prompt)
        if result:
            return result

        # Last resort: structured excerpt
        lines = [f"{m.role.value}: {m.content[:200]}" for m in messages[-10:]]
        return "Previous context:\n" + "\n".join(lines)

    async def _call_lightweight_llm(self, prompt: str) -> str | None:
        """
        Call a free CLI provider for background tasks (summarization, fact extraction).
        Tries gemini-2.5-flash first, then qwen as fallback.
        Returns None on any failure.
        """
        # Try gemini CLI first (free, no auth needed if installed)
        try:
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

        return None

    def _format_openai(self, messages: list[Message]) -> list[dict[str, str]]:
        result = []
        for msg in messages:
            if msg.role in (MessageRole.SUMMARY, MessageRole.SYSTEM):
                result.append({"role": "system", "content": msg.content})
            elif msg.role.value in ("user", "assistant"):
                result.append({"role": msg.role.value, "content": msg.content})
        return result

    def _format_gemini(self, messages: list[Message]) -> list[dict]:
        result = []
        for msg in messages:
            if msg.role in (MessageRole.SUMMARY, MessageRole.SYSTEM):
                # Gemini uses "user" turn for injected context blocks
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
            CREATE TABLE IF NOT EXISTS core_memory (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                category   TEXT NOT NULL,
                fact       TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, fact)
            );
        """)

        # Create FTS5 virtual table for recall search (separate statement)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS message_fts "
                "USING fts5(content, content='messages', content_rowid='id')"
            )
            conn.commit()
        except Exception:
            pass

        # Backfill existing messages into FTS5 (one-time migration)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO message_fts (rowid, content)
                SELECT id, content FROM messages
                WHERE id NOT IN (SELECT rowid FROM message_fts)
                """
            )
            conn.commit()
        except Exception:
            pass

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
