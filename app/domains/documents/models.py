"""Models SQLAlchemy do domínio documents.

Documentos de identificação (CPF, CNPJ, passaporte e equivalentes
europeus). Sem coluna de dono, por [C3]: quem aponta é o dono
(`Participant.document_id`, `Organization.document_id`), quando essas
tabelas existirem.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DocType(enum.Enum):
    CPF = "cpf"
    CNPJ = "cnpj"
    NIF = "nif"
    NIPC = "nipc"
    PASSAPORTE = "passaporte"
    VAT_EU = "vat_eu"
    OUTRO = "outro"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("type", "value", name="uq_documents_type_value"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[DocType] = mapped_column(Enum(DocType, name="doc_type"), nullable=False)
    value: Mapped[str] = mapped_column(String(100), nullable=False)
    issuing_country: Mapped[str | None] = mapped_column(
        String(2), nullable=True
    )  # ISO 3166-1
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
