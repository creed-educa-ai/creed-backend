"""Models SQLAlchemy do domínio users.

Identidade da plataforma. A credencial em si não mora aqui: quem guarda senha é
o Keycloak (P-012), e o elo entre as duas pontas é o `keycloak_id` — o `sub` do
JWT, que é como se acha o usuário a partir do token sem depender do e-mail.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RecordStatus(enum.Enum):
    """Status de um registro (contrato-api.md: `status`)."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class UserRole(enum.Enum):
    """Papéis do realm, na lista fixada pela P-006."""

    ADMIN = "admin"
    GESTOR = "gestor"
    RESPONDENTE = "respondente"


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # `sub` do JWT. Único porque um usuário do realm é um usuário daqui.
    keycloak_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # 🟡 Premissa P-013 — o acesso nasce `active`. Confirmar na próxima reunião.
    # Quem aplica a premissa é o service; este default é a rede de quem construir
    # um User por fora dele (a coluna é NOT NULL).
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), nullable=False, default=RecordStatus.ACTIVE
    )

    # Enquanto `Vinculo` não existe, o papel é coluna e nasce no menor privilégio
    # (P-008: o vínculo é quem manda, e ele ainda não tem tabela).
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), nullable=False, default=UserRole.RESPONDENTE
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
