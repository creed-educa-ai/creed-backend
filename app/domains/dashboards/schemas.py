"""Schemas Pydantic do domínio dashboards.

Separados por direção: entrada e saída.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.dashboards.models import Dashboard


class DashboardCreate(BaseModel):
    """Dados necessários para criar um dashboard."""

    user_id: uuid.UUID = Field(
        description="Identificador do usuário associado ao dashboard."
    )
    form_id: uuid.UUID = Field(
        description="Identificador da resposta de formulário associada ao dashboard."
    )
    is_private: bool = Field(description="Indica se o dashboard é privado.")


class DashboardResponse(BaseModel):
    """Representação de saída de um dashboard."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="Identificador do dashboard.")
    user_id: uuid.UUID = Field(
        description="Identificador do usuário associado ao dashboard."
    )
    form_id: uuid.UUID = Field(
        description="Identificador da resposta de formulário associada ao dashboard."
    )
    is_private: bool = Field(description="Indica se o dashboard é privado.")
    created_at: datetime = Field(description="Data e hora de criação do dashboard.")

    @classmethod
    def de_model(cls, dashboard: Dashboard) -> "DashboardResponse":
        """Monta a saída a partir do model SQLAlchemy."""
        return cls(
            id=dashboard.id,
            user_id=dashboard.user_id,
            form_id=dashboard.form_id,
            is_private=dashboard.is_private,
            created_at=dashboard.created_at,
        )
