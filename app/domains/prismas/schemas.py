"""Schemas Pydantic do domínio prismas (ADR-002, secao 2.3)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.shared.enums import Dimension, Prisma


class DimensionScore(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dimension: Dimension
    average: float = Field(
        ..., ge=1.0, le=5.0, description="Média obtida na dimensão (1 a 5)"
    )


class PrismaScore(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prisma: Prisma
    score: float = Field(
        ..., ge=1.0, le=5.0, description="Pontuação do prisma (escala 1 a 5)"
    )
    score_100: float = Field(
        ..., ge=0.0, le=100.0, description="Pontuação normalizada (escala 0 a 100)"
    )


class FormResponsePrismasRead(BaseModel):
    """Resultado individual dos prismas de uma resposta de formulário."""

    model_config = ConfigDict(from_attributes=True)

    form_response_id: uuid.UUID
    form_id: uuid.UUID
    vinculo_id: uuid.UUID
    scores: dict[str, float] = Field(
        ..., description="Pontuações dos 5 prismas na escala 1 a 5"
    )
    scores_100: dict[str, float] = Field(
        ..., description="Pontuações dos 5 prismas normalizadas de 0 a 100"
    )
    dimensions: dict[str, float] = Field(
        ..., description="Médias individuais das 7 dimensões da Matriz CREED"
    )
