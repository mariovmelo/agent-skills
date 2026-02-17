# 🤖 orchestrate — Agent Skill para Orquestração Multi-IA via CLI

> Compatível com **Claude Code**, **Antigravity**, **Cursor**, **Codex CLI** e qualquer agente que suporte SKILL.md.

## O que faz

Ensina o agente a montar **equipes de IAs via CLI** (Gemini, Codex, Qwen, Claude) para tarefas complexas com papéis dinâmicos — análise, execução, revisão, validação cruzada.

## Instalação

```bash
# Claude Code (global)
cp -r orchestrate/ ~/.claude/skills/

# Antigravity (global)
cp -r orchestrate/ ~/.agent/skills/
```

## Como usar

```
/orchestrate analise arquitetural do arquivo X.py com Gemini e Codex
```

## Estrutura

```
orchestrate/
├── SKILL.md                # Política de decisão, fluxo, privacidade (LGPD)
├── ai-catalog.md           # Catálogo: modelos, custos, comandos, quirks
├── team-patterns.md        # 8 padrões de equipe prontos
├── calling-conventions.md  # Comandos CLI exatos, timeouts, validação JSON
└── examples.md             # 6 exemplos práticos + anti-patterns
```

## Avaliações (skill-judge, 120 pts)

| Avaliador | Nota | Letra |
|-----------|------|-------|
| Codex gpt-5.3-codex | 118/120 | A (98%) |
| Claude Opus 4.6 | 115/120 | A (94%) |

## IAs suportadas

| IA | Modelos | Custo |
|----|---------|-------|
| Gemini | gemini-3-pro-preview, gemini-3-flash-preview | Gratuito* |
| Qwen | qwen3-coder (480B) | Gratuito |
| Codex | gpt-5.3-codex | Pago |
| Claude | opus-4-6, sonnet-4-5 | Pago |

## Autor

**Diego Câmara** — [@diegocamara89](https://github.com/diegocamara89)

Criado com Claude Code + Gemini CLI + Codex CLI (fev/2026).

## Licença

MIT
