"""Models SQLAlchemy do domínio organizacoes."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    pass


class User(Base):
    """Classe responsável por fazer simulação e criação da tabela user

    Attributes:
        id (uuid.UUID): Chave primária gerada automaticamente pelo sistema
        email (str): Email do Usuário
        hash_password (str): Hash da senha criptografada
        id_link (uuid.UUID): Id do vinculo que esse usuário está linkado.
    """

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False)

    hash_password: Mapped[str] = mapped_column(String(255), nullable=False)

    id_link: Mapped[uuid.UUID] = relationship(
        "Connection", back_populates="user", cascade="all, delete-orphan", lazy="select"
    )
