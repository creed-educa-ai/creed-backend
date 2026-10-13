"""Models SQLAlchemy do domínio insights.

Cada linha é um bloco de análise textual gerado para um formulário
respondido. O motor que produz o texto não mora aqui.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    form_response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "form_responses.id",
            name="fk_insights_form_response_id_form_responses",
        ),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Prisma(enum.Enum):
    """As cinco dimensões de análise do produto, conforme a CREED-53.1.

    Diverge do enum `Prisma` de `app/domains/questions/models.py`
    (CREED-351), cujos valores vêm do `modelo-de-dados.proposta.dbml`. O tipo
    no Postgres é nomeado `insight_prisma` para que os dois possam coexistir
    até que a divergência seja resolvida.
    """

    SEGURANCA_PSICOLOGICA = "seguranca_psicologica"
    LIDERANCA_ADAPTATIVA = "lideranca_adaptativa"
    CULTURA_EMPREENDEDORA = "cultura_empreendedora"
    ADAPTABILIDADE_COGNITIVA = "adaptabilidade_cognitiva"
    NEUROINOVACAO_PRISMA = "neuroinovacao_prisma"


class InsightPrisma(Base):
    __tablename__ = "insight_prismas"

    insight_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "insights.id",
            name="fk_insight_prismas_insight_id_insights",
        ),
        primary_key=True,
    )
    prisma: Mapped[Prisma] = mapped_column(
        Enum(Prisma, name="insight_prisma"),
        primary_key=True,
    )
