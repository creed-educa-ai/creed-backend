"""Acesso a dados do domínio de forms.

Esta camada NÃO contém regra de negócio: só queries e agregações.
Agregação pesada é empurrada para o Postgres, nunca feita em memória.
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.forms.models import Form


class FormRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, form_id: uuid.UUID) -> Form | None:
        result = await self.db.execute(select(Form).where(Form.id == form_id))
        return result.scalar_one_or_none()

    async def get_open_for_link(
        self, organization_id: uuid.UUID, link_id: uuid.UUID, now: datetime
    ) -> Form | None:
        """O formulário aberto em `now`, para a organização inteira ou só o vínculo.

        Sem período (`opens_at` ou `closes_at` nulos), o formulário não entra: a
        comparação com nulo nunca é verdadeira. O `limit(1)` e a ordem existem para
        um eventual empate não virar erro: primeiro o do vínculo, depois o mais recente.
        """
        result = await self.db.execute(
            select(Form)
            .where(
                Form.organization_id == organization_id,
                or_(Form.link_id.is_(None), Form.link_id == link_id),
                Form.opens_at <= now,
                Form.closes_at > now,
            )
            .order_by(Form.link_id.is_(None), Form.opens_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_periods(
        self, organization_id: uuid.UUID, link_id: uuid.UUID | None
    ) -> list[Form]:
        """Os períodos do público pedido, do mais recente ao mais antigo.

        `link_id` nulo são os períodos "para todos". Formulário sem datas não é
        período e fica de fora.
        """
        audience = Form.link_id.is_(None) if link_id is None else Form.link_id == link_id
        result = await self.db.execute(
            select(Form)
            .where(
                Form.organization_id == organization_id,
                audience,
                Form.opens_at.is_not(None),
                Form.closes_at.is_not(None),
            )
            .order_by(Form.opens_at.desc())
        )
        return list(result.scalars().all())

    async def lock_period_audience(
        self, organization_id: uuid.UUID, link_id: uuid.UUID | None
    ) -> None:
        """Serializa a criação para o mesmo público até commit/rollback.

        O lock também funciona quando ainda não existe nenhum formulário. Com
        READ COMMITTED, a consulta seguinte enxerga o período da requisição que
        acabou de liberar o lock. Todos os criadores de períodos devem usá-lo.
        """
        audience = f"forms:period:{organization_id}:{link_id}"
        await self.db.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(audience, 0)))
        )

    async def has_overlapping_period(
        self,
        organization_id: uuid.UUID,
        link_id: uuid.UUID | None,
        opens_at: datetime,
        closes_at: datetime,
    ) -> bool:
        """Há período do mesmo público que cruza ou toca este intervalo?"""
        audience = Form.link_id.is_(None) if link_id is None else Form.link_id == link_id
        result = await self.db.execute(
            select(Form.id)
            .where(
                Form.organization_id == organization_id,
                audience,
                Form.opens_at.is_not(None),
                Form.closes_at.is_not(None),
                Form.opens_at <= closes_at,
                Form.closes_at >= opens_at,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def create(self, form: Form) -> Form:
        """Cria um formulário no banco."""
        self.db.add(form)
        await self.db.flush()
        await self.db.refresh(form)
        return form

    async def list_ids_by_link(self, link_id: uuid.UUID) -> list[uuid.UUID]:
        """Os formulários feitos só para este vínculo, com ou sem datas."""
        result = await self.db.execute(select(Form.id).where(Form.link_id == link_id))
        return list(result.scalars().all())

    async def list_ids_by_organization(
        self, organization_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Todos os formulários da organização: os "para todos" e os individuais."""
        result = await self.db.execute(
            select(Form.id).where(Form.organization_id == organization_id)
        )
        return list(result.scalars().all())

    async def delete_by_ids(self, form_ids: list[uuid.UUID]) -> None:
        if not form_ids:
            return
        await self.db.execute(delete(Form).where(Form.id.in_(form_ids)))
