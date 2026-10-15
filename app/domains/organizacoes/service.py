"""Regra de negócio do domínio organizacoes (ADR-0004).

Esta camada não conhece HTTP nem detalhes de ORM. Documento é de outro domínio:
a pergunta "ele existe?" vai ao `DocumentService`, nunca ao model de `documents`
— o mesmo caminho de `participants/service.py`.

Quem pode o quê (CREED-38):
- `admin` cadastra, lista, lê e altera qualquer organização. Restringir cadastro,
  listagem e alteração a `admin` é do router (`require_role`).
- `gestor` só lê a própria organização. Essa regra mora aqui, porque compara o
  recurso com quem pede (P-033, a mesma regra de `forms`).
"""

import uuid

from app.domains.documents.service import DocumentService
from app.domains.organizacoes.models import Organization
from app.domains.organizacoes.repository import OrganizationRepository
from app.domains.organizacoes.schemas import OrganizationCreate, OrganizationUpdate
from app.shared.enums import RecordStatus
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

ADMIN = "admin"


def _documento_em_uso(document_id: uuid.UUID) -> ConflictError:
    return ConflictError(f"O documento {document_id} já pertence a outra organização")


class OrganizationService:
    def __init__(
        self, repository: OrganizationRepository, documents: DocumentService
    ) -> None:
        self.repository = repository
        self.documents = documents

    async def create(self, request: OrganizationCreate) -> Organization:
        if not await self.documents.document_exists(request.document_id):
            raise ValidationError(f"Documento {request.document_id} não encontrado")

        if await self.repository.get_by_document_id(request.document_id) is not None:
            raise _documento_em_uso(request.document_id)

        organization = Organization(
            name=request.name,
            address=request.address,
            document_id=request.document_id,
            status=RecordStatus.ACTIVE,
        )
        created = await self.repository.create(organization)

        # `None`: outro cadastro ligou o mesmo documento entre a checagem acima e
        # a gravação. Para quem chamou, é o mesmo conflito.
        if created is None:
            raise _documento_em_uso(request.document_id)

        return created

    async def get(
        self, organization_id: uuid.UUID, *, role: str, own_organization_id: uuid.UUID
    ) -> Organization:
        """`role` e `own_organization_id` são de quem pede.

        A checagem de acesso vem antes da busca: um `gestor` que pede uma
        organização alheia recebe 403 mesmo se ela não existir, para a resposta
        não revelar quais organizações existem.
        """
        if role != ADMIN and organization_id != own_organization_id:
            raise ForbiddenError("Sem acesso a organização de outro vínculo")

        organization = await self.repository.get_by_id(organization_id)
        if organization is None:
            raise NotFoundError(f"Organização {organization_id} não encontrada")

        return organization

    async def list_page(
        self, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Organization], int]:
        """Uma página e o total. `pagina` começa em 1."""
        offset = (pagina - 1) * tamanho_pagina
        itens = await self.repository.list_page(offset, tamanho_pagina)
        total = await self.repository.count()
        return itens, total

    async def update(
        self, organization_id: uuid.UUID, request: OrganizationUpdate
    ) -> Organization:
        """Altera só os campos enviados: o que não veio no PATCH fica como está."""
        organization = await self.repository.get_by_id(organization_id)
        if organization is None:
            raise NotFoundError(f"Organização {organization_id} não encontrada")

        for campo, valor in request.model_dump(exclude_unset=True).items():
            setattr(organization, campo, valor)

        return await self.repository.save(organization)
