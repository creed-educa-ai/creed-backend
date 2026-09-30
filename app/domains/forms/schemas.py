"""Schemas Pydantic do domínio forms."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.forms.models import Form, FormStatus


class FormBase(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=200,
        description="Nome do formulário.",
        examples=["Formulário de exemplo"],
    )

    organization_id: uuid.UUID


class FormCreate(FormBase):
    """Payload de criação.

    Sem 'status': o formulário nasce sempre em rascunho
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Formulário de exemplo",
                    "organization_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
                }
            ]
        }
    )


class FormRead(FormBase):
    """Representação de saída."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d40b7a55-b9cc-4b78-ae5d-ab325fd655e2",
                    "name": "Formulário de exemplo",
                    "organization_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
                    "status": "draft",
                    "created_at": "2026-09-22T14:30:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador do formulário na plataforma.")
    status: FormStatus = Field(description="Estado do formulário.")
    created_at: datetime = Field(description="Data e hora de criação do formulário.")

    @classmethod
    def de_model(cls, form: Form) -> "FormRead":
        """Monta a saída a partir do model."""
        return cls.model_validate(form)
