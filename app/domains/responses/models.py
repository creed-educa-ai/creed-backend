"""Models SQLAlchemy do domínio respostas.

//comentario sobre esse domínio.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, UniqueConstraint, func
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

    form_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("form.id", name="fk_form_responses_form_id_form"),
        nullable=False,
        index=True,
    )

    # Aponta para `links`: o vínculo virou `Link` no código (ADR-0005), mas a coluna
    # manteve o nome antigo. Renomear pede migration própria (P-029, refutada).
    vinculo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("links.id", name="fk_form_responses_vinculo_id_links"),
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


class Answer(Base):
    __tablename__ = "answer"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    form_response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("form_responses.id", name="fk_answer_form_response_id_form_responses"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", name="fk_answer_question_id_questions"),
        nullable=False,
        index=True,
    )
    # Sem FK: a tabela de alternativas nasce com a CREED-37.
    option_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
