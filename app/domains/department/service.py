"""Regras de negócio do domínio department.

Organização é de outro domínio: a pergunta "ela existe?" vai ao
`OrganizationService`, nunca ao model de `organizacoes`.
"""

import uuid

from app.domains.department.models import Department
from app.domains.department.repository import DepartmentRepository
from app.domains.department.schemas import DepartmentCreate
from app.domains.organizacoes.service import OrganizationService
from app.shared.enums import DepartmentType
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

    async def get_or_create(
        self, organization_id: uuid.UUID, department_type: DepartmentType
    ) -> Department:
        """O setor daquele tipo na organização, criado na hora se ela ainda não tem.

        Não confere se a organização existe: quem chama (a troca de setor do
        membro) já conferiu, e a FK de `departments.organization_id` garante o resto.
        """
        existing = await self.repository.get_by_organization_and_type(
            organization_id, department_type
        )
        if existing is not None:
            return existing

        created = await self.repository.create_if_absent(
            Department(organization_id=organization_id, type=department_type)
        )
        if created is not None:
            return created

        # Outro pedido criou o mesmo setor entre a busca acima e o INSERT: a
        # unicidade recusou o nosso, e o dele já está gravado.
        department = await self.repository.get_by_organization_and_type(
            organization_id, department_type
        )
        if department is None:
            raise RuntimeError(
                f"Setor {department_type.value} da organização {organization_id} "
                "recusado como duplicado, mas não encontrado"
            )
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
