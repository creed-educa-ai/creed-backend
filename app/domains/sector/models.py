"""Models SQLAlchemy do domínio users.

Identidade da plataforma. A credencial em si não mora aqui: quem guarda senha é
o Keycloak (P-012), e o elo entre as duas pontas é o `keycloak_id` — o `sub` do
JWT, que é como se acha o usuário a partir do token sem depender do e-mail.
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
        Enum(SectorType),
        nullable=False,
    )
