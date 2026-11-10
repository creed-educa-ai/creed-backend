"""Schemas Pydantic do domínio organizacoes.

Separados por direção (ADR-0004): entrada e saída não se contaminam.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.organizacoes.models import Organization, OrganizationStatus
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

    `status` é `RecordStatus`, e não `OrganizationStatus`, de propósito: o PATCH não
    aceita `pending` (422). Tirar uma empresa de `pending` também não é do PATCH:
    o service recusa (409), porque ela só sai desse estado aprovada ou rejeitada.
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


class OrganizationDocument(BaseModel):
    """O documento da organização, como a tela da administradora mostra."""

    type: str = Field(description="Tipo do documento: `cpf`, `cnpj`, `nipc`...")
    value: str = Field(description="Número do documento, como está guardado.")


class OrganizationResponse(BaseModel):
    """Representação de saída de uma organização."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "5a1e9c3b-2f7d-4b8a-9e6c-0d4f1b2a3c5e",
                    "name": "Organização Exemplo",
                    "address": "Av. Ipiranga, 6681, Porto Alegre - RS",
                    "document_id": "3b2f8c1a-6d4e-4f7a-9c5b-1e0d2a8f6b94",
                    "status": "pending",
                    "email": "gestora@empresa.com.br",
                    "contact_name": "Gestora Exemplo",
                    "phone": "51 99999-0000",
                    "document": {"type": "cnpj", "value": "12345678000190"},
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
    status: OrganizationStatus = Field(
        description=(
            "Estado do cadastro. `pending` é a empresa que se cadastrou e ainda não "
            "foi aprovada."
        )
    )
    email: str | None = Field(
        description="E-mail informado no cadastro; nulo se a organização não o tem."
    )
    contact_name: str | None = Field(
        description="Nome do responsável informado no cadastro; nulo se não há."
    )
    phone: str | None = Field(
        description="Telefone informado no cadastro; nulo se não há."
    )
    document: OrganizationDocument = Field(
        description="Tipo e número do documento apontado por `document_id`."
    )
    created_at: datetime = Field(description="Data e hora do cadastro.")
    updated_at: datetime | None = Field(
        description="Data e hora da última alteração; nulo se nunca foi alterada."
    )

    @classmethod
    def de_model(
        cls, organization: Organization, document_type: str, document_value: str
    ) -> "OrganizationResponse":
        """Monta a saída a partir do model e do documento dele.

        O documento não vem de `organization`: mora em `documents`, e quem o lê é o
        `OrganizationService.with_documents`. Este schema não importa o service, que
        já importa este arquivo.
        """
        return cls(
            id=organization.id,
            name=organization.name,
            address=organization.address,
            document_id=organization.document_id,
            status=organization.status,
            email=organization.email,
            contact_name=organization.contact_name,
            phone=organization.phone,
            document=OrganizationDocument(type=document_type, value=document_value),
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )
