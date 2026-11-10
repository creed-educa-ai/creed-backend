"""Acesso a dados do domínio department.

Esta camada NÃO contém regra de negócio: só queries e persistência.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.department.models import Department
from app.shared.enums import DepartmentType


class DepartmentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, department_id: uuid.UUID) -> Department | None:
        """Busca um departamento pelo identificador."""
        result = await self.db.execute(
            select(Department).where(Department.id == department_id)
        )
        return result.scalar_one_or_none()

    async def get_by_organization_and_type(
        self, organization_id: uuid.UUID, department_type: DepartmentType
    ) -> Department | None:
        """Busca o setor de um tipo dentro de uma organização."""
        result = await self.db.execute(
            select(Department).where(
                Department.organization_id == organization_id,
                Department.type == department_type,
            )
        )
        return result.scalar_one_or_none()

    async def create_if_absent(self, department: Department) -> Department | None:
        """Cria o setor, ou devolve `None` se a organização já tem um desse tipo.

        `None` só acontece quando outro pedido criou o mesmo setor entre a busca do
        service e este `flush()`: a `uq_departments_organization_type` recusa o
        segundo. O savepoint (`begin_nested`) desfaz só este INSERT. Sem ele, a
        sessão inteira recusaria consultas até o rollback, e o service não
        conseguiria ler o setor que o outro pedido criou.
        """
        try:
            async with self.db.begin_nested():
                self.db.add(department)
                await self.db.flush()
        except IntegrityError as exc:
            if "uq_departments_organization_type" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(department)
        return department

    async def create(self, department: Department) -> Department:
        """Cria um departamento no banco."""
        self.db.add(department)
        await self.db.flush()
        await self.db.refresh(department)
        return department
