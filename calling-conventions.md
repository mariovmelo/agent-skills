# Convencoes de Chamada - Como Chamar Cada IA via CLI

> Este documento define os comandos EXATOS para chamar cada IA.
> Testado e validado no ambiente do usuario (Windows + Git Bash/MSYS2).

---

## AMBIENTE DO USUARIO

- **OS**: Windows 10/11 com MSYS2/Git Bash
- **Shell padrao no Claude Code**: Bash (via MSYS2)
- **PowerShell**: Disponivel via `powershell -Command "..."`
- **Encoding**: UTF-8

---

## 1. GEMINI CLI

### Chamada direta (recomendada)
```bash
# Prompt simples
gemini -m gemini-3-pro-preview -p "seu prompt aqui"

# Prompt de arquivo
gemini -m gemini-3-flash-preview -p "@caminho/do/arquivo.txt"

# Com output JSON
gemini -m gemini-3-pro-preview --output-format json -p "prompt"

# Modelo rapido para tarefas leves
gemini -m gemini-2.5-flash -p "prompt"
```

### Via subprocess Python
```python
import subprocess
result = subprocess.run(
    ['gemini', '-m', 'gemini-3-flash-preview', '-p', prompt],
    capture_output=True, text=True, timeout=300, encoding='utf-8'
)
output = result.stdout
```

### Via Bash tool do Claude
```bash
gemini -m gemini-3-pro-preview -p "prompt aqui"
```

### Timeout recomendado
- Flash: 120s (2min)
- Pro: 300s (5min)
- Analises longas: 600s (10min) via Bash tool com timeout

### Parsing de saida
- Saida em texto puro por padrao
- Com `--output-format json`: JSON direto
- Para extrair JSON de texto misto: regex `\{[\s\S]*\}`

---

## 2. CODEX CLI

### CRITICO: Limpar variaveis OpenRouter antes de chamar
```bash
# OBRIGATORIO quando chamado pelo Claude (que usa OpenRouter)
unset OPENAI_BASE_URL && unset OPENAI_API_KEY && codex exec --skip-git-repo-check "prompt"
```

### Chamada direta
```bash
# Padrao
codex exec --skip-git-repo-check "prompt"

# Com sandbox de escrita
codex exec --skip-git-repo-check --sandbox workspace-write "prompt"
```

### Timeout recomendado
- Padrao: 120s
- Tarefas complexas: 300s
- Maximo: 1800s (30min)

### Parsing de saida
- Saida em texto puro
- Codex tende a ser direto e conciso
- Para JSON: pedir explicitamente no prompt

---

## 3. QWEN CLI

### Chamada direta
```bash
# Prompt simples
qwen -p "prompt"

# Modo autonomo (executa codigo)
qwen -p "prompt" --yolo

# Via pipe (para prompts grandes)
echo "prompt grande" | qwen
```

### Via arquivo temporario (Windows - para prompts grandes)
```bash
# Escrever prompt em arquivo temp, depois pipe
echo "prompt" > /tmp/qwen_prompt.txt && cat /tmp/qwen_prompt.txt | qwen && rm /tmp/qwen_prompt.txt
```

### Timeout recomendado
- Padrao: 60s
- Tarefas maiores: 120s

### Parsing de saida
- Saida em texto puro com formatacao Markdown
- Qwen e mais verboso - pode precisar de limpeza
- Para JSON: pedir "Responda APENAS JSON, sem texto adicional"

### Limites
- 2.000 requisicoes/dia (gratuito via OpenRouter)
- Sem limite via Ollama local

---

## 4. CLAUDE CODE (auto-referencia)

### Chamada direta (de outro processo)
```bash
claude -p "prompt"
```

### NOTA: Claude normalmente e o ORQUESTRADOR, nao o orquestrado.
Raramente voce chamara Claude de dentro do Claude.
Mas e possivel para pipelines encadeados.

---

## PADROES DE CHAMADA COMUNS

### Padrao 1: Chamada simples com captura
```bash
# Bash tool - resultado vai para stdout
resultado=$(gemini -m gemini-3-flash-preview -p "analise X")
echo "$resultado"
```

### Padrao 2: Encadeamento (output de uma IA como input de outra)
```bash
# Gemini analisa, Qwen valida
analise=$(gemini -m gemini-3-pro-preview -p "analise arquitetural de X")
validacao=$(echo "$analise" | qwen -p "valide esta analise: ")
```

### Padrao 3: Paralelo via background
```bash
# Rodar em paralelo e coletar resultados
gemini -m gemini-3-flash-preview -p "tarefa A" > /tmp/resultado_gemini.txt &
qwen -p "tarefa B" > /tmp/resultado_qwen.txt &
wait
# Ler resultados
cat /tmp/resultado_gemini.txt
cat /tmp/resultado_qwen.txt
```

### Padrao 4: Com arquivo de prompt (para prompts grandes)
```bash
# Salvar prompt em arquivo
cat > /tmp/prompt.txt << 'PROMPT_EOF'
Seu prompt grande aqui
com multiplas linhas
PROMPT_EOF

# Chamar com @arquivo
gemini -m gemini-3-pro-preview -p "@/tmp/prompt.txt"
```

### Padrao 5: Resultado em arquivo (para saidas grandes)
```bash
gemini -m gemini-3-pro-preview -p "prompt" > resultado.txt 2>&1
```

---

## TRATAMENTO DE ERROS

### Erros comuns e solucoes

| Erro | IA | Solucao |
|------|-----|---------|
| Timeout | Todas | Aumentar timeout, reduzir prompt |
| "command not found" | Todas | Verificar PATH, reinstalar |
| JSON invalido | Todas | Usar regex para extrair, retry |
| Rate limit | Qwen | Esperar, usar outra IA |
| Auth error | Codex | Limpar OPENAI_BASE_URL/KEY |
| Encoding | Todas | Forcar UTF-8 no subprocess |

### Funcao de validacao JSON (use SEMPRE antes de parsear saida de IA)
```bash
# Valida se string e JSON valido. Retorna 0 (ok) ou 1 (invalido).
validar_json() {
    local json="$1"
    if echo "$json" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        return 0
    fi
    # fallback: tentar extrair JSON embutido em texto
    local extraido
    extraido=$(echo "$json" | grep -oP '\{.*\}' | head -1)
    if [ -n "$extraido" ] && echo "$extraido" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        echo "$extraido"  # imprime o JSON extraido para captura
        return 0
    fi
    return 1
}

# Uso padrao:
resultado=$(gemini -m gemini-3-flash-preview -p "retorne JSON")
if json_limpo=$(validar_json "$resultado"); then
    echo "JSON valido: $json_limpo"
else
    echo "ERRO: saida nao e JSON valido. Conteudo: $resultado"
    # retry ou marcar como ERRO
fi
```

### Retry logic
```bash
# Tentar ate 3 vezes com backoff
for i in 1 2 3; do
    resultado=$(gemini -m gemini-3-flash-preview -p "prompt" 2>&1) && break
    echo "Tentativa $i falhou, aguardando..."
    sleep $((i * 5))
done
```

---

## DICAS DE PERFORMANCE

1. **Prefira Gemini Flash ou Qwen** para tarefas de triagem/filtragem
2. **Reserve Gemini Pro e Codex** para analises profundas
3. **Use arquivos temp** para prompts > 1000 caracteres
4. **Salve resultados intermediarios** em lotes para nao perder progresso
5. **Pipe e redirecionamento** sao mais eficientes que subprocess Python quando possivel
