"""Models SQLAlchemy do domínio vinculos.

Vínculo é o elo entre uma pessoa (participante) e uma organização: guarda o papel da
pessoa ali, o tipo do vínculo e o período. A mesma pessoa em duas organizações tem dois
vínculos, e cada vínculo tem o próprio login (`user.vinculo_id`, em `users/models.py`).

`Participant`, `Organization` e `Setor` ainda não têm tabela — por isso
`participant_id`, `organization_id` e `setor_id` são UUIDs soltos, sem `ForeignKey`.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VincType(enum.Enum):
    """Tipo do vínculo entre a pessoa e a organização."""

    EMPREGO = "emprego"
    MENTORIA = "mentoria"
    ACADEMICO = "academico"
    PESSOAL = "pessoal"


class Roles(enum.Enum):
    """Papéis do vínculo, na lista fixada pela P-006.

    Duplica os valores de `UserRole`, em `users/models.py`, porque um domínio não
    importa model de outro (`test_dominio_nao_importa_dominio`). A duplicação dura
    até a CREED-32/task 6, que apaga `UserRole` de vez.
    """

    ADMIN = "admin"
    GESTOR = "gestor"
    RESPONDENTE = "respondente"


class Vinculo(Base):
    __tablename__ = "vinculos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # FK para Participant — tabela ainda não criada
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # FK para Organization — tabela ainda não criada
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # FK para Setor — tabela ainda não criada
    setor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    type: Mapped[VincType] = mapped_column(Enum(VincType), nullable=False)

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
