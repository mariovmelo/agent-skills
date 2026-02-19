"""
Team patterns — codified from team-patterns.md.

These are the 8 pre-built orchestration patterns adapted from the existing
skill documentation. They are SUGGESTIONS, not fixed rules.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TeamRole:
    role: str
    provider: str
    model: str | None
    prompt_template: str
    is_free: bool


@dataclass
class TeamPattern:
    name: str
    description: str
    roles: list[TeamRole]
    execution: Literal["parallel", "sequential", "mixed"]
    cost_estimate: Literal["free", "mostly_free", "mixed", "paid"]


# ──────────────────────────────────────────────────────────────────────────────
PATTERNS: dict[str, TeamPattern] = {

    "full_analysis": TeamPattern(
        name="Full Code Analysis",
        description="Complete analysis: architecture (Gemini), bugs (Codex), review (Qwen) — parallel, then Claude consolidates",
        roles=[
            TeamRole("architect",  "gemini", "pro",   "Analyze architecture, anti-patterns, SOLID principles: {task}", True),
            TeamRole("debugger",   "codex",  None,    "Find bugs, security issues, performance problems: {task}", False),
            TeamRole("reviewer",   "qwen",   None,    "Educational code review, suggest improvements: {task}", True),
        ],
        execution="parallel",
        cost_estimate="mixed",
    ),

    "daily_dev": TeamPattern(
        name="Daily Development (Economic)",
        description="Quick review with free providers, escalate only if needed",
        roles=[
            TeamRole("reviewer",   "qwen",   None,    "Initial code review, find obvious issues: {task}", True),
            TeamRole("validator",  "gemini", "flash", "Confirm findings from previous review: {task}", True),
        ],
        execution="sequential",
        cost_estimate="free",
    ),

    "critical_debug": TeamPattern(
        name="Critical Debugging",
        description="Sequential deep debug: Codex identifies, Qwen validates, Gemini checks impact, Claude plans fix",
        roles=[
            TeamRole("debugger",   "codex",  None,    "Identify the exact bug and root cause: {task}", False),
            TeamRole("analyst",    "qwen",   None,    "Understand context and impact of the bug: {task}", True),
            TeamRole("architect",  "gemini", "pro",   "Check architectural impact: {task}", True),
            TeamRole("planner",    "claude", "sonnet","Plan systematic fix and prevention: {task}", False),
        ],
        execution="sequential",
        cost_estimate="mixed",
    ),

    "lgpd_audit": TeamPattern(
        name="LGPD/Privacy Audit",
        description="Privacy audit: Gemini and Qwen audit in parallel, Claude decides",
        roles=[
            TeamRole("auditor_1",  "gemini", "pro",   "Perform exhaustive privacy/LGPD audit: {task}", True),
            TeamRole("auditor_2",  "qwen",   None,    "Second opinion privacy audit: {task}", True),
        ],
        execution="parallel",
        cost_estimate="mostly_free",
    ),

    "batch_processing": TeamPattern(
        name="Batch Processing",
        description="Parallel free workers process items, paid provider QA-samples the results",
        roles=[
            TeamRole("worker_1",   "qwen",   None,    "Process each item: {task}", True),
            TeamRole("worker_2",   "gemini", "flash", "Process each item (second batch): {task}", True),
        ],
        execution="parallel",
        cost_estimate="free",
    ),

    "brainstorm": TeamPattern(
        name="Brainstorm / Multiple Perspectives",
        description="All providers answer the same prompt in parallel, Claude synthesizes",
        roles=[
            TeamRole("perspective_gemini", "gemini", "pro",   "Provide architectural perspective: {task}", True),
            TeamRole("perspective_qwen",   "qwen",   None,    "Provide educational perspective: {task}", True),
            TeamRole("perspective_claude", "claude", "sonnet","Provide executive/strategic perspective: {task}", False),
        ],
        execution="parallel",
        cost_estimate="mixed",
    ),

    "cross_validation": TeamPattern(
        name="Cross-Validation Pipeline",
        description="Producer generates, Validator critiques, Arbitrator decides — sequential chain",
        roles=[
            TeamRole("producer",   "gemini", "pro",   "Generate solution for: {task}", True),
            TeamRole("validator",  "codex",  None,    "Validate and critique the solution: {task}", False),
            TeamRole("arbitrator", "claude", "sonnet","Arbitrate between producer and validator: {task}", False),
        ],
        execution="sequential",
        cost_estimate="mixed",
    ),

    "specialist_generalist": TeamPattern(
        name="Specialist + Generalist",
        description="Domain specialist + different model for second opinion — parallel",
        roles=[
            TeamRole("specialist",   "codex",  None,    "As a code specialist: {task}", False),
            TeamRole("generalist",   "gemini", "pro",   "As a generalist analyst: {task}", True),
        ],
        execution="parallel",
        cost_estimate="mixed",
    ),
}


def get_pattern(name: str) -> TeamPattern | None:
    return PATTERNS.get(name)


def list_patterns() -> list[str]:
    return list(PATTERNS.keys())
