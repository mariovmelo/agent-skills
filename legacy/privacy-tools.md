# Ferramentas de Privacidade e Qualidade para Orquestração

> Carregue este arquivo APENAS quando a tarefa envolver dados sensiveis (modo `sensitive`)
> ou quando precisar de logging estruturado, validacao de schema ou output formatado.

---

## 1. MICROSOFT PRESIDIO — Anonimizacao de PII (LGPD)

**Quando usar**: ANTES de enviar qualquer documento com dados pessoais para IAs externas.
**Detecta**: CPF, RG, nome, telefone, e-mail, endereco, data de nascimento, placa de veiculo, etc.

### Instalacao
```bash
pip install presidio-analyzer presidio-anonymizer
python -m spacy download pt_core_news_lg  # modelo portugues
```

### Uso basico (anonimizar antes de enviar para IA)
```python
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

def anonimizar(texto: str) -> str:
    """Remove PII do texto antes de enviar para IAs externas."""
    resultados = analyzer.analyze(text=texto, language="pt")
    return anonymizer.anonymize(text=texto, analyzer_results=resultados).text

# Uso no pipeline de orquestracao:
with open("documento_policial.txt") as f:
    texto_original = f.read()

texto_seguro = anonimizar(texto_original)

# Agora e seguro enviar para Gemini/Codex/Qwen
with open("/tmp/doc_anonimizado.txt", "w") as f:
    f.write(texto_seguro)

# Chamada CLI segura
import subprocess
resultado = subprocess.run(
    ["gemini", "-m", "gemini-3-flash-preview", "-p", f"@/tmp/doc_anonimizado.txt"],
    capture_output=True, text=True
)
```

### Entidades suportadas em portugues
| Entidade | Codigo | Exemplo |
|----------|--------|---------|
| CPF | `BR_CPF` | 123.456.789-00 |
| RG | `BR_RG` | 12.345.678-9 |
| Nome | `PERSON` | Joao da Silva |
| Telefone | `PHONE_NUMBER` | (84) 99999-9999 |
| E-mail | `EMAIL_ADDRESS` | joao@email.com |
| Endereco | `LOCATION` | Rua das Flores, 123 |

### Substituicoes personalizadas (recomendado para contexto policial)
```python
from presidio_anonymizer.entities import OperatorConfig

# Substituir por tags descritivas em vez de <PERSON>
operadores = {
    "PERSON":       OperatorConfig("replace", {"new_value": "[NOME_OMITIDO]"}),
    "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[TELEFONE_OMITIDO]"}),
    "BR_CPF":       OperatorConfig("replace", {"new_value": "[CPF_OMITIDO]"}),
    "LOCATION":     OperatorConfig("replace", {"new_value": "[LOCAL_OMITIDO]"}),
}
texto_seguro = anonymizer.anonymize(
    text=texto_original,
    analyzer_results=resultados,
    operators=operadores
).text
```

---

## 2. STRUCTLOG — Logging Estruturado (Auditoria LGPD)

**Quando usar**: Para registrar QUAIS dados foram enviados para QUAIS IAs e quando.
**Obrigacao LGPD**: Manter rastro de processamento de dados pessoais.

### Configuracao padrao para orquestracao
```python
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()

# Registrar cada chamada de IA
log.info("ia_chamada",
    ia="gemini",
    modelo="gemini-3-flash-preview",
    dados_anonimizados=True,
    entidades_removidas=["PERSON", "BR_CPF"],
    arquivo_origem="documento_policial.txt",
    timestamp_anonimizacao="2026-02-17T10:30:00"
)

# Registrar resultado
log.info("ia_resultado",
    ia="gemini",
    status="OK",
    tokens_usados=1250,
    custo_estimado_usd=0.001
)
```

### Output exemplo (JSON para auditoria)
```json
{"event": "ia_chamada", "ia": "gemini", "dados_anonimizados": true, "timestamp": "2026-02-17T10:30:00Z"}
{"event": "ia_resultado", "ia": "gemini", "status": "OK", "timestamp": "2026-02-17T10:30:05Z"}
```

