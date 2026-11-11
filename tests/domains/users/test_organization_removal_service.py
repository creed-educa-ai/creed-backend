"""Testes da exclusão de empresa (`OrganizationRemovalService.remove_organization`, E-6).

Sem banco e sem HTTP, como `test_member_removal_service.py`. Os services de cada
dono são dublês sobre um mesmo `World`, um banco em memória que recusa apagar linha
ainda referenciada, como as chaves estrangeiras do Postgres: apagar fora de ordem
levanta `FakeIntegrityError`. O `log` guarda cada chamada, leituras incluídas, e é
o que prova a ordem e que nada foi chamado antes de uma recusa.

A exclusão de cada membro é um dublê do `MemberRemovalService`: o que ela apaga já
é provado em `test_member_removal_service.py`. Aqui ela só tira o vínculo e
devolve o login dele.

As consultas de cada repository (os `DELETE ... WHERE`) e a ordem contra as chaves
estrangeiras de verdade só rodam contra o Postgres: ver o "Como verificar" do PR.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.domains.users.service import OrganizationRemovalService
from app.shared.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)


class FakeIntegrityError(Exception):
    """O que o banco levanta ao apagar uma linha que outra ainda referencia."""


@dataclass
class World:
    """As tabelas que a exclusão de empresa toca, com as referências da ordem."""

    organizations: dict[uuid.UUID, Organization] = field(default_factory=dict)
    documents: set[uuid.UUID] = field(default_factory=set)
    # participante -> documento
    participant_documents: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    departments: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)  # -> org
    # vínculo -> (organização, setor)
    links: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID | None]] = field(
        default_factory=dict
    )
    logins: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)  # vínculo -> kc
    forms: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)  # -> organização
    questions: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)  # -> form
    # resposta -> formulário; as alternativas marcadas (`answer`) saem com ela
    responses: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    insights: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)  # -> resposta
    dashboards: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)  # -> resposta
    realm: set[uuid.UUID] = field(default_factory=set)
    keycloak_down: bool = False
    log: list[str] = field(default_factory=list)

    def refuse_if(self, referenced: bool, what: str) -> None:
        if referenced:
            raise FakeIntegrityError(f"{what} ainda é referenciado")


class FakeMemberRemovalService:
    """Registra as próprias chamadas. Cada membro sai com o vínculo e o login."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.deleted: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.keycloak_calls: list[list[uuid.UUID]] = []

    async def delete_member_data(
        self, organization_id: uuid.UUID, link_id: uuid.UUID
    ) -> uuid.UUID | None:
        w = self.world
        w.log.append("members.delete_member_data")
        self.deleted.append((organization_id, link_id))
        del w.links[link_id]
        return w.logins.pop(link_id, None)

    async def remove_logins_from_keycloak(self, keycloak_ids: list[uuid.UUID]) -> None:
        w = self.world
        w.log.append("members.remove_logins_from_keycloak")
        self.keycloak_calls.append(list(keycloak_ids))
        if w.keycloak_down:
            raise ServiceUnavailableError("Não foi possível remover o acesso agora.")
        w.realm.difference_update(keycloak_ids)


