"""Regra de negócio do domínio documents (ADR-0004).

Responde se um documento existe, que é o que `participants` e `organizacoes`
precisam para aceitar um `document_id` (P-021), lê documentos por lista de ids,
para `organizacoes` mostrar o número de cada um, e cria o CPF ou CNPJ do cadastro
público de empresa (`OrganizationService.sign_up`). Apaga o documento da empresa
excluída (E-6). Editar documento não tem rota.
"""

import uuid

from app.domains.documents.models import DocType, Document
from app.domains.documents.repository import DocumentRepository
from app.shared.exceptions import ConflictError

DOCUMENT_ALREADY_REGISTERED = "Já existe um cadastro com este documento"


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

    async def create_brazilian_document(self, number: str) -> Document:
        """Cria um CPF (11 dígitos) ou um CNPJ (14) a partir do número já limpo.

        Quem limpa e confere os dígitos é o schema de entrada
        (`OrganizationSignUp`); aqui o tamanho só escolhe o tipo. Outro tamanho é
        erro de quem chamou, não do usuário, e levanta `ValueError` (500).

        🟡 Premissa P-076 — o mesmo tipo e número já cadastrados é 409, sem dizer de
        quem é o documento.
        """
        if len(number) == 11:
            doc_type = DocType.CPF
        elif len(number) == 14:
            doc_type = DocType.CNPJ
        else:
            raise ValueError(f"Número com {len(number)} caracteres não é CPF nem CNPJ")

        if await self.repository.get_by_type_value(doc_type, number) is not None:
            raise ConflictError(DOCUMENT_ALREADY_REGISTERED)

        created = await self.repository.create(Document(type=doc_type, value=number))

        # `None`: outro cadastro gravou o mesmo documento entre a checagem acima e
        # a gravação. Para quem chamou, é o mesmo conflito.
        if created is None:
            raise ConflictError(DOCUMENT_ALREADY_REGISTERED)

        return created

    async def delete_document(self, document_id: uuid.UUID) -> None:
        """Apaga o documento na exclusão de empresa (E-6).

        Sem regra: quem chama já apagou a organização e conferiu que nenhum
        participante aponta para ele (`ParticipantService.document_in_use`).
        """
        await self.repository.delete_by_id(document_id)
