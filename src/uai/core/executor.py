"""
Request Executor — top-level orchestrator that ties all core components together.

Flow for a single request:
  1. Load config and initialize providers
  2. Get/create session and load history
  3. Router selects best provider
  4. Context Manager prepares and formats history
  5. FallbackChain executes request with resilience
  6. Save assistant response to session
  7. Return UAIResponse
"""
from __future__ import annotations
import asyncio
from pathlib import Path

from uai.core.auth import AuthManager
from uai.core.config import ConfigManager
from uai.core.context import ContextManager
from uai.core.fallback import FallbackChain, AllProvidersFailedError
from uai.core.quota import QuotaTracker
from uai.core.router import RouterEngine
from uai.models.context import Message
from uai.models.provider import BackendType
from uai.models.quota import UsageRecord
from uai.models.request import UAIRequest, UAIResponse
from uai.providers import get_provider_class
from uai.providers.base import BaseProvider, ProviderError, RateLimitError, AuthError


class RequestExecutor:
    def __init__(
        self,
        config: ConfigManager,
        auth: AuthManager,
        quota: QuotaTracker,
        context: ContextManager,
        router: RouterEngine,
        fallback: FallbackChain,
        providers: dict[str, BaseProvider],
    ) -> None:
        """Accept pre-built components. Use create_default() for normal usage."""
        self._config = config
        self._auth = auth
        self._quota = quota
        self._context = context
        self._router = router
        self._fallback = fallback
        self._providers = providers

    @classmethod
    def create_default(cls, config_dir: Path | None = None) -> "RequestExecutor":
        """Build a fully wired RequestExecutor from scratch (normal usage)."""
        config = ConfigManager(config_dir)
        config.initialize()

        auth = AuthManager(config.config_dir)
        quota = QuotaTracker(config.config_dir / "quota.db")
        context = ContextManager(config.config_dir / "sessions")
        router = RouterEngine(config, auth, quota)

        cfg = config.load()
        providers: dict[str, BaseProvider] = {}
        for name, prov_cfg in cfg.providers.items():
            if not prov_cfg.enabled:
                continue
            try:
                from uai.providers import get_provider_class
                cls_p = get_provider_class(name)
                providers[name] = cls_p(auth, prov_cfg)
            except Exception:
                pass

        fallback = FallbackChain(providers, quota)
        return cls(config, auth, quota, context, router, fallback, providers)

    # ──────────────────────────────────────────────────────────────────
    async def execute(self, request: UAIRequest, on_status=None) -> UAIResponse:
        cfg = self._config.load()
        session = self._context.get_session(request.session_name)

        # 1. Load and prepare history
        history: list[Message] | None = None
        history_tokens = 0
        if request.use_context:
            history = await self._prepare_history(session, request, cfg)
            history_tokens = sum(m.tokens or 0 for m in history) if history else 0

        # 2. Route to best provider (pass cfg to avoid re-loading)
        import time as _time
        _t0 = _time.monotonic()
        decision = await self._router.route(
            prompt=request.prompt,
            task_type=request.task_type,
            prefer_provider=request.provider,
            free_only=request.free_only,
            history_tokens=history_tokens,
            cfg=cfg,
        )
        if on_status:
            on_status("routing", decision, _time.monotonic() - _t0)

        # 3. Save user message to context
        user_msg = None
        if request.use_context:
            user_msg = self._context.add_user_message(session, request.prompt)

        # 4. Execute with fallback
        response, providers_tried = await self._fallback.execute(
            prompt=request.prompt,
            decision=decision,
            history=history,
            on_status=on_status,
        )

        # 5. Save assistant response and update user message with actual input token count
        if request.use_context:
            # Replace the estimated token count on the user message with the actual
            # tokens_input reported by the API (covers prompt + history overhead).
            if user_msg and response.tokens_input and response.tokens_input > 0:
                self._context.update_message_tokens(session, user_msg.id, response.tokens_input)
            self._context.add_assistant_message(
                session,
                content=response.text,
                provider=response.provider,
                model=response.model,
                tokens=response.tokens_output,
            )
            # Fire background fact extraction for core memory (Layer 3)
            _task = asyncio.create_task(
                self._context.update_core_memory(session, request.prompt, response.text)
            )
            _task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        return UAIResponse(
            text=response.text,
            provider=response.provider,
            model=response.model,
            backend=response.backend,
            session_name=request.session_name,
            tokens_input=response.tokens_input,
            tokens_output=response.tokens_output,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            fallback_used=len(providers_tried) > 1,
            providers_tried=providers_tried,
        )

    async def _prepare_history(
        self, session, request: UAIRequest, cfg=None, exclude_last: bool = False
    ) -> list[Message]:
        """Get history messages.

        exclude_last=True when the caller already added the current user message to the
        DB before calling this (so we strip it to avoid feeding it to the provider twice).
        When exclude_last=False (default) the user message has NOT been saved yet — use
        all existing messages as context.
        """
        cfg = cfg or self._config.load()
        all_messages = self._context.get_messages(session)
        history = all_messages[:-1] if (exclude_last and all_messages) else all_messages
        if not history:
            return []

        # Find the target provider instance to size context correctly.
        # Fall back to any available provider so prepare_context() is always used.
        provider = (
            self._providers.get(request.provider or "")
            or next(iter(self._providers.values()), None)
        )
        if provider is None:
            # No providers loaded at all — simple windowed fallback
            return history[-cfg.defaults.context_window_turns * 2:]

        prepared = await self._context.prepare_context(
            session=session,
            target_provider=provider,
            strategy=cfg.defaults.context_strategy,  # type: ignore[arg-type]
            keep_recent_turns=cfg.context.keep_recent_turns,
            max_history_tokens=cfg.context.max_history_tokens,
            current_prompt=request.prompt,
        )
        return prepared

    # ──────────────────────────────────────────────────────────────────
    async def execute_stream(self, request: UAIRequest, on_status=None):
        """
        Like execute(), but yields tokens as they arrive via the provider's stream().

        Includes the same 3-layer fallback logic as FallbackChain.execute():
          - If the primary provider fails before yielding any tokens → try alternatives
          - If tokens are already flowing when an error occurs → save partial text, stop
        The full (or partial) response is saved to the session context after streaming.

        on_status: optional callable(event: str, *args) for real-time UI updates.
          "routing"  decision, routing_s        — decision made; routing_s = seconds taken
          "fallback" from_prov, error, to_prov  — provider failed, trying next
        """
        import time as _time
        cfg = self._config.load()
        session = self._context.get_session(request.session_name)

        # Load project-level instructions (UAI.md / .uai/instructions.md)
        instructions = None
        try:
            from uai.core.project_context import find_project_instructions
            instructions = find_project_instructions()
        except Exception:
            pass

        _user_msg_saved = False

        # Prepare history
        history: list[Message] | None = None
        history_tokens = 0
        if request.use_context:
            history = await self._prepare_history(session, request, cfg)
            if instructions and history is not None:
                from uai.models.context import MessageRole, Message as _SysMsg
                sys_msg = _SysMsg(
                    id=-99,
                    role=MessageRole.SYSTEM,
                    content=f"[Project instructions]:\n{instructions}",
                    tokens=self._context._estimate_tokens(instructions),
                )
                history = [sys_msg] + history
            history_tokens = sum(m.tokens or 0 for m in history) if history else 0

        # Route to best provider — measure duration (includes smart classifier await)
        _t0_route = _time.monotonic()
        decision = await self._router.route(
            prompt=request.prompt,
            task_type=request.task_type,
            prefer_provider=request.provider,
            free_only=request.free_only,
            history_tokens=history_tokens,
            cfg=cfg,
        )
        _routing_s = _time.monotonic() - _t0_route

        # Notify caller: routing decision + how long it took
        if on_status:
            on_status("routing", decision, _routing_s)

        # Save user message to context
        if request.use_context:
            self._context.add_user_message(session, request.prompt)
            _user_msg_saved = True

        # Build fallback chain: primary first, then alternatives
        chain = [decision.provider] + decision.alternatives
        errors: dict[str, str] = {}

        for i, provider_name in enumerate(chain):
            provider = self._providers.get(provider_name)
            if provider is None:
                errors[provider_name] = "not instantiated"
                if on_status:
                    on_status("fallback", provider_name, "not instantiated",
                              chain[i + 1] if i + 1 < len(chain) else None)
                continue

            if on_status:
                on_status("attempt", provider_name, 1, "stream")

            full_text = ""
            tokens_yielded = 0

            try:
                async for token in provider.stream(request.prompt, history=history):
                    full_text += token
                    tokens_yielded += 1
                    yield token

                # Streaming completed successfully — record and save
                self._quota.record(UsageRecord(
                    provider=provider_name,
                    model=decision.model or "",
                    backend="cli",
                    tokens_output=self._context._estimate_tokens(full_text),
                    success=True,
                ))
                if request.use_context and full_text:
                    self._context.add_assistant_message(
                        session,
                        content=full_text,
                        provider=provider.name,
                        model=decision.model or "",
                        tokens=self._context._estimate_tokens(full_text),
                    )
                    # Fire background fact extraction for core memory (Layer 3)
                    _task = asyncio.create_task(
                        self._context.update_core_memory(session, request.prompt, full_text)
                    )
                    _task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                return  # Done — don't try remaining providers

            except (RateLimitError, AuthError, ProviderError, Exception) as e:
                errors[provider_name] = str(e)
                self._quota.record(UsageRecord(
                    provider=provider_name,
                    model=decision.model or "",
                    backend="cli",
                    success=False,
                    error=str(e),
                ))

                if tokens_yielded > 0:
                    # Tokens were already sent to the user — can't retract them.
                    # Save whatever arrived and stop.
                    if request.use_context and full_text:
                        self._context.add_assistant_message(
                            session,
                            content=full_text,
                            provider=provider.name,
                            model=decision.model or "",
                            tokens=self._context._estimate_tokens(full_text),
                        )
                    return

                # No tokens yielded yet → safe to try the next provider in chain
                if isinstance(e, RateLimitError):
                    self._quota.set_cooldown(provider_name, 300)

                # Notify caller of fallback before continuing to next provider
                next_prov = chain[i + 1] if i + 1 < len(chain) else None
                if on_status:
                    on_status("fallback", provider_name, str(e), next_prov)
                continue

        # Every provider in the chain failed before yielding a single token
        raise AllProvidersFailedError(errors)

    # ──────────────────────────────────────────────────────────────────
    # Convenience accessors used by CLI commands
    # ──────────────────────────────────────────────────────────────────

    @property
    def config(self) -> ConfigManager:
        return self._config

    @property
    def auth(self) -> AuthManager:
        return self._auth

    @property
    def quota(self) -> QuotaTracker:
        return self._quota

    @property
    def context(self) -> ContextManager:
        return self._context

    @property
    def providers(self) -> dict[str, BaseProvider]:
        return self._providers

    @property
    def router(self) -> RouterEngine:
        return self._router
