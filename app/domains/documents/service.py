"""Regra de negócio do domínio documents (ADR-0004).

Responde se um documento existe, que é o que `participants` e `organizacoes`
precisam para aceitar um `document_id` (P-021), e lê documentos por lista de ids,
para `organizacoes` mostrar o número de cada um. Criar e editar documento não tem
rota.
"""

import uuid

from app.domains.documents.models import Document
from app.domains.documents.repository import DocumentRepository


class DocumentService:
    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    async def document_exists(self, document_id: uuid.UUID) -> bool:
        return await self.repository.get_by_id(document_id) is not None

    async def list_by_ids(self, document_ids: list[uuid.UUID]) -> list[Document]:
        """Os documentos desses ids, numa consulta só, em qualquer ordem.

        Quem chama monta o mapa por id: é o que deixa uma página de organizações
        custar uma consulta de documentos, e não uma por organização.
        """
        return await self.repository.list_by_ids(document_ids)
