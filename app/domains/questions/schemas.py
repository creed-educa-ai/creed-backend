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
    QuestionSection,
    QuestionType,
)

__all__ = [
    "Prisma",
    "QuestionCreate",
    "QuestionResponse",
    "QuestionSection",
    "QuestionType",
]


class QuestionBase(BaseModel):
    form_id: uuid.UUID
    text: str = Field(min_length=1)
    order_index: int = Field(ge=0)
    type: QuestionType
    section: QuestionSection


class QuestionCreate(QuestionBase):
    """Payload de criacao.

    `required` nasce true e `prisma` nasce vazio quando omitidos — mesma
    forma que o model, mas explicito aqui porque e o service quem decide
    (ADR-0004: o que muda se o produto mudar de ideia mora no service, mas
    o *default de payload* e contrato de entrada, entao mora no schema).
    """

    required: bool = True
    prisma: Prisma | None = None


class QuestionResponse(QuestionBase):
    """Representacao de saida."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    required: bool
    prisma: Prisma | None
    created_at: datetime

    @classmethod
    def de_model(cls, question: Question) -> "QuestionResponse":
        """Monta a saida a partir do model."""
        return cls.model_validate(question)
