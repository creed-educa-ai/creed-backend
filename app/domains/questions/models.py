"""Models SQLAlchemy do domínio questions.

Uma pergunta pertence a um formulário (`form_id`). A `ForeignKey` para `form` entrou
na integração da sprint 2 (CREED-47): as duas tabelas nasceram em paralelo, na CREED-33
e na CREED-35, e só puderam ser ligadas depois de as duas existirem.

Textos exibidos ao usuário (`Question.text`, `QuestionOption.label`) ficam em PT (padrão).
Traduções (EN/ES) vivem em `QuestionTranslation` e `QuestionOptionTranslation`.
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class QuestionLang(enum.Enum):
    """Idiomas de tradução. O Português vive em Question.text / QuestionOption.label."""

    EN = "en"
    ES = "es"


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

    translations: Mapped[list["QuestionTranslation"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
    )


class QuestionTranslation(Base):
    __tablename__ = "question_translations"

    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "lang",
            name="uq_question_translations_question_id_lang",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "questions.id",
            name="fk_question_translations_question_id_questions",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    lang: Mapped[QuestionLang] = mapped_column(
        Enum(QuestionLang, name="translation_lang"), nullable=False
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    question: Mapped["Question"] = relationship(back_populates="translations")


class QuestionOption(Base):
    __tablename__ = "question_options"

    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "order_index",
            name="uq_question_options_question_id_order_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", name="fk_question_options_question_id_questions"),
        nullable=False,
        index=True,
    )

    label: Mapped[str] = mapped_column(Text, nullable=False)

    value: Mapped[str] = mapped_column(Text, nullable=False)

    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    translations: Mapped[list["QuestionOptionTranslation"]] = relationship(
        back_populates="option",
        cascade="all, delete-orphan",
    )


class QuestionOptionTranslation(Base):
    __tablename__ = "question_option_translations"

    __table_args__ = (
        UniqueConstraint(
            "option_id",
            "lang",
            name="uq_question_option_translations_option_id_lang",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    option_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "question_options.id",
            name="fk_question_option_translations_option_id_question_options",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    lang: Mapped[QuestionLang] = mapped_column(
        Enum(QuestionLang, name="translation_lang"), nullable=False
    )

    label: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    option: Mapped["QuestionOption"] = relationship(back_populates="translations")


__all__ = [
    "Prisma",
    "Question",
    "QuestionLang",
    "QuestionOption",
    "QuestionOptionTranslation",
    "QuestionSection",
    "QuestionTranslation",
    "QuestionType",
]
