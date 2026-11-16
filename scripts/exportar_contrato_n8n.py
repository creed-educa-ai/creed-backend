"""Escreve os schemas do kit de contrato da esteira a partir dos modelos (CREED-801).

O N8N não lê Python: quem monta o workflow lê `docker/n8n/contrato/ida.schema.json`
e `volta.schema.json`. Este script gera os dois a partir dos modelos Pydantic, que
são a fonte do contrato. Rode da raiz do repo depois de mudar um campo do contrato, e
commite os arquivos junto com a mudança:

    python scripts/exportar_contrato_n8n.py

`tests/external_services/n8n/test_contrato.py` fica vermelho enquanto os arquivos
commitados divergirem dos modelos.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.domains.insights.schemas import InsightCallback
from app.external_services.n8n.schemas import IndividualInsightRequest

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "docker" / "n8n" / "contrato"


def contract_schemas() -> dict[str, dict[str, Any]]:
    """Nome de cada arquivo do kit e o JSON Schema que ele deve conter.

    A volta é a união de `done` e `failed`, e união não é classe: por isso o
    `TypeAdapter`, que dá o mesmo schema que o FastAPI vai usar no callback.
    """
    return {
        "ida.schema.json": IndividualInsightRequest.model_json_schema(),
        "volta.schema.json": TypeAdapter(InsightCallback).json_schema(),
    }


def main() -> int:
    for file_name, schema in contract_schemas().items():
        # `ensure_ascii=False` deixa os acentos legíveis no diff; `newline="\n"`
        # evita que o Windows grave CRLF e o diff acuse o arquivo inteiro.
        text = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        (CONTRACT_DIR / file_name).write_text(text, encoding="utf-8", newline="\n")
        # Sem acento de propósito: no Windows, o stdout sai em cp1252.
        print(f"escrito: docker/n8n/contrato/{file_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
