"""Models SQLAlchemy do domínio questions.

Uma pergunta pertence a um instrumento (`instrument_id`), e não ao formulário: o
formulário é um período (quando e para quem), e todo período aplica as mesmas
perguntas. Hoje existe um instrumento só, o CREED (`CREED_INSTRUMENT_ID`), que entra
por migration de dados. Antes de editar, remover ou acrescentar pergunta que já tem
resposta gravada, crie um instrumento novo: mudar a pergunta no lugar muda o passado.

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
    """Seção do formulário original da cliente; o front desenha uma aba por seção.

    As seções de S2 a S8 são as das dimensões da Matriz CREED, e S9 (Propostas e
    Recomendações) é a das perguntas abertas. Os itens 1 a 11 do formulário são o
    perfil demográfico do onboarding, fora do instrumento. Fecha a P-020 e a P-023.
    """

    S2 = "S2"
    S4 = "S4"
    S5A = "S5A"
    S5B = "S5B"
    S6 = "S6"
    S7 = "S7"
    S8 = "S8"
    S9 = "S9"


class QuestionLang(enum.Enum):
    """Idiomas de tradução. O Português vive em Question.text / QuestionOption.label."""

    EN = "en"
    ES = "es"


class Instrument(Base):
    """O conjunto de perguntas que um período aplica."""

    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Question(Base):
    __tablename__ = "questions"

    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "order_index",
            name="uq_questions_instrument_id_order_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("instruments.id", name="fk_questions_instrument_id_instruments"),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)

    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    type: Mapped[QuestionType] = mapped_column(Enum(QuestionType), nullable=False)

    # Sem índice: o filtro por seção sempre vem junto de instrument_id, que já indexa.
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

    # Ordenada no banco: o `order_by` vira ORDER BY na consulta do selectinload.
    options: Mapped[list["QuestionOption"]] = relationship(
        back_populates="question",
        order_by="QuestionOption.order_index",
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

    question: Mapped["Question"] = relationship(back_populates="options")

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
    "Instrument",
    "Prisma",
    "Question",
    "QuestionLang",
    "QuestionOption",
    "QuestionOptionTranslation",
    "QuestionSection",
    "QuestionTranslation",
    "QuestionType",
]
