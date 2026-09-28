"""Schemas Pydantic do domínio vinculos.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`, e não no
router: o schema já conhece a forma do model (`from_attributes=True`), enquanto o
router não pode conhecer (ADR-0004, item 7).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.vinculos.models import Roles, VincType, Vinculo


class VinculoCreate(BaseModel):
    """Payload de criação.

    Sem `organization_id`: vem da URL (`/organizacoes/{organization_id}/vinculos`),
    não do corpo — quem monta o `Vinculo` com ele é o service.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "participant_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
                    "setor_id": None,
                    "type": "emprego",
                    "role": "gestor",
                }
            ]
        }
    )

    participant_id: uuid.UUID = Field(description="Participante dono do vínculo.")
    setor_id: uuid.UUID | None = Field(
        default=None,
        description="Setor da organização, se já existir um na hora do cadastro.",
    )
    type: VincType = Field(description="Tipo do vínculo com a organização.")
    role: Roles = Field(description="Papel do participante neste vínculo.")


class VinculoResponse(BaseModel):
    """Representação de saída, na forma de `Vinculo` no `.dbml`."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d40b7a55-b9cc-4b78-ae5d-ab325fd655e2",
                    "participant_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
                    "organization_id": "8f14e45f-ceea-467e-adde-3f81905dbc1c",
                    "setor_id": None,
                    "type": "emprego",
                    "role": "gestor",
                    "start_at": "2026-09-24T14:00:00Z",
                    "end_at": None,
                    "created_at": "2026-09-24T14:00:00Z",
                    "updated_at": None,
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador do vínculo.")
    participant_id: uuid.UUID = Field(description="Participante dono do vínculo.")
    organization_id: uuid.UUID = Field(description="Organização do vínculo.")
    setor_id: uuid.UUID | None = Field(description="Setor da organização, se houver.")
    type: VincType = Field(description="Tipo do vínculo com a organização.")
    role: Roles = Field(description="Papel do participante neste vínculo.")
    start_at: datetime = Field(description="Início do vínculo.")
    end_at: datetime | None = Field(description="Fim do vínculo, se já encerrado.")
    created_at: datetime = Field(description="Data e hora de criação do registro.")
    updated_at: datetime | None = Field(description="Última atualização, se houve.")

    @classmethod
    def de_model(cls, vinculo: Vinculo) -> "VinculoResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(vinculo)
