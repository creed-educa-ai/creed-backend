"""Models SQLAlchemy do domínio insights.

Cada linha é um pedido de insight e, quando a esteira responde, o texto dele. A
linha nasce `pending` no envio da resposta e é o que o worker despacha ao N8N
(ADR-0010). O motor que produz o texto não mora aqui.

Dois tipos de linha, separados por `form_response_id`:

- **individual**: aponta a resposta enviada (P-042, uma resposta, um insight);
- **da empresa**: `form_response_id` nulo, e só `organization_id` e `form_id` dizem
  de que grupo e de que período é. Nasce na CREED-8013.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.enums import Prisma
from app.shared.languages import DEFAULT_LANGUAGE


class InsightStatus(enum.Enum):
    """Em que ponto da esteira o pedido está (ADR-0010).

    `dispatched` é o pedido que já foi ao N8N e espera a volta. Na leitura, quem
    consome o insight vê `dispatched` como `pending`.
    """

    PENDING = "pending"
    DISPATCHED = "dispatched"
    DONE = "done"
    FAILED = "failed"


class Insight(Base):
    __tablename__ = "insights"

    # O banco grava o NOME do membro ('DONE', 'PENDING'), não o valor: é o que
    # `Enum(InsightStatus)` faz, e o que os literais abaixo precisam usar.
    __table_args__ = (
        # Uma resposta, um insight (P-042). No Postgres, NULL não colide com NULL,
        # então os insights da empresa (sem resposta) não esbarram nesta restrição.
        UniqueConstraint("form_response_id", name="uq_insights_form_response_id"),
        # `done` e `content` andam juntos. Os dois lados do `=` são booleanos e
        # nenhum pode ser NULL (`status` é obrigatório), então o CHECK não passa
        # em branco.
        CheckConstraint(
            "(status = 'DONE') = (content IS NOT NULL)",
            name="ck_insights_done_has_content",
        ),
        # No máximo um insight da empresa esperando por período. É o que deixa o
        # envio gravar com ON CONFLICT DO NOTHING sem que dois envios ao mesmo
        # tempo derrubem um ao outro (CREED-8013).
        Index(
            "uq_insights_organization_pending_per_form",
            "organization_id",
            "form_id",
            unique=True,
            postgresql_where=text("form_response_id IS NULL AND status = 'PENDING'"),
        ),
        CheckConstraint(
            "language IN ('pt-BR', 'en', 'es')",
            name="ck_insights_language",
        ),
        # O worker busca o que está pendente e vencido.
        Index("ix_insights_status_next_attempt_at", "status", "next_attempt_at"),
        # O dashboard da empresa busca o mais recente de (organização, período).
        Index(
            "ix_insights_organization_id_form_id_created_at",
            "organization_id",
            "form_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # No individual, copiada do formulário da resposta; na empresa, é o grupo.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="fk_insights_organization_id_organizations",
        ),
        nullable=False,
    )

    # O período: cada período é um formulário (P-089).
    form_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("form.id", name="fk_insights_form_id_form"),
        nullable=False,
    )

    # Nulo = insight da empresa. A restrição única mora em `__table_args__`.
    form_response_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "form_responses.id",
            name="fk_insights_form_response_id_form_responses",
        ),
        nullable=True,
    )

    status: Mapped[InsightStatus] = mapped_column(
        Enum(InsightStatus),
        nullable=False,
        default=InsightStatus.PENDING,
        server_default=InsightStatus.PENDING.name,
    )

    # Em que língua o texto é escrito: a da tela de quem enviou a resposta. O da
    # empresa fica em pt-BR, porque é um texto só para todos os leitores do período.
    language: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default=DEFAULT_LANGUAGE,
        server_default=DEFAULT_LANGUAGE,
    )

    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    # Quando o worker pode pegar o pedido. No insight da empresa, é também a espera
    # de 30 min que junta os envios de um mesmo pico.
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # O `InsightContent` já validado (insights/schemas.py). Nulo até o `done`.
    # `none_as_null=True`: sem ele, o SQLAlchemy grava o `None` do Python como o
    # valor JSON `null`, que não é NULL para o banco. O CHECK acima recusaria um
    # pedido pendente com `content=None` e aceitaria um `done` sem texto.
    content: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    # De onde saiu o texto, para comparar modelos e versões de prompt.
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    # A data que a tela mostra.
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
