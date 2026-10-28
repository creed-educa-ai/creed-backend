"""Acesso a dados do domínio department.

Esta camada NÃO contém regra de negócio: só queries e persistência.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.department.models import Department


class DepartmentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, department_id: uuid.UUID) -> Department | None:
        """Busca um departamento pelo identificador."""
        result = await self.db.execute(
            select(Department).where(Department.id == department_id)
        )
        return result.scalar_one_or_none()

    async def create(self, department: Department) -> Department:
        """Cria um departamento no banco."""
        self.db.add(department)
        await self.db.flush()
        await self.db.refresh(department)
        return department
