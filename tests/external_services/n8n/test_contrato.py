"""Testes do kit de contrato da esteira (`docker/n8n/contrato/`, CREED-801).

O kit é o que o back e o N8N da AWS usam como verdade antes de se encontrarem em
produção (spec da CREED-80, "Abordagem técnica", item 5). Aqui se prova o lado do
back: os exemplos valem pelos modelos, versões alteradas deles são recusadas, os
schemas commitados são os dos modelos, e a função de assinatura chega ao valor do
vetor.

Que o N8N valida a entrada e assina igual não passa por aqui: é a CREED-806 que
prova, no editor dele, com estes mesmos arquivos.
"""

import json
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.security import compute_webhook_signature
from app.domains.insights.schemas import (
    InsightCallback,
    InsightCallbackDone,
    InsightCallbackFailed,
)
from app.external_services.n8n.schemas import (
    DimensionScores,
    IndividualInsightRequest,
    InsightResult,
    OpenAnswer,
    PrismaScores,
)
from app.shared.enums import Dimension, Prisma
from scripts.exportar_contrato_n8n import CONTRACT_DIR, contract_schemas

CALLBACK: TypeAdapter[InsightCallback] = TypeAdapter(InsightCallback)


def _load(file_name: str) -> Any:
    return json.loads((CONTRACT_DIR / file_name).read_text(encoding="utf-8"))


# --- Ida --------------------------------------------------------------------


def test_ida_nao_leva_dado_que_identifica_a_pessoa() -> None:
    """P-091: o pedido não leva nome, e-mail, documento, organização, setor, dado
    demográfico nem `form_response_id`.

    A lista é dos campos que PODEM ir. Campo novo deixa este teste vermelho, e quem
    o acrescenta precisa decidir, aqui, que ele não identifica ninguém.
    """
    assert set(IndividualInsightRequest.model_fields) == {
        "contract_version",
        "scope",
        "insight_id",
        "attempt",
        "language",
        "result",
        "open_answers",
    }
    assert set(InsightResult.model_fields) == {
        "prismas",
        "dimensions",
        "destaque",
        "oportunidade",
    }
    assert set(OpenAnswer.model_fields) == {"section", "question", "answer"}


def test_notas_da_ida_tem_um_campo_por_prisma_e_por_dimensao() -> None:
    """Os campos repetem os enums: se um enum mudar, o contrato tem que mudar junto."""
    assert set(PrismaScores.model_fields) == {prisma.value for prisma in Prisma}
    assert set(DimensionScores.model_fields) == {
        dimension.value for dimension in Dimension
    }


def test_exemplo_de_ida_vale_pelo_modelo() -> None:
    request = IndividualInsightRequest.model_validate(
        _load("exemplo-ida-individual.json")
    )

    assert request.scope == "individual"
    assert request.result.destaque is Prisma.SEGURANCA_PSICOLOGICA
    assert len(request.open_answers) == 2


def test_ida_sem_campo_obrigatorio_e_recusada() -> None:
    payload = _load("exemplo-ida-individual.json")
    del payload["insight_id"]

    with pytest.raises(ValidationError, match="insight_id"):
        IndividualInsightRequest.model_validate(payload)


def test_ida_com_campo_fora_do_contrato_e_recusada() -> None:
    """O que não está no contrato não sai do back, nem por descuido."""
    payload = _load("exemplo-ida-individual.json")
    payload["email"] = "pessoa@exemplo.com"

    with pytest.raises(ValidationError, match="email"):
        IndividualInsightRequest.model_validate(payload)


def test_ida_com_sexto_prisma_e_recusada() -> None:
    payload = _load("exemplo-ida-individual.json")
    payload["result"]["prismas"]["empatia"] = 50.0

    with pytest.raises(ValidationError, match="empatia"):
        IndividualInsightRequest.model_validate(payload)


@pytest.mark.parametrize("nota", [-0.1, 100.1])
def test_ida_com_nota_fora_de_0_a_100_e_recusada(nota: float) -> None:
    payload = _load("exemplo-ida-individual.json")
    payload["result"]["prismas"]["lideranca_adaptativa"] = nota

    with pytest.raises(ValidationError, match="lideranca_adaptativa"):
        IndividualInsightRequest.model_validate(payload)


