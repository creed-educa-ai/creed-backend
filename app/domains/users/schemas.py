"""Schemas Pydantic do domínio users.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`, e não no
router: o schema já conhece a forma do model (`from_attributes=True`), enquanto o
router não pode conhecer (ADR-0004, item 7).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domains.users.models import RecordStatus, User, UserRole


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

    Sem senha: credencial é do Keycloak (P-012). O que atravessa é o
    `keycloak_id`, o `sub` do JWT do usuário já provisionado no realm.

    Sem `role`: o papel vem do vínculo, não do payload — `contrato-api.md` é
    explícito ("mandar `role` no POST é sintoma de ter entendido o modelo ao
    contrário"). Até `Vinculo` existir, vale o default do model.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Pessoa Exemplo",
                    "email": "pessoa@exemplo.com",
                    "keycloak_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
                }
            ]
        }
    )

    keycloak_id: uuid.UUID = Field(
        description="Identificador `sub` do usuário provisionado no Keycloak.",
        examples=["e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339"],
    )


class UserResponse(UserBase):
    """Representação de saída, na forma do `User` do contrato-api.md.

    `keycloak_id` fica de fora de propósito: é o elo interno com o realm, e o
    contrato não o expõe.
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
                    "created_at": "2026-09-22T14:30:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador do usuário na plataforma.")
    status: RecordStatus = Field(description="Estado de acesso do usuário.")
    role: UserRole = Field(description="Papel atual do usuário.")
    created_at: datetime = Field(description="Data e hora de criação do usuário.")

    @classmethod
    def de_model(cls, user: User) -> "UserResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(user)
