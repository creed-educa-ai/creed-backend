"""Models SQLAlchemy do domínio organizacoes.

Organização é a instituição parceira à qual as pessoas se vinculam (`Link`,
em `links/models.py`). O documento dela (CNPJ, NIPC, VAT) mora em `documents`,
e quem aponta é a organização ([C3]): um documento por organização, no máximo.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.enums import RecordStatus


class Organization(Base):
    __tablename__ = "organizations"

    __table_args__ = (
        UniqueConstraint("document_id", name="uq_organizations_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 🟡 Premissa P-021 — texto livre, sem CEP/logradouro separados.
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), nullable=False, default=RecordStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
