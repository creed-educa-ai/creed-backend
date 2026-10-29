"""Schemas Pydantic do domínio users.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`, e não no
router: o schema já conhece a forma do model (`from_attributes=True`), enquanto o
router não pode conhecer (ADR-0004, item 7).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.domains.users.models import User
from app.shared.enums import LinkType, RecordStatus, Roles
from app.shared.validators import sem_caractere_de_controle


class UserBase(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=200,
        description="Nome completo do usuário.",
        examples=["Pessoa Exemplo"],
    )
    email: EmailStr = Field(
        description="E-mail único usado para identificar o usuário.",
        examples=["pessoa@exemplo.com"],
    )


class UserCreate(UserBase):
    """Payload de criação.

    Sem senha: credencial é do Keycloak (P-012), e a pessoa a define pelo link do
    convite. Sem `keycloak_id`: quem cria o usuário no realm é o back, que grava o
    id que o Keycloak devolve (CREED-23.8). Um `keycloak_id` que ainda chegue no
    corpo é ignorado, como qualquer campo que o schema não declara.

    Sem `role`: o papel vem do vínculo, não do payload — `contrato-api.md` é
    explícito ("mandar `role` no POST é sintoma de ter entendido o modelo ao
    contrário"). `link_id` é obrigatório (P-008: todo login nasce de um
    vínculo), e é o service quem confere se ele existe e se já não está em uso.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Pessoa Exemplo",
                    "email": "pessoa@exemplo.com",
                    "link_id": "3f9a2b1c-4d5e-4f6a-8b7c-9d0e1f2a3b4c",
                }
            ]
        }
    )

    link_id: uuid.UUID = Field(
        description="Vínculo que dá o papel e a organização deste login.",
        examples=["3f9a2b1c-4d5e-4f6a-8b7c-9d0e1f2a3b4c"],
    )

    @field_validator("name")
    @classmethod
    def _sem_caractere_de_controle(cls, name: str) -> str:
        """Só na entrada: a saída devolve o que está gravado."""
        return sem_caractere_de_controle(name)


class MemberInvite(UserBase):
    """Payload do convite de membro (`POST /organizations/{organization_id}/members`).

    Uma chamada cria participante, vínculo e usuário (D8). Sem `link_id`, ao
    contrário do `UserCreate`: o vínculo nasce aqui, na organização do endereço, com o
    papel e o tipo deste corpo.

    Espaços nas pontas saem antes da validação, como no `ParticipantCreate`: o mesmo
    nome vai para o participante e para o usuário, e sem isso os dois gravariam nomes
    diferentes.

    🟡 Premissa P-046 — o nome vai para o participante e para o usuário; o Keycloak
    recebe só o e-mail.
    🟡 Premissa P-047 — sem `type`, o vínculo é `emprego`.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "name": "Pessoa Exemplo",
                    "email": "pessoa@exemplo.com",
                    "role": "gestor",
                    "type": "emprego",
                }
            ]
        },
    )

    role: Roles = Field(
        description=(
            "Papel do vínculo novo. O gestor só convida como gestor ou respondente."
        ),
        examples=["gestor"],
    )
    type: LinkType = Field(
        default=LinkType.EMPREGO,
        description="Tipo do vínculo novo. Sem o campo, `emprego`.",
        examples=["emprego"],
    )

    @field_validator("name")
    @classmethod
    def _sem_caractere_de_controle(cls, name: str) -> str:
        """Só na entrada: a saída devolve o que está gravado."""
        return sem_caractere_de_controle(name)


class UserResponse(UserBase):
    """Representação de saída, na forma do `User` do contrato-api.md.

    `keycloak_id` fica de fora de propósito: é o elo interno com o realm, e o
    contrato não o expõe.

    `role` é `str`, não `Roles`: o papel de saída vem do `Link`, e este
    schema não pode importar `app.domains.links.models` (`schemas.py` não
    está entre os submódulos de composição de `tests/test_arquitetura.py`).
    A sessão de login (`UserSessionResponse.role`) já segue essa mesma forma.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d40b7a55-b9cc-4b78-ae5d-ab325fd655e2",
                    "name": "Pessoa Exemplo",
                    "email": "pessoa@exemplo.com",
                    "status": "active",
                    "role": "respondente",
                    "link_id": "3f9a2b1c-4d5e-4f6a-8b7c-9d0e1f2a3b4c",
                    "organization_id": "8f14e45f-ceea-467e-adde-3f81905dbc1c",
                    "created_at": "2026-09-22T14:30:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador do usuário na plataforma.")
    status: RecordStatus = Field(description="Estado de acesso do usuário.")
    role: str = Field(description="Papel do usuário, lido do vínculo dele.")
    link_id: uuid.UUID = Field(description="Vínculo que dá o papel a este login.")
    organization_id: uuid.UUID = Field(description="Organização do vínculo.")
    created_at: datetime = Field(description="Data e hora de criação do usuário.")

    @classmethod
    def de_model(
        cls,
        user: User,
        *,
        role: str,
        link_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> "UserResponse":
        """Monta a saída a partir do usuário e do papel/organização do vínculo.

        `role` e `organization_id` não vêm de `user`: quem os sabe é o
        `Link`, e este schema não importa a classe dele (spec, "Abordagem
        técnica", item 9). Quem chama — o service, que já tem o `Link` em
        mãos — decide os valores.
        """
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            status=user.status,
            role=role,
            link_id=link_id,
            organization_id=organization_id,
            created_at=user.created_at,
        )
