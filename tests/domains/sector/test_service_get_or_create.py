"""Testes do `DepartmentService.get_or_create` (task 1 da CREED-6910).

Sem banco: o repository é um dublê em memória. O que se prova é a decisão do
service, ou seja, quando reaproveitar, quando criar e o que fazer quando o
repository diz que outro pedido criou o mesmo setor no meio do caminho.
"""

import uuid

from app.domains.department.models import Department
from app.domains.department.service import DepartmentService
from app.shared.enums import DepartmentType


class FakeDepartmentRepository:
    """Dublê do repository: guarda em lista e conta as criações.

    Com `created_by_other_request`, simula a corrida: o `create_if_absent` grava o
    setor do outro pedido e devolve `None`, como a unicidade do banco faria.
    """

    def __init__(
        self,
        existing: list[Department] | None = None,
        created_by_other_request: Department | None = None,
    ) -> None:
        self.items: list[Department] = list(existing or [])
        self.created_by_other_request = created_by_other_request
        self.create_calls = 0

    async def get_by_organization_and_type(
        self, organization_id: uuid.UUID, department_type: DepartmentType
    ) -> Department | None:
        return next(
            (
                d
                for d in self.items
                if d.organization_id == organization_id and d.type == department_type
            ),
            None,
        )

    async def create_if_absent(self, department: Department) -> Department | None:
        self.create_calls += 1
        if self.created_by_other_request is not None:
            self.items.append(self.created_by_other_request)
            return None
        department.id = uuid.uuid4()
        self.items.append(department)
        return department


def make_service(repository: FakeDepartmentRepository) -> DepartmentService:
    # `get_or_create` não usa o `OrganizationService`: quem chama já conferiu a
    # organização.
    return DepartmentService(repository, organizations=None)  # type: ignore[arg-type]


def make_department(
    organization_id: uuid.UUID, department_type: DepartmentType
) -> Department:
    return Department(
        id=uuid.uuid4(), organization_id=organization_id, type=department_type
    )


async def test_organization_without_the_department_creates_it() -> None:
    organization_id = uuid.uuid4()
    repository = FakeDepartmentRepository()

    department = await make_service(repository).get_or_create(
        organization_id, DepartmentType.MARKETING
    )

    assert department.organization_id == organization_id
    assert department.type == DepartmentType.MARKETING
    assert repository.create_calls == 1
    assert repository.items == [department]


async def test_organization_with_the_department_reuses_it_without_creating() -> None:
    organization_id = uuid.uuid4()
    existing = make_department(organization_id, DepartmentType.MARKETING)
    repository = FakeDepartmentRepository(existing=[existing])

    department = await make_service(repository).get_or_create(
        organization_id, DepartmentType.MARKETING
    )

    assert department is existing
    assert repository.create_calls == 0


async def test_same_type_in_two_organizations_creates_two_departments() -> None:
    other_organization = make_department(uuid.uuid4(), DepartmentType.MARKETING)
    repository = FakeDepartmentRepository(existing=[other_organization])
    organization_id = uuid.uuid4()

    department = await make_service(repository).get_or_create(
        organization_id, DepartmentType.MARKETING
    )

    assert department is not other_organization
    assert department.organization_id == organization_id
    assert repository.create_calls == 1


async def test_another_type_in_the_same_organization_creates_a_new_department() -> None:
    organization_id = uuid.uuid4()
    financeiro = make_department(organization_id, DepartmentType.FINANCEIRO)
    repository = FakeDepartmentRepository(existing=[financeiro])

    department = await make_service(repository).get_or_create(
        organization_id, DepartmentType.MARKETING
    )

    assert department is not financeiro
    assert department.type == DepartmentType.MARKETING


async def test_race_returns_the_department_the_other_request_created() -> None:
    organization_id = uuid.uuid4()
    from_other_request = make_department(organization_id, DepartmentType.MARKETING)
    repository = FakeDepartmentRepository(created_by_other_request=from_other_request)

    department = await make_service(repository).get_or_create(
        organization_id, DepartmentType.MARKETING
    )

    assert department is from_other_request
    assert repository.create_calls == 1
