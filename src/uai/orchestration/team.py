"""TeamBuilder — executes multi-AI team patterns."""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field

from rich import print as rprint
from rich.progress import Progress, SpinnerColumn, TextColumn

from uai.core.auth import AuthManager
from uai.core.config import ConfigManager
from uai.core.quota import QuotaTracker
from uai.models.quota import UsageRecord
from uai.orchestration.patterns import TeamPattern, TeamRole
from uai.providers import get_provider_class
from uai.providers.base import BaseProvider, ProviderError


@dataclass
class RoleResult:
    role: str
    provider: str
    model: str
    status: str           # "ok" | "error"
    text: str
    error: str | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0


@dataclass
class TeamResult:
    pattern_name: str
    task: str
    role_results: list[RoleResult] = field(default_factory=list)
    consolidated: str = ""
    total_cost_usd: float = 0.0
    execution_ms: float = 0.0


class TeamBuilder:
    def __init__(
        self,
        config: ConfigManager,
        auth: AuthManager,
        quota: QuotaTracker,
    ) -> None:
        self._config = config
        self._auth = auth
        self._quota = quota

    async def execute(self, pattern: TeamPattern, task: str) -> TeamResult:
        t0 = time.monotonic()
        result = TeamResult(pattern_name=pattern.name, task=task)

        rprint(f"\n[bold]Team:[/bold] {pattern.name} | [dim]Execution: {pattern.execution}[/dim]")

        if pattern.execution == "parallel":
            role_results = await self._run_parallel(pattern.roles, task)
        else:
            role_results = await self._run_sequential(pattern.roles, task)

        result.role_results = role_results
        result.total_cost_usd = sum(r.cost_usd for r in role_results)
        result.execution_ms = (time.monotonic() - t0) * 1000

        # Consolidate results using Claude (or best available provider)
        result.consolidated = await self._consolidate(pattern, task, role_results)
        return result

    async def _run_parallel(self, roles: list[TeamRole], task: str) -> list[RoleResult]:
        rprint(f"[dim]Running {len(roles)} providers in parallel...[/dim]")
        tasks = [self._execute_role(role, task, {}) for role in roles]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r if isinstance(r, RoleResult) else RoleResult(
            role=roles[i].role, provider=roles[i].provider, model="",
            status="error", text="", error=str(results[i]),
        ) for i, r in enumerate(results)]

    async def _run_sequential(self, roles: list[TeamRole], task: str) -> list[RoleResult]:
        """Sequential: each role's output is passed as context to the next."""
        results: list[RoleResult] = []
        accumulated: dict[str, str] = {}

        for role in roles:
            rprint(f"  [cyan]{role.role}[/cyan] ({role.provider})...", end=" ")
            result = await self._execute_role(role, task, accumulated)
            results.append(result)
            if result.status == "ok":
                accumulated[role.role] = result.text
                rprint("[green]done[/green]")
            else:
                rprint(f"[red]failed: {result.error}[/red]")

        return results

    async def _execute_role(
        self, role: TeamRole, task: str, context: dict[str, str]
    ) -> RoleResult:
        """Execute a single role using the specified provider."""
        cfg = self._config.load()
        prov_cfg = cfg.providers.get(role.provider)
        if not prov_cfg or not prov_cfg.enabled:
            return RoleResult(
                role=role.role, provider=role.provider, model="",
                status="error", text="", error=f"Provider {role.provider} not enabled",
            )

        try:
            cls = get_provider_class(role.provider)
            provider = cls(self._auth, prov_cfg)
        except Exception as e:
            return RoleResult(
                role=role.role, provider=role.provider, model="",
                status="error", text="", error=str(e),
            )

        # Build prompt from template
        context_text = ""
        if context:
            context_text = "\n\nPrevious results:\n" + "\n".join(
                f"[{r}]: {t[:500]}" for r, t in context.items()
            )
        prompt = role.prompt_template.format(task=task) + context_text

        t0 = time.monotonic()
        try:
            response = await provider.send(prompt=prompt, model=role.model, timeout=300)
            latency = (time.monotonic() - t0) * 1000

            # Record usage
            self._quota.record(UsageRecord(
                provider=role.provider,
                model=response.model,
                tokens_input=response.tokens_input or 0,
                tokens_output=response.tokens_output or 0,
                cost_usd=response.cost_usd or 0.0,
                latency_ms=latency,
                success=True,
            ))

            return RoleResult(
                role=role.role,
                provider=role.provider,
                model=response.model,
                status="ok",
                text=response.text,
                latency_ms=latency,
                cost_usd=response.cost_usd or 0.0,
            )
        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            self._quota.record(UsageRecord(
                provider=role.provider, success=False, error=str(e), latency_ms=latency,
            ))
            return RoleResult(
                role=role.role, provider=role.provider, model="",
                status="error", text="", error=str(e), latency_ms=latency,
            )

    async def _consolidate(self, pattern: TeamPattern, task: str, results: list[RoleResult]) -> str:
        """Use Claude (or best available) to consolidate all role results."""
        ok_results = [r for r in results if r.status == "ok"]
        if not ok_results:
            return "All providers failed to produce results."

        if len(ok_results) == 1:
            return ok_results[0].text

        # Build consolidation prompt
        summaries = "\n\n".join(
            f"## {r.role.upper()} ({r.provider}):\n{r.text[:2000]}"
            for r in ok_results
        )
        consolidation_prompt = f"""You are consolidating results from a multi-AI team analysis.

Task: {task}

Team results:
{summaries}

Please provide a unified consolidated report that:
1. Identifies key points all providers agreed on (consensus)
2. Notes any conflicting views (divergences)
3. Gives a final recommendation synthesizing all perspectives
4. Lists the most important action items

Be concise and actionable."""

        # Try Claude first for consolidation, fall back to Gemini
        cfg = self._config.load()
        for consolidator in ["claude", "gemini"]:
            prov_cfg = cfg.providers.get(consolidator)
            if not prov_cfg or not prov_cfg.enabled:
                continue
            try:
                cls = get_provider_class(consolidator)
                provider = cls(self._auth, prov_cfg)
                response = await provider.send(prompt=consolidation_prompt, timeout=180)
                return response.text
            except Exception:
                continue

        # Final fallback: format the results directly
        return "## Consolidated Results\n\n" + "\n\n---\n\n".join(
            f"**{r.role}** ({r.provider}):\n{r.text}" for r in ok_results
        )
