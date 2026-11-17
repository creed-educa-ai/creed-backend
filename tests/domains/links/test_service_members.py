"""Testes da troca de setor de um membro (`LinkService.update_member_department`).

Sem banco e sem HTTP: o repository e o `DepartmentService` são dublês em memória.
O que se prova é a regra: quem pode (P-066), o que é 404, o que `None` faz e que o
setor da empresa é pedido ao `DepartmentService`, nunca criado aqui. A consulta do
`get_member` (JOINs) só roda contra o Postgres: ver o "Como verificar" da spec.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domains.department.models import Department
from app.domains.links.models import Link
from app.domains.links.schemas import MemberDepartmentUpdate, MemberResponse
from app.domains.links.service import LinkService
from app.shared.enums import DepartmentType, LinkType, Roles
from app.shared.exceptions import ForbiddenError, NotFoundError


class FakeMemberRepository:
    """Dublê do repository: guarda vínculos com nome e e-mail, conta as leituras.

    `save` preenche `updated_at`, como o `onupdate` do model faz no UPDATE.
    """

    def __init__(self, links: list[Link] | None = None) -> None:
        self.links = list(links or [])
        self.get_member_calls = 0
        self.saved: list[Link] = []

    async def get_member(
        self, organization_id: uuid.UUID, link_id: uuid.UUID
    ) -> tuple[Link, str, str | None, DepartmentType | None] | None:
        self.get_member_calls += 1
        for link in self.links:
            if link.id == link_id and link.organization_id == organization_id:
                return link, "Ana Souza", "ana@empresa.com.br", None
        return None

    async def save(self, link: Link) -> Link:
        link.updated_at = datetime.now(UTC)
        self.saved.append(link)
        return link


class FakeDepartmentService:
    """Dublê do `DepartmentService`: um setor por organização e tipo."""

    def __init__(self) -> None:
        self.departments: dict[tuple[uuid.UUID, DepartmentType], Department] = {}
        self.calls = 0

    async def get_or_create(
        self, organization_id: uuid.UUID, department_type: DepartmentType
    ) -> Department:
        self.calls += 1
        key = (organization_id, department_type)
        if key not in self.departments:
            self.departments[key] = Department(
                id=uuid.uuid4(), organization_id=organization_id, type=department_type
            )
        return self.departments[key]


def make_link(organization_id: uuid.UUID, **fields: object) -> Link:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "participant_id": uuid.uuid4(),
        "organization_id": organization_id,
        "department_id": None,
        "type": LinkType.EMPREGO,
        "role": Roles.RESPONDENTE,
        "start_at": datetime(2026, 11, 1, tzinfo=UTC),
        "end_at": None,
        "created_at": datetime(2026, 11, 1, tzinfo=UTC),
        "updated_at": None,
    }
    return Link(**{**defaults, **fields})


def make_service(
    repository: FakeMemberRepository, departments: FakeDepartmentService
) -> LinkService:
    # Participante e organização não entram na troca de setor.
    return LinkService(
        repository,  # type: ignore[arg-type]
        participants=None,  # type: ignore[arg-type]
        organizations=None,  # type: ignore[arg-type]
        departments=departments,  # type: ignore[arg-type]
    )


ORGANIZATION = uuid.uuid4()
OTHER_ORGANIZATION = uuid.uuid4()


class TestUpdateMemberDepartment:
    async def test_gestor_picks_a_department_the_company_did_not_have(self) -> None:
        link = make_link(ORGANIZATION)
        repository = FakeMemberRepository([link])
        departments = FakeDepartmentService()

        member = await make_service(repository, departments).update_member_department(
            ORGANIZATION,
            link.id,
            DepartmentType.MARKETING,
            role="gestor",
            own_organization_id=ORGANIZATION,
        )

        created = departments.departments[(ORGANIZATION, DepartmentType.MARKETING)]
        assert link.department_id == created.id
        assert member.department == DepartmentType.MARKETING
        assert member.name == "Ana Souza"
        assert member.email == "ana@empresa.com.br"
        assert repository.saved == [link]
        assert link.updated_at is not None

    async def test_two_members_in_the_same_department_share_it(self) -> None:
        first = make_link(ORGANIZATION)
        second = make_link(ORGANIZATION)
        repository = FakeMemberRepository([first, second])
        departments = FakeDepartmentService()
        links = make_service(repository, departments)

        for link in (first, second):
            await links.update_member_department(
                ORGANIZATION,
                link.id,
                DepartmentType.FINANCEIRO,
                role="gestor",
                own_organization_id=ORGANIZATION,
            )

        assert first.department_id is not None
        assert first.department_id == second.department_id
        assert len(departments.departments) == 1

    async def test_none_removes_the_department_without_asking_for_one(self) -> None:
        link = make_link(ORGANIZATION, department_id=uuid.uuid4())
        repository = FakeMemberRepository([link])
        departments = FakeDepartmentService()

        member = await make_service(repository, departments).update_member_department(
            ORGANIZATION, link.id, None, role="gestor", own_organization_id=ORGANIZATION
        )

        assert link.department_id is None
        assert member.department is None
        assert departments.calls == 0
        assert repository.saved == [link]

    async def test_admin_changes_a_member_of_any_organization(self) -> None:
        link = make_link(OTHER_ORGANIZATION)
        repository = FakeMemberRepository([link])

        member = await make_service(
            repository, FakeDepartmentService()
        ).update_member_department(
            OTHER_ORGANIZATION,
            link.id,
            DepartmentType.ADMINISTRATIVO,
            role="admin",
            own_organization_id=ORGANIZATION,
        )

        assert member.department == DepartmentType.ADMINISTRATIVO

    async def test_gestor_of_another_organization_is_forbidden_before_any_read(
        self,
    ) -> None:
        link = make_link(OTHER_ORGANIZATION)
        repository = FakeMemberRepository([link])
        departments = FakeDepartmentService()

        with pytest.raises(ForbiddenError):
            await make_service(repository, departments).update_member_department(
                OTHER_ORGANIZATION,
                link.id,
                DepartmentType.MARKETING,
                role="gestor",
                own_organization_id=ORGANIZATION,
            )

        assert repository.get_member_calls == 0
        assert departments.calls == 0
        assert link.department_id is None

    async def test_respondente_is_forbidden_even_in_own_organization(self) -> None:
        link = make_link(ORGANIZATION)
        repository = FakeMemberRepository([link])

        with pytest.raises(ForbiddenError):
            await make_service(
                repository, FakeDepartmentService()
            ).update_member_department(
                ORGANIZATION,
                link.id,
                DepartmentType.MARKETING,
                role="respondente",
                own_organization_id=ORGANIZATION,
            )

        assert repository.get_member_calls == 0

    async def test_link_of_another_organization_is_not_found(self) -> None:
        link = make_link(OTHER_ORGANIZATION)
        repository = FakeMemberRepository([link])
        departments = FakeDepartmentService()

        with pytest.raises(NotFoundError):
            await make_service(repository, departments).update_member_department(
                ORGANIZATION,
                link.id,
                DepartmentType.MARKETING,
                role="gestor",
                own_organization_id=ORGANIZATION,
            )

        assert departments.calls == 0
        assert repository.saved == []

    async def test_unknown_link_is_not_found(self) -> None:
        repository = FakeMemberRepository()

        with pytest.raises(NotFoundError):
            await make_service(
                repository, FakeDepartmentService()
            ).update_member_department(
                ORGANIZATION,
                uuid.uuid4(),
                None,
                role="admin",
                own_organization_id=ORGANIZATION,
            )


class TestMemberDepartmentUpdate:
    def test_accepts_each_of_the_five_departments_and_null(self) -> None:
        for department in DepartmentType:
            body = MemberDepartmentUpdate.model_validate({"department": department.value})
            assert body.department == department

        assert (
            MemberDepartmentUpdate.model_validate({"department": None}).department is None
        )

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"department": "Vendas"},
            {"department": "Recursos Humanos"},
            {"department": "Marketing", "role": "admin"},
        ],
        ids=["vazio", "fora-dos-cinco", "rotulo-com-espaco", "campo-a-mais"],
    )
    def test_rejects_invalid_body(self, body: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            MemberDepartmentUpdate.model_validate(body)


class TestMemberResponse:
    def test_builds_from_link_and_values_read_from_other_tables(self) -> None:
        updated_at = datetime(2026, 11, 9, 14, tzinfo=UTC)
        link = make_link(ORGANIZATION, role=Roles.GESTOR, updated_at=updated_at)

        response = MemberResponse.from_model(
            link, name="Ana Souza", email=None, department=DepartmentType.MARKETING
        )

        assert response.model_dump(mode="json") == {
            "link_id": str(link.id),
            "name": "Ana Souza",
            "email": None,
            "role": "gestor",
            "type": "emprego",
            "department": "Marketing",
            "updated_at": "2026-11-09T14:00:00Z",
        }
