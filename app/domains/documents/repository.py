"""Acesso a dados do domínio documents.

Esta camada NÃO contém regra de negócio: só queries. Quem decide o que fazer com
um `None` é o service.

`create` devolve `None` quando a constraint única de tipo e número recusa a
gravação — o mesmo formato de `organizacoes/repository.py`. Não é decisão de
negócio: é o banco fechando a corrida que a checagem do service não fecha.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.models import DocType, Document


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def get_by_type_value(self, doc_type: DocType, value: str) -> Document | None:
        result = await self.db.execute(
            select(Document).where(Document.type == doc_type, Document.value == value)
        )
        return result.scalar_one_or_none()

    async def list_by_ids(self, document_ids: list[uuid.UUID]) -> list[Document]:
        """Os documentos com esses ids, numa consulta só. Id inexistente não vem."""
        result = await self.db.execute(
            select(Document).where(Document.id.in_(document_ids))
        )
        return list(result.scalars().all())

    async def create(self, document: Document) -> Document | None:
        """Cria um documento no banco.

        Devolve `None` se o mesmo tipo e número foram gravados entre a checagem do
        service e este `flush()` — dois cadastros simultâneos, sem lock, fechados
        pela constraint única.
        """
        self.db.add(document)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_documents_type_value" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(document)
        return document
