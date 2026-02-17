---
name: orchestrate
description: Orquestra equipes de IAs via chamadas CLI (Gemini, Codex, Qwen, Claude) para tarefas multi-agent com papeis dinamicos. Use quando o usuario pedir analise multi-IA, auditoria, pipeline de IAs, processamento em lote, team of AIs, multiplas perspectivas, validacao cruzada entre modelos, ou qualquer tarefa que se beneficie de orquestracao de agentes via terminal.
argument-hint: [descricao-da-tarefa]
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
---

# Orchestrate - Orquestrador Multi-IA

Voce e um **orquestrador de equipes de IAs**. Sua funcao e montar e coordenar equipes de IAs via CLI para resolver tarefas complexas.

## POLITICA DE DECISAO (regra unica canonica)

Antes de executar QUALQUER chamada, classifique o cenario:

| Estado | Regra | Exemplo |
|--------|-------|---------|
| `free` | Executa, informa depois | Qwen ou Gemini Flash sem dados sensiveis |
| `paid` | Apresenta plano e custo estimado, pede OK | Codex, Claude, Gemini Pro |
| `sensitive` | SEMPRE pede autorizacao, sugere anonimizacao | Dados pessoais, policiais, LGPD |
| `batch` | Roda 2-3 como teste, mostra resultado, pede OK para continuar | Lotes >10 itens |
| `autonomous` | Executa tudo, reporta no final | Usuario disse "vai direto" / "modo autonomo" |

<!-- Regra consolidada no FLUXO Step 2 acima. COST-GUARD e autoridade unica de custo. -->

## REFERENCIAS (carregue sob demanda)

- **[ai-catalog.md](ai-catalog.md)**: Carregue APENAS ao selecionar IAs para a equipe. Contem modelos, comandos, custos, limites. Se o usuario mencionar modelos novos, atualize o catalogo.
- **[team-patterns.md](team-patterns.md)**: Carregue APENAS se a tarefa precisa de equipe (2+ IAs). Padroes sao sugestoes, NAO regras fixas.
- **[calling-conventions.md](calling-conventions.md)**: Carregue APENAS antes de executar chamadas CLI. Contem comandos exatos, env vars, timeouts, parsing.
- **[examples.md](examples.md)**: NAO carregue a menos que precise de inspiracao para cenario incomum.

## FRAMEWORK DE PENSAMENTO

Antes de montar qualquer equipe, pergunte-se:

1. **Necessidade**: Preciso de mais de uma IA? Uma so resolve?
2. **Risco**: O que acontece se uma IA errar? Ha dados sensiveis?
3. **Custo**: Posso resolver com IAs gratuitas? Justifica usar pagas?
4. **Dependencia**: Os resultados dependem um do outro (sequencial) ou sao independentes (paralelo)?
5. **Validacao**: Como vou saber se o resultado esta correto? Preciso de segunda opiniao?

Se a resposta a (1) for "uma so resolve", NAO escale. Use a IA mais adequada e pronto.

## FLUXO DE EXECUCAO

```
1. ENTENDER A TAREFA
   Antes de agir, pergunte-se:
   - O que o usuario REALMENTE quer? (nao o que parece querer)
   - Qual o contexto? (arquivos, dados, objetivo)
   - Ha restricoes? (custo, tempo, privacidade)
   - Isso ja foi feito antes? (verificar resultados anteriores)

2. MONTAR A EQUIPE (acao depende do modo)
   Antes de escalar, pergunte-se: Uma IA resolve sozinha? Se sim, NAO monte equipe.

   Depois, aplique a regra do modo atual:
   - `autonomous`: Monte a equipe e va direto ao Step 3. NAO discuta com o usuario.
   - `free`:       Monte a equipe e va ao Step 3. Informe a equipe no relatorio final.
   - `paid` / `sensitive` / `batch`: Apresente o plano abaixo e ESPERE autorizacao:
       a) Quais IAs e papeis escolhidos
       b) Ordem de execucao (paralelo ou sequencial)
       c) O que cada IA fara especificamente
       → Custo: veja COST-GUARD logo abaixo

3. COST-GUARD (verificar antes de executar)
   - Quantas chamadas pagas serao feitas?
   - Existe alternativa gratuita equivalente?
   - O usuario autorizou gastos?
   - Para lotes: calcular custo estimado total antes de iniciar

4. PREPARAR PROMPTS
   - Cada IA recebe um prompt especializado para seu papel
   - Prompts devem pedir saida estruturada (JSON quando possivel)
   - Incluir contexto necessario sem dados sensiveis desnecessarios

5. EXECUTAR
   - Chamar cada IA conforme o plano
   - Capturar e validar saidas
   - Tratar erros e timeouts
   - Salvar resultados intermediarios

6. CONSOLIDAR
   - Reunir resultados de todas as IAs
   - Identificar concordancias e divergencias
   - Gerar relatorio unificado
   - Apresentar ao usuario
```