def test_ida_sem_respostas_abertas_e_aceita() -> None:
    """Quem não respondeu nenhuma pergunta descritiva manda a lista vazia."""
    payload = _load("exemplo-ida-individual.json")
    payload["open_answers"] = []

    request = IndividualInsightRequest.model_validate(payload)

    assert request.open_answers == []


# --- Volta ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_name", "expected_type"),
    [
        ("exemplo-volta-done.json", InsightCallbackDone),
        ("exemplo-volta-failed.json", InsightCallbackFailed),
    ],
)
def test_exemplos_de_volta_valem_pelo_modelo(file_name: str, expected_type: type) -> None:
    callback = CALLBACK.validate_python(_load(file_name))

    assert isinstance(callback, expected_type)


def test_volta_done_sem_content_e_recusada() -> None:
    body = _load("exemplo-volta-done.json")
    del body["content"]

    with pytest.raises(ValidationError, match="content"):
        CALLBACK.validate_python(body)


def test_volta_done_com_sexto_prisma_e_recusada() -> None:
    body = _load("exemplo-volta-done.json")
    body["content"]["prismas"]["empatia"] = "Um texto curto."

    with pytest.raises(ValidationError, match="empatia"):
        CALLBACK.validate_python(body)


def test_volta_done_com_paragrafo_longo_demais_e_recusada() -> None:
    body = _load("exemplo-volta-done.json")
    body["content"]["analise"][0] = "a" * 901

    with pytest.raises(ValidationError, match="analise"):
        CALLBACK.validate_python(body)


def test_volta_failed_sem_retryable_e_recusada() -> None:
    body = _load("exemplo-volta-failed.json")
    del body["retryable"]

    with pytest.raises(ValidationError, match="retryable"):
        CALLBACK.validate_python(body)


# --- Schemas commitados -----------------------------------------------------


@pytest.mark.parametrize("file_name", ["ida.schema.json", "volta.schema.json"])
def test_schema_commitado_e_o_dos_modelos(file_name: str) -> None:
    """Compara o JSON lido, e não o texto: no Windows o git pode trocar a quebra
    de linha do arquivo, e isso não muda o contrato."""
    assert _load(file_name) == contract_schemas()[file_name], (
        f"docker/n8n/contrato/{file_name} diverge dos modelos Pydantic. "
        "Rode `python scripts/exportar_contrato_n8n.py` e commite o resultado."
    )


def test_todo_schema_do_kit_esta_no_exportador() -> None:
    """Um `*.schema.json` que o script não gera nunca seria conferido pelo teste
    acima, e envelheceria calado."""
    on_disk = {path.name for path in CONTRACT_DIR.glob("*.schema.json")}

    assert on_disk == set(contract_schemas())


# --- Assinatura -------------------------------------------------------------


def test_assinatura_reproduz_o_vetor() -> None:
    vector = _load("vetor-hmac.json")

    signature = compute_webhook_signature(
        vector["secret"], vector["timestamp"], vector["body"].encode("utf-8")
    )

    assert signature == vector["signature"]


def test_mudar_um_byte_do_corpo_muda_a_assinatura() -> None:
    vector = _load("vetor-hmac.json")
    body = bytearray(vector["body"].encode("utf-8"))
    body[-2] ^= 0x01

    signature = compute_webhook_signature(
        vector["secret"], vector["timestamp"], bytes(body)
    )

    assert signature != vector["signature"]


def test_mudar_o_timestamp_muda_a_assinatura() -> None:
    vector = _load("vetor-hmac.json")
    later = str(int(vector["timestamp"]) + 1)

    signature = compute_webhook_signature(
        vector["secret"], later, vector["body"].encode("utf-8")
    )

    assert signature != vector["signature"]


def test_corpo_reformatado_muda_a_assinatura() -> None:
    """O mesmo JSON com acento escapado não é o mesmo corpo: quem assina tem que
    assinar a string exata que manda (README do kit, "Duas armadilhas")."""
    vector = _load("vetor-hmac.json")
    same_json_other_bytes = json.dumps(json.loads(vector["body"])).encode("utf-8")

    signature = compute_webhook_signature(
        vector["secret"], vector["timestamp"], same_json_other_bytes
    )

    assert signature != vector["signature"]


def test_segredo_do_vetor_e_de_teste() -> None:
    """O vetor é público, no git: o segredo dele não pode ser um de verdade."""
    # S105: é o segredo de teste do vetor, publicado de propósito no kit.
    assert _load("vetor-hmac.json")["secret"] == "segredo-de-teste-nao-use"  # noqa: S105