class FakeOrganizationService:
    """`get_calls` guarda o papel e a organização com que o service leu a empresa."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.get_calls: list[dict[str, object]] = []

    async def get(
        self, organization_id: uuid.UUID, *, role: str, own_organization_id: uuid.UUID
    ) -> Organization:
        self.world.log.append("organizations.get")
        self.get_calls.append(
            {
                "organization_id": organization_id,
                "role": role,
                "own_organization_id": own_organization_id,
            }
        )
        organization = self.world.organizations.get(organization_id)
        if organization is None:
            raise NotFoundError(f"Organização {organization_id} não encontrada")
        return organization

    async def delete_organization(self, organization: Organization) -> None:
        w = self.world
        w.refuse_if(
            any(org == organization.id for org, _ in w.links.values()),
            "organização (vínculo)",
        )
        w.refuse_if(organization.id in w.forms.values(), "organização (formulário)")
        w.refuse_if(organization.id in w.departments.values(), "organização (setor)")
        del w.organizations[organization.id]
        w.log.append("organizations.delete_organization")


class FakeLinkService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def list_organization_link_ids(
        self, organization_id: uuid.UUID
    ) -> list[uuid.UUID]:
        self.world.log.append("links.list_organization_link_ids")
        return [
            link_id
            for link_id, (org, _) in self.world.links.items()
            if org == organization_id
        ]


class FakeFormService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def list_organization_form_ids(
        self, organization_id: uuid.UUID
    ) -> list[uuid.UUID]:
        self.world.log.append("forms.list_organization_form_ids")
        return [form for form, org in self.world.forms.items() if org == organization_id]

    async def delete_organization_forms(self, form_ids: list[uuid.UUID]) -> None:
        w = self.world
        for form_id in form_ids:
            w.refuse_if(form_id in w.questions.values(), "formulário (pergunta)")
            w.refuse_if(form_id in w.responses.values(), "formulário (resposta)")
            del w.forms[form_id]
        w.log.append("forms.delete_organization_forms")


class FakeQuestionService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def delete_for_forms(self, form_ids: list[uuid.UUID]) -> None:
        w = self.world
        for question_id, form_id in list(w.questions.items()):
            if form_id in form_ids:
                # As alternativas marcadas (`answer`) apontam para a pergunta.
                w.refuse_if(form_id in w.responses.values(), "pergunta (resposta)")
                del w.questions[question_id]
        w.log.append("questions.delete_for_forms")


class FakeFormResponseService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def list_ids_for_forms(self, form_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        self.world.log.append("responses.list_ids_for_forms")
        return [
            response
            for response, form in self.world.responses.items()
            if form in form_ids
        ]

    async def delete_with_answers(self, form_response_ids: list[uuid.UUID]) -> None:
        w = self.world
        for response_id in form_response_ids:
            w.refuse_if(response_id in w.insights.values(), "resposta (insight)")
            w.refuse_if(response_id in w.dashboards.values(), "resposta (dashboard)")
            del w.responses[response_id]
        w.log.append("responses.delete_with_answers")


class FakeInsightService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def delete_for_form_responses(self, form_response_ids: list[uuid.UUID]) -> None:
        w = self.world
        for insight_id, response_id in list(w.insights.items()):
            if response_id in form_response_ids:
                del w.insights[insight_id]
        w.log.append("insights.delete_for_form_responses")


class FakeDashboardService:
    def __init__(self, world: World) -> None:
        self.world = world
        self.user_ids: list[uuid.UUID | None] = []

    async def delete_for_member_removal(
        self, form_response_ids: list[uuid.UUID], user_id: uuid.UUID | None
    ) -> None:
        w = self.world
        self.user_ids.append(user_id)
        for dashboard_id, response_id in list(w.dashboards.items()):
            if response_id in form_response_ids:
                del w.dashboards[dashboard_id]
        w.log.append("dashboards.delete_for_member_removal")


class FakeDepartmentService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def delete_for_organization(self, organization_id: uuid.UUID) -> None:
        w = self.world
        for department_id, org in list(w.departments.items()):
            if org == organization_id:
                w.refuse_if(
                    any(dept == department_id for _, dept in w.links.values()),
                    "setor (vínculo)",
                )
                del w.departments[department_id]
        w.log.append("departments.delete_for_organization")


class FakeParticipantService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def document_in_use(self, document_id: uuid.UUID) -> bool:
        self.world.log.append("participants.document_in_use")
        return document_id in self.world.participant_documents.values()


class FakeDocumentService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def delete_document(self, document_id: uuid.UUID) -> None:
        w = self.world
        w.refuse_if(
            any(org.document_id == document_id for org in w.organizations.values()),
            "documento (organização)",
        )
        w.refuse_if(
            document_id in w.participant_documents.values(), "documento (participante)"
        )
        w.documents.discard(document_id)
        w.log.append("documents.delete_document")


@dataclass
class Setup:
    """O service montado sobre o `World`, com os dublês que registram chamadas."""

    service: OrganizationRemovalService
    members: FakeMemberRemovalService
    dashboards: FakeDashboardService
    organizations: FakeOrganizationService


def build(world: World) -> Setup:
    members = FakeMemberRemovalService(world)
    dashboards = FakeDashboardService(world)
    organizations = FakeOrganizationService(world)
    service = OrganizationRemovalService(
        members,  # type: ignore[arg-type]
        organizations,  # type: ignore[arg-type]
        FakeLinkService(world),  # type: ignore[arg-type]
        FakeFormService(world),  # type: ignore[arg-type]
        FakeQuestionService(world),  # type: ignore[arg-type]
        FakeFormResponseService(world),  # type: ignore[arg-type]
        FakeInsightService(world),  # type: ignore[arg-type]
        dashboards,  # type: ignore[arg-type]
        FakeDepartmentService(world),  # type: ignore[arg-type]
        FakeParticipantService(world),  # type: ignore[arg-type]
        FakeDocumentService(world),  # type: ignore[arg-type]
    )
    return Setup(
        service=service,
        members=members,
        dashboards=dashboards,
        organizations=organizations,
    )


CREED = uuid.uuid4()


def add_organization(
    world: World, *, status: OrganizationStatus = OrganizationStatus.ACTIVE
) -> Organization:
    """Uma organização com o documento dela."""
    document_id = uuid.uuid4()
    organization = Organization(
        id=uuid.uuid4(),
        name="Empresa Teste",
        address="[A informar]",
        document_id=document_id,
        status=status,
        email=None,
        contact_name=None,
        phone=None,
        created_at=datetime(2026, 11, 10, tzinfo=UTC),
        updated_at=None,
    )
    world.organizations[organization.id] = organization
    world.documents.add(document_id)
    return organization


def add_member(
    world: World,
    organization: Organization,
    *,
    with_login: bool = True,
    department_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Um vínculo na organização, com login no banco e no realm (se pedido)."""
    link_id = uuid.uuid4()
    world.links[link_id] = (organization.id, department_id)
    if with_login:
        keycloak_id = uuid.uuid4()
        world.logins[link_id] = keycloak_id
        world.realm.add(keycloak_id)
    return link_id


