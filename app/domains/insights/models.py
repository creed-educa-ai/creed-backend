"""Models SQLAlchemy do domínio insights.

Cada linha é um bloco de análise textual gerado para um formulário
respondido. O motor que produz o texto não mora aqui.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.enums import Prisma


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
        Enum(Prisma),
        primary_key=True,
    )
