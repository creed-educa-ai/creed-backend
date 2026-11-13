"""Testes da exclusão de membro (`MemberRemovalService.remove_member`, M-3).

Sem banco e sem HTTP. Os services de cada dono são dublês sobre um mesmo `World`,
um banco em memória que recusa apagar linha ainda referenciada, como as chaves
estrangeiras do Postgres. É isso que prova a ordem: apagar fora dela levanta
`FakeIntegrityError`, em vez de passar porque cada dublê só anota a chamada.

As consultas de cada repository (os `DELETE ... WHERE ... IN`) só rodam contra o
Postgres: ver o "Como verificar" do PR.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.domains.links.models import Link
from app.domains.users.models import User
from app.domains.users.service import MemberRemovalService
from app.shared.enums import LinkType, RecordStatus, Roles
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)


class FakeIntegrityError(Exception):
    """O que o banco levanta ao apagar uma linha que outra ainda referencia."""


@dataclass
class World:
    """As tabelas que a exclusão toca, com as referências que importam para a ordem.

    `log` guarda cada exclusão na ordem em que aconteceu, e `realm` são os
    `keycloak_id` que existem no Keycloak.
    """

    links: dict[uuid.UUID, Link] = field(default_factory=dict)
    logins: dict[uuid.UUID, User] = field(default_factory=dict)  # por link_id
    forms: dict[uuid.UUID, uuid.UUID | None] = field(default_factory=dict)  # -> link
    # resposta -> (formulário, vínculo)
    responses: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID]] = field(default_factory=dict)
    insights: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)  # -> resposta
    # dashboard -> (resposta, login)
    dashboards: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID]] = field(default_factory=dict)
    demographics: set[uuid.UUID] = field(default_factory=set)  # participant_id
    participants: set[uuid.UUID] = field(default_factory=set)
    realm: set[uuid.UUID] = field(default_factory=set)
    keycloak_down: bool = False
    # Só estes `keycloak_id` falham; vazio, vale `keycloak_down`.
    keycloak_failing: set[uuid.UUID] = field(default_factory=set)
    log: list[str] = field(default_factory=list)

    def refuse_if(self, referenced: bool, what: str) -> None:
        if referenced:
            raise FakeIntegrityError(f"{what} ainda é referenciado")


class FakeLinkService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def get_member_link(
        self, organization_id: uuid.UUID, link_id: uuid.UUID
    ) -> Link:
        link = self.world.links.get(link_id)
        if link is None or link.organization_id != organization_id:
            raise NotFoundError(f"Membro {link_id} não encontrado")
        return link

    async def delete_link(self, link: Link) -> None:
        w = self.world
        w.refuse_if(link.id in w.logins, "vínculo (login)")
        w.refuse_if(
            any(owner == link.id for _, owner in w.responses.values()),
            "vínculo (resposta)",
        )
        w.refuse_if(link.id in w.forms.values(), "vínculo (formulário)")
        del w.links[link.id]
        w.log.append("link")

    async def participant_has_links(self, participant_id: uuid.UUID) -> bool:
        return any(
            link.participant_id == participant_id for link in self.world.links.values()
        )


class FakeFormService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def list_individual_form_ids(self, link_id: uuid.UUID) -> list[uuid.UUID]:
        return [form for form, owner in self.world.forms.items() if owner == link_id]

    async def delete_individual_forms(self, form_ids: list[uuid.UUID]) -> None:
        w = self.world
        for form_id in form_ids:
            w.refuse_if(
                any(form == form_id for form, _ in w.responses.values()),
                "formulário (resposta)",
            )
            del w.forms[form_id]
        w.log.append("forms")


class FakeFormResponseService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def list_ids_for_member_removal(
        self, link_id: uuid.UUID, individual_form_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]:
        return [
            response
            for response, (form, owner) in self.world.responses.items()
            if owner == link_id or form in individual_form_ids
        ]

    async def delete_with_answers(self, form_response_ids: list[uuid.UUID]) -> None:
        w = self.world
        for response_id in form_response_ids:
            w.refuse_if(response_id in w.insights.values(), "resposta (insight)")
            w.refuse_if(
                any(response == response_id for response, _ in w.dashboards.values()),
                "resposta (dashboard)",
            )
            del w.responses[response_id]
        w.log.append("responses")


class FakeInsightService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def delete_for_form_responses(self, form_response_ids: list[uuid.UUID]) -> None:
        w = self.world
        for insight_id, response_id in list(w.insights.items()):
            if response_id in form_response_ids:
                del w.insights[insight_id]
        w.log.append("insights")


class FakeDashboardService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def delete_for_member_removal(
        self, form_response_ids: list[uuid.UUID], user_id: uuid.UUID | None
    ) -> None:
        w = self.world
        for dashboard_id, (response_id, owner) in list(w.dashboards.items()):
            if response_id in form_response_ids or owner == user_id:
                del w.dashboards[dashboard_id]
        w.log.append("dashboards")


class FakeUserService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def get_login_of_link(self, link_id: uuid.UUID) -> User | None:
        return self.world.logins.get(link_id)

    async def delete_login(self, user: User) -> uuid.UUID:
        w = self.world
        w.refuse_if(
            any(owner == user.id for _, owner in w.dashboards.values()),
            "login (dashboard)",
        )
        del w.logins[user.link_id]
        w.log.append("login")
        return user.keycloak_id

    async def remove_from_keycloak(self, keycloak_id: uuid.UUID) -> None:
        self.world.log.append("keycloak")
        if self.world.keycloak_down or keycloak_id in self.world.keycloak_failing:
            raise ServiceUnavailableError("Não foi possível remover o acesso agora.")
        self.world.realm.discard(keycloak_id)


class FakeDemographicService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def delete_for_participant(self, participant_id: uuid.UUID) -> None:
        self.world.demographics.discard(participant_id)
        self.world.log.append("demographics")


class FakeParticipantService:
    def __init__(self, world: World) -> None:
        self.world = world

    async def delete_participant(self, participant_id: uuid.UUID) -> None:
        w = self.world
        w.refuse_if(
            any(link.participant_id == participant_id for link in w.links.values()),
            "participante (vínculo)",
        )
        w.refuse_if(participant_id in w.demographics, "participante (demográfico)")
        w.participants.discard(participant_id)
        w.log.append("participant")


def service(world: World) -> MemberRemovalService:
    return MemberRemovalService(
        FakeUserService(world),  # type: ignore[arg-type]
        FakeLinkService(world),  # type: ignore[arg-type]
        FakeFormService(world),  # type: ignore[arg-type]
        FakeFormResponseService(world),  # type: ignore[arg-type]
        FakeInsightService(world),  # type: ignore[arg-type]
        FakeDashboardService(world),  # type: ignore[arg-type]
        FakeDemographicService(world),  # type: ignore[arg-type]
        FakeParticipantService(world),  # type: ignore[arg-type]
    )


CREED = uuid.uuid4()
EMPRESA = uuid.uuid4()


def add_person(
    world: World,
    organization_id: uuid.UUID,
    *,
    participant_id: uuid.UUID | None = None,
    with_login: bool = True,
    link_type: LinkType = LinkType.MENTORIA,
    role: Roles = Roles.RESPONDENTE,
) -> Link:
    """Um vínculo na organização, com login (se pedido) e o participante dele."""
    participant_id = participant_id or uuid.uuid4()
    link = Link(
        id=uuid.uuid4(),
        participant_id=participant_id,
        organization_id=organization_id,
        department_id=None,
        type=link_type,
        role=role,
        start_at=datetime(2026, 11, 1, tzinfo=UTC),
        end_at=None,
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
        updated_at=None,
    )
    world.links[link.id] = link
    world.participants.add(participant_id)
    if with_login:
        user = User(
            id=uuid.uuid4(),
            keycloak_id=uuid.uuid4(),
            name="Ana Souza",
            email=f"{link.id}@empresa.com.br",
            status=RecordStatus.ACTIVE,
            link_id=link.id,
            created_at=datetime(2026, 11, 1, tzinfo=UTC),
        )
        world.logins[link.id] = user
        world.realm.add(user.keycloak_id)
    return link


def add_answered_form(
    world: World, link: Link, *, individual: bool
) -> tuple[uuid.UUID, uuid.UUID]:
    """Um questionário respondido pelo vínculo. Devolve
    (formulário, resposta)."""
    form_id = uuid.uuid4()
    world.forms[form_id] = link.id if individual else None
    response_id = uuid.uuid4()
    world.responses[response_id] = (form_id, link.id)
    return form_id, response_id


async def remove(world: World, target: Link, requester: Link) -> None:
    await service(world).remove_member(
        target.organization_id,
        target.id,
        own_organization_id=requester.organization_id,
        own_link_id=requester.id,
    )


class TestRemoveMember:
    async def test_mentee_loses_answers_periods_and_access(self) -> None:
        """Primeiro item do "Pronto quando" da M-3, com os insights e dashboards
        que pendem das respostas e do login (P-072)."""
        world = World()
        admin = add_person(world, CREED, role=Roles.ADMIN, link_type=LinkType.EMPREGO)
        mentee = add_person(world, CREED)
        world.demographics.add(mentee.participant_id)
        individual_form, individual_response = add_answered_form(
            world, mentee, individual=True
        )
        _, shared_response = add_answered_form(world, mentee, individual=False)
        world.insights[uuid.uuid4()] = individual_response
        login = world.logins[mentee.id]
        world.dashboards[uuid.uuid4()] = (shared_response, login.id)
        keycloak_id = login.keycloak_id

        await remove(world, mentee, admin)

        assert mentee.id not in world.links
        assert mentee.id not in world.logins
        assert keycloak_id not in world.realm  # não consegue mais entrar
        assert individual_form not in world.forms
        assert world.responses == {}
        assert world.insights == {}
        assert world.dashboards == {}
        assert mentee.participant_id not in world.participants
        assert mentee.participant_id not in world.demographics
        # Quem pediu continua lá.
        assert admin.id in world.links
        assert admin.id in world.logins

    async def test_keycloak_is_called_last(self) -> None:
        """Se uma exclusão do banco falhar, o realm nem foi tocado."""
        world = World()
        admin = add_person(world, CREED, role=Roles.ADMIN)
        mentee = add_person(world, CREED)
        add_answered_form(world, mentee, individual=True)

        await remove(world, mentee, admin)

        assert world.log[-1] == "keycloak"
        assert world.log.count("keycloak") == 1

    async def test_other_organization_keeps_participant_and_link(self) -> None:
        """Segundo item do "Pronto quando": a mesma pessoa em outra organização é
        outro vínculo do mesmo participante ([C2])."""
        world = World()
        gestor = add_person(world, EMPRESA, role=Roles.GESTOR, link_type=LinkType.EMPREGO)
        member = add_person(world, EMPRESA, link_type=LinkType.EMPREGO)
        world.demographics.add(member.participant_id)
        elsewhere = add_person(world, CREED, participant_id=member.participant_id)
        _, elsewhere_response = add_answered_form(world, elsewhere, individual=True)

        await remove(world, member, gestor)

        assert member.id not in world.links
        assert elsewhere.id in world.links
        assert elsewhere.id in world.logins
        assert elsewhere_response in world.responses
        assert member.participant_id in world.participants
        assert member.participant_id in world.demographics
        assert "participant" not in world.log

    async def test_other_peoples_answers_to_shared_forms_stay(self) -> None:
        """Do questionário "para todos" sai só a resposta da pessoa."""
        world = World()
        gestor = add_person(world, EMPRESA, role=Roles.GESTOR)
        member = add_person(world, EMPRESA)
        colleague = add_person(world, EMPRESA)
        shared_form, _ = add_answered_form(world, member, individual=False)
        colleague_response = uuid.uuid4()
        world.responses[colleague_response] = (shared_form, colleague.id)

        await remove(world, member, gestor)

        assert shared_form in world.forms
        assert world.responses == {colleague_response: (shared_form, colleague.id)}

    async def test_member_without_login_is_removed_without_keycloak(self) -> None:
        world = World()
        gestor = add_person(world, EMPRESA, role=Roles.GESTOR)
        member = add_person(world, EMPRESA, with_login=False)

        await remove(world, member, gestor)

        assert member.id not in world.links
        assert "keycloak" not in world.log
        assert "login" not in world.log

    async def test_removing_yourself_is_refused(self) -> None:
        """Terceiro item do "Pronto quando": 409, e nada foi apagado."""
        world = World()
        gestor = add_person(world, EMPRESA, role=Roles.GESTOR)

        with pytest.raises(ConflictError):
            await remove(world, gestor, gestor)

        assert world.log == []
        assert gestor.id in world.links

    async def test_gestor_of_another_organization_is_forbidden(self) -> None:
        """Quarto item do "Pronto quando": 403, antes de procurar o membro."""
        world = World()
        gestor = add_person(world, EMPRESA, role=Roles.GESTOR)
        mentee = add_person(world, CREED)

        with pytest.raises(ForbiddenError):
            await remove(world, mentee, gestor)

        assert world.log == []
        assert mentee.id in world.links

    async def test_admin_outside_creed_is_forbidden(self) -> None:
        """🟡 P-071: o admin exclui só na organização do próprio vínculo."""
        world = World()
        admin = add_person(world, CREED, role=Roles.ADMIN)
        member = add_person(world, EMPRESA)

        with pytest.raises(ForbiddenError):
            await remove(world, member, admin)

        assert member.id in world.links

    async def test_forbidden_comes_before_not_found(self) -> None:
        """Quem não pode mexer na organização não descobre quais vínculos existem."""
        world = World()
        gestor = add_person(world, EMPRESA, role=Roles.GESTOR)

        with pytest.raises(ForbiddenError):
            await service(world).remove_member(
                CREED,
                uuid.uuid4(),
                own_organization_id=gestor.organization_id,
                own_link_id=gestor.id,
            )

    async def test_link_of_another_organization_is_not_found(self) -> None:
        """O vínculo existe, mas não é da organização do endereço: o mesmo 404."""
        world = World()
        gestor = add_person(world, EMPRESA, role=Roles.GESTOR)
        mentee = add_person(world, CREED)

        with pytest.raises(NotFoundError):
            await service(world).remove_member(
                EMPRESA,
                mentee.id,
                own_organization_id=gestor.organization_id,
                own_link_id=gestor.id,
            )

        assert world.log == []

    async def test_keycloak_down_is_unavailable_after_the_database(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """O banco já passou pelo flush: o rollback do `get_db` desfaz tudo, e o
        login continua no realm para a próxima tentativa. O log diz qual login."""
        world = World()
        admin = add_person(world, CREED, role=Roles.ADMIN)
        mentee = add_person(world, CREED)
        keycloak_id = world.logins[mentee.id].keycloak_id
        world.keycloak_down = True

        with (
            caplog.at_level(logging.WARNING, logger="app.domains.users.service"),
            pytest.raises(ServiceUnavailableError),
        ):
            await remove(world, mentee, admin)

        assert world.log[-1] == "keycloak"
        assert keycloak_id in world.realm
        assert str(keycloak_id) in caplog.text


class TestDeleteMemberData:
    """A etapa do banco, sem conferência de acesso, que a E-6 vai chamar por membro."""

    async def test_deletes_and_returns_the_keycloak_id_without_calling_it(self) -> None:
        world = World()
        mentee = add_person(world, CREED)
        add_answered_form(world, mentee, individual=True)
        keycloak_id = world.logins[mentee.id].keycloak_id

        returned = await service(world).delete_member_data(CREED, mentee.id)

        assert returned == keycloak_id
        assert mentee.id not in world.links
        assert "keycloak" not in world.log
        assert keycloak_id in world.realm

    async def test_member_without_login_returns_none(self) -> None:
        world = World()
        member = add_person(world, EMPRESA, with_login=False)

        assert await service(world).delete_member_data(EMPRESA, member.id) is None
        assert member.id not in world.links

    async def test_link_of_another_organization_is_not_found(self) -> None:
        world = World()
        mentee = add_person(world, CREED)

        with pytest.raises(NotFoundError):
            await service(world).delete_member_data(EMPRESA, mentee.id)

        assert world.log == []


class TestRemoveLoginsFromKeycloak:
    """A etapa do realm, com vários logins, como a E-6 vai chamar."""

    async def test_removes_every_login(self) -> None:
        world = World()
        ids = [uuid.uuid4() for _ in range(3)]
        world.realm.update(ids)

        await service(world).remove_logins_from_keycloak(ids)

        assert world.realm == set()

    async def test_failure_logs_what_was_left_and_stops(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """O 503 desfaz o banco; o log separa o que já saiu do realm, o que talvez
        tenha saído (sem resposta) e o que nem foi tentado."""
        world = World()
        first, failing, untried = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        world.realm.update([first, failing, untried])
        world.keycloak_failing.add(failing)

        with (
            caplog.at_level(logging.WARNING, logger="app.domains.users.service"),
            pytest.raises(ServiceUnavailableError),
        ):
            await service(world).remove_logins_from_keycloak([first, failing, untried])

        assert world.realm == {failing, untried}
        assert world.log == ["keycloak", "keycloak"]
        message = caplog.records[-1].getMessage()
        assert f"Já apagados no realm: {first}." in message
        assert f"Talvez apagado (sem resposta): {failing}" in message
        assert f"Não tentados: {untried}." in message
