"""Schemas Pydantic do domínio department.

Separados por direção (ADR-002, seção 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`,
e não no router (ADR-0004, item 7).
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domains.department.models import Department, DepartmentType


class DepartmentCreate(BaseModel):
    """Payload de criação de um departamento."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "organization_id": "00000000-0000-0000-0000-000000000001",
                    "type": "TecnologiaInformacao",
                },
            ]
        }
    )

    organization_id: uuid.UUID = Field(
        description="Identificador da organização à qual o departamento pertence.",
    )

    type: DepartmentType = Field(
        description="Tipo do departamento.",
        examples=["TecnologiaInformacao"],
    )


class DepartmentResponse(BaseModel):
    """Representação de saída de um departamento."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "organization_id": "00000000-0000-0000-0000-000000000002",
                    "type": "TecnologiaInformacao",
                },
            ]
        },
    )

    id: uuid.UUID = Field(
        description="Identificador do departamento.",
    )
    organization_id: uuid.UUID = Field(
        description="Identificador da organização à qual o departamento pertence.",
    )
    type: DepartmentType = Field(
        description="Tipo do departamento.",
    )

    @classmethod
    def de_model(cls, department: Department) -> "DepartmentResponse":
        """Monta a resposta a partir do model Department."""
        return cls(
            id=department.id,
            organization_id=department.organization_id,
            type=department.type,
        )
