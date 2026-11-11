"""Schemas Pydantic do domínio dashboards (ADR-002, secao 2.3)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.shared.enums import Prisma


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
