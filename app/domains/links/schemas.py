"""Schemas Pydantic do domínio links.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `from_model()`, e não no
router: o schema já conhece a forma do model (`from_attributes=True`), enquanto o
router não pode conhecer (ADR-0004, item 7).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.links.models import Link, LinkType, Roles
from app.shared.enums import DepartmentType


class LinkCreate(BaseModel):
    """Payload de criação.

    Sem `organization_id`: vem da URL (`/organizations/{organization_id}/links`),
    não do corpo — quem monta o `Link` com ele é o service.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "participant_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
                    "department_id": None,
                    "type": "emprego",
                    "role": "gestor",
                }
            ]
        }
    )

    participant_id: uuid.UUID = Field(description="Participante dono do vínculo.")
    department_id: uuid.UUID | None = Field(
        default=None,
        description="Setor da organização, se já existir um na hora do cadastro.",
    )
    type: LinkType = Field(description="Tipo do vínculo com a organização.")
    role: Roles = Field(description="Papel do participante neste vínculo.")


class LinkResponse(BaseModel):
    """Representação de saída, na forma do vínculo no `.dbml`."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d40b7a55-b9cc-4b78-ae5d-ab325fd655e2",
                    "participant_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
                    "organization_id": "8f14e45f-ceea-467e-adde-3f81905dbc1c",
                    "department_id": None,
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
    department_id: uuid.UUID | None = Field(
        description="Setor da organização, se houver."
    )
    type: LinkType = Field(description="Tipo do vínculo com a organização.")
    role: Roles = Field(description="Papel do participante neste vínculo.")
    start_at: datetime = Field(description="Início do vínculo.")
    end_at: datetime | None = Field(description="Fim do vínculo, se já encerrado.")
    created_at: datetime = Field(description="Data e hora de criação do registro.")
    updated_at: datetime | None = Field(description="Última atualização, se houve.")

    @classmethod
    def from_model(cls, link: Link) -> "LinkResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(link)


class MemberDepartmentUpdate(BaseModel):
    """Corpo da troca de setor de um membro.

    `department` é obrigatório: ou um dos cinco setores, ou `null` para tirar o
    setor. Corpo vazio é 422, e não um "não muda nada" silencioso. Campo a mais
    (papel, tipo) também é 422: esta rota só mexe no setor.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"department": "Marketing"}, {"department": None}]
        },
    )

    department: DepartmentType | None = Field(
        description=(
            "Setor do membro, um dos cinco fixos. `null` tira o setor. A empresa que "
            "ainda não tem o setor ganha o cadastro dele na hora."
        )
    )


class MemberResponse(BaseModel):
    """Um membro da organização: o vínculo visto com a pessoa.

    A listagem de membros (M-2) devolve este mesmo schema, acrescido do período.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "link_id": "d40b7a55-b9cc-4b78-ae5d-ab325fd655e2",
                    "name": "Ana Souza",
                    "email": "ana@empresa.com.br",
                    "role": "respondente",
                    "type": "emprego",
                    "department": "Marketing",
                    "updated_at": "2026-11-09T14:00:00Z",
                }
            ]
        }
    )

    link_id: uuid.UUID = Field(description="Identificador do vínculo do membro.")
    name: str = Field(description="Nome da pessoa.")
    email: str | None = Field(
        description="E-mail de acesso. `null` quando o vínculo não tem login."
    )
    role: Roles = Field(description="Papel do membro nesta organização.")
    type: LinkType = Field(description="Tipo do vínculo com a organização.")
    department: DepartmentType | None = Field(description="Setor do membro, se houver.")
    updated_at: datetime | None = Field(
        description="Última alteração do vínculo, se houve."
    )

    @classmethod
    def from_model(
        cls,
        link: Link,
        *,
        name: str,
        email: str | None,
        department: DepartmentType | None,
    ) -> "MemberResponse":
        """Monta a saída a partir do vínculo e do que veio das outras tabelas.

        Nome, e-mail e setor não moram no `Link`: quem chama já os leu (na mesma
        consulta, em `LinkRepository.get_member`) e os passa aqui.
        """
        return cls(
            link_id=link.id,
            name=name,
            email=email,
            role=link.role,
            type=link.type,
            department=department,
            updated_at=link.updated_at,
        )
