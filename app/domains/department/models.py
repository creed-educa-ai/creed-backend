"""Models SQLAlchemy do domínio department.

Os departamentos pertencem a uma organização e especificam a qual setor
um participante está vinculado.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DepartmentType(enum.Enum):
    MARKETING = "Marketing"
    FINANCEIRO = "Financeiro"
    ADMINISTRATIVO = "Administrativo"
    RECURSOS_HUMANOS = "RecursosHumanos"
    TECNOLOGIA_INFORMACAO = "TecnologiaInformacao"


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "type",
            name="uq_departments_organization_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id", name="fk_departments_organization_id_organizations"
        ),
        nullable=False,
    )

    type: Mapped[DepartmentType] = mapped_column(
        Enum(DepartmentType, name="department_type"),
        nullable=False,
    )
