"""Schemas Pydantic do domínio dashboards (ADR-002, secao 2.3)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.dashboards.models import Dashboard
from app.shared.enums import Prisma


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


class MetricCardRead(BaseModel):
    """Representação de um card de métrica (Destaque, Oportunidade ou Mais Comum)."""

    model_config = ConfigDict(from_attributes=True)

    rotulo: str = Field(
        ..., description="Rótulo da métrica (ex: Destaque, Oportunidade, Mais Comum)"
    )
    titulo: str = Field(..., description="Nome de exibição do prisma")
    valor: float = Field(..., description="Pontuação do prisma na escala 0 a 100")
    descricao: str = Field(..., description="Texto descritivo do significado da métrica")
    prisma: Prisma


class CompanySummaryRead(BaseModel):
    """Resumo consolidado do dashboard da empresa (ResumoCards e Radar)."""

    model_config = ConfigDict(from_attributes=True)

    form_id: uuid.UUID
    organization_id: uuid.UUID
    nome_empresa: str
    concluidos: int = Field(..., ge=0, description="Total de questionários concluídos")
    convidados: int = Field(..., ge=0, description="Total de membros convidados")
    taxa_conclusao: int = Field(
        ..., ge=0, le=100, description="Taxa de conclusão percentual"
    )
    destaque: MetricCardRead
    oportunidade: MetricCardRead
    mais_comum: MetricCardRead
    scores: dict[str, float] = Field(
        ..., description="Médias consolidadas dos 5 prismas na escala 1 a 5"
    )
    scores_100: dict[str, float] = Field(
        ..., description="Médias consolidadas dos 5 prismas na escala 0 a 100"
    )
