"""Acesso a dados do domínio de links.

Esta camada NÃO contém regra de negócio: só queries e agregações.
Agregação pesada é empurrada para o Postgres, nunca feita em memória.

Leitura entre domínios (ADR-0004, item 4, e o adendo da CREED-6910): o membro
(`get_member`) é o vínculo lido junto com o nome do participante, o e-mail do login e
o tipo do setor, numa consulta só, com JOIN em `participants`, `user` e
`departments`. Aqui só se LÊ essas tabelas: a escrita fora de `links` continua no
service do dono (o setor novo é do `DepartmentService.get_or_create`). Declarado também
em `LEITURA_ENTRE_DOMINIOS`, em `tests/test_arquitetura.py`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.department.models import Department
from app.domains.links.models import Link
from app.domains.participants.models import Participant
from app.domains.users.models import User
from app.shared.enums import DepartmentType


class LinkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(self, link: Link) -> Link:
        """Grava um vínculo no banco."""
        self.db.add(link)
        await self.db.flush()
        await self.db.refresh(link)
        return link

    async def get_by_id(self, link_id: uuid.UUID) -> Link | None:
        result = await self.db.execute(select(Link).where(Link.id == link_id))
        return result.scalar_one_or_none()

    async def get_member(
        self, organization_id: uuid.UUID, link_id: uuid.UUID
    ) -> tuple[Link, str, str | None, DepartmentType | None] | None:
        """O vínculo, o nome da pessoa, o e-mail do login e o tipo do setor.

        `None` se o vínculo não existe ou é de outra organização: o filtro pelos
        dois ids não distingue os casos, de propósito.

        O login e o setor entram por LEFT JOIN: vínculo criado sem convite não tem
        login (e-mail `None`), e vínculo sem setor tem `department_id` nulo. Cada
        vínculo tem no máximo um login (`user.link_id` é único), então a consulta
        devolve no máximo uma linha.
        """
        result = await self.db.execute(
            select(Link, Participant.name, User.email, Department.type)
            .join(Participant, Participant.id == Link.participant_id)
            .outerjoin(User, User.link_id == Link.id)
            .outerjoin(Department, Department.id == Link.department_id)
            .where(Link.id == link_id, Link.organization_id == organization_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row.tuple()

    async def save(self, link: Link) -> Link:
        """Grava as alterações de um vínculo já carregado pela sessão.

        O `refresh` relê o `updated_at`, que o banco preenche no UPDATE
        (`onupdate=func.now()` no model).
        """
        await self.db.flush()
        await self.db.refresh(link)
        return link
