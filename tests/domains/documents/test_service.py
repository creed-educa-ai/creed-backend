"""Testes do service do domínio documents.

O repository é um dublê em memória: o que se prova é a resposta de
`document_exists`, que é o que `participants` consulta.
"""

import uuid

from app.domains.documents.models import DocType, Document
from app.domains.documents.service import DocumentService


class FakeDocumentRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(self, existentes: list[Document] | None = None) -> None:
        self.itens: list[Document] = list(existentes or [])

    async def get_by_id(self, document_id: uuid.UUID) -> Document | None:
        return next((d for d in self.itens if d.id == document_id), None)


def servico(repository: FakeDocumentRepository) -> DocumentService:
    return DocumentService(repository)  # type: ignore[arg-type]


async def test_documento_cadastrado_existe() -> None:
    documento = Document(id=uuid.uuid4(), type=DocType.CPF, value="000.000.000-00")

    assert await servico(FakeDocumentRepository([documento])).document_exists(
        documento.id
    )


async def test_documento_desconhecido_nao_existe() -> None:
    assert not await servico(FakeDocumentRepository()).document_exists(uuid.uuid4())
