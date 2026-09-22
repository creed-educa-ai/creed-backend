"""Models SQLAlchemy do domínio respostas.

//comentario sobre esse domínio.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FormResponseStatus(enum.Enum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"


class FormResponse(Base):
    __tablename__ = "form_responses"

    __table_args__ = (
        UniqueConstraint(
            "form_id",
            "vinculo_id",
            name="uq_form_responses_form_id_vinculo_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # FK para Form — tabela ainda não criada
    form_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # FK para Vinculo — tabela ainda não criada
    vinculo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    status: Mapped[FormResponseStatus] = mapped_column(
        Enum(FormResponseStatus),
        nullable=False,
        default=FormResponseStatus.IN_PROGRESS,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
