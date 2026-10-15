"""Schemas Pydantic do domínio organizacoes.

Separados por direção (ADR-0004): entrada e saída não se contaminam.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    @field_validator("name", "address")
    @classmethod
    def _sem_caractere_de_controle(cls, valor: str | None) -> str | None:
        return None if valor is None else sem_caractere_de_controle(valor)
