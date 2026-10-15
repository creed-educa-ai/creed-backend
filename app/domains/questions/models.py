"""Models SQLAlchemy do domínio questions.

Uma pergunta pertence a um formulário (`form_id`). A `ForeignKey` para `form` entrou
na integração da sprint 2 (CREED-47): as duas tabelas nasceram em paralelo, na CREED-33
e na CREED-35, e só puderam ser ligadas depois de as duas existirem.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.enums import Dimension, Prisma


class QuestionType(enum.Enum):
    """Tipo de resposta esperado pela pergunta (CREED-351)."""

    OBJECTIVE = "objective"
    DESCRIPTIVE = "descriptive"


class QuestionSection(enum.Enum):
    """Bloco da tela em que a pergunta é desenhada.

    🟡 Premissa P-020 — valores provisórios; o time ainda não definiu as seções.
    Confirmar antes de gravar a primeira pergunta real: depois disso, trocar um
    valor é ALTER TYPE + atualização das linhas + troca das chaves de i18n no front.
    """

    PROFILE = "profile"
    ASSESSMENT = "assessment"
    CLOSING = "closing"


class Question(Base):
    __tablename__ = "questions"

    __table_args__ = (
        UniqueConstraint(
            "form_id",
            "order_index",
            name="uq_questions_form_id_order_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    form_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("form.id", name="fk_questions_form_id_form"),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)

    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    type: Mapped[QuestionType] = mapped_column(Enum(QuestionType), nullable=False)

    # Sem índice: o filtro por seção sempre vem junto de form_id, que já indexa.
    section: Mapped[QuestionSection] = mapped_column(
        Enum(QuestionSection), nullable=False
    )

    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    prisma: Mapped[Prisma | None] = mapped_column(Enum(Prisma), nullable=True)

    dimensao: Mapped[Dimension | None] = mapped_column(
        Enum(Dimension, name="dimension"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["Prisma", "Question", "QuestionSection", "QuestionType"]
