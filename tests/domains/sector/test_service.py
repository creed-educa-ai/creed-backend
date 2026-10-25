"""Testes do service de Department."""

import uuid

import pytest

from app.domains.department.models import Department, DepartmentType
from app.domains.department.schemas import DepartmentCreate
from app.domains.department.service import DepartmentService
from app.shared.exceptions import NotFoundError


class FakeDepartmentRepository:
    def __init__(self) -> None:
        self.department: Department | None = None

    async def get_by_id(
        self,
        department_id: uuid.UUID,
    ) -> Department | None:
        if self.department and self.department.id == department_id:
            return self.department
        return None

    async def create(self, department: Department) -> Department:
        self.department = department
        return department


@pytest.fixture
def um_department() -> Department:
    return Department(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        type=DepartmentType.TECNOLOGIA_INFORMACAO,
    )


@pytest.fixture
def repository() -> FakeDepartmentRepository:
    return FakeDepartmentRepository()


@pytest.fixture
def service(repository: FakeDepartmentRepository) -> DepartmentService:
    return DepartmentService(repository)  # type: ignore[arg-type]


class TestDepartmentService:
    @pytest.mark.asyncio
    async def test_get_by_id(
        self,
        service: DepartmentService,
        repository: FakeDepartmentRepository,
        um_department: Department,
    ) -> None:
        repository.department = um_department

        result = await service.get_by_id(um_department.id)

        assert result == um_department

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        service: DepartmentService,
    ) -> None:
        with pytest.raises(NotFoundError):
            await service.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_create(
        self,
        service: DepartmentService,
        repository: FakeDepartmentRepository,
        um_department: Department,
    ) -> None:
        data = DepartmentCreate(
            organization_id=um_department.organization_id,
            type=um_department.type,
        )

        result = await service.create(data)

        assert result.organization_id == um_department.organization_id
        assert result.type == um_department.type
        assert repository.department is result
