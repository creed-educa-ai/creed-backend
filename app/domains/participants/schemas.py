"""Schemas Pydantic do domínio participants.

Separados por direção (ADR-0004): entrada e saída não se contaminam. A montagem
da saída a partir do model mora aqui, em `de_model()`, e não no router.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.participants.models import Participant
from app.shared.enums import RecordStatus


class ParticipantBase(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Nome completo da pessoa.",
        examples=["Pessoa Exemplo"],
    )


class ParticipantCreate(ParticipantBase):
    """Payload de cadastro.

    Espaços nas pontas do nome saem antes da validação: `"   "` vira texto vazio e
    é recusado, em vez de gravar um nome em branco.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"name": "Pessoa Exemplo"}]},
    )


class ParticipantResponse(ParticipantBase):
    """Representação de saída de um participante."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "7f9c2b1e-4a3d-4c8e-9b6f-2d1e0a5c8b73",
                    "name": "Pessoa Exemplo",
                    "status": "active",
                    "created_at": "2026-09-27T14:30:00Z",
                    "updated_at": None,
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador do participante na plataforma.")
    status: RecordStatus = Field(description="Estado do cadastro do participante.")
    created_at: datetime = Field(description="Data e hora do cadastro.")
    updated_at: datetime | None = Field(
        description="Data e hora da última alteração; nulo se nunca foi alterado."
    )

    @classmethod
    def de_model(cls, participant: Participant) -> "ParticipantResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(participant)
