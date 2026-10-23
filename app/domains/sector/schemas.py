"""Schemas Pydantic do domínio sector.

Separados por direção (ADR-002, seção 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`,
e não no router (ADR-0004, item 7).
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domains.sector.models import Sector, SectorType


class SectorCreate(BaseModel):
    """Payload de criação de um setor."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"type": "technology"},
            ]
        }
    )

    type: SectorType = Field(
        description="Tipo do setor.",
        examples=["technology"],
    )

    def to_model(self) -> Sector:
        return Sector(type=self.type)


class SectorResponse(BaseModel):
    """Representação de saída de um setor."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(
        description="Identificador do setor.",
    )
    type: SectorType = Field(
        description="Tipo do setor.",
    )

    @classmethod
    def de_model(cls, sector: Sector) -> "SectorResponse":
        """Monta a resposta a partir do model Sector."""
        return cls(
            id=sector.id,
            type=sector.type,
        )
