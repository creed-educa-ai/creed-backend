"""Testes dos schemas do domínio insights.

Entrada e saída são separadas de propósito (ADR-002, secao 2.3): o que o
cliente manda não é o que o banco devolve.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from app.domains.insights.models import Insight
from app.domains.insights.schemas import (
    InsightCallback,
    InsightCallbackDone,
    InsightCallbackFailed,
    InsightContent,
    InsightCreate,
    InsightResponse,
    PrismaTexts,
)
from app.shared.enums import Prisma


def test_entrada_leva_so_o_que_o_cliente_manda() -> None:
    """`id` e `created_at` são do banco, não do payload."""
    assert set(InsightCreate.model_fields) == {"form_response_id", "content"}


def test_saida_devolve_as_quatro_colunas() -> None:
    assert set(InsightResponse.model_fields) == {
        "id",
        "form_response_id",
        "content",
        "created_at",
    }


def test_entrada_sem_content_e_recusada() -> None:
    with pytest.raises(ValidationError):
        InsightCreate(form_response_id=uuid.uuid4())  # type: ignore[call-arg]


def test_entrada_sem_form_response_id_e_recusada() -> None:
    with pytest.raises(ValidationError):
        InsightCreate(content="texto")  # type: ignore[call-arg]


def test_de_model_monta_a_saida_a_partir_do_model() -> None:
    insight = Insight(
        id=uuid.uuid4(),
        form_response_id=uuid.uuid4(),
        content="O time demonstra alta segurança psicológica.",
        created_at=datetime(2026, 10, 8, tzinfo=UTC),
    )

    saida = InsightResponse.de_model(insight)

    assert saida.id == insight.id
    assert saida.form_response_id == insight.form_response_id
    assert saida.content == insight.content
    assert saida.created_at == insight.created_at


# --- InsightContent: o texto que volta da esteira (CREED-801, P-088) ----------


def _content() -> dict[str, Any]:
    """Um `content` válido, no menor tamanho que o contrato aceita."""
    return {
        "analise": ["Primeiro parágrafo.", "Segundo parágrafo."],
        "prismas": {prisma.value: "Um texto curto." for prisma in Prisma},
        "recomendacao": ["Uma recomendação."],
    }


def test_content_valido_e_aceito() -> None:
    content = InsightContent.model_validate(_content())

    assert len(content.analise) == 2
    assert content.prismas.seguranca_psicologica == "Um texto curto."


def test_prismas_do_content_sao_os_do_enum() -> None:
    """Os campos repetem o enum `Prisma`: se ele mudar, o contrato muda junto."""
    assert set(PrismaTexts.model_fields) == {prisma.value for prisma in Prisma}


@pytest.mark.parametrize(
    ("paragrafos", "aceito"), [(1, False), (2, True), (4, True), (5, False)]
)
def test_analise_tem_de_2_a_4_paragrafos(paragrafos: int, aceito: bool) -> None:
    content = _content()
    content["analise"] = ["Um parágrafo."] * paragrafos

    if aceito:
        InsightContent.model_validate(content)
    else:
        with pytest.raises(ValidationError, match="analise"):
            InsightContent.model_validate(content)


@pytest.mark.parametrize(
    ("paragrafos", "aceito"), [(0, False), (1, True), (3, True), (4, False)]
)
def test_recomendacao_tem_de_1_a_3_paragrafos(paragrafos: int, aceito: bool) -> None:
    content = _content()
    content["recomendacao"] = ["Um parágrafo."] * paragrafos

    if aceito:
        InsightContent.model_validate(content)
    else:
        with pytest.raises(ValidationError, match="recomendacao"):
            InsightContent.model_validate(content)


@pytest.mark.parametrize(
    ("campo", "limite"),
    [("analise", 900), ("recomendacao", 700)],
)
def test_paragrafo_tem_tamanho_maximo(campo: str, limite: int) -> None:
    no_limite = _content()
    no_limite[campo][0] = "a" * limite
    InsightContent.model_validate(no_limite)

    acima = _content()
    acima[campo][0] = "a" * (limite + 1)
    with pytest.raises(ValidationError, match=campo):
        InsightContent.model_validate(acima)


def test_texto_de_prisma_tem_ate_320_caracteres() -> None:
    no_limite = _content()
    no_limite["prismas"]["lideranca_adaptativa"] = "a" * 320
    InsightContent.model_validate(no_limite)

    acima = _content()
    acima["prismas"]["lideranca_adaptativa"] = "a" * 321
    with pytest.raises(ValidationError, match="lideranca_adaptativa"):
        InsightContent.model_validate(acima)


def test_paragrafo_vazio_e_recusado() -> None:
    """Viraria um card em branco na tela."""
    content = _content()
    content["analise"][1] = ""

    with pytest.raises(ValidationError, match="analise"):
        InsightContent.model_validate(content)


def test_prisma_escrito_de_outro_jeito_e_recusado() -> None:
    """Cinco chaves, mas uma com cedilha: falta `seguranca_psicologica` e sobra a
    escrita errada. As duas coisas são erro, e nenhuma passa calada."""
    content = _content()
    texto = content["prismas"].pop("seguranca_psicologica")
    content["prismas"]["segurança_psicologica"] = texto

    with pytest.raises(ValidationError) as erro:
        InsightContent.model_validate(content)

    campos = {str(item["loc"][-1]) for item in erro.value.errors()}
    assert campos == {"seguranca_psicologica", "segurança_psicologica"}


def test_prisma_faltando_e_recusado() -> None:
    content = _content()
    del content["prismas"]["neuroinovacao_prisma"]

    with pytest.raises(ValidationError, match="neuroinovacao_prisma"):
        InsightContent.model_validate(content)


# --- Callback: done ou failed, pelo `status` ---------------------------------

CALLBACK: TypeAdapter[InsightCallback] = TypeAdapter(InsightCallback)


def _done() -> dict[str, Any]:
    return {
        "contract_version": "insight-v1",
        "insight_id": str(uuid.uuid4()),
        "status": "done",
        "content": _content(),
        "model_id": "anthropic.claude-opus-5-5",
        "prompt_version": "individual-v1+dossie-v1",
    }


def _failed() -> dict[str, Any]:
    return {
        "contract_version": "insight-v1",
        "insight_id": str(uuid.uuid4()),
        "status": "failed",
        "error": "bedrock_throttled",
        "retryable": True,
    }


def test_callback_done_vira_o_modelo_done() -> None:
    callback = CALLBACK.validate_python(_done())

    assert isinstance(callback, InsightCallbackDone)
    assert isinstance(callback.content, InsightContent)


def test_callback_failed_vira_o_modelo_failed() -> None:
    callback = CALLBACK.validate_python(_failed())

    assert isinstance(callback, InsightCallbackFailed)
    assert callback.retryable is True


def test_callback_com_status_desconhecido_e_recusado() -> None:
    body = _failed()
    body["status"] = "pending"

    with pytest.raises(ValidationError, match="status"):
        CALLBACK.validate_python(body)


def test_callback_com_outra_versao_de_contrato_e_recusado() -> None:
    body = _done()
    body["contract_version"] = "insight-v2"

    with pytest.raises(ValidationError, match="contract_version"):
        CALLBACK.validate_python(body)


def test_callback_failed_com_content_e_recusado() -> None:
    """`failed` não traz texto: um `content` nele é corpo fora do contrato."""
    body = _failed()
    body["content"] = _content()

    with pytest.raises(ValidationError, match="content"):
        CALLBACK.validate_python(body)
