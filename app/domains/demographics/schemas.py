"""Schemas Pydantic do domínio demographics.

Separados por direção (ADR-0004): entrada e saída não se contaminam. A montagem
da saída a partir do model mora aqui, em `de_model()`, e não no router.

Os enums trafegam pelo `value` (`"18_25"`, `"nao_binario"`), o mesmo do front.
"""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.demographics.models import (
    AgeRange,
    BrazilState,
    Demographic,
    Ethnicity,
    Gender,
    Nationality,
    PortugalRegion,
    Religion,
)
from app.shared.validators import sem_caractere_de_controle


class DemographicBase(BaseModel):
    gender: Gender | None = Field(
        default=None, description="Gênero.", examples=["feminino"]
    )
    age_range: AgeRange | None = Field(
        default=None, description="Faixa etária.", examples=["26_35"]
    )
    ethnicities: list[Ethnicity] = Field(
        default_factory=list,
        description="Origens étnicas. Aceita mais de uma, sem repetir.",
        examples=[["europeia", "latino_americana"]],
    )
    religions: list[Religion] = Field(
        default_factory=list,
        description="Religiões. Aceita mais de uma, sem repetir.",
        examples=[["crista"]],
    )
    nationality: Nationality | None = Field(
        default=None, description="Nacionalidade.", examples=["brasileira"]
    )
    brazil_state: BrazilState | None = Field(
        default=None,
        description="UF; só com nacionalidade `brasileira`.",
        examples=["RS"],
    )
    portugal_region: PortugalRegion | None = Field(
        default=None,
        description="Região; só com nacionalidade `portuguesa`.",
        examples=["norte"],
    )
    other_nationality: str | None = Field(
        default=None,
        max_length=100,
        description="Nacionalidade por extenso; só com nacionalidade `outra`.",
        examples=["argentina"],
    )


class DemographicCreate(DemographicBase):
    """Payload do perfil demográfico. Todo campo é opcional.

    Normaliza campos válidos que não batem com a nacionalidade; valor inválido é
    recusado. A normalização é a do `normalizeDemographics` do front, e é o que os
    checks da tabela exigem.

    🟡 Premissa a validar com a cliente — "prefiro não responder" pode vir junto
    com outras opções nas listas.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "gender": "feminino",
                    "age_range": "26_35",
                    "ethnicities": ["europeia", "latino_americana"],
                    "religions": ["crista"],
                    "nationality": "brasileira",
                    "brazil_state": "RS",
                }
            ]
        },
    )

    @field_validator("ethnicities", "religions")
    @classmethod
    def _reject_duplicates[T](cls, options: list[T]) -> list[T]:
        """A PK das tabelas filhas é (perfil, opção): repetida, o banco recusaria."""
        if len(set(options)) != len(options):
            raise ValueError("Não pode repetir opção")
        return options

    @field_validator("other_nationality")
    @classmethod
    def _blank_is_empty(cls, other_nationality: str | None) -> str | None:
        """Texto em branco é campo não preenchido. Só na entrada: a saída devolve o
        que está gravado."""
        if not other_nationality:
            return None
        return sem_caractere_de_controle(other_nationality)

    @model_validator(mode="after")
    def _clear_fields_of_other_nationalities(self) -> Self:
        if self.nationality is not Nationality.BRASILEIRA:
            self.brazil_state = None
        if self.nationality is not Nationality.PORTUGUESA:
            self.portugal_region = None
        if self.nationality is not Nationality.OUTRA:
            self.other_nationality = None
        return self


class DemographicResponse(DemographicBase):
    """Representação de saída do perfil demográfico."""

    # A saída sempre traz todos os campos, então todos são obrigatórios na
    # OpenAPI, mesmo os que têm default herdado da base.
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "5d8e2a1b-7c4f-4e9a-8b3d-6f1c0e2a9b47",
                    "participant_id": "7f9c2b1e-4a3d-4c8e-9b6f-2d1e0a5c8b73",
                    "gender": "feminino",
                    "age_range": "26_35",
                    "ethnicities": ["europeia", "latino_americana"],
                    "religions": ["crista"],
                    "nationality": "brasileira",
                    "brazil_state": "RS",
                    "portugal_region": None,
                    "other_nationality": None,
                    "created_at": "2026-10-18T14:30:00Z",
                    "updated_at": None,
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador do perfil demográfico.")
    participant_id: uuid.UUID = Field(description="Participante dono do perfil.")
    # Sem o default da base: o model não tem as listas, e `model_validate` direto
    # nele falha em vez de devolver `[]` calado. A saída passa por `de_model()`.
    ethnicities: list[Ethnicity] = Field(
        description="Origens étnicas marcadas; vazia se nenhuma."
    )
    religions: list[Religion] = Field(description="Religiões marcadas; vazia se nenhuma.")
    created_at: datetime = Field(description="Data e hora do cadastro.")
    updated_at: datetime | None = Field(
        description="Data e hora da última alteração; nulo se nunca foi alterado."
    )

    @classmethod
    def de_model(
        cls,
        demographic: Demographic,
        *,
        ethnicities: list[Ethnicity],
        religions: list[Religion],
    ) -> "DemographicResponse":
        """Monta a saída a partir do perfil e das opções marcadas.

        As listas moram nas tabelas filhas, que o model não carrega (não há
        `relationship`): quem chama já as leu e as passa aqui.
        """
        return cls(
            id=demographic.id,
            participant_id=demographic.participant_id,
            gender=demographic.gender,
            age_range=demographic.age_range,
            ethnicities=ethnicities,
            religions=religions,
            nationality=demographic.nationality,
            brazil_state=demographic.brazil_state,
            portugal_region=demographic.portugal_region,
            other_nationality=demographic.other_nationality,
            created_at=demographic.created_at,
            updated_at=demographic.updated_at,
        )
