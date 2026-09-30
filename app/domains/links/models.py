"""Models SQLAlchemy do domínio links.

Vínculo é o elo entre uma pessoa (participante) e uma organização: guarda o papel da
pessoa ali, o tipo do vínculo e o período. A mesma pessoa em duas organizações tem dois
vínculos, e cada vínculo tem o próprio login (`user.link_id`, em `users/models.py`).

`participant_id`, `organization_id` e `department_id` são UUIDs soltos, sem `ForeignKey`.
`Organization` e `Department` ainda não têm tabela. `Participant` tem (`participants`,
desde o PR #28), mas a FK dele também fica para a amarração, junto com as outras duas: ela
exige o seed criar o participante de dev e o `POST` de vínculo conferir se o participante
existe, e isso é escopo que a CREED-32 não previu.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
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

    # FK para `participants` — a tabela existe, a FK entra na amarração (ver docstring)
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # FK para Organization — tabela ainda não criada
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # FK para Department — tabela ainda não criada
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
