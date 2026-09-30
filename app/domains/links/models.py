"""Models SQLAlchemy do domínio links.

Vínculo é o elo entre uma pessoa (participante) e uma organização: guarda o papel da
pessoa ali, o tipo do vínculo e o período. A mesma pessoa em duas organizações tem dois
vínculos, e cada vínculo tem o próprio login (`user.link_id`, em `users/models.py`).

`participant_id` tem `ForeignKey` para `participants` desde a integração da sprint 2
(CREED-47). `organization_id` e `department_id` seguem UUIDs soltos: `Organization` e
`Department` ainda não têm tabela, e as FKs deles entram com a CREED-38 e a CREED-39.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LinkType(enum.Enum):
    """Tipo do vínculo entre a pessoa e a organização."""

    EMPREGO = "emprego"
    MENTORIA = "mentoria"
    ACADEMICO = "academico"
    PESSOAL = "pessoal"


class Roles(enum.Enum):
    """Papéis do vínculo, na lista fixada pela P-006.

    É a única fonte do papel de acesso na plataforma: `user` não guarda papel.
    """

    ADMIN = "admin"
    GESTOR = "gestor"
    RESPONDENTE = "respondente"


class Link(Base):
    __tablename__ = "links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", name="fk_links_participant_id_participants"),
        nullable=False,
        index=True,
    )

    # FK para Organization — tabela ainda não criada (CREED-38)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # FK para Department — tabela ainda não criada (CREED-39)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    type: Mapped[LinkType] = mapped_column(Enum(LinkType), nullable=False)

    role: Mapped[Roles] = mapped_column(Enum(Roles), nullable=False)

    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
