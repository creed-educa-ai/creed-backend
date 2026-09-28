"""Models SQLAlchemy do domínio questions.

Uma pergunta pertence a um formulário (`form_id`), sem chave estrangeira: a tabela
de formulários nasce em paralelo, na CREED-33, e pode não existir ainda quando esta
migration rodar. A ligação por FK é tarefa futura, de amarração entre os domínios.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


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


class Prisma(enum.Enum):
    """As cinco dimensões de análise do produto (CREED-351).

    Identificador Python em inglês (ADR-0005); o valor de cada membro — o que
    trafega no JSON — é o termo em português já fixado no modelo de dados
    (`context/modelo-de-dados.proposta.dbml`, `Enum Prisma`), que a spec da
    CREED-35 também publica. Corrige a P-021, que tinha traduzido o valor para
    inglês sem checar que o modelo já havia decidido os termos em português.
    """

    HUMAN_PLASTICITY = "plasticidade_humana"
    ENTREPRENEURSHIP = "empreendedorismo"
    MULTICULTURALISM = "multiculturalismo"
    NEUROINNOVATION = "neuroinovacao"
    DECISION_MAKING = "tomada_decisao"


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
        UUID(as_uuid=True), nullable=False, index=True
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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
