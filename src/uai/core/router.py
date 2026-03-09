"""Router Engine — intelligent provider selection with cost-awareness.

Routing uses a two-stage classification pipeline:
  Stage 1 (fast, always runs): keyword matching → zero latency fallback
  Stage 2 (parallel, best-effort): free LLM classifier (Gemini Flash / Qwen)
    - Runs concurrently with context preparation in executor
    - 1.5s hard timeout; falls back to Stage 1 result on any failure
    - Handles multilingual prompts, complexity estimation, long-context detection
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from uai.core.auth import AuthManager
from uai.core.config import ConfigManager
from uai.core.quota import QuotaTracker
from uai.models.config import ConfigSchema
from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.providers import get_provider_class, list_providers
from uai.utils.health import get_provider_status, mark_cooldown


# Prefixes that indicate a conversational/preference question.
# Prompts starting with these (or ending with '?') without explicit code markers
# are classified as GENERAL_CHAT even if they contain code-adjacent verbs.
_QUESTION_PREFIXES: tuple[str, ...] = (
    "qual ", "quais ", "o que ", "como ", "quando ", "onde ",
    "por que ", "por quê ", "você prefere", "gostaria ",
    "what ", "which ", "how ", "when ", "where ", "why ", "who ", "should i ",
)
_TECHNICAL_MARKERS: tuple[str, ...] = (
    "def ", "class ", "function ", "```", "import ", "error:", "traceback",
    "erro:", "bug:", ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
)

# Task-type keyword hints (order matters: first match wins)
_TASK_KEYWORDS: list[tuple[TaskCapability, list[str]]] = [
    (TaskCapability.DEBUGGING,       ["bug", "error", "fix", "debug", "traceback", "exception", "crash", "fail",
                                       "erro", "falha", "corrigir", "depurar", "conserta"]),
    (TaskCapability.ARCHITECTURE,    ["architect", "design", "pattern", "solid", "structure", "refactor", "ddd",
                                       "arquitetura", "estrutura", "refatora", "padrão"]),
    (TaskCapability.CODE_REVIEW,     ["review", "audit", "check", "assess", "improve", "quality",
                                       "revisar", "avaliar", "melhorar", "auditoria"]),
    (TaskCapability.CODE_GENERATION, ["implement", "write", "create", "generate", "build", "add feature",
                                       "implementar", "escrever", "criar", "gerar", "construir"]),
    (TaskCapability.LONG_CONTEXT,    ["entire codebase", "all files", "full project", "whole repo",
                                       "todo o projeto", "todos os arquivos", "repositório inteiro"]),
    (TaskCapability.BATCH_PROCESSING,["batch", "bulk", "all items", "for each", "loop over", "process all",
                                       "em lote", "todos os itens", "para cada"]),
    (TaskCapability.PRIVACY_AUDIT,   ["lgpd", "gdpr", "pii", "privacy", "personal data", "sensitive data",
                                       "privacidade", "dados pessoais", "dados sensíveis"]),
    (TaskCapability.DATA_ANALYSIS,   ["analyze", "analyse", "stats", "metrics", "chart", "summarize",
                                       "analisar", "análise", "métricas", "estatísticas", "resumir"]),
]

# Classification prompt for the LLM classifier (compact to minimize tokens)
_CLASSIFY_PROMPT = """\
Classify this developer request. Respond with ONLY a JSON object, no other text.

Request: {prompt}

JSON format:
{{
  "task_type": "<one of: debugging|code_generation|code_review|architecture|long_context|data_analysis|batch_processing|privacy_audit|general_chat>",
  "complexity": "<simple|medium|complex>",
  "needs_long_context": <true|false>,
  "prefer_free": <true if simple enough for a free model, else false>
}}

