"""Models SQLAlchemy do domínio participants.

O participante é a **pessoa**, e o `user` é o **login**. Pelo modelo do time, a
mesma pessoa em duas organizações tem dois logins e um só participante ([C2]),
e é no participante que as análises se juntam.

Sem `gender` e `address` nesta entrega: gênero é da CREED-40 (demográficos), e
endereço entra quando alguma tela pedir ([C19]).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.enums import RecordStatus


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Mesmo tipo `recordstatus` do `user`: é um enum só no banco ([C6]).
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), nullable=False, default=RecordStatus.ACTIVE
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