---

## 3. RICH — Output Formatado no Terminal

**Quando usar**: Para mostrar progresso de lotes, tabelas de resultados e status de orquestracao.

### Progresso de lote
```python
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.console import Console
from rich.table import Table

console = Console()

# Barra de progresso para lotes
with Progress(
    SpinnerColumn(),
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    TextColumn("{task.completed}/{task.total}"),
) as progress:
    task = progress.add_task("Processando com Gemini...", total=len(arquivos))
    for arquivo in arquivos:
        # processar...
        progress.advance(task)

# Tabela de resultados consolidados
tabela = Table(title="Resultados da Orquestracao")
tabela.add_column("Arquivo", style="cyan")
tabela.add_column("Gemini", style="green")
tabela.add_column("Qwen", style="yellow")
tabela.add_column("Consenso", style="bold")

tabela.add_row("doc_01.txt", "APROVADO", "APROVADO", "✓ APROVADO")
tabela.add_row("doc_02.txt", "REPROVADO", "APROVADO", "⚠ DIVERGENCIA")

console.print(tabela)
```

---

## 4. PYDANTIC — Validacao de Schema das IAs

**Quando usar**: Para validar o JSON retornado por cada IA antes de processar.

### Schema base para resposta de IA
```python
from pydantic import BaseModel, field_validator
from typing import Literal
from datetime import datetime

class RespostaIA(BaseModel):
    status: Literal["OK", "ERRO"]
    resultado: str
    ia: Literal["gemini", "codex", "qwen", "claude"]
    modelo: str
    timestamp: datetime

    @field_validator("resultado")
    @classmethod
    def resultado_nao_vazio(cls, v):
        if not v.strip():
            raise ValueError("Resultado nao pode ser vazio")
        return v

# Validar resposta de IA
import json

def validar_resposta(json_str: str) -> RespostaIA | None:
    try:
        dados = json.loads(json_str)
        return RespostaIA(**dados)
    except Exception as e:
        return None  # marcar como ERRO e fazer retry

# Uso:
resposta_raw = subprocess.run(...).stdout
resposta = validar_resposta(resposta_raw)
if resposta is None:
    log.error("resposta_invalida", ia="gemini", raw=resposta_raw[:200])
```

### Schema para relatorio LGPD de auditoria
```python
class RelatorioAuditoria(BaseModel):
    arquivo: str
    dados_anonimizados: bool
    entidades_removidas: list[str]
    ias_consultadas: list[str]
    resultado_final: str
    timestamp: datetime
    aprovado_por: Literal["gemini", "codex", "qwen", "consenso", "humano"]
```

---

## FLUXO COMPLETO — Dado Sensivel → Anonimizacao → IA → Validacao → Log

```python
import subprocess, json, structlog
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from pydantic import BaseModel
from rich.console import Console

log = structlog.get_logger()
console = Console()
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

def processar_documento_sensivel(arquivo: str, ia: str = "gemini") -> dict:
    # 1. Ler e anonimizar
    texto = open(arquivo).read()
    resultados_pii = analyzer.analyze(text=texto, language="pt")
    texto_seguro = anonymizer.anonymize(text=texto, analyzer_results=resultados_pii).text
    entidades = list({r.entity_type for r in resultados_pii})

    log.info("anonimizacao_ok", arquivo=arquivo, entidades=entidades)

    # 2. Salvar em temp e chamar IA
    tmp = f"/tmp/anonimizado_{hash(arquivo)}.txt"
    open(tmp, "w").write(texto_seguro)

    cmd = ["gemini", "-m", "gemini-3-flash-preview", "-p", f"@{tmp}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    log.info("ia_chamada", ia=ia, arquivo=arquivo, status="OK" if proc.returncode == 0 else "ERRO")

    # 3. Retornar resultado estruturado
    return {
        "arquivo": arquivo,
        "ia": ia,
        "resultado": proc.stdout,
        "entidades_removidas": entidades,
        "dados_anonimizados": True
    }
```

