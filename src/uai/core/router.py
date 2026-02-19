"""Router Engine — intelligent provider selection with cost-awareness."""
from __future__ import annotations
from dataclasses import dataclass, field

from uai.core.auth import AuthManager
from uai.core.config import ConfigManager
from uai.core.quota import QuotaTracker
from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.providers import get_provider_class, list_providers
from uai.utils.health import get_provider_status, mark_cooldown


# Task-type keyword hints (order matters: first match wins)
_TASK_KEYWORDS: list[tuple[TaskCapability, list[str]]] = [
    (TaskCapability.DEBUGGING,       ["bug", "error", "fix", "debug", "traceback", "exception", "crash", "fail"]),
    (TaskCapability.ARCHITECTURE,    ["architect", "design", "pattern", "solid", "structure", "refactor", "ddd"]),
    (TaskCapability.CODE_REVIEW,     ["review", "audit", "check", "assess", "improve", "quality"]),
    (TaskCapability.CODE_GENERATION, ["implement", "write", "create", "generate", "build", "add feature"]),
    (TaskCapability.LONG_CONTEXT,    ["entire codebase", "all files", "full project", "whole repo"]),
    (TaskCapability.BATCH_PROCESSING,["batch", "bulk", "all items", "for each", "loop over", "process all"]),
    (TaskCapability.PRIVACY_AUDIT,   ["lgpd", "gdpr", "pii", "privacy", "personal data", "sensitive data"]),
    (TaskCapability.DATA_ANALYSIS,   ["analyze", "analyse", "stats", "metrics", "chart", "summarize"]),
]


@dataclass
class RoutingDecision:
    provider: str
    model: str | None
    backend: BackendType
    task_type: TaskCapability
    estimated_cost: float
    reason: str
    alternatives: list[str] = field(default_factory=list)


class NoProviderAvailableError(Exception):
    pass


class RouterEngine:
    def __init__(
        self,
        config: ConfigManager,
        auth: AuthManager,
        quota: QuotaTracker,
    ) -> None:
        self._config = config
        self._auth = auth
        self._quota = quota

    async def route(
        self,
        prompt: str,
        task_type: TaskCapability | None = None,
        prefer_provider: str | None = None,
        free_only: bool | None = None,
        history_tokens: int = 0,
    ) -> RoutingDecision:
        cfg = self._config.load()

        # Override free_only from config if not explicitly set
        if free_only is None:
            free_only = cfg.defaults.cost_mode == "free_only"

        # Force a specific provider
        if prefer_provider:
            return await self._pin_provider(prefer_provider, prompt, task_type, history_tokens)

        # Classify task
        if task_type is None:
            task_type = self._classify(prompt)

        # Get ordered candidate chain for this task
        chain = cfg.routing.task_routing.get(task_type.value, cfg.routing.fallback_chain)

        # Build scored list of available providers
        scored: list[tuple[str, float]] = []
        for name in chain:
            prov_cfg = cfg.providers.get(name)
            if not prov_cfg or not prov_cfg.enabled:
                continue

            # Check quota
            if self._quota.in_cooldown(name):
                continue
            daily_limit = prov_cfg.daily_limit
            if daily_limit and self._quota.is_exhausted(name, daily_limit):
                continue

            # Check health (cached)
            try:
                cls = get_provider_class(name)
            except ValueError:
                continue

            # Filter free-only
            if free_only and not cls.is_free:
                continue

            # Filter by context window (history must fit)
            if history_tokens > 0 and history_tokens > cls.context_window_tokens * 0.6:
                continue

            score = self._score(name, cls, task_type, prov_cfg, free_only)
            scored.append((name, score))

        if not scored:
            # Try without free constraint as a last resort
            if free_only:
                return await self.route(prompt, task_type, prefer_provider, free_only=False, history_tokens=history_tokens)
            raise NoProviderAvailableError(
                "No providers available. Run 'uai status' for details."
            )

        scored.sort(key=lambda x: x[1], reverse=True)
        winner, _ = scored[0]
        alternatives = [n for n, _ in scored[1:]]

        prov_cls = get_provider_class(winner)
        prov_cfg = cfg.providers[winner]
        backend = self._select_backend(prov_cls, prov_cfg)
        model = prov_cfg.default_model

        return RoutingDecision(
            provider=winner,
            model=model,
            backend=backend,
            task_type=task_type,
            estimated_cost=0.0,   # Fine-grained cost estimated in executor
            reason=self._explain(winner, task_type, free_only, prov_cls.is_free),
            alternatives=alternatives,
        )

    # ──────────────────────────────────────────────────────────────────
    async def _pin_provider(
        self,
        name: str,
        prompt: str,
        task_type: TaskCapability | None,
        history_tokens: int,
    ) -> RoutingDecision:
        cfg = self._config.load()
        prov_cfg = cfg.providers.get(name)
        if not prov_cfg or not prov_cfg.enabled:
            raise NoProviderAvailableError(f"Provider '{name}' is not enabled.")
        try:
            cls = get_provider_class(name)
        except ValueError:
            raise NoProviderAvailableError(f"Provider '{name}' not found.")
        backend = self._select_backend(cls, prov_cfg)
        task = task_type or self._classify(prompt)
        return RoutingDecision(
            provider=name,
            model=prov_cfg.default_model,
            backend=backend,
            task_type=task,
            estimated_cost=0.0,
            reason=f"Pinned by user to {name}",
        )

    def _score(self, name: str, cls, task: TaskCapability, prov_cfg, free_only: bool) -> float:
        score = 0.0

        # Capability match (0–40)
        if task in cls.capabilities:
            idx = cls.capabilities.index(task)
            score += max(0, 40 - idx * 8)

        # Cost factor (0–30): free providers win
        if cls.is_free:
            score += 30
        elif not free_only:
            score += 10

        # Priority from config (0–20)
        score += prov_cfg.priority * 4

        # Recent success rate (0–10)
        success_rate = self._quota.get_success_rate(name)
        score += success_rate * 10

        return score

    def _classify(self, prompt: str) -> TaskCapability:
        lower = prompt.lower()
        for cap, keywords in _TASK_KEYWORDS:
            if any(kw in lower for kw in keywords):
                return cap
        return TaskCapability.GENERAL_CHAT

    def _select_backend(self, cls, prov_cfg) -> BackendType:
        pref = getattr(prov_cfg, "preferred_backend", "auto")
        if pref == "cli" and BackendType.CLI in cls.supported_backends:
            return BackendType.CLI
        if pref == "api" and BackendType.API in cls.supported_backends:
            return BackendType.API
        return cls.supported_backends[0] if cls.supported_backends else BackendType.API

    def _explain(self, provider: str, task: TaskCapability, free_only: bool, is_free: bool) -> str:
        parts = [f"Selected {provider}"]
        parts.append(f"(best for {task.value})")
        if is_free:
            parts.append("[free]")
        if free_only:
            parts.append("[cost-zero mode]")
        return " ".join(parts)
