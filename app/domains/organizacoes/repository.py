"""Acesso a dados do domínio organizacoes.

Esta camada NÃO contém regra de negócio: só queries. Quem decide o que fazer com
um `None` é o service.

`create` devolve `None` quando a constraint única de `document_id` recusa a
gravação — o mesmo formato de `participants/repository.py`. Não é decisão de
negócio: é o banco fechando a corrida que a checagem do service não fecha.

A paginação é feita na consulta (`OFFSET`/`LIMIT` e `COUNT`), nunca trazendo
tudo para a memória.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.organizacoes.models import Organization


class OrganizationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        result = await self.db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        return result.scalar_one_or_none()

    async def get_by_document_id(self, document_id: uuid.UUID) -> Organization | None:
        result = await self.db.execute(
            select(Organization).where(Organization.document_id == document_id)
        )
        return result.scalar_one_or_none()

    async def create(self, organization: Organization) -> Organization | None:
        """Cria uma organização no banco.

        Devolve `None` se o documento foi ligado a outra organização entre a
        checagem do service e este `flush()` — dois cadastros simultâneos, sem
        lock, fechados pela constraint única.
        """
        self.db.add(organization)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_organizations_document_id" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(organization)
        return organization

    async def save(self, organization: Organization) -> Organization:
        """Grava as alterações de uma organização já carregada pela sessão."""
        await self.db.flush()
        await self.db.refresh(organization)
        return organization

    async def list_page(self, offset: int, limit: int) -> list[Organization]:
        """Uma página de organizações, por nome. O `id` desempata nomes iguais,
        para a mesma organização não aparecer em duas páginas."""
        result = await self.db.execute(
            select(Organization)
            .order_by(Organization.name, Organization.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(Organization))
        return result.scalar_one()
