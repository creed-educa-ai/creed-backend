"""Testes dos schemas do domínio insights.

Entrada e saída são separadas de propósito (ADR-002, secao 2.3): o que o
cliente manda não é o que o banco devolve.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domains.insights.models import Insight
from app.domains.insights.schemas import InsightCreate, InsightResponse


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
