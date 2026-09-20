"""Schemas Pydantic do domínio respostas.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`, e não no
router: o schema já conhece a forma do model (`from_attributes=True`), enquanto o
router não pode conhecer (ADR-0004, item 7).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domains.respostas.models import FormResponse, FormResponseStatus


class FormResponseCreate(BaseModel):
    """Payload de criação."""

    form_id: uuid.UUID
    vinculo_id: uuid.UUID


class FormResponseResponse(BaseModel):
    """Representação de saída."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    form_id: uuid.UUID
    vinculo_id: uuid.UUID
    status: FormResponseStatus
    started_at: datetime
    submitted_at: datetime | None = None

    @classmethod
    def de_model(cls, form_response: FormResponse) -> "FormResponseResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(form_response)