def add_answered_form(world: World, organization: Organization) -> uuid.UUID:
    """Um questionário "para todos" com uma pergunta e uma resposta que ainda
    aponta para ele, com insight e dashboard. Devolve a resposta."""
    form_id = uuid.uuid4()
    world.forms[form_id] = organization.id
    world.questions[uuid.uuid4()] = form_id
    response_id = uuid.uuid4()
    world.responses[response_id] = form_id
    world.insights[uuid.uuid4()] = response_id
    world.dashboards[uuid.uuid4()] = response_id
    return response_id


async def remove(setup: Setup, organization_id: uuid.UUID) -> None:
    await setup.service.remove_organization(organization_id, own_organization_id=CREED)


class TestRemoveOrganization:
    async def test_company_with_members_leaves_nothing_behind(self) -> None:
        """Nenhuma linha aponta para a empresa no fim, e os logins saem do realm."""
        world = World()
        company = add_organization(world)
        department_id = uuid.uuid4()
        world.departments[department_id] = company.id
        first = add_member(world, company, department_id=department_id)
        second = add_member(world, company)
        logins = {world.logins[first], world.logins[second]}
        add_answered_form(world, company)

        await remove(build(world), company.id)

        assert world.organizations == {}
        assert world.documents == set()
        assert world.links == {}
        assert world.departments == {}
        assert world.forms == {}
        assert world.questions == {}
        assert world.responses == {}
        assert world.insights == {}
        assert world.dashboards == {}
        assert world.realm.isdisjoint(logins)

    async def test_order_is_the_foreign_keys_one(self) -> None:
        """Os passos 2 a 8 da task, e o Keycloak por último."""
        world = World()
        company = add_organization(world)
        world.departments[uuid.uuid4()] = company.id
        add_member(world, company)
        add_member(world, company)
        add_answered_form(world, company)

        await remove(build(world), company.id)

        assert world.log == [
            "organizations.get",
            "links.list_organization_link_ids",
            "members.delete_member_data",
            "members.delete_member_data",
            "forms.list_organization_form_ids",
            "responses.list_ids_for_forms",
            "insights.delete_for_form_responses",
            "dashboards.delete_for_member_removal",
            "responses.delete_with_answers",
            "questions.delete_for_forms",
            "forms.delete_organization_forms",
            "departments.delete_for_organization",
            "organizations.delete_organization",
            "participants.document_in_use",
            "documents.delete_document",
            "members.remove_logins_from_keycloak",
        ]

    async def test_each_member_once_and_keycloak_once_with_every_login(self) -> None:
        world = World()
        company = add_organization(world)
        first = add_member(world, company)
        second = add_member(world, company)
        logins = [world.logins[first], world.logins[second]]
        setup = build(world)

        await remove(setup, company.id)

        assert setup.members.deleted == [(company.id, first), (company.id, second)]
        assert setup.members.keycloak_calls == [logins]
        assert world.log[-1] == "members.remove_logins_from_keycloak"

    async def test_member_without_login_is_left_out_of_keycloak(self) -> None:
        world = World()
        company = add_organization(world)
        with_login = add_member(world, company)
        without_login = add_member(world, company, with_login=False)
        login = world.logins[with_login]
        setup = build(world)

        await remove(setup, company.id)

        assert (company.id, without_login) in setup.members.deleted
        assert setup.members.keycloak_calls == [[login]]

    async def test_dashboards_are_deleted_by_response_only(self) -> None:
        """Os logins dos membros já saíram: o dashboard não é procurado por login."""
        world = World()
        company = add_organization(world)
        add_answered_form(world, company)
        setup = build(world)

        await remove(setup, company.id)

        assert setup.dashboards.user_ids == [None]

    async def test_pending_company_deletes_organization_and_document(self) -> None:
        """🟡 P-078: a rejeição. Sem membro nem questionário, sai só a organização e
        o documento, e o Keycloak é chamado com a lista vazia."""
        world = World()
        pending = add_organization(world, status=OrganizationStatus.PENDING)
        setup = build(world)

        await remove(setup, pending.id)

        assert world.organizations == {}
        assert world.documents == set()
        assert setup.members.deleted == []
        assert setup.members.keycloak_calls == [[]]

    async def test_document_used_by_a_participant_stays(self) -> None:
        """🟡 P-080: a organização sai, o documento fica."""
        world = World()
        company = add_organization(world)
        world.participant_documents[uuid.uuid4()] = company.document_id

        await remove(build(world), company.id)

        assert world.organizations == {}
        assert company.document_id in world.documents
        assert "documents.delete_document" not in world.log
        assert world.log[-1] == "members.remove_logins_from_keycloak"

    async def test_own_organization_is_refused_before_any_call(self) -> None:
        """🟡 P-079: 409, sem nenhuma chamada a nenhum dublê."""
        world = World()
        world.organizations[CREED] = Organization(id=CREED, document_id=uuid.uuid4())
        setup = build(world)

        with pytest.raises(ConflictError):
            await remove(setup, CREED)

        assert world.log == []
        assert setup.members.deleted == []
        assert setup.members.keycloak_calls == []
        assert CREED in world.organizations

    async def test_reads_the_organization_as_admin(self) -> None:
        """A guarda da rota só deixa passar o `admin`, e o service lê como ele.

        Lida com outro papel, a organização inexistente viraria 403 em vez de 404.
        """
        world = World()
        company = add_organization(world)
        setup = build(world)

        await remove(setup, company.id)

        assert setup.organizations.get_calls == [
            {
                "organization_id": company.id,
                "role": "admin",
                "own_organization_id": CREED,
            }
        ]

    async def test_unknown_organization_is_not_found_without_deleting(self) -> None:
        world = World()
        other = add_organization(world)
        add_member(world, other)

        with pytest.raises(NotFoundError):
            await remove(build(world), uuid.uuid4())

        assert world.log == ["organizations.get"]
        assert other.id in world.organizations

    async def test_keycloak_down_is_raised_after_the_database(self) -> None:
        """O 503 sobe sem ser tratado: o `get_db` desfaz o banco (P-073). O log de
        quem já saiu do realm é do `remove_logins_from_keycloak`, provado em
        `test_member_removal_service.py`."""
        world = World()
        company = add_organization(world)
        member = add_member(world, company)
        login = world.logins[member]
        world.keycloak_down = True

        with pytest.raises(ServiceUnavailableError):
            await remove(build(world), company.id)

        assert world.log[-1] == "members.remove_logins_from_keycloak"
        assert login in world.realm
