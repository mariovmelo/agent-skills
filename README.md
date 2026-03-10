# UAI — Unified AI CLI

> One tool. All AI providers. Persistent context. Intelligent routing. Zero lock-in.

`uai` is an installable Python CLI that integrates multiple AI providers (Claude, Gemini, Codex, Qwen, Ollama, DeepSeek, Groq) under a single interface. It manages credentials, routes requests intelligently, maintains its own persistent context (so you can switch providers mid-conversation), and never leaves you without a response thanks to automatic fallback.

---

## Install

The recommended way to install `uai` is via [`pipx`](https://pipx.pypa.io), which automatically adds the command to your PATH:

```bash
pipx install uai-cli
```

If you don't have `pipx`:

```bash
# macOS
brew install pipx
pipx ensurepath

# Linux / Windows (WSL)
pip install pipx
pipx ensurepath
```

> **Avoid plain `pip install` for CLIs.** On macOS, pip installs binaries to `~/Library/Python/3.x/bin/` which is not in PATH by default, requiring manual PATH configuration.

Or from source:

```bash
git clone https://github.com/your-org/agent-skills
cd agent-skills
pipx install -e .
```

---

## Quick Start

```bash
# First-time setup (detects installed CLIs, creates ~/.uai/config.yaml)
uai setup

# Connect your providers
uai connect gemini      # OAuth via Gemini CLI (free)
uai connect qwen        # OAuth via qwen-code CLI (1000 req/day free)
uai connect claude      # API key
uai connect codex       # API key

# Ask anything
uai ask "explain this error: TypeError: NoneType is not subscriptable"

# Continue the conversation (context is persisted automatically)
uai ask "how would I fix it?"

# Switch providers mid-conversation — context is injected automatically
uai ask --provider gemini "now show me the corrected code"

# Interactive chat session
uai chat

# Code tasks (routes to best code-focused provider)
uai code "implement a binary search tree in Python"

# Multi-AI orchestration
uai orchestrate "review the architecture of src/"
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Multi-provider** | Claude, Gemini, Codex, Qwen, Ollama, DeepSeek, Groq |
| **Dual backend** | Each provider supports API (SDK) and CLI — CLI preferred when free |
| **Persistent context** | SQLite sessions at `~/.uai/sessions/` — independent of provider context |
| **Provider switching** | Change providers mid-conversation; history is reformatted and injected |
| **Intelligent routing** | 2-stage classification (keyword + LLM) → scoring → best available provider |
| **Automatic fallback** | 3-layer resilience: retry → cross-provider failover → API→CLI degradation |
| **Quota tracking** | Per-provider usage, cost (USD), alerts before hitting limits |
| **Auto-install CLIs** | `uai setup --install` installs missing provider CLIs via npm/curl |
| **Multi-AI teams** | 8 orchestration patterns: parallel analysis, cross-validation, etc. |
| **Cost-zero default** | Free providers and free CLI backends are always tried first |
| **Debug mode** | `--debug` / `-d` shows full trace: routing, attempts, errors, timings |
| **File access control** | Per-provider `readonly`/`readwrite` via `/access` — bulk with `all` |

---

## Providers

| Provider | Free Tier | Backend | Best For |
|----------|-----------|---------|----------|
| **Gemini** | CLI (unlimited) | CLI: `gemini -m MODEL -p` / API: google-genai | Architecture, long context (1M tokens) |
| **Qwen** | CLI (1000 req/day) | CLI: `qwen -p` / API: OpenRouter | Code review, batch processing |
| **Ollama** | Local (unlimited) | API: OpenAI-compatible local | Privacy, offline use |
| **DeepSeek** | Free tier | API: OpenAI-compatible | Cost-efficient general tasks |
| **Groq** | Free tier | API: OpenAI-compatible | Ultra-low latency |
| **Claude** | Paid | CLI: `claude -p` / API: anthropic | Consolidation, strategy |
| **Codex** | Paid | CLI: `codex exec` / API: openai | Debugging, implementation |

---

## Commands

```
uai setup                          First-time wizard: detect CLIs, create config
uai setup --install                Auto-install missing provider CLIs

uai connect <provider>             Connect a provider account (API key or CLI auth)

uai ask "prompt"                   Single query with session context
uai ask --provider gemini "..."    Force a specific provider
uai ask --free "..."               Cost-zero providers only
uai ask --new "..."                Ignore session context for this query
uai ask --session myproject "..."  Use a named session
uai ask --debug "..."              Show full provider trace (routing, errors, timings)

uai chat                           Interactive REPL with persistent context
uai chat --session myproject       Named session
uai chat --provider claude         Force provider for the session
uai chat --debug                   Show debug trace after every response

uai code "task"                    Code-focused task (routes to code providers)
uai orchestrate "task"             Multi-AI team orchestration

uai sessions list                  List all sessions
uai sessions show [name]           View session history
uai sessions delete [name]         Delete a session
uai sessions export [name] --format markdown   Export conversation

uai status                         Provider health dashboard
uai quota                          Usage and cost report
uai config show                    Show current configuration
uai config set defaults.cost_mode balanced    Change a config value
uai providers                      List providers with status
```

### Chat REPL Commands

Inside `uai chat`, use slash commands:

```
/provider gemini          Switch provider (context is carried over)
/provider                 Return to automatic routing
/history                  Show conversation history
/clear                    Clear current session history
/export [file.md]         Export session to markdown
/status                   Show provider status
/session                  Show current session and list available ones
/access <prov> readonly   Block file writes for a provider
/access <prov> readwrite  Allow file writes for a provider
/access all readonly      Set readonly for ALL providers at once
/access all readwrite     Set readwrite for ALL providers at once
/providers                List providers with file_access column
/exit                     Exit chat
```

---

## Context Management

UAI maintains its own conversation history in SQLite databases at `~/.uai/sessions/`. This is independent of any provider's native context.

### Injection Strategies

When sending a request, UAI automatically selects the best strategy:

| Strategy | When Used | How |
|----------|-----------|-----|
| **full** | History fits in provider's context window | Inject all messages |
| **windowed** | History is long but recent turns are enough | Inject last N turns |
| **summarized** | History too long for windowed | Auto-summarize old turns (using free provider), inject summary + recent turns |

### Switching Providers Mid-Conversation

```bash
uai ask "explain this function"                    # uses Gemini (free)
uai ask "now refactor it"                          # still Gemini
uai ask --provider claude "write unit tests"        # switches to Claude
# Claude receives the full conversation history, reformatted to its native API format
```

History is automatically adapted to each provider's format:
- **Claude / OpenAI**: `[{"role": "user", "content": "..."}, {"role": "assistant", ...}]`
- **Gemini**: `[{"role": "user", "parts": [{"text": "..."}]}, {"role": "model", ...}]`
- **CLI providers**: Plain text `User: ...\nAssistant: ...`

---

## Orchestration

UAI includes 8 multi-AI team patterns:

| Pattern | Execution | Providers |
|---------|-----------|-----------|
| **Full Analysis** | Parallel → consolidate | Gemini + Codex + Qwen → Claude |
| **Daily Dev** | Sequential escalation | Qwen → Gemini → Claude |
| **Critical Debug** | Sequential | Codex → Qwen → Gemini → Claude |
| **LGPD Audit** | Parallel → consolidate | Gemini + Qwen → Claude |
| **Batch Processing** | Parallel workers | Qwen + Gemini |
| **Brainstorm** | Parallel → synthesize | All → Claude |
| **Cross-Validation** | Sequential | Producer → Validator → Arbiter |
| **Specialist + Generalist** | Parallel | Specialist + second opinion |

```bash
uai orchestrate "perform a full security audit of src/"
# Runs parallel analysis on Gemini, Codex, and Qwen
# Claude consolidates results into a unified report
```

---

## Configuration

Config file: `~/.uai/config.yaml` (created by `uai setup`, see `uai.yaml.example`).

```yaml
version: 1

defaults:
  session: default
  cost_mode: free_only      # free_only | balanced | performance
  context_strategy: auto    # auto | full | windowed | summarized

providers:
  gemini:
    enabled: true
    default_model: flash
    preferred_backend: cli  # CLI is free and preferred
    priority: 5
  qwen:
    enabled: true
    default_model: coder
    preferred_backend: cli  # qwen-code OAuth is free (1000 req/day)
    priority: 4
    daily_limit: 1000
  claude:
    enabled: true
    default_model: sonnet
    preferred_backend: api
    priority: 2             # Paid — use only when needed

routing:
  fallback_chain: [gemini, qwen, ollama, claude, codex]

context:
  summarize_with: gemini    # free provider used for auto-summarization
  max_history_tokens: 50000
  keep_recent_turns: 10

quota:
  alert_threshold_usd: 1.0
  alert_threshold_percent: 80
```

---

## Routing

Requests are classified and routed to the best scoring provider:

| Task Type | Keywords | Default Providers |
|-----------|----------|-------------------|
| Debugging | bug, error, fix, debug, traceback | Codex, Claude, Gemini |
| Code Generation | implement, write, create, generate | Codex, Qwen, Claude |
| Code Review | review, audit, check, quality | Qwen, Gemini, Claude |
| Architecture | architect, design, pattern, solid | Gemini, Claude |
| Long Context | analyze, large file, codebase | Gemini (1M tokens) |
| General Chat | explain, what, how, describe | Gemini, Qwen, Ollama |

Scoring (0-100): capability match (0-40) + cost bonus for free (0-30) + priority (0-20) + recent success rate (0-10).

---

## Fallback

3-layer automatic fallback:

1. **Intra-provider retry**: 3 attempts with backoff (5s / 15s / 45s)
2. **Cross-provider failover**: rate limit or auth error → next in fallback chain
3. **Graceful degradation**: API fails → tries CLI backend of same provider

---

## Debug Mode

Add `--debug` (or `-d`) to any `ask` or `chat` command to see a full execution trace:

```bash
uai ask "fix this bug" --debug
uai chat --debug
```

The debug panel shows every event with relative timestamps:

```
╭──────────────── uai debug trace ────────────────╮
│ +1.5s  ROUTING     qwen CLI · qwen3-coder  routing=1.5s
│                      alternatives: gemini, claude
│ +1.6s  ATTEMPT     qwen  #1  via stream
│ +73.7s FALLBACK    qwen failed
│                      Qwen CLI timed out after 120s | stderr: ...
│                      → trying gemini
│ +73.7s ATTEMPT     gemini  #1  via stream
│ +164s  DONE        OK  total=164.58s
╰─────────────────────────────────────────────────╯
```

---

## File Access Control

Control whether providers are allowed to write files:

```bash
# Inside uai chat:
/access all readonly        # block writes for all providers
/access all readwrite       # allow writes for all providers
/access gemini readonly     # per-provider control
```

Or via config:

```bash
uai config set providers.qwen.file_access readonly
```

---

## Packaging

The project uses [Hatchling](https://hatch.pypa.io/) as its build backend.

### Build a distribution

```bash
pip install build
python -m build
# produces dist/uai-X.Y.Z.tar.gz and dist/uai-X.Y.Z-py3-none-any.whl
```

### Publish to PyPI

```bash
pip install twine
twine upload dist/*
```

Or with Hatch directly:

```bash
pip install hatch
hatch build
hatch publish          # prompts for PyPI token
```

### Bump version before publishing

Edit `pyproject.toml` and `src/uai/__init__.py`:

```toml
# pyproject.toml
version = "0.2.0"
```

```python
# src/uai/__init__.py
__version__ = "0.2.0"
```

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

Optional privacy features (PII anonymization via Presidio):

```bash
pip install -e ".[privacy]"
```

### Adding a Provider Plugin

```toml
[project.entry-points."uai.providers"]
myprovider = "mypkg.provider:MyProvider"
```

---

## Legacy Documentation

Original orchestration skill documentation preserved in [`legacy/`](legacy/):

| File | Contents |
|------|----------|
| `legacy/SKILL.md` | Original Claude Code skill policy |
| `legacy/ai-catalog.md` | AI CLI catalog with calling conventions |
| `legacy/calling-conventions.md` | Exact CLI commands, timeouts, output parsing |
| `legacy/team-patterns.md` | 8 multi-AI team patterns (codified in `orchestration/patterns.py`) |
| `legacy/examples.md` | 6 practical orchestration examples |
| `legacy/privacy-tools.md` | LGPD compliance and PII anonymization |

---

## Author

**Diego Câmara** — [@diegocamara89](https://github.com/diegocamara89)

## License

MIT
