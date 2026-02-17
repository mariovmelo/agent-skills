# Padroes de Equipe - Exemplificativos

> **IMPORTANTE**: Estes padroes sao EXEMPLOS, nao regras fixas.
> A IA orquestradora DEVE pensar na melhor estrutura para cada tarefa
> e DISCUTIR com o usuario antes de executar.
> O usuario pode definir sua propria estrutura a qualquer momento.

---

## PAPEIS POSSIVEIS

Cada IA pode assumir qualquer papel. Os papeis mais comuns:

| Papel | Descricao | IAs tipicas |
|-------|-----------|-------------|
| **Lider** | Define estrategia, distribui tarefas, consolida | Claude, Gemini Pro |
| **Arquiteto** | Analisa estrutura, sugere design | Gemini Pro, Claude |
| **Executor** | Implementa codigo, faz alteracoes | Codex, Qwen |
| **Revisor** | Valida qualidade, encontra problemas | Qwen, Gemini Pro |
| **Debugger** | Encontra bugs, diagnostica erros | Codex, Claude |
| **Analista** | Pesquisa, coleta dados, investiga | Gemini Flash, Qwen |
| **Documentador** | Gera relatorios, documenta decisoes | Claude, Qwen |
| **Auditor** | Valida conformidade, seguranca, privacidade | Gemini Pro, Claude |

---

## PADRAO 1: ANALISE COMPLETA DE CODIGO

```
Lider: Claude (define o que analisar)
  |
  +-- Arquiteto: Gemini Pro (anti-patterns, SOLID, design)
  |
  +-- Debugger: Codex (bugs linha por linha)
  |
  +-- Revisor: Qwen (review educativo, alternativas)
  |
  v
Consolidador: Claude (relatorio unificado)
```

**Execucao**: Arquiteto + Debugger + Revisor em PARALELO, depois Claude consolida.
**Custo**: Gemini (gratis) + Codex (pago) + Qwen (gratis) + Claude (pago)

---

## PADRAO 2: DESENVOLVIMENTO DIARIO (ECONOMICO)

```
1. Revisor: Qwen (review inicial GRATUITO)
2. Validador: Gemini Flash (confirma achados GRATUITO)
3. Se necessario: Codex ou Claude (implementacao/decisao)
```

**Execucao**: SEQUENCIAL (escala so se necessario)
**Custo**: Majoritariamente GRATUITO

---

## PADRAO 3: DEBUGGING CRITICO

```
1. Debugger: Codex (identifica bug exato)
2. Analista: Qwen (entende contexto e impacto)
3. Arquiteto: Gemini Pro (verifica impacto arquitetural)
4. Lider: Claude (planeja correcao sistemica)
```

**Execucao**: SEQUENCIAL (cada etapa informa a proxima)
**Custo**: Misto

---

## PADRAO 4: AUDITORIA DE PRIVACIDADE / LGPD

```
Auditor Principal: Gemini Pro (analise exaustiva)
  |
  +-- Auditor Secundario: Qwen (segunda opiniao)
  |
  v
Consolidador: Claude (relatorio final, decisao)
```

**Execucao**: Auditores em PARALELO, depois Claude decide.
**Custo**: Gemini (gratis) + Qwen (gratis) + Claude (pago)
**NOTA**: Dados devem ser anonimizados ANTES de enviar para IAs

---

## PADRAO 5: PROCESSAMENTO EM LOTE

```
Worker Pool:
  +-- Worker 1: Qwen (itens 1-N sequencial, GRATUITO)
  +-- Worker 2: Gemini Flash (itens 1-N sequencial, GRATUITO)
  |
  v
Validador: Gemini Pro ou Claude (amostragem para QA)
```

**Execucao**: Workers em PARALELO processando itens diferentes
**Custo**: Majoritariamente GRATUITO
**NOTA**: Salvar progresso incrementalmente para nao perder trabalho

---

## PADRAO 6: BRAINSTORM / MULTIPLAS PERSPECTIVAS

```
Todos em PARALELO com o MESMO prompt:
  +-- Perspectiva 1: Claude (visao executiva)
  +-- Perspectiva 2: Gemini Pro (visao arquitetural)
  +-- Perspectiva 3: Qwen (visao educativa)
  |
  v
Sintese: Claude (compara, identifica consenso e divergencias)
```

**Execucao**: PARALELO total
**Custo**: Claude (pago) + Gemini (gratis) + Qwen (gratis)

---

## PADRAO 7: PIPELINE DE VALIDACAO CRUZADA

```
Produtor: IA-A (gera resultado)
  |
  v
Validador: IA-B (valida/critica resultado)
  |
  v
Arbitro: IA-C (decide se aceita ou pede revisao)
```

**Qualquer combinacao de IAs pode assumir qualquer papel.**
**Execucao**: SEQUENCIAL (cada etapa depende da anterior)

---

## PADRAO 8: ESPECIALISTA + GENERALISTA

```
Especialista: IA mais forte na area (conforme catalogo)
  |
  v
Generalista: IA diferente para segunda opiniao
  |
  v
Decisor: Usuario ou Claude
```

---

## COMO ESCOLHER O PADRAO

Pergunte-se (e discuta com o usuario):

1. **A tarefa e simples ou complexa?**
   - Simples → 1 IA basta, nao escale
   - Complexa → Monte equipe

2. **Precisa de multiplas perspectivas ou uma so?**
   - Multiplas → Padrao 6 (brainstorm) ou 7 (validacao cruzada)
   - Uma so → Padrao 8 (especialista)

3. **Ha restricao de custo?**
   - Sim → Priorize Qwen + Gemini (gratuitos)
   - Nao → Use a melhor IA para cada papel

4. **Os resultados dependem um do outro?**
   - Sim → SEQUENCIAL
   - Nao → PARALELO

5. **Ha dados sensiveis?**
   - Sim → Anonimize primeiro, prefira IAs locais
   - Nao → Qualquer IA

6. **E processamento em lote?**
   - Sim → Padrao 5 (workers)
   - Nao → Padroes 1-4 ou 6-8

---

## CRIANDO PADROES CUSTOMIZADOS

O usuario pode definir seus proprios padroes a qualquer momento:

```
Usuario: "Quero que o Gemini analise a arquitetura, o Qwen implemente,
          e o Codex faca debug do resultado"

Orquestrador: Entendido! Montando equipe:
  1. Gemini Pro (Arquiteto) → analisa e sugere
  2. Qwen (Executor) → implementa baseado na sugestao
  3. Codex (Debugger) → valida a implementacao
  Execucao: SEQUENCIAL
  Posso prosseguir?
```
