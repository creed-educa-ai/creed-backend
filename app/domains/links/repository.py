"""Acesso a dados do domínio de links.

Esta camada NÃO contém regra de negócio: só queries e agregações.
Agregação pesada é empurrada para o Postgres, nunca feita em memória. A escolha do
período de cada membro (`pick_period`, no service) não é agregação: não soma nem
conta, só escolhe um período entre os que valem para a pessoa (spec da CREED-697,
"Abordagem técnica").

Leitura entre domínios (ADR-0004, item 4, e o adendo da CREED-6910): o membro
(`get_member`, `list_members`) é o vínculo lido junto com o nome do participante, o
e-mail do login e o tipo do setor, com JOIN em `participants`, `user` e
`departments`. A lista de membros (CREED-697) lê também `form` (os períodos) e
`form_responses` (quem já enviou). Aqui só se LÊ essas tabelas: a escrita fora de
`links` continua no service do dono (o setor novo é do
`DepartmentService.get_or_create`). Declarado também em `LEITURA_ENTRE_DOMINIOS`, em
`tests/test_arquitetura.py`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.department.models import Department
from app.domains.forms.models import Form
from app.domains.links.models import Link, LinkType
from app.domains.participants.models import Participant
from app.domains.responses.models import FormResponse, FormResponseStatus
from app.domains.users.models import User
from app.shared.enums import DepartmentType

MemberRow = tuple[Link, str, str | None, DepartmentType | None]
"""Vínculo, nome do participante, e-mail do login (ou `None`) e tipo do setor."""

# O vínculo com nome, e-mail e setor: a base de `get_member` e `list_members`. O
# login e o setor entram por LEFT JOIN: vínculo sem login tem e-mail `None`, e
# vínculo sem setor tem setor `None` (por isso quem devolve a linha declara
# `MemberRow`). Constante de módulo de propósito: um `select` é imutável, cada
# `.where()` devolve outro, e sem uma função anotada o tipo vale igual nas versões
# 2.0 e 2.1 do SQLAlchemy.
_MEMBER_QUERY = (
    select(Link, Participant.name, User.email, Department.type)
    .join(Participant, Participant.id == Link.participant_id)
    .outerjoin(User, User.link_id == Link.id)
    .outerjoin(Department, Department.id == Link.department_id)
)


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
    ) -> MemberRow | None:
        """O vínculo, o nome da pessoa, o e-mail do login e o tipo do setor.

        `None` se o vínculo não existe ou é de outra organização: o filtro pelos
        dois ids não distingue os casos, de propósito.

        O login e o setor entram por LEFT JOIN: vínculo criado sem convite não tem
        login (e-mail `None`), e vínculo sem setor tem `department_id` nulo. Cada
        vínculo tem no máximo um login (`user.link_id` é único), então a consulta
        devolve no máximo uma linha.
        """
        result = await self.db.execute(
            _MEMBER_QUERY.where(
                Link.id == link_id, Link.organization_id == organization_id
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row.tuple()

    async def list_members(
        self, organization_id: uuid.UUID, link_type: LinkType | None
    ) -> list[MemberRow]:
        """Os membros da organização, do mesmo jeito que `get_member` lê um.

        🟡 Premissa P-070: em ordem de nome, com o id do vínculo desempatando nomes
        iguais, e sem paginação. Com `link_type`, só os vínculos daquele tipo.
        """
        query = _MEMBER_QUERY.where(Link.organization_id == organization_id)
        if link_type is not None:
            query = query.where(Link.type == link_type)

        result = await self.db.execute(query.order_by(Participant.name, Link.id))
        return [row.tuple() for row in result.all()]

    async def list_organization_periods(self, organization_id: uuid.UUID) -> list[Form]:
        """Todos os períodos da organização: os "para todos" e os individuais.

        Formulário sem `opens_at` ou `closes_at` não é período e fica de fora, como
        no `FormRepository.list_periods`. Quem escolhe o de cada membro é o
        `pick_period`, no service.
        """
        result = await self.db.execute(
            select(Form).where(
                Form.organization_id == organization_id,
                Form.opens_at.is_not(None),
                Form.closes_at.is_not(None),
            )
        )
        return list(result.scalars().all())

    async def list_submitted(
        self, organization_id: uuid.UUID
    ) -> set[tuple[uuid.UUID, uuid.UUID]]:
        """Os pares (formulário, vínculo) com resposta enviada, na organização.

        🟡 Premissa P-069: só a resposta enviada conta como "já respondeu". A
        coluna do vínculo em `form_responses` ainda se chama `vinculo_id`.
        """
        result = await self.db.execute(
            select(FormResponse.form_id, FormResponse.vinculo_id)
            .join(Form, Form.id == FormResponse.form_id)
            .where(
                Form.organization_id == organization_id,
                FormResponse.status == FormResponseStatus.SUBMITTED,
            )
        )
        return {row.tuple() for row in result.all()}

    async def save(self, link: Link) -> Link:
        """Grava as alterações de um vínculo já carregado pela sessão.

        O `refresh` relê o `updated_at`, que o banco preenche no UPDATE
        (`onupdate=func.now()` no model).
        """
        await self.db.flush()
        await self.db.refresh(link)
        return link
