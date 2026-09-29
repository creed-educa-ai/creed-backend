"""Schemas Pydantic do domínio forms."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domains.forms.models import FormStatus


class FormBase(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=200,
        description="Nome do formulário.",
        examples=["Formulário de exemplo"],
    )

    organization_id: uuid.UUID

    status: FormStatus = FormStatus.DRAFT


class FormCreate(FormBase):
    """Payload de criação de Table."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Pessoa Exemplo",
                    "organization_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
                }
            ]
        }
    )

    keycloak_id: uuid.UUID = Field(
        description="Identificador `sub` do usuário provisionado no Keycloak.",
        examples=["e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339"],
    )
