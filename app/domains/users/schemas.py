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
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr


class UserCreate(UserBase):
    """Payload de criação.

    Sem senha: credencial é do Keycloak (P-012). O que atravessa é o
    `keycloak_id`, o `sub` do JWT do usuário já provisionado no realm.

    Sem `role`: o papel vem do vínculo, não do payload — `contrato-api.md` é
    explícito ("mandar `role` no POST é sintoma de ter entendido o modelo ao
    contrário"). Até `Vinculo` existir, vale o default do model.
    """

    keycloak_id: uuid.UUID


class UserResponse(UserBase):
    """Representação de saída, na forma do `User` do contrato-api.md.

    `keycloak_id` fica de fora de propósito: é o elo interno com o realm, e o
    contrato não o expõe.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: RecordStatus
    role: UserRole
    created_at: datetime

    @classmethod
    def de_model(cls, user: User) -> "UserResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(user)
