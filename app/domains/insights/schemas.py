"""Schemas Pydantic do domínio insights.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`, e não no
router: o schema já conhece a forma do model (`from_attributes=True`), enquanto o
router não pode conhecer (ADR-0004, item 7).

A volta da esteira (o callback do N8N e o `InsightContent`) também mora aqui, porque
quem a recebe é este domínio. É o contrato `insight-v1` da spec da CREED-80, seção
"Volta: N8N → back" (P-087 e P-088), e o N8N o lê em
`docker/n8n/contrato/volta.schema.json`, gerado destes modelos por
`scripts/exportar_contrato_n8n.py`.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.insights.models import Insight


class InsightCreate(BaseModel):
    """Payload de criação de um bloco de análise."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "form_response_id": "3b1bb89a-471f-48b0-9025-cfda3b20d240",
                    "content": "O time demonstra alta segurança psicológica...",
                }
            ]
        }
    )

    form_response_id: uuid.UUID = Field(
        description="Identificador do formulário respondido que originou a análise.",
        examples=["3b1bb89a-471f-48b0-9025-cfda3b20d240"],
    )
    content: str = Field(description="Texto da análise gerada.")


class InsightResponse(BaseModel):
    """Representação de saída de um bloco de análise."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "0b4e1f2a-9c3d-4a5b-8e6f-7d8c9b0a1e2f",
                    "form_response_id": "3b1bb89a-471f-48b0-9025-cfda3b20d240",
                    "content": None,
                    "created_at": "2026-10-08T13:30:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da análise.")
    form_response_id: uuid.UUID | None = Field(
        description=(
            "Identificador do formulário respondido que originou a análise. Nulo no "
            "insight da empresa."
        )
    )
    content: dict[str, Any] | None = Field(
        description="O `InsightContent` gerado. Nulo até o insight ficar pronto."
    )
    created_at: datetime = Field(description="Data e hora de geração da análise.")

    @classmethod
    def de_model(cls, insight: Insight) -> "InsightResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(insight)


# Tamanhos da spec da CREED-80 ("Volta: N8N → back"). Texto vazio também é recusado:
# viraria um card em branco na tela.
AnalysisParagraph = Annotated[str, Field(min_length=1, max_length=900)]
PrismaText = Annotated[str, Field(min_length=1, max_length=320)]
RecommendationParagraph = Annotated[str, Field(min_length=1, max_length=700)]


class PrismaTexts(BaseModel):
    """Um texto curto para cada um dos cinco prismas. Os cinco vêm sempre."""

    model_config = ConfigDict(extra="forbid")

    seguranca_psicologica: PrismaText
    lideranca_adaptativa: PrismaText
    cultura_empreendedora: PrismaText
    adaptabilidade_cognitiva: PrismaText
    neuroinovacao_prisma: PrismaText


class InsightContent(BaseModel):
    """O texto do insight, conferido pelo back antes de gravar.

    É o mesmo no insight individual e no da empresa: no individual, fala com a
    pessoa; no da empresa, fala do grupo com a gestão (P-088). Campo a mais é
    recusado, como uma chave de prisma escrita de outro jeito.
    """

    model_config = ConfigDict(extra="forbid")

    analise: list[AnalysisParagraph] = Field(
        min_length=2,
        max_length=4,
        description="De 2 a 4 parágrafos, de até 900 caracteres cada.",
    )
    prismas: PrismaTexts
    recomendacao: list[RecommendationParagraph] = Field(
        min_length=1,
        max_length=3,
        description="De 1 a 3 parágrafos, de até 700 caracteres cada.",
    )


class InsightCallbackDone(BaseModel):
    """Volta do N8N com o texto pronto."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["insight-v1"]
    insight_id: uuid.UUID = Field(description="O mesmo id que foi no pedido.")
    status: Literal["done"]
    content: InsightContent
    model_id: str = Field(
        min_length=1,
        description="Modelo que gerou o texto, como o Bedrock o identifica.",
    )
    prompt_version: str = Field(
        min_length=1,
        description="Versão dos prompts e do dossiê, ex.: individual-v1+dossie-v1.",
    )


class InsightCallbackFailed(BaseModel):
    """Volta do N8N quando o texto não saiu."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["insight-v1"]
    insight_id: uuid.UUID = Field(description="O mesmo id que foi no pedido.")
    status: Literal["failed"]
    error: str = Field(
        min_length=1,
        description="Código curto do erro, para o log, ex.: bedrock_throttled.",
    )
    retryable: bool = Field(
        description=(
            "false quando tentar de novo não muda o resultado, como numa recusa do "
            "modelo. O back encerra o insight sem gastar as tentativas restantes."
        )
    )


# O corpo do callback é um dos dois, e o `status` diz qual. Com o discriminador, um
# erro de validação aponta o campo do modelo certo, e não os dois modelos.
InsightCallback = Annotated[
    InsightCallbackDone | InsightCallbackFailed, Field(discriminator="status")
]
