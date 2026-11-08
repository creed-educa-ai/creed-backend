"""Schemas Pydantic do domínio forms."""

import enum
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
                    "opens_at": "2026-10-01T00:00:00Z",
                    "closes_at": "2026-10-31T23:59:59Z",
                    "link_id": "3f2b8c1e-7a4d-4e9b-9c0a-5d6e7f8a9b0c",
                    "created_at": "2026-09-22T14:30:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador do formulário na plataforma.")
    status: FormStatus = Field(description="Estado do formulário.")
    opens_at: datetime | None = Field(
        description="Quando o questionário abre. Nulo: sem período definido."
    )
    closes_at: datetime | None = Field(
        description="Quando o questionário fecha. Nulo: sem período definido."
    )
    link_id: uuid.UUID | None = Field(
        description="Vínculo da única pessoa que responde. Nulo: a organização inteira."
    )
    created_at: datetime = Field(description="Data e hora de criação do formulário.")

    @classmethod
    def de_model(cls, form: Form) -> "FormRead":
        """Monta a saída a partir do model."""
        return cls.model_validate(form)


class PeriodStatus(enum.Enum):
    """Situação do período em relação ao momento da consulta."""

    PAST = "past"
    OPEN = "open"
    SCHEDULED = "scheduled"


class PeriodRead(FormRead):
    """Um período: o formulário, com as datas sempre preenchidas e a situação."""

    opens_at: datetime = Field(description="Quando o período abre.")
    closes_at: datetime = Field(description="Quando o período fecha.")
    period_status: PeriodStatus = Field(
        description="Situação do período, calculada pelo back no momento da consulta."
    )

    @classmethod
    def de_form(cls, form: Form, period_status: PeriodStatus) -> "PeriodRead":
        """Monta a saída a partir do model e da situação já calculada."""
        return cls(
            **FormRead.model_validate(form).model_dump(), period_status=period_status
        )