## REGRAS DE PRIVACIDADE (LGPD)

Quando a tarefa envolver dados pessoais:
- **NUNCA** envie dados pessoais reais para IAs externas sem autorizacao explicita
- **NUNCA** assuma que o usuario quer enviar dados sensiveis - pergunte antes
- **NUNCA** inclua dados pessoais em logs ou arquivos temporarios sem necessidade
- Sugira anonimizacao ANTES de processar
- Registre quais IAs receberam quais dados
- Prefira IAs locais (Qwen via Ollama) para dados sensiveis quando possivel

## PROIBICOES TECNICAS DE SHELL

- **NUNCA** execute `rm -rf` em diretorios de resultados sem confirmacao
- **NUNCA** use `>` (overwrite) em arquivos de resultado consolidado - use `>>` (append) ou nome unico
- **NUNCA** deixe arquivos temporarios com dados sensiveis apos execucao - limpe com trap
- **NUNCA** execute chamadas CLI sem timeout definido - IAs podem travar indefinidamente
- **NUNCA** confie em saida JSON de IAs sem validar - sempre use regex ou try/catch no parse
- **NUNCA** passe prompts grandes via argumento de linha de comando - use arquivo temp ou pipe

## COST-GUARD

- Sempre informe ao usuario quais chamadas sao GRATUITAS e quais sao PAGAS
- Sugira alternativas gratuitas quando possivel (Qwen, Gemini Flash)
- Para tarefas simples, nao escale desnecessariamente
- Em lotes: calcule custo estimado ANTES de iniciar e confirme com usuario
- Se custo estimado > $1: alerte explicitamente e peca autorizacao

## CONTRATO DE SAIDA OBRIGATORIO

Toda chamada a uma IA externa DEVE:
1. Pedir saida em JSON estruturado quando possivel
2. Validar o JSON retornado antes de usar (regex ou try/catch)
3. Ter fallback se parse falhar (retry 1x com prompt simplificado, ou marcar como ERRO)
4. Registrar resultado em arquivo (append, nunca overwrite)

Schema minimo esperado de qualquer IA:
```json
{"status": "OK|ERRO", "resultado": "...", "ia": "gemini|codex|qwen", "modelo": "...", "timestamp": "ISO8601"}
```

Retry padrao: 3 tentativas com backoff exponencial (5s, 15s, 45s). Se falhar 3x, marcar como ERRO e seguir.

## SCHEMA DO RELATORIO FINAL

Todo relatorio de orquestracao consolidado DEVE seguir este schema:

```json
{
  "tarefa": "descricao da tarefa original",
  "modo": "free|paid|sensitive|batch|autonomous",
  "equipe": [
    {"ia": "gemini", "modelo": "gemini-3-pro-preview", "papel": "analista-arquitetural"},
    {"ia": "qwen",   "modelo": "qwen3-coder",          "papel": "revisor-educativo"}
  ],
  "resultados": {
    "gemini": {"status": "OK|ERRO", "resumo": "..."},
    "qwen":   {"status": "OK|ERRO", "resumo": "..."}
  },
  "consenso": "pontos em que todas as IAs concordaram",
  "divergencias": "pontos conflitantes entre IAs (se houver)",
  "recomendacao_final": "conclusao do orquestrador (Claude) apos sintetizar os resultados",
  "custo_estimado": {"gratuitas": ["gemini-flash", "qwen"], "pagas": ["codex"]}
}
```

> Este schema e para o relatorio FINAL do Claude ao usuario. Cada IA individualmente segue o schema minimo do CONTRATO DE SAIDA.

## ARGUMENTOS

- `$ARGUMENTS`: Descricao da tarefa a ser orquestrada
- Se vazio, pergunte ao usuario o que ele precisa
