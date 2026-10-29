"""Regras de negócio do domínio department.

Organização é de outro domínio: a pergunta "ela existe?" vai ao
`OrganizationService`, nunca ao model de `organizacoes`.
"""

import uuid

from app.domains.department.models import Department
from app.domains.department.repository import DepartmentRepository
from app.domains.department.schemas import DepartmentCreate
from app.domains.organizacoes.service import OrganizationService
from app.shared.exceptions import NotFoundError, ValidationError


class DepartmentService:
    def __init__(
        self, repository: DepartmentRepository, organizations: OrganizationService
    ) -> None:
        self.repository = repository
        self.organizations = organizations

    async def get_by_id(self, department_id: uuid.UUID) -> Department:
        """Busca um departamento pelo identificador."""
        department = await self.repository.get_by_id(department_id)

        if department is None:
            raise NotFoundError(f"Departamento {department_id} não encontrado")

        return department

    async def create(self, dados: DepartmentCreate) -> Department:
        """Cria um departamento a partir dos dados validados.

        A organização veio no corpo: inexistente é `ValidationError` (422), e não
        `NotFoundError` (spec da CREED-47, item 11).
        """
        if not await self.organizations.organization_exists(dados.organization_id):
            raise ValidationError(f"Organização {dados.organization_id} não encontrada")

        department = Department(
            organization_id=dados.organization_id,
            type=dados.type,
        )
        return await self.repository.create(department)
