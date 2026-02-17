# Catalogo de IAs Disponiveis

> **Ultima atualizacao**: 2026-02-17
> **Como atualizar**: Edite este arquivo quando novos modelos forem lancados.
> Para verificar modelos atuais: `gemini --help`, `codex --help`, `qwen --help`, `claude --version`

---

## 1. CLAUDE CODE

| Campo | Valor |
|-------|-------|
| **Comando** | `claude -p "prompt"` |
| **Modelo Top** | `claude-opus-4-6` |
| **Modelo Rapido** | `claude-haiku-4-5-20251001` |
| **Modelo Default** | `claude-sonnet-4-5-20250929` |
| **Custo** | Pago ($5/$25 por milhao de tokens para Opus) |
| **Contexto** | 1M tokens (beta) |
| **Timeout** | Configuravel ate 60min |
| **Saida max** | 128K tokens |

### Forcas
- Orquestracao e visao executiva (10/10)
- Planejamento estrategico e roadmaps
- Subagents nativos (Explore, Plan, general-purpose)
- Agent Teams (paralelismo real, experimental)

### Fraquezas
- Custo elevado
- Nao deve ser usado para tarefas triviais

### Quando usar como membro da equipe
- Lider/Orquestrador (papel natural)
- Consolidador de resultados de outras IAs
- Analista de riscos sistemicos
- Documentador final

---

## 2. GEMINI

| Campo | Valor |
|-------|-------|
| **Comando** | `gemini -m MODELO -p "prompt"` |
| **Modelo Top** | `gemini-3-pro-preview` |
| **Modelo Rapido** | `gemini-3-flash-preview` |
| **Modelo Economico** | `gemini-2.5-flash` |
| **Custo** | GRATUITO (tier generoso) |
| **Contexto** | 1M tokens |
| **Timeout** | Configuravel via Bash (ate 10min) |
| **Output format** | Suporta `--output-format json` |

### Forcas
- Arquitetura e design patterns (9.5/10)
- Anti-patterns, SOLID, code smells
- Analise rapida (~2min)
- GRATUITO

### Fraquezas
- Pode ser verboso demais
- Menos preciso em debugging linha-a-linha

### Quando usar como membro da equipe
- Arquiteto (analise estrutural)
- Revisor de qualidade
- Validador de decisoes tecnicas
- Analista de performance

### Modelos disponiveis (verificar com `gemini /model`)
- `gemini-3-pro-preview` - Analises serias, arquitetura, decisoes
- `gemini-3-flash-preview` - Rapido, bom custo-beneficio
- `gemini-2.5-flash` - Apenas consultas triviais
- `gemini-2.5-pro` - Estavel, GA

---

## 3. CODEX CLI

| Campo | Valor |
|-------|-------|
| **Comando** | `codex exec --skip-git-repo-check "prompt"` |
| **Modelo Top** | `gpt-5.3-codex` |
| **Modelo Rapido** | `gpt-5.3-codex-spark` |
| **Custo** | Pago (requer plano ChatGPT) |
| **Timeout** | 30min configuravel |

### IMPORTANTE: Variaveis de ambiente
Quando chamado pelo Claude, DEVE limpar variaveis OpenRouter:
```bash
# Bash
unset OPENAI_BASE_URL && unset OPENAI_API_KEY && codex exec --skip-git-repo-check "prompt"
```

### Forcas
- Debugging linha-a-linha (9.5/10)
- Precisao cirurgica em bugs
- Implementacao de codigo

### Fraquezas
- Problemas com arquivos muito grandes
- Custo por token

### Quando usar como membro da equipe
- Debugger (encontrar bugs exatos)
- Implementador (escrever codigo)
- Executor de tarefas especificas

---

## 4. QWEN CLI

| Campo | Valor |
|-------|-------|
| **Comando** | `qwen -p "prompt"` |
| **Modo autonomo** | `qwen -p "prompt" --yolo` |
| **Modelo** | `qwen3-coder` (via OpenRouter: `qwen/qwen3-coder:free`) |
| **Modelo Local** | `qwen3-coder-next` (80B/3B ativo, via Ollama) |
| **Custo** | GRATUITO (2.000 req/dia) |
| **Contexto** | 256K tokens |

### Forcas
- Code review educativo (8.5/10)
- Multiplas implementacoes alternativas
- GRATUITO
- Pode orquestrar Codex CLI

### Fraquezas
- Ferramentas internas limitadas
- Menos preciso que Gemini Pro em arquitetura

### Quando usar como membro da equipe
- Professor/Explicador (analise educativa)
- Revisor inicial (primeiro olhar gratuito)
- Normalizador de dados (tarefas repetitivas)
- Worker para tarefas em lote (gratuito)

---

## 5. OUTRAS IAs CLI (FUTURAS)

Adicione aqui novas IAs conforme forem instaladas:

| IA | Comando | Modelo | Status |
|----|---------|--------|--------|
| *Exemplo* | `nova-ia -p "prompt"` | `modelo-x` | Nao instalada |

---

## MATRIZ DE DECISAO RAPIDA

| Necessidade | 1a Opcao | 2a Opcao | Justificativa |
|-------------|----------|----------|---------------|
| Analise gratuita | Qwen | Gemini Flash | Zero custo |
| Arquitetura | Gemini Pro | Claude | Profundidade |
| Bugs especificos | Codex | Claude | Precisao |
| Visao executiva | Claude | Gemini Pro | Estrategia |
| Lote grande | Qwen | Gemini Flash | Custo zero |
| Dados sensiveis | Qwen Local (Ollama) | Claude | Privacidade |
| Code review | Qwen | Gemini Pro | Educativo |
| Performance | Gemini Pro | Claude | Gargalos |
