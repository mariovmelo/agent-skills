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
from pathlib import Path

from uai.core.auth import AuthManager
from uai.core.config import ConfigManager
from uai.core.context import ContextManager
from uai.core.fallback import FallbackChain
from uai.core.quota import QuotaTracker
from uai.core.router import RouterEngine
from uai.models.context import Message
from uai.models.provider import BackendType
from uai.models.request import UAIRequest, UAIResponse
from uai.providers import get_provider_class
from uai.providers.base import BaseProvider


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
    async def execute(self, request: UAIRequest) -> UAIResponse:
        cfg = self._config.load()
        session = self._context.get_session(request.session_name)

        # 1. Save the user message
        if request.use_context:
            self._context.add_user_message(session, request.prompt)

        # 2. Load and prepare history (pass cfg to avoid re-loading)
        history: list[Message] | None = None
        history_tokens = 0
        if request.use_context:
            history = await self._prepare_history(session, request, cfg)
            history_tokens = sum(m.tokens or 0 for m in history) if history else 0

        # 3. Route to best provider (pass cfg to avoid re-loading)
        decision = await self._router.route(
            prompt=request.prompt,
            task_type=request.task_type,
            prefer_provider=request.provider,
            free_only=request.free_only,
            history_tokens=history_tokens,
            cfg=cfg,
        )

        # 4. Execute with fallback
        response, providers_tried = await self._fallback.execute(
            prompt=request.prompt,
            decision=decision,
            history=history,
        )

        # 5. Save assistant response
        if request.use_context:
            self._context.add_assistant_message(
                session,
                content=response.text,
                provider=response.provider,
                model=response.model,
                tokens=response.tokens_output,
            )

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
        self, session, request: UAIRequest, cfg=None
    ) -> list[Message]:
        """Get history messages, excluding the most recent user message (just added)."""
        cfg = cfg or self._config.load()
        all_messages = self._context.get_messages(session)
        # Exclude the last message (which we just added)
        history = all_messages[:-1] if all_messages else []
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
        )
        return prepared

    # ──────────────────────────────────────────────────────────────────
    async def execute_stream(self, request: UAIRequest):
        """
        Like execute(), but yields tokens as they arrive via the provider's stream().

        The full response is saved to the session context after streaming completes.
        This is an async generator — use `async for token in executor.execute_stream(req)`.
        """
        cfg = self._config.load()  # Load once; passed to sub-calls to avoid re-parsing
        session = self._context.get_session(request.session_name)

        # Load project-level instructions (UAI.md / .uai/instructions.md)
        instructions = None
        try:
            from uai.core.project_context import find_project_instructions
            instructions = find_project_instructions()
        except Exception:
            pass

        # Save user message to context
        if request.use_context:
            self._context.add_user_message(session, request.prompt)

        # Prepare history (pass cfg to avoid re-loading)
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

        # Route to best provider (pass cfg to avoid re-loading)
        decision = await self._router.route(
            prompt=request.prompt,
            task_type=request.task_type,
            prefer_provider=request.provider,
            free_only=request.free_only,
            history_tokens=history_tokens,
            cfg=cfg,
        )

        provider = self._providers.get(decision.provider)
        if provider is None:
            provider = next(iter(self._providers.values()), None)
        if provider is None:
            from uai.core.errors import NoProviderAvailableError
            raise NoProviderAvailableError()

        # Stream tokens and accumulate
        full_text = ""
        async for token in provider.stream(request.prompt, history=history):
            full_text += token
            yield token

        # Save complete response to context (estimate tokens from accumulated text)
        if request.use_context and full_text:
            self._context.add_assistant_message(
                session,
                content=full_text,
                provider=provider.name,
                model=decision.model or "",
                tokens=self._context._estimate_tokens(full_text),
            )

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
