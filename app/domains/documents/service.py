"""Regra de negócio do domínio documents (ADR-0004).

Por enquanto só responde se um documento existe: é o que `participants` precisa
para aceitar um `document_id` (P-021). Criar e editar documento não tem rota
nesta entrega.
"""

import uuid

from app.domains.documents.repository import DocumentRepository


class DocumentService:
    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    async def document_exists(self, document_id: uuid.UUID) -> bool:
        return await self.repository.get_by_id(document_id) is not None
