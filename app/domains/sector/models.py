"""Models SQLAlchemy do domínio sector.

Os setores especificam a relação Vínculo entre participante e organização,
explicando a qual setor em específico daquela organização, aquele participante
faz parte naquela organização.
"""

import enum
import uuid

from sqlalchemy import Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SectorType(enum.Enum):
    MARKETING = "marketing"
    FINANCIAL = "financial"
    ADMINISTRATIVE = "administrative"
    HUMAN_RESOURCES = "human_resources"
    TECHNOLOGY = "technology"


class Sector(Base):
    __tablename__ = "sector"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    type: Mapped[SectorType] = mapped_column(
        Enum(SectorType, name="sector_type"),
        nullable=False,
    )
