"""Acesso a dados do domínio documents.

Esta camada NÃO contém regra de negócio: só queries.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.models import Document


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def list_by_ids(self, document_ids: list[uuid.UUID]) -> list[Document]:
        """Os documentos com esses ids, numa consulta só. Id inexistente não vem."""
        result = await self.db.execute(
            select(Document).where(Document.id.in_(document_ids))
        )
        return list(result.scalars().all())
