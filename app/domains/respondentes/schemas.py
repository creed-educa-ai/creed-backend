"""Schemas Pydantic do domínio respondentes.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`, e não no
router: o schema já conhece a forma do model (`from_attributes=True`), enquanto o
router não pode conhecer (ADR-0004, item 7).
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domains.respondentes.models import Respondente
from app.domains.respondentes.utils import calcular_idade


class RespondenteBase(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    email: EmailStr
    data_nascimento: date | None = None
    genero: str | None = Field(default=None, max_length=50)
    regiao: str | None = Field(default=None, max_length=100)
    pais: str | None = Field(default=None, min_length=2, max_length=2)


class RespondenteCreate(RespondenteBase):
    """Payload de criação."""


class RespondenteUpdate(BaseModel):
    """Payload de atualização parcial — todos os campos opcionais."""

    nome: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    data_nascimento: date | None = None
    genero: str | None = Field(default=None, max_length=50)
    regiao: str | None = Field(default=None, max_length=100)
    pais: str | None = Field(default=None, min_length=2, max_length=2)


class RespondenteResponse(RespondenteBase):
    """Representação de saída."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idade: int | None = None
    criado_em: datetime

    @classmethod
    def de_model(cls, respondente: Respondente) -> "RespondenteResponse":
        """Monta a saída a partir do model, preenchendo o campo derivado."""
        resposta = cls.model_validate(respondente)
        resposta.idade = calcular_idade(respondente.data_nascimento)
        return resposta
