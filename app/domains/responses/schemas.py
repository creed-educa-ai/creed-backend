"""Schemas Pydantic do domínio respostas.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`, e não no
router: o schema já conhece a forma do model (`from_attributes=True`), enquanto o
router não pode conhecer (ADR-0004, item 7).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.responses.models import FormResponse, FormResponseStatus


class FormResponseCreate(BaseModel):
    """Payload de criação."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "form_id": "7d94e9bb-25ca-4df9-9c08-d90251dd8d68",
                    "vinculo_id": "2956a8ec-b76d-4398-99af-f4bba109ccba",
                }
            ]
        }
    )

    form_id: uuid.UUID = Field(
        description="Identificador do formulário que será respondido.",
        examples=["7d94e9bb-25ca-4df9-9c08-d90251dd8d68"],
    )
    vinculo_id: uuid.UUID = Field(
        description="Identificador do vínculo responsável pela resposta.",
        examples=["2956a8ec-b76d-4398-99af-f4bba109ccba"],
    )


class FormResponseResponse(BaseModel):
    """Representação de saída."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "3b1bb89a-471f-48b0-9025-cfda3b20d240",
                    "form_id": "7d94e9bb-25ca-4df9-9c08-d90251dd8d68",
                    "vinculo_id": "2956a8ec-b76d-4398-99af-f4bba109ccba",
                    "status": "in_progress",
                    "started_at": "2026-09-22T14:30:00Z",
                    "submitted_at": None,
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da resposta de formulário.")
    form_id: uuid.UUID = Field(description="Identificador do formulário respondido.")
    vinculo_id: uuid.UUID = Field(
        description="Identificador do vínculo responsável pela resposta."
    )
    status: FormResponseStatus = Field(description="Estado atual da resposta.")
    started_at: datetime = Field(description="Data e hora de início da resposta.")
    submitted_at: datetime | None = Field(
        default=None,
        description="Data e hora de submissão; nulo enquanto estiver em andamento.",
    )

    @classmethod
    def de_model(cls, form_response: FormResponse) -> "FormResponseResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(form_response)