Rules:
- needs_long_context: true when the request implies large files, full codebase, or many files
- complexity: simple = single question/task; medium = multi-step; complex = system design or deep analysis
- prefer_free: false for complex reasoning, security, or production-critical tasks"""


class ClassificationCache:
    """Cache para classificação de prompts com expiração por tempo (TTL).
    
    Reduz custos (100-200 tokens por chamada) e latência do classificador LLM.
    """
    
    def __init__(self, max_size: int = 512, ttl_seconds: int = 300) -> None:
        self._cache: OrderedDict[str, tuple[SmartClassification, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
    
    def _hash_prompt(self, prompt: str) -> str:
        """Criar hash do prompt para usar como chave."""
        return hashlib.sha256(prompt.encode()).hexdigest()[:32]
    
    def get(self, prompt: str) -> SmartClassification | None:
        """Obter classificação cacheda se ainda válida."""
        key = self._hash_prompt(prompt)
        if key not in self._cache:
            return None
        
        result, timestamp = self._cache[key]
        if time.time() - timestamp > self._ttl:
            del self._cache[key]
            return None
        
        self._cache.move_to_end(key)
        return result
    
    def set(self, prompt: str, classification: SmartClassification) -> None:
        """Armazenar classificação no cache."""
        key = self._hash_prompt(prompt)
        
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        
        self._cache[key] = (classification, time.time())


@dataclass
class SmartClassification:
    """Result from the LLM-based classifier. All fields have safe defaults."""
    task_type: TaskCapability = TaskCapability.GENERAL_CHAT
    complexity: str = "medium"          # "simple" | "medium" | "complex"
    needs_long_context: bool = False
    prefer_free: bool = True


@dataclass
class RoutingDecision:
    provider: str
    model: str | None
    backend: BackendType
    task_type: TaskCapability
    estimated_cost: float
    reason: str
    alternatives: list[str] = field(default_factory=list)
    file_access: str = "readwrite"   # mirrors ProviderConfig.file_access — "readonly" blocks writing files


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
        
        cfg = self._config.load()
        self._classification_cache = ClassificationCache(
            max_size=cfg.router.classification_cache_size,
            ttl_seconds=cfg.router.classification_cache_ttl,
        )

    async def route(
        self,
        prompt: str,
        task_type: TaskCapability | None = None,
        prefer_provider: str | None = None,
        free_only: bool | None = None,
        history_tokens: int = 0,
        cfg: ConfigSchema | None = None,
        _smart: SmartClassification | None = None,
    ) -> RoutingDecision:
        cfg = cfg or self._config.load()

        # Override free_only from config if not explicitly set
        if free_only is None:
            free_only = cfg.defaults.cost_mode == "free_only"

        # Force a specific provider
        if prefer_provider:
            return await self._pin_provider(prefer_provider, prompt, task_type, history_tokens)

        # Stage 1: fast keyword classification (always available)
        keyword_type = self._classify(prompt)

        # Stage 2: LLM classifier — skip when keyword matching already found a specific
        # task type.  Running it only for GENERAL_CHAT saves ~2.5s on every code request.
        smart: SmartClassification | None = _smart  # caller may pre-supply result
        if smart is None and task_type is None and keyword_type == TaskCapability.GENERAL_CHAT:
            smart = await self._smart_classify(prompt, cfg)

        # Resolve final task_type
        if task_type is None:
            task_type = (smart.task_type if smart else None) or keyword_type

        # If LLM says long_context is needed and keyword didn't catch it, upgrade
        if smart and smart.needs_long_context and task_type not in (
            TaskCapability.LONG_CONTEXT, TaskCapability.BATCH_PROCESSING
        ):
            # Only override if not already a more specific type
            if task_type == TaskCapability.GENERAL_CHAT:
                task_type = TaskCapability.LONG_CONTEXT

        # Adjust free_only based on LLM complexity signal
        # If the LLM says "prefer_free=False" AND free_only wasn't forced by user/config, relax it
        if smart and not smart.prefer_free and free_only and cfg.defaults.cost_mode != "free_only":
            free_only = False

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

            # Skip providers that are not yet configured/ready
            try:
                if not cls(self._auth, prov_cfg).is_configured():
                    continue
            except Exception:
                continue

            score = self._score(name, cls, task_type, prov_cfg, free_only, smart)
            scored.append((name, score))

        if not scored:
            if free_only:
                return await self.route(
                    prompt, task_type, prefer_provider,
                    free_only=False, history_tokens=history_tokens, _smart=smart
                )
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
            estimated_cost=0.0,
            reason=self._explain(winner, task_type, free_only, prov_cls.is_free, smart),
            alternatives=alternatives,
            file_access=prov_cfg.file_access,
        )

    # ──────────────────────────────────────────────────────────────────
    # LLM-based smart classifier (Stage 2)
    # ──────────────────────────────────────────────────────────────────

    async def _smart_classify(self, prompt: str, cfg: ConfigSchema) -> SmartClassification | None:
        """
        Use a free LLM (Gemini Flash → Qwen fallback) to classify the prompt.

        Uses cache to avoid redundant LLM calls for similar prompts (saves 100-200 tokens/call).
        Runs with a configurable hard timeout.
        On any failure (timeout, parse error, subprocess not installed) returns None.

        Returns a SmartClassification with task_type, complexity, needs_long_context,
        and prefer_free signals. All fields default to safe values.
        """
        # Verificar cache primeiro
        cached = self._classification_cache.get(prompt)
        if cached is not None:
            return cached
        
        classify_prompt = _CLASSIFY_PROMPT.format(prompt=prompt[:600])
        try:
            raw = await asyncio.wait_for(
                self._call_free_llm(classify_prompt), timeout=cfg.router.smart_classifier_timeout
            )
        except (asyncio.TimeoutError, Exception):
            return None

        if not raw:
            return None

        try:
            # Strip markdown fences if the model wraps the JSON
            cleaned = re.sub(r'```(?:json)?\s*|\s*```', '', raw).strip()
            # Find the first {...} block in case the model adds preamble
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group())

            task_str = str(data.get("task_type", "")).strip().lower()
            task_type = TaskCapability.GENERAL_CHAT
            for cap in TaskCapability:
                if cap.value == task_str:
                    task_type = cap
                    break

            result = SmartClassification(
                task_type=task_type,
                complexity=str(data.get("complexity", "medium")).lower(),
                needs_long_context=bool(data.get("needs_long_context", False)),
                prefer_free=bool(data.get("prefer_free", True)),
            )
            
            # Armazenar no cache
            self._classification_cache.set(prompt, result)
            
            return result
        except Exception:
            return None

    async def _call_free_llm(self, prompt: str) -> str | None:
        """Try gemini CLI then qwen CLI for a quick LLM call."""
        for cmd in (
            ["gemini", "-m", "gemini-2.5-flash", "-p", prompt, "--approval-mode=yolo"],
            ["qwen", "-p", prompt, "-y"],
        ):
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=0.9)
                if proc.returncode == 0:
                    return stdout.decode(errors="replace").strip()
            except asyncio.TimeoutError:
                if proc is not None:
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
                continue
            except Exception:
                continue
        return None

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
            file_access=prov_cfg.file_access,
        )

    def _score(
        self,
        name: str,
        cls,
        task: TaskCapability,
        prov_cfg,
        free_only: bool,
        smart: SmartClassification | None = None,
    ) -> float:
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

        # ── Smart classification bonuses (0–20 extra) ───────────────
        if smart:
            # Long-context tasks: boost providers with large context windows
            if smart.needs_long_context:
                window = getattr(cls, "context_window_tokens", 0)
                if window >= 500_000:
                    score += 15   # Gemini 2M, etc.
                elif window >= 100_000:
                    score += 8

            # Complex tasks: prefer paid/higher-quality providers
            if smart.complexity == "complex" and not cls.is_free:
                score += 10
            # Simple tasks: prefer free/fast providers
            elif smart.complexity == "simple" and cls.is_free:
                score += 8

        return score

    def _classify(self, prompt: str) -> TaskCapability:
        lower = prompt.lower().strip()

        # Conversational/preference questions: don't misclassify as code tasks.
        # e.g. "Qual dessas melhorias você gostaria que eu começasse a implementar agora?"
        is_question = lower.endswith("?") or lower.startswith(_QUESTION_PREFIXES)
        if is_question and not any(m in lower for m in _TECHNICAL_MARKERS):
            return TaskCapability.GENERAL_CHAT

        for cap, keywords in _TASK_KEYWORDS:
            if any(kw in lower for kw in keywords):
                return cap
        return TaskCapability.GENERAL_CHAT

    def _select_backend(self, cls, prov_cfg) -> BackendType:
        """Delegate to provider's preferred_backend() — single source of truth.
        
        Avoids duplicating logic between router.py and base.py (DRY principle).
        """
        # Create temporary instance to call preferred_backend()
        # Note: We pass minimal config since we only need backend selection
        from uai.models.config import ProviderConfig
        temp_cfg = ProviderConfig(
            enabled=True,
            priority=prov_cfg.priority,
            default_model=prov_cfg.default_model,
            preferred_backend=getattr(prov_cfg, "preferred_backend", "cli"),
        )
        provider_instance = cls(auth=self._auth, provider_cfg=temp_cfg)
        return provider_instance.preferred_backend()

    def _explain(
        self,
        provider: str,
        task: TaskCapability,
        free_only: bool,
        is_free: bool,
        smart: SmartClassification | None = None,
    ) -> str:
        parts = [f"Selected {provider}"]
        parts.append(f"(best for {task.value})")
        if is_free:
            parts.append("[free]")
        if free_only:
            parts.append("[cost-zero mode]")
        if smart:
            parts.append(f"[{smart.complexity}]")
            if smart.needs_long_context:
                parts.append("[long-ctx]")
        return " ".join(parts)
