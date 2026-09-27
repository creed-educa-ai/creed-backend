"""Models SQLAlchemy do domínio forms."""

import enum
import uuid

from sqlalchemy import Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FormStatus(enum.Enum):
    """Status de um Formulário."""

    DRAFT = "draft"


class Form(Base):
    __tablename__ = "form"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False
    )

    status: Mapped[FormStatus] = mapped_column(
        Enum(FormStatus), nullable=False, default=FormStatus.DRAFT
    )
