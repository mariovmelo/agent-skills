# UAI — Tutorial de Instalacao e Uso

> Guia completo para instalar o UAI a partir do repositorio Git e utilizar todos os comandos disponiveis.

---

## Sumario

1. [Pre-requisitos](#1-pre-requisitos)
2. [Instalacao a partir do Git](#2-instalacao-a-partir-do-git)
3. [Configuracao inicial](#3-configuracao-inicial)
4. [Conectando provedores de IA](#4-conectando-provedores-de-ia)
5. [Comandos principais](#5-comandos-principais)
   - [uai ask](#51-uai-ask--pergunta-unica)
   - [uai chat](#52-uai-chat--chat-interativo)
   - [uai code](#53-uai-code--tarefas-de-codigo)
   - [uai orchestrate](#54-uai-orchestrate--orquestracao-multi-ia)
6. [Gerenciamento de sessoes](#6-gerenciamento-de-sessoes)
7. [Configuracao avancada](#7-configuracao-avancada)
8. [Monitoramento de uso e custo](#8-monitoramento-de-uso-e-custo)
9. [Provedores disponiveis](#9-provedores-disponiveis)
10. [Referencia rapida](#10-referencia-rapida)

---

## 1. Pre-requisitos

- **Python 3.11** ou superior
- **python3-venv** (para criar ambientes virtuais)
- **Git**

No Ubuntu/Debian, instale os pre-requisitos com:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git
```

Verifique suas versoes:

```bash
python3 --version   # deve ser >= 3.11
git --version
```

---

## 2. Instalacao a partir do Git

> **Nota para Ubuntu/Debian:** O Python do sistema e "externally managed" (PEP 668),
> o que impede o uso direto de `pip install`. Sempre use um ambiente virtual.

### 2.1 Clonar o repositorio

Clone diretamente o branch com o codigo da ferramenta:

```bash
git clone -b claude/unified-cli-integrator-KxQ8s \
    https://github.com/your-org/agent-skills.git
cd agent-skills
```

> **Se ja clonou o repositorio** e esta no branch `master`, troque para o branch correto:
>
> ```bash
> git fetch origin
> git checkout claude/unified-cli-integrator-KxQ8s
> ```

### 2.2 Criar e ativar o ambiente virtual

```bash
python3 -m venv .venv
source .venv/bin/activate
```

O prompt do terminal muda para `(.venv)` indicando que o ambiente esta ativo.

Para desativar o ambiente virtual quando nao estiver usando:

```bash
deactivate
```

### 2.3 Instalar em modo editavel

Com o ambiente virtual ativo, instale o projeto. O modo editavel (`-e`) faz com que
alteracoes no codigo fonte sejam refletidas imediatamente, sem precisar reinstalar:

```bash
pip install -e .
```

### 2.4 (Opcional) Instalar com dependencias de desenvolvimento

Se voce pretende rodar testes ou contribuir com o projeto:

```bash
pip install -e ".[dev]"
```

### 2.5 (Opcional) Instalar com suporte a privacidade (LGPD/GDPR)

Para anonimizacao automatica de dados pessoais (PII) via Presidio:

```bash
pip install -e ".[privacy]"
```

### 2.6 Ativar o ambiente em novas sessoes do terminal

O ambiente virtual precisa ser reativado toda vez que voce abrir um novo terminal:

```bash
cd agent-skills
source .venv/bin/activate
uai --help
```

**Dica:** Adicione ao seu `~/.bashrc` ou `~/.zshrc` para ativar automaticamente
ao entrar no diretorio:

```bash
# Adicione ao ~/.bashrc
if [ -f "$HOME/agent-skills/.venv/bin/activate" ]; then
    alias uai-env="source $HOME/agent-skills/.venv/bin/activate"
fi
```

### 2.7 Verificar a instalacao

Com o ambiente virtual ativo:

```bash
uai --help
```

Saida esperada:

```
Usage: uai [OPTIONS] COMMAND [ARGS]...

  UAI - Unified AI CLI

Commands:
  ask          Send a single prompt to an AI provider
  chat         Interactive chat session with persistent context
  code         Code-focused task routing
  config       View and edit configuration
  connect      Connect an AI provider account
  orchestrate  Multi-AI team orchestration
  providers    List and inspect AI providers
  quota        Usage and cost report
  sessions     Manage conversation sessions
  setup        First-time setup wizard
  status       Provider health dashboard
```

---

## 3. Configuracao inicial

Execute o assistente de configuracao na primeira vez:

```bash
uai setup
```

Este comando:
- Cria o diretorio `~/.uai/` com o arquivo `config.yaml`
- Detecta quais CLIs de provedores estao instalados no sistema (gemini, claude, codex, qwen)
- Inicializa o armazenamento de sessoes

Para instalar automaticamente CLIs de provedores que estejam faltando:

```bash
uai setup --install
```

---

## 4. Conectando provedores de IA

Antes de usar um provedor, voce precisa conectar sua conta. O UAI suporta 7 provedores:

### Provedores gratuitos (recomendados para comecar)

```bash
# Gemini (Google) — gratuito, sem limites via CLI
uai connect gemini
# Vai solicitar a API key. Obtenha em: https://aistudio.google.com/app/apikey

# Groq — gratuito, ultra-rapido
uai connect groq
# Obtenha a key em: https://console.groq.com/keys

# Ollama — gratuito, local, totalmente offline
uai connect ollama
# Nao precisa de API key. Instale o Ollama: https://ollama.ai
```

### Provedores pagos

```bash
# Claude (Anthropic)
uai connect claude
# Obtenha a key em: https://console.anthropic.com/

# Codex (OpenAI)
uai connect codex
# Obtenha a key em: https://platform.openai.com/api-keys

# DeepSeek — custo muito baixo
uai connect deepseek
# Obtenha a key em: https://platform.deepseek.com/
```

### Passar a API key diretamente (sem prompt interativo)

```bash
uai connect gemini --key "sua-api-key-aqui"
```

### Desabilitar teste de conexao

```bash
uai connect claude --key "sk-..." --no-test
```

### Verificar quais provedores estao configurados

```bash
uai status
```

Mostra uma tabela com o status de cada provedor:

```
Provider   Status        Backend   Model          Cost
─────────────────────────────────────────────────────────
gemini     available     API       flash          Free
groq       available     API       llama          Free
claude     available     API       sonnet         $3/$15 per M
ollama     not_configured  -       qwen2.5-coder  Free
```

---

## 5. Comandos principais

### 5.1 `uai ask` — Pergunta unica

O comando mais simples. Envia um prompt e recebe a resposta:

```bash
uai ask "explique o que e um decorator em Python"
```

**Opcoes:**

| Flag | Descricao |
|------|-----------|
| `--provider, -p` | Forcar um provedor especifico |
| `--model, -m` | Escolher o modelo (ex: `opus`, `flash`, `pro`) |
| `--session, -s` | Usar uma sessao nomeada (padrao: `default`) |
| `--free` | Usar apenas provedores gratuitos |
| `--no-context` | Ignorar historico da sessao |
| `--raw` | Saida em texto puro, sem formatacao Markdown |
| `--verbose, -v` | Mostrar detalhes de roteamento (provedor, custo, latencia) |

**Exemplos:**

```bash
# Pergunta simples (o UAI escolhe o melhor provedor automaticamente)
uai ask "como funciona o garbage collector do Python?"

# Forcar o uso do Claude
uai ask -p claude "analise este codigo para vulnerabilidades"

# Apenas provedores gratuitos
uai ask --free "explique SOLID com exemplos"

# Com contexto de arquivo (injeta o conteudo do arquivo no prompt)
uai ask "revise este codigo: @src/main.py"

# Com saida de comando shell
uai ask "o que mostram os ultimos commits? !git log --oneline -10"

# Modo verbose (mostra qual provedor foi escolhido e por que)
uai ask -v "escreva um hello world em Rust"
```

**Contexto persistente:**

O `uai ask` mantem historico entre chamadas na mesma sessao:

```bash
uai ask "o que e uma linked list?"
# resposta sobre linked list...

uai ask "agora implemente uma em Python"
# o provedor recebe todo o historico anterior, entao sabe
# que voce quer implementar uma linked list
```

### 5.2 `uai chat` — Chat interativo

Abre um REPL interativo com streaming de respostas e comandos especiais:

```bash
uai chat
```

**Opcoes:**

| Flag | Descricao |
|------|-----------|
| `--session, -s` | Sessao nomeada |
| `--provider, -p` | Forcar provedor para toda a sessao |
| `--free` | Apenas provedores gratuitos |
| `--new` | Iniciar sessao limpa (limpa historico) |
| `--resume, -r` | Retomar a sessao mais recente |

**Exemplo de uso:**

```bash
uai chat --session meu-projeto
```

Dentro do chat, digite normalmente para conversar. Para comandos especiais, use `/`:

#### Comandos de barra (slash commands)

| Comando | Aliases | O que faz |
|---------|---------|-----------|
| `/help` | `/h`, `/?` | Mostra a lista de comandos |
| `/exit` | `/quit`, `/q` | Sai do chat |
| `/clear` | — | Limpa o historico da sessao atual |
| `/history` | — | Mostra quantas mensagens tem na sessao |
| `/provider <nome>` | — | Troca o provedor (ex: `/provider claude`) |
| `/provider` | — | Volta para roteamento automatico |
| `/export [arquivo.md]` | — | Exporta a conversa para Markdown |
| `/status` | — | Mostra status dos provedores em tempo real |
| `/session` | — | Mostra a sessao atual e lista as disponiveis |

**Exemplo de sessao de chat:**

```
uai> Explique o padrao Repository em Python
[Gemini] O padrao Repository e uma camada de abstracao...

uai> /provider claude
Switched to: claude

uai> Agora implemente um exemplo completo
[Claude] Claro, aqui esta uma implementacao completa...

uai> /export conversa-repository.md
Exported to conversa-repository.md

uai> /exit
Goodbye!
```

### 5.3 `uai code` — Tarefas de codigo

Comando otimizado para tarefas de programacao. Classifica automaticamente o tipo de tarefa e roteia para o provedor mais adequado:

```bash
uai code "implemente um binary search tree em Python"
```

**Opcoes:**

| Flag | Descricao |
|------|-----------|
| `--provider, -p` | Forcar provedor |
| `--session, -s` | Sessao nomeada |
| `--free` | Apenas provedores gratuitos |
| `--verbose, -v` | Mostrar classificacao da tarefa e latencia |

**Classificacao automatica de tarefas:**

| Tipo | Palavras-chave detectadas | Provedores preferidos |
|------|---------------------------|----------------------|
| Debugging | bug, error, fix, debug, exception | Codex, Claude |
| Code Review | review, audit, check, improve | Qwen, Gemini |
| Architecture | architect, design, refactor, structure | Gemini, Claude |
| Code Generation | implement, write, create, build | Codex, Qwen |

**Exemplos:**

```bash
# Debugging (roteado para Codex/Claude)
uai code "fix this error: TypeError: cannot unpack non-iterable NoneType"

# Code review (roteado para Qwen/Gemini)
uai code "review @src/auth.py for security issues"

# Arquitetura (roteado para Gemini/Claude)
uai code "design a microservice architecture for an e-commerce platform"

# Geracao de codigo (roteado para Codex/Qwen)
uai code "implement a REST API with FastAPI for user management"
```

### 5.4 `uai orchestrate` — Orquestracao multi-IA

Executa uma tarefa usando multiplos provedores de IA em equipe:

```bash
uai orchestrate "faca uma auditoria completa de seguranca em src/"
```

**Opcoes:**

| Flag | Descricao |
|------|-----------|
| `--pattern, -p` | Escolher o padrao de equipe (ver tabela abaixo) |
| `--autonomous, -a` | Pular confirmacoes de custo |
| `--list, -l` | Listar padroes disponiveis |

**Padroes de equipe disponiveis:**

```bash
uai orchestrate --list
```

| Padrao | Execucao | Descricao |
|--------|----------|-----------|
| `full_analysis` | Paralelo + consolidacao | Gemini + Codex + Qwen analisam, Claude consolida |
| `daily_dev` | Sequencial | Qwen revisa, Gemini valida (gratuito) |
| `critical_debug` | Sequencial profundo | Codex > Qwen > Gemini > Claude |
| `lgpd_audit` | Paralelo + consolidacao | Auditoria de privacidade com 2+ provedores |
| `brainstorm` | Paralelo + sintese | Todos analisam, Claude sintetiza |
| `batch_processing` | Paralelo | Workers simultaneos para tarefas em lote |
| `cross_validation` | Pipeline | Produtor > Validador > Arbitro |
| `specialist_generalist` | Paralelo | Especialista + segunda opiniao |

**Exemplos:**

```bash
# Analise completa (3 provedores em paralelo + consolidacao)
uai orchestrate "analise a arquitetura de src/ e sugira melhorias"

# Padrao especifico
uai orchestrate -p critical_debug "investigate crash on startup with segfault"

# Brainstorm com multiplas perspectivas
uai orchestrate -p brainstorm "como otimizar o tempo de resposta da API?"

# Modo autonomo (sem pedir confirmacao de custo)
uai orchestrate -a "full security audit of the authentication module"
```

---

## 6. Gerenciamento de sessoes

O UAI armazena o historico de conversas em sessoes SQLite em `~/.uai/sessions/`.

### Listar sessoes

```bash
uai sessions list
```

Saida:

```
Name          Messages   Tokens   Last Active          Size
──────────────────────────────────────────────────────────────
default       24         12,450   2026-02-25 14:30     48 KB
meu-projeto   8          4,200    2026-02-24 10:15     16 KB
debug-api     3          1,800    2026-02-23 09:00     8 KB
```

### Ver historico de uma sessao

```bash
uai sessions show default           # ultimas 20 mensagens
uai sessions show default --limit 5 # ultimas 5 mensagens
```

### Exportar sessao

```bash
# Exportar como Markdown
uai sessions export meu-projeto --format markdown --output conversa.md

# Exportar como JSON
uai sessions export meu-projeto --format json --output conversa.json
```

### Deletar sessao

```bash
uai sessions delete debug-api

# Sem confirmacao
uai sessions delete debug-api --yes
```

---

## 7. Configuracao avancada

### Ver configuracao atual

```bash
uai config show
```

Mostra o YAML completo com syntax highlighting.

### Alterar valores via linha de comando

Use notacao de ponto para acessar chaves aninhadas:

```bash
# Modo de custo: free_only | balanced | performance
uai config set defaults.cost_mode balanced

# Tema: default | dark | minimal
uai config set ux.theme dark

# Habilitar/desabilitar streaming
uai config set ux.streaming true

# Timeout em segundos
uai config set defaults.timeout 180

# Desabilitar um provedor
uai config set providers.codex.enabled false

# Alterar modelo padrao de um provedor
uai config set providers.claude.default_model opus

# Prioridade do provedor (1-5, maior = mais preferido)
uai config set providers.gemini.priority 5

# Limite diario de requisicoes
uai config set providers.qwen.daily_limit 500
```

### Variaveis de ambiente

Voce pode sobrescrever configuracoes via variaveis de ambiente:

```bash
export UAI_DEFAULT_PROVIDER=claude    # Provedor padrao
export UAI_COST_MODE=performance      # Modo de custo
export UAI_THEME=dark                 # Tema
export UAI_STREAMING=false            # Desabilitar streaming
export UAI_TIMEOUT=300                # Timeout

# API keys dos provedores
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."
export OPENAI_API_KEY="sk-..."
export GROQ_API_KEY="gsk_..."
export DEEPSEEK_API_KEY="..."
```

### Configuracao por projeto

Crie um arquivo `.uai/config.yaml` na raiz do seu projeto para ter configuracoes especificas:

```bash
mkdir -p .uai
cat > .uai/config.yaml << 'EOF'
defaults:
  cost_mode: free_only
  session: meu-projeto

providers:
  gemini:
    priority: 5
  claude:
    enabled: false
EOF
```

O UAI faz merge automatico: **usuario** < **projeto** < **variaveis de ambiente**.

### Instrucoes de projeto (UAI.md)

Crie um arquivo `UAI.md` na raiz do seu projeto com instrucoes que serao injetadas automaticamente em toda requisicao:

```markdown
# Contexto do Projeto

Este e um projeto Python usando FastAPI.
Sempre responda em portugues.
Siga PEP 8 e use type hints.
```

---

## 8. Monitoramento de uso e custo

### Ver uso e custo

```bash
uai quota
```

Saida:

```
Provider   Today   Month   Cost(Month)   Daily Limit   Success 24h   Status
──────────────────────────────────────────────────────────────────────────────
gemini     45      312     $0.00         unlimited     100%          OK
claude     3       18      $0.42         unlimited     100%          OK
groq       12      89      $0.00         unlimited     95%           OK
codex      0       5       $0.15         unlimited     100%          OK

Total monthly cost: $0.57
```

### Ver status dos provedores em tempo real

```bash
uai status

# Com detalhes
uai status --verbose
```

### Listar provedores e suas capacidades

```bash
# Tabela resumida
uai providers list

# Detalhes de um provedor especifico
uai providers detail claude
```

---

## 9. Provedores disponiveis

| Provedor | Gratuito | Modelos | Contexto | Melhor para |
|----------|----------|---------|----------|-------------|
| **Gemini** | Sim | flash, pro, flash-lite | 1M tokens | Arquitetura, contexto longo |
| **Qwen** | Sim | coder, coder-plus | 128K tokens | Code review, batch |
| **Ollama** | Sim (local) | qwen2.5-coder, qualquer modelo local | 128K tokens | Privacidade, offline |
| **Groq** | Sim | llama, gemma, deepseek | 128K tokens | Ultra-baixa latencia |
| **DeepSeek** | Custo baixo | chat, coder | 64K tokens | Tarefas gerais economicas |
| **Claude** | Pago | opus, sonnet, haiku | 200K tokens | Consolidacao, estrategia |
| **Codex** | Pago | gpt-5.3-codex | 128K tokens | Debugging, implementacao |

### Precos (provedores pagos)

| Provedor | Modelo | Input (por 1M tokens) | Output (por 1M tokens) |
|----------|--------|-----------------------|------------------------|
| Claude | opus | $15.00 | $75.00 |
| Claude | sonnet | $3.00 | $15.00 |
| Claude | haiku | $0.80 | $4.00 |
| Codex | gpt-5.3-codex | $2.00 | $8.00 |
| DeepSeek | chat/coder | $0.14 | $0.28 |

---

## 10. Referencia rapida

```bash
# ── Setup ──────────────────────────────────────────
uai setup                                # Wizard inicial
uai setup --install                      # Instalar CLIs faltando
uai connect <provedor>                   # Conectar provedor
uai connect <provedor> --key "..."       # Conectar com key direto

# ── Consultas ──────────────────────────────────────
uai ask "prompt"                         # Pergunta unica
uai ask -p claude "prompt"               # Forcar provedor
uai ask --free "prompt"                  # Apenas gratuitos
uai ask -s projeto "prompt"              # Sessao nomeada
uai ask "analise @arquivo.py"            # Injetar arquivo
uai ask "veja !git diff"                 # Injetar saida de comando

# ── Chat interativo ───────────────────────────────
uai chat                                 # Abrir REPL
uai chat -s projeto                      # Sessao nomeada
uai chat --resume                        # Retomar ultima sessao

# ── Codigo ─────────────────────────────────────────
uai code "implemente X"                  # Tarefa de codigo
uai code -v "fix bug em Y"              # Com detalhes de roteamento

# ── Orquestracao ───────────────────────────────────
uai orchestrate "tarefa"                 # Equipe multi-IA
uai orchestrate -p brainstorm "tarefa"   # Padrao especifico
uai orchestrate --list                   # Listar padroes

# ── Sessoes ────────────────────────────────────────
uai sessions list                        # Listar sessoes
uai sessions show <nome>                 # Ver historico
uai sessions delete <nome>               # Deletar sessao
uai sessions export <nome> -f markdown   # Exportar

# ── Config e status ───────────────────────────────
uai config show                          # Ver config
uai config set <chave> <valor>           # Alterar config
uai status                               # Dashboard de provedores
uai quota                                # Uso e custos
uai providers list                       # Lista de provedores
uai providers detail <nome>              # Detalhes do provedor

# ── Slash commands (dentro do chat) ───────────────
/help                                    # Ajuda
/provider <nome>                         # Trocar provedor
/provider                                # Voltar para auto
/history                                 # Contar mensagens
/clear                                   # Limpar historico
/export [arquivo.md]                     # Exportar sessao
/status                                  # Status dos provedores
/session                                 # Info da sessao
/exit                                    # Sair
```

---

## Proximos passos

1. Execute `uai setup` para configurar o ambiente
2. Conecte pelo menos um provedor gratuito: `uai connect gemini` ou `uai connect groq`
3. Faca sua primeira pergunta: `uai ask "hello world"`
4. Explore o chat interativo: `uai chat`
5. Experimente a orquestracao multi-IA: `uai orchestrate "analise este projeto"`
