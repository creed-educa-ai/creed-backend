"""Models SQLAlchemy do domínio documentos.

Documentos de identificação vinculados a um usuário (CPF, CNPJ,
passaporte e equivalentes europeus).
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TipoDocumento(enum.Enum):
    CPF = "CPF"
    CNPJ = "CNPJ"
    NIF = "NIF"
    NIPC = "NIPC"
    PASSAPORTE = "PASSAPORTE"
    VAT_EU = "VAT_EU"
    OUTRO = "OUTRO"


class Documento(Base):
    __tablename__ = "documentos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    tipo: Mapped[TipoDocumento] = mapped_column(
        Enum(TipoDocumento, name="tipo_documento"), nullable=False
    )
    valor: Mapped[str] = mapped_column(String(100), nullable=False)
    pais_emissor: Mapped[str | None] = mapped_column(String(2), nullable=True)
