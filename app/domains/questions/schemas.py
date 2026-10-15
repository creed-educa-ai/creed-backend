"""Schemas Pydantic do dominio questions.

Separados por direcao (ADR-002, secao 2.3): entrada e saida nao se
contaminam. A montagem da saida a partir do model mora aqui, em `de_model()`,
e nao no router (mesmo padrao de app/domains/users/schemas.py).

Reexporta QuestionSection: a terceira entrega (router) precisa do tipo para
o filtro `?section=`, e a rota nao pode importar de models.py.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.questions.models import (
    Prisma,
    Question,
    QuestionOption,
    QuestionSection,
    QuestionType,
)

__all__ = [
    "Prisma",
    "QuestionCreate",
    "QuestionOptionCreate",
    "QuestionOptionResponse",
    "QuestionResponse",
    "QuestionSection",
    "QuestionType",
]


class QuestionBase(BaseModel):
    form_id: uuid.UUID = Field(
        description="Identificador do formulário ao qual a pergunta pertence.",
        examples=["00000000-0000-0000-0000-000000000001"],
    )
    text: str = Field(
        min_length=1,
        description="Enunciado da pergunta.",
        examples=["Como você avalia sua adaptabilidade?"],
    )
    order_index: int = Field(
        ge=0,
        description="Posição da pergunta no formulário, começando em 0.",
        examples=[0],
    )
    type: QuestionType = Field(description="Tipo de resposta esperado pela pergunta.")
    section: QuestionSection = Field(
        description="Bloco do formulário em que a pergunta é desenhada na tela."
    )


class QuestionCreate(QuestionBase):
    """Payload de criacao.

    `required` nasce true e `prisma` nasce vazio quando omitidos — mesma
    forma que o model, mas explicito aqui porque e o service quem decide
    (ADR-0004: o que muda se o produto mudar de ideia mora no service, mas
    o *default de payload* e contrato de entrada, entao mora no schema).
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "form_id": "00000000-0000-0000-0000-000000000001",
                    "text": "Como você avalia sua adaptabilidade?",
                    "order_index": 0,
                    "type": "objective",
                    "section": "assessment",
                }
            ]
        }
    )

    required: bool = Field(
        default=True,
        description="Se a pergunta exige resposta para submeter o formulário.",
    )
    prisma: Prisma | None = Field(
        default=None,
        description="Dimensão de análise associada à pergunta, quando houver.",
    )


class QuestionResponse(QuestionBase):
    """Representacao de saida."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "7ae21494-975f-46ab-97cc-4c42b5ae7aaa",
                    "form_id": "00000000-0000-0000-0000-000000000001",
                    "text": "Como você avalia sua adaptabilidade?",
                    "order_index": 0,
                    "type": "objective",
                    "section": "assessment",
                    "required": True,
                    "prisma": "plasticidade_humana",
                    "created_at": "2026-09-22T14:00:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da pergunta.")
    required: bool = Field(
        description="Se a pergunta exige resposta para submeter o formulário."
    )
    prisma: Prisma | None = Field(
        description="Dimensão de análise associada à pergunta, quando houver."
    )
    created_at: datetime = Field(description="Data e hora de criação da pergunta.")

    @classmethod
    def de_model(cls, question: Question) -> "QuestionResponse":
        """Monta a saida a partir do model."""
        return cls.model_validate(question)


class QuestionOptionBase(BaseModel):
    label: str = Field(
        min_length=1,
        description="Texto da alternativa, como aparece para quem responde.",
        examples=["Sim"],
    )
    value: str = Field(
        min_length=1,
        description="Valor gravado quando a alternativa é escolhida.",
        examples=["sim"],
    )
    order_index: int = Field(
        ge=0,
        description="Posição da alternativa na pergunta, começando em 0.",
        examples=[0],
    )


class QuestionOptionCreate(QuestionOptionBase):
    """Payload de criação.

    A pergunta vem do caminho da URL (`/questions/{question_id}/options`), não do
    corpo: aceitar nos dois lugares deixaria dois valores possíveis para o mesmo dado.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"label": "Sim", "value": "sim", "order_index": 0}]
        }
    )


class QuestionOptionResponse(QuestionOptionBase):
    """Representação de saída."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "7ae21494-975f-46ab-97cc-4c42b5ae7aab",
                    "question_id": "7ae21494-975f-46ab-97cc-4c42b5ae7aaa",
                    "label": "Sim",
                    "value": "sim",
                    "order_index": 0,
                    "created_at": "2026-10-14T14:00:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da alternativa.")
    question_id: uuid.UUID = Field(
        description="Identificador da pergunta a que a alternativa pertence."
    )
    created_at: datetime = Field(description="Data e hora de criação da alternativa.")

    @classmethod
    def de_model(cls, option: QuestionOption) -> "QuestionOptionResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(option)
