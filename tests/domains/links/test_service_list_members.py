"""Testes da lista de membros (`LinkService.list_members`, CREED-697).

Sem banco e sem HTTP: o repository e o `OrganizationService` são dublês. O que se
prova é a montagem: quem pode (P-066), o 404 do admin, o período de cada membro
(P-068, via `pick_period`), o "já respondeu" (P-069) e que o número de consultas não
cresce com o número de membros. As consultas em si (JOINs, filtro de `type`, ordem)
só rodam contra o Postgres.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domains.forms.models import Form, FormStatus
from app.domains.forms.schemas import PeriodStatus
from app.domains.links.models import Link
from app.domains.links.schemas import MemberListItem, MemberPeriod
from app.domains.links.service import LinkService, MemberWithPeriod
from app.shared.enums import DepartmentType, LinkType, Roles
from app.shared.exceptions import ForbiddenError, NotFoundError

ORGANIZATION = uuid.uuid4()
OTHER_ORGANIZATION = uuid.uuid4()
DAY = timedelta(days=1)

MemberRow = tuple[Link, str, str | None, DepartmentType | None]


class FakeListRepository:
    """Dublê do repository: devolve o que recebeu e conta cada chamada."""

    def __init__(
        self,
        rows: list[MemberRow] | None = None,
        periods: list[Form] | None = None,
        submitted: set[tuple[uuid.UUID, uuid.UUID]] | None = None,
    ) -> None:
        self.rows = list(rows or [])
        self.periods = list(periods or [])
        self.submitted = set(submitted or set())
        self.calls: list[str] = []
        self.link_type_received: LinkType | None = None

    async def list_members(
        self, organization_id: uuid.UUID, link_type: LinkType | None
    ) -> list[MemberRow]:
        self.calls.append("list_members")
        self.link_type_received = link_type
        return self.rows

    async def list_organization_periods(self, organization_id: uuid.UUID) -> list[Form]:
        self.calls.append("list_organization_periods")
        return self.periods

    async def list_submitted(
        self, organization_id: uuid.UUID
    ) -> set[tuple[uuid.UUID, uuid.UUID]]:
        self.calls.append("list_submitted")
        return self.submitted


class FakeOrganizationService:
    def __init__(self, *, exists: bool = True) -> None:
        self.exists = exists

    async def organization_exists(self, organization_id: uuid.UUID) -> bool:
        return self.exists


def make_service(
    repository: FakeListRepository, *, organization_exists: bool = True
) -> LinkService:
    # Participante e setor não entram na lista: o repository já traz nome e setor.
    return LinkService(
        repository,  # type: ignore[arg-type]
        participants=None,  # type: ignore[arg-type]
        organizations=FakeOrganizationService(exists=organization_exists),  # type: ignore[arg-type]
        departments=None,  # type: ignore[arg-type]
    )


def make_row(name: str, link_type: LinkType = LinkType.EMPREGO) -> MemberRow:
    link = Link(
        id=uuid.uuid4(),
        participant_id=uuid.uuid4(),
        organization_id=ORGANIZATION,
        department_id=None,
        type=link_type,
        role=Roles.RESPONDENTE,
        start_at=datetime(2026, 11, 1, tzinfo=UTC),
        end_at=None,
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
        updated_at=None,
    )
    return link, name, f"{name.lower()}@empresa.com.br", None


def make_period(
    opens_in: timedelta, closes_in: timedelta, link_id: uuid.UUID | None = None
) -> Form:
    """Período com datas relativas a agora: o service usa o relógio de verdade."""
    now = datetime.now(UTC)
    return Form(
        id=uuid.uuid4(),
        name="Plasticidade Humana",
        organization_id=ORGANIZATION,
        status=FormStatus.DRAFT,
        opens_at=now + opens_in,
        closes_at=now + closes_in,
        link_id=link_id,
        created_at=now - 30 * DAY,
    )


async def list_as_gestor(repository: FakeListRepository) -> list[MemberWithPeriod]:
    return await make_service(repository).list_members(
        ORGANIZATION, None, role="gestor", own_organization_id=ORGANIZATION
    )


def period_of(item: MemberWithPeriod) -> MemberPeriod:
    """O período do membro, quando o teste espera que ele exista."""
    assert item.period is not None
    return item.period


class TestListMembers:
    async def test_each_member_gets_their_own_period(self) -> None:
        ana, bruno = make_row("Ana"), make_row("Bruno")
        for_everyone = make_period(DAY, 2 * DAY)
        only_ana = make_period(-DAY, DAY, link_id=ana[0].id)
        repository = FakeListRepository(
            rows=[ana, bruno], periods=[for_everyone, only_ana]
        )

        members = await list_as_gestor(repository)

        assert [m.member.name for m in members] == ["Ana", "Bruno"]
        assert period_of(members[0]).form_id == only_ana.id
        assert period_of(members[0]).period_status is PeriodStatus.OPEN
        assert period_of(members[1]).form_id == for_everyone.id
        assert period_of(members[1]).period_status is PeriodStatus.SCHEDULED

    async def test_has_answered_only_for_the_pair_period_and_link(self) -> None:
        ana, bruno = make_row("Ana"), make_row("Bruno")
        current = make_period(-DAY, DAY)
        older = make_period(-10 * DAY, -5 * DAY)
        repository = FakeListRepository(
            rows=[ana, bruno],
            periods=[current, older],
            # Ana enviou o atual; Bruno só enviou o antigo, que não é o período dele.
            submitted={(current.id, ana[0].id), (older.id, bruno[0].id)},
        )

        members = await list_as_gestor(repository)

        assert period_of(members[0]).has_answered is True
        assert period_of(members[1]).form_id == current.id
        assert period_of(members[1]).has_answered is False

    async def test_member_without_any_period_has_none(self) -> None:
        repository = FakeListRepository(rows=[make_row("Ana")])

        members = await list_as_gestor(repository)

        assert members[0].period is None

    async def test_period_dates_and_member_fields_are_carried(self) -> None:
        ana = make_row("Ana")
        current = make_period(-DAY, DAY)
        repository = FakeListRepository(rows=[ana], periods=[current])

        [member] = await list_as_gestor(repository)

        assert member.member.link is ana[0]
        assert member.member.email == "ana@empresa.com.br"
        assert period_of(member).opens_at == current.opens_at
        assert period_of(member).closes_at == current.closes_at

    async def test_type_filter_is_passed_to_the_repository(self) -> None:
        repository = FakeListRepository()

        await make_service(repository).list_members(
            ORGANIZATION,
            LinkType.MENTORIA,
            role="admin",
            own_organization_id=ORGANIZATION,
        )

        assert repository.link_type_received is LinkType.MENTORIA

    async def test_empty_organization_returns_empty_list(self) -> None:
        assert await list_as_gestor(FakeListRepository()) == []

    @pytest.mark.parametrize("member_count", [1, 10])
    async def test_three_queries_whatever_the_number_of_members(
        self, member_count: int
    ) -> None:
        rows = [make_row(f"Pessoa {n}") for n in range(member_count)]
        periods = [make_period(-DAY, DAY, link_id=row[0].id) for row in rows]
        repository = FakeListRepository(rows=rows, periods=periods)

        members = await list_as_gestor(repository)

        assert len(members) == member_count
        assert repository.calls == [
            "list_members",
            "list_organization_periods",
            "list_submitted",
        ]


class TestListMembersAccess:
    async def test_gestor_of_another_organization_is_forbidden_before_any_query(
        self,
    ) -> None:
        repository = FakeListRepository()

        with pytest.raises(ForbiddenError):
            await make_service(repository).list_members(
                OTHER_ORGANIZATION, None, role="gestor", own_organization_id=ORGANIZATION
            )

        assert repository.calls == []

    async def test_respondente_is_forbidden_even_in_own_organization(self) -> None:
        repository = FakeListRepository()

        with pytest.raises(ForbiddenError):
            await make_service(repository).list_members(
                ORGANIZATION, None, role="respondente", own_organization_id=ORGANIZATION
            )

        assert repository.calls == []

    async def test_admin_lists_another_organization(self) -> None:
        repository = FakeListRepository(rows=[make_row("Ana")])

        members = await make_service(repository).list_members(
            OTHER_ORGANIZATION, None, role="admin", own_organization_id=ORGANIZATION
        )

        assert len(members) == 1

    async def test_admin_on_unknown_organization_is_not_found(self) -> None:
        repository = FakeListRepository()

        with pytest.raises(NotFoundError):
            await make_service(repository, organization_exists=False).list_members(
                OTHER_ORGANIZATION, None, role="admin", own_organization_id=ORGANIZATION
            )

        assert repository.calls == []


class TestMemberListItem:
    def test_is_the_member_response_plus_the_period(self) -> None:
        link, name, email, _ = make_row("Ana", LinkType.MENTORIA)
        period = MemberPeriod(
            form_id=uuid.UUID("5b1f0a7e-4c2d-4f7a-9d3e-2a6b8c0d1e2f"),
            opens_at=datetime(2026, 11, 1, tzinfo=UTC),
            closes_at=datetime(2026, 11, 30, tzinfo=UTC),
            period_status=PeriodStatus.OPEN,
            has_answered=True,
        )

        item = MemberListItem.from_member(
            link, name=name, email=email, department=None, period=period
        )

        assert item.model_dump(mode="json") == {
            "link_id": str(link.id),
            "name": "Ana",
            "email": "ana@empresa.com.br",
            "role": "respondente",
            "type": "mentoria",
            "department": None,
            "updated_at": None,
            "period": {
                "form_id": "5b1f0a7e-4c2d-4f7a-9d3e-2a6b8c0d1e2f",
                "opens_at": "2026-11-01T00:00:00Z",
                "closes_at": "2026-11-30T00:00:00Z",
                "period_status": "open",
                "has_answered": True,
            },
        }

    def test_period_can_be_null(self) -> None:
        link, name, email, _ = make_row("Ana")

        item = MemberListItem.from_member(
            link, name=name, email=email, department=None, period=None
        )

        assert item.model_dump(mode="json")["period"] is None
