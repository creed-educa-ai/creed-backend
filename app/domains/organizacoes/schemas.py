"""Schemas Pydantic do domínio organizacoes.

Separados por direção (ADR-0004): entrada e saída não se contaminam.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.organizacoes.models import Organization
from app.shared.enums import RecordStatus
from app.shared.validators import sem_caractere_de_controle


class OrganizationCreate(BaseModel):
    """Payload de cadastro. O documento precisa já existir."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=255)
    document_id: uuid.UUID

    @field_validator("name", "address")
    @classmethod
    def _sem_caractere_de_controle(cls, valor: str) -> str:
        return sem_caractere_de_controle(valor)


class OrganizationUpdate(BaseModel):
    """Payload do PATCH: todo campo é opcional, e só o que vier é alterado.

    `document_id` fica de fora: trocar o documento de uma organização não está no
    contrato da CREED-38.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, min_length=1, max_length=255)
    status: RecordStatus | None = None

    @field_validator("name", "address", "status")
    @classmethod
    def _nulo_nao_apaga(cls, valor: object) -> object:
        """Recusa `null` enviado: os três campos são obrigatórios no banco.

        Sem isto, `{"name": null}` chegava ao service como "alterar para None" e o
        banco recusava no `flush()`, com 500. Para manter o valor, omite-se o campo.
        O validador só roda no que veio no corpo, não no default.
        """
        if valor is None:
            raise ValueError("não pode ser nulo; omita o campo para mantê-lo")
        return valor

    @field_validator("name", "address")
    @classmethod
    def _sem_caractere_de_controle(cls, valor: str | None) -> str | None:
        return None if valor is None else sem_caractere_de_controle(valor)


class OrganizationResponse(BaseModel):
    """Representação de saída de uma organização."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "5a1e9c3b-2f7d-4b8a-9e6c-0d4f1b2a3c5e",
                    "name": "Organização Exemplo",
                    "address": "Av. Ipiranga, 6681, Porto Alegre - RS",
                    "document_id": "3b2f8c1a-6d4e-4f7a-9c5b-1e0d2a8f6b94",
                    "status": "active",
                    "created_at": "2026-10-15T14:30:00Z",
                    "updated_at": None,
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da organização na plataforma.")
    name: str = Field(description="Nome da organização.")
    address: str = Field(description="Endereço, em texto livre (P-021).")
    document_id: uuid.UUID = Field(description="Documento da organização.")
    status: RecordStatus = Field(description="Estado do cadastro da organização.")
    created_at: datetime = Field(description="Data e hora do cadastro.")
    updated_at: datetime | None = Field(
        description="Data e hora da última alteração; nulo se nunca foi alterada."
    )

    @classmethod
    def de_model(cls, organization: Organization) -> "OrganizationResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(organization)
