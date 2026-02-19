# Exemplos Praticos - Cenarios Reais

> Baseados nos scripts reais do usuario.
> Estes sao EXEMPLOS para inspirar, nao templates rigidos.

---

## EXEMPLO 1: Auditoria de Anonimizacao (LGPD)

**Cenario**: Verificar se documentos foram anonimizados corretamente.

**Equipe sugerida**:
```
Auditor 1: Gemini Flash (varredura rapida, GRATUITO)
Auditor 2: Qwen (segunda opiniao, GRATUITO)
Consolidador: Claude (relatorio final)
```

**Execucao**:
```bash
# Montar prompt em arquivo temporario (SEGURO - evita escaping e limite de CLI)
cat > /tmp/audit_prompt.txt << 'PROMPT_EOF'
Voce e um auditor LGPD. Analise o documento abaixo e encontre QUALQUER dado pessoal real nao anonimizado.
Responda APENAS JSON: {"status":"APROVADO|REPROVADO","dados_encontrados":[{"dado":"...","tipo":"..."}],"total_vazamentos":0}
PROMPT_EOF
cat documento.txt >> /tmp/audit_prompt.txt

# Auditor 1 - Gemini (paralelo)
gemini -m gemini-3-flash-preview -p "@/tmp/audit_prompt.txt" > /tmp/resultado_gemini.json &

# Auditor 2 - Qwen (paralelo)
qwen -p "@/tmp/audit_prompt.txt" > /tmp/resultado_qwen.json &
wait

# Limpar prompts temporarios
rm -f /tmp/audit_prompt.txt

# Claude consolida ambos os resultados
```

**Fluxo de discussao com usuario**:
```
Claude: Para auditar a anonimizacao, sugiro:
  - Gemini Flash como auditor principal (rapido, gratuito)
  - Qwen como segundo auditor (perspectiva diferente, gratuito)
  - Eu consolido os resultados e gero relatorio
  Custo total: ZERO (so eu sou pago, mas ja estou aqui)
  Posso executar?
```

---

## EXEMPLO 2: Avaliacao Curricular em Lote

**Cenario**: Avaliar 50+ curriculos com criterios especificos.

**Equipe sugerida**:
```
Worker: Gemini Flash (processa todos, GRATUITO, rapido)
QA: Gemini Pro (valida amostra de 10%, GRATUITO)
Relatorio: Claude (ranking final, dashboard)
```

**Execucao**:
```bash
# Worker processa cada curriculo
for arquivo in curriculos/*.txt; do
    gemini -m gemini-3-flash-preview -p "Avalie este curriculo (0-100) para a vaga X. JSON: {score, recomendacao, justificativa}. Curriculo: $(cat $arquivo)" >> resultados.jsonl
    sleep 1  # rate limit
done

# QA valida amostra
amostra=$(shuf -n 5 resultados.jsonl)
gemini -m gemini-3-pro-preview -p "Valide estas avaliacoes. Estao coerentes? $amostra"
```

---

## EXEMPLO 3: Analise Arquitetural de Codigo

**Cenario**: Analisar arquivo complexo (4000+ linhas) para refatoracao.

**Equipe sugerida**:
```
Arquiteto: Gemini Pro (anti-patterns, SOLID)
Debugger: Codex (bugs especificos)
Professor: Qwen (explicacao educativa)
CTO: Claude (roadmap de refatoracao, ROI)
```

**Execucao**: PARALELO (os 3 primeiros), depois Claude consolida.
```bash
# Preparar prompt via arquivo (seguro para arquivos grandes)
cat > /tmp/prompt_arq.txt << 'EOF'
Identifique anti-patterns e violacoes SOLID no codigo abaixo. Responda em JSON.
EOF
cat codigo.js >> /tmp/prompt_arq.txt

# Paralelo - cada IA recebe via @arquivo
gemini -m gemini-3-pro-preview -p "@/tmp/prompt_arq.txt" > /tmp/arquitetura.json &
unset OPENAI_BASE_URL && unset OPENAI_API_KEY && codex exec --skip-git-repo-check "Encontre bugs no arquivo codigo.js neste diretorio" > /tmp/bugs.txt &
qwen -p "Explique como melhorar o codigo em codigo.js com exemplos praticos" > /tmp/review.txt &
wait

# Limpeza de temporarios
rm -f /tmp/prompt_arq.txt

# Claude consolida os 3 resultados
```

---

## EXEMPLO 4: Normalizacao de Dados com IA

**Cenario**: Mapear nomes livres para siglas oficiais.

**Equipe sugerida**:
```
Worker: Qwen (normalizacao item a item, GRATUITO)
Validador: Gemini Flash (confirma mapeamentos duvidosos)
```

**Execucao**: SEQUENCIAL
```bash
# Qwen normaliza
qwen -p "Lista oficial: [DPCA, DRCC, DPI, ...]. Qual sigla para 'Delegacia de Protecao a Crianca'? Responda APENAS a sigla."

# Se Qwen retornar algo duvidoso, Gemini confirma
gemini -m gemini-3-flash-preview -p "A sigla oficial para 'Delegacia de Protecao a Crianca' e DPCA? Sim ou Nao."
```

---

## EXEMPLO 5: Investigacao de Bug Critico

**Cenario**: Bug em producao, precisa de diagnostico urgente.

**Equipe sugerida**:
```
Diagnostico: Codex (encontra o bug exato)
Contexto: Qwen (explica o impacto)
Plano: Claude (define correcao segura)
```

**Execucao**: SEQUENCIAL (cada etapa informa a proxima)
```bash
# 1. Codex identifica
unset OPENAI_BASE_URL && unset OPENAI_API_KEY && codex exec --skip-git-repo-check "Por que a funcao X na linha 1282 causa stale data?"

# 2. Qwen contextualiza
qwen -p "Explique o impacto de stale data na funcao X e quais modulos sao afetados"

# 3. Claude planeja correcao
# (Claude ja esta aqui, consolida e planeja)
```

---

## EXEMPLO 6: Brainstorm Multi-Perspectiva

**Cenario**: Decidir abordagem para nova feature.

**Equipe sugerida**:
```
Todos recebem o MESMO prompt, cada um da sua perspectiva:
  - Claude: Visao de negocio e ROI
  - Gemini Pro: Viabilidade tecnica e arquitetura
  - Codex: Complexidade de implementacao e alternativas
```

**Execucao**: PARALELO
```bash
prompt="Como implementar autenticacao SSO no sistema X? Considere custo, complexidade e manutencao."

gemini -m gemini-3-pro-preview -p "$prompt" > /tmp/gemini.txt &
qwen -p "$prompt" > /tmp/qwen.txt &
wait

# Claude analisa as 3 perspectivas (incluindo a propria)
```

---

## ANTI-PADROES

> Anti-padroes detalhados e proibicoes tecnicas de shell estao em SKILL.md.
> Aqui apenas lembretes rapidos contextualizados nos exemplos acima.

- Nao escale: 1 IA basta para perguntas simples
- Nao envie dados brutos: use arquivo temp, nunca `$(cat sensivel.txt)` inline
- Nao ignore erros: retry com backoff ou IA alternativa
- Nao gaste: Qwen/Gemini Flash para triagem, pagas so para analise profunda
