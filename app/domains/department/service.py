"""Regras de negócio do domínio department."""

import uuid

from app.domains.department.models import Department
from app.domains.department.repository import DepartmentRepository
from app.domains.department.schemas import DepartmentCreate
from app.shared.exceptions import NotFoundError


class DepartmentService:
    def __init__(self, repository: DepartmentRepository) -> None:
        self.repository = repository

    async def get_by_id(self, department_id: uuid.UUID) -> Department:
        """Busca um departamento pelo identificador."""
        department = await self.repository.get_by_id(department_id)

        if department is None:
            raise NotFoundError(f"Departamento {department_id} não encontrado")

        return department

    async def create(self, dados: DepartmentCreate) -> Department:
        """Cria um departamento a partir dos dados validados."""
        department = Department(
            organization_id=dados.organization_id,
            type=dados.type,
        )
        return await self.repository.create(department)
