"""Models SQLAlchemy do domínio forms.

`organization_id` tem `ForeignKey` para `organizations` desde a integração da
sprint 3: a CREED-47 a deixou para quando a tabela existisse (D1).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FormStatus(enum.Enum):
    """Status de um Formulário."""

    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"


class Form(Base):
    __tablename__ = "form"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_form_organization_id_organizations"),
        nullable=False,
        index=True,
    )

    status: Mapped[FormStatus] = mapped_column(
        Enum(FormStatus), nullable=False, default=FormStatus.DRAFT
    )

    # O período do questionário. Nulos no formulário que ainda não tem período,
    # como o de demonstração do seed.
    opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # O público: nulo é a organização inteira; preenchido, só a pessoa deste
    # vínculo.
    link_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("links.id", name="fk_form_link_id_links"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
