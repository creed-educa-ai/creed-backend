"""Models SQLAlchemy do domínio de Users."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RecordStatus(enum.Enum):
    """Enum para o status de um registro."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class UserRole(enum.Enum):
    """Papéis disponíveis para usuários no realm."""

    ADMIN = "admin"
    GESTOR = "gestor"
    RESPONDENTE = "respondente"


class User(Base):
    """Classe responsável pela criação da tabela de usuários."""

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )

    hash_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus),
        nullable=False,
        default=RecordStatus.INACTIVE,
    )

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),
        nullable=False,
        default=UserRole.RESPONDENTE,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
