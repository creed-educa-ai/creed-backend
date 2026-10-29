"""Testes do `MemberService`, o convite de membro (CREED-23.8, D8).

Sem banco, sem HTTP e sem Keycloak. Os services são os de verdade —
`OrganizationService`, `ParticipantService`, `LinkService` e `UserService` —, e só
os repositories e a Admin API são dublês em memória. Assim a regra de quem convida
quem (P-045, P-033) é a do dono da organização, e o tudo ou nada do acesso (D7) é o
do `create_user_service`, sem cópia nos dublês.

Os dublês são deste arquivo, como em todo arquivo de teste do repo, e têm só o que
o convite usa.

O que não passa por aqui é o rollback: quando o acesso falha, participante e vínculo
já estão nos dublês, e quem os desfaz no banco é o `get_db`, que não roda sem
requisição. Que ele desfaz quando a rota levanta `HTTPException` está provado em
tests/test_database.py.
"""

import re
import uuid

import pytest

from app.domains.links.models import Link
from app.domains.links.service import LinkService
from app.domains.organizacoes.models import Organization
from app.domains.organizacoes.service import OrganizationService
from app.domains.participants.models import Participant
from app.domains.participants.service import ParticipantService
from app.domains.users.models import User
from app.domains.users.schemas import MemberInvite
from app.domains.users.service import CreatedUser, MemberService, UserService
from app.external_services.keycloak import admin as keycloak_admin
from app.external_services.keycloak.client import KeycloakUnavailableError
from app.shared.enums import LinkType, RecordStatus, Roles
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)

OWN_ORGANIZATION_ID = uuid.UUID("8f14e45f-ceea-467e-adde-3f81905dbc1c")
OTHER_ORGANIZATION_ID = uuid.UUID("0b6a4c2e-1d3f-4e5a-9b8c-7d6e5f4a3b2c")


class FakeKeycloakAdmin:
    """Dublê de `app/external_services/keycloak/admin.py`: um realm em memória.

    `users` é o que existe no realm (`keycloak_id -> e-mail`), `roles` é o papel dado
    a cada um, `emails_sent` é quem recebeu o convite e `deleted` é quem a
    compensação apagou. Com `smtp_down`, o envio do convite levanta
    `KeycloakUnavailableError`, como o SMTP fora do ar.
    """

    def __init__(self) -> None:
        self.users: dict[uuid.UUID, str] = {}
        self.roles: dict[uuid.UUID, str] = {}
        self.emails_sent: list[uuid.UUID] = []
        self.deleted: list[uuid.UUID] = []
        self.smtp_down = False

    async def create_user(self, email: str) -> uuid.UUID:
        keycloak_id = uuid.uuid4()
        self.users[keycloak_id] = email
        return keycloak_id

    async def assign_realm_role(self, keycloak_id: uuid.UUID, role: str) -> None:
        self.roles[keycloak_id] = role

    async def send_update_password_email(self, keycloak_id: uuid.UUID) -> None:
        if self.smtp_down:
            raise KeycloakUnavailableError("SMTP fora do ar")
        self.emails_sent.append(keycloak_id)

    async def delete_user(self, keycloak_id: uuid.UUID) -> None:
        self.users.pop(keycloak_id, None)
        self.deleted.append(keycloak_id)


@pytest.fixture(autouse=True)
def keycloak(monkeypatch: pytest.MonkeyPatch) -> FakeKeycloakAdmin:
    """Autouse: nenhum teste deste arquivo pode chegar a um Keycloak de verdade."""
    fake = FakeKeycloakAdmin()
    monkeypatch.setattr(keycloak_admin, "create_user", fake.create_user)
    monkeypatch.setattr(keycloak_admin, "assign_realm_role", fake.assign_realm_role)
    monkeypatch.setattr(
        keycloak_admin, "send_update_password_email", fake.send_update_password_email
    )
    monkeypatch.setattr(keycloak_admin, "delete_user", fake.delete_user)
    return fake


class FakeOrganizationRepository:
    """Só as organizações cujos ids recebeu."""

    def __init__(self, ids: list[uuid.UUID]) -> None:
        self.items = {
            organization_id: Organization(
                id=organization_id,
                name="Organização Exemplo",
                address="Av. Ipiranga, 6681, Porto Alegre",
                document_id=uuid.uuid4(),
                status=RecordStatus.ACTIVE,
            )
            for organization_id in ids
        }

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        return self.items.get(organization_id)


class FakeParticipantRepository:
    """Guarda em lista. O id é dado aqui, como o default do model no flush."""

    def __init__(self) -> None:
        self.items: list[Participant] = []

    async def get_by_id(self, participant_id: uuid.UUID) -> Participant | None:
        return next((p for p in self.items if p.id == participant_id), None)

    async def get_by_document_id(self, document_id: uuid.UUID) -> Participant | None:
        return next((p for p in self.items if p.document_id == document_id), None)

    async def create(self, participant: Participant) -> Participant | None:
        participant.id = uuid.uuid4()
        self.items.append(participant)
        return participant


class FakeLinkRepository:
    """Guarda em lista. O id é dado aqui, como o default do model no flush."""

    def __init__(self) -> None:
        self.items: list[Link] = []

    async def insert(self, link: Link) -> Link:
        link.id = uuid.uuid4()
        self.items.append(link)
        return link

    async def get_by_id(self, link_id: uuid.UUID) -> Link | None:
        return next((v for v in self.items if v.id == link_id), None)


class FakeUserRepository:
    """Guarda em lista, não decide nada: só o que o `create_user_service` consulta."""

    def __init__(self, existing: list[User] | None = None) -> None:
        self.items: list[User] = list(existing or [])

    async def get_user_by_email(self, user_email: str) -> User | None:
        return next((u for u in self.items if u.email == user_email), None)

    async def get_by_link_id(self, link_id: uuid.UUID) -> User | None:
        return next((u for u in self.items if u.link_id == link_id), None)

    async def create(self, user: User) -> User:
        self.items.append(user)
        return user


class Scenario:
    """Os quatro services de verdade, sobre repositories em memória."""

    def __init__(self, users: FakeUserRepository | None = None) -> None:
        self.organizations = FakeOrganizationRepository(
            [OWN_ORGANIZATION_ID, OTHER_ORGANIZATION_ID]
        )
        self.participants = FakeParticipantRepository()
        self.links = FakeLinkRepository()
        self.users = users or FakeUserRepository()

        # Sem `DocumentService`: o convite não traz documento, então ele não é chamado.
        participant_service = ParticipantService(
            self.participants,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
        link_service = LinkService(self.links, participant_service)  # type: ignore[arg-type]
        self.service = MemberService(
            UserService(self.users, link_service),  # type: ignore[arg-type]
            participant_service,
            link_service,
            OrganizationService(self.organizations, None),  # type: ignore[arg-type]
        )

    async def invite(
        self,
        organization_id: uuid.UUID = OWN_ORGANIZATION_ID,
        *,
        caller_role: str = "admin",
        **body: object,
    ) -> CreatedUser:
        request = MemberInvite.model_validate(
            {
                "name": "Pessoa Exemplo",
                "email": "pessoa@exemplo.com",
                "role": "respondente",
                **body,
            }
        )
        return await self.service.invite_member_service(
            organization_id,
            request,
            role=caller_role,
            own_organization_id=OWN_ORGANIZATION_ID,
        )

    def nothing_was_created(self) -> bool:
        return not (self.participants.items or self.links.items or self.users.items)


class TestAdmin:
    async def test_cria_participante_vinculo_e_acesso_e_convida(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        scenario = Scenario()

        await scenario.invite(OTHER_ORGANIZATION_ID, role="gestor")

        (participant,) = scenario.participants.items
        (link,) = scenario.links.items
        (user,) = scenario.users.items
        # 🟡 P-046: o mesmo nome no participante e no usuário.
        assert participant.name == "Pessoa Exemplo"
        assert user.name == "Pessoa Exemplo"
        assert link.participant_id == participant.id
        assert link.organization_id == OTHER_ORGANIZATION_ID
        assert link.role is Roles.GESTOR
        assert user.link_id == link.id
        assert keycloak.roles == {user.keycloak_id: "gestor"}
        assert keycloak.emails_sent == [user.keycloak_id]

    async def test_devolve_o_acesso_com_papel_e_organizacao_do_vinculo(self) -> None:
        scenario = Scenario()

        created = await scenario.invite(OTHER_ORGANIZATION_ID, role="admin")

        (user,) = scenario.users.items
        assert created.user is user
        assert created.role == "admin"
        assert created.organization_id == OTHER_ORGANIZATION_ID

    async def test_sem_type_o_vinculo_e_emprego(self) -> None:
        """🟡 P-047."""
        scenario = Scenario()

        await scenario.invite()

        assert scenario.links.items[0].type is LinkType.EMPREGO

    async def test_type_mentoria_cria_vinculo_de_mentoria(self) -> None:
        """🟡 P-048: o mentorando é um vínculo `mentoria`."""
        scenario = Scenario()

        await scenario.invite(type="mentoria")

        assert scenario.links.items[0].type is LinkType.MENTORIA

    async def test_organizacao_inativa_recebe_convite(self) -> None:
        """🟡 P-057: o convite não confere o status da organização.

        Se a cliente disser que inativa bloqueia, é esta asserção que muda.
        """
        scenario = Scenario()
        organization = scenario.organizations.items[OWN_ORGANIZATION_ID]
        organization.status = RecordStatus.INACTIVE

        await scenario.invite()

        (link,) = scenario.links.items
        assert link.organization_id == OWN_ORGANIZATION_ID
        assert len(scenario.users.items) == 1

    async def test_organizacao_inexistente_e_not_found_sem_criar_nada(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        scenario = Scenario()
        unknown = uuid.uuid4()

        with pytest.raises(NotFoundError, match=str(unknown)):
            await scenario.invite(unknown)

        assert scenario.nothing_was_created()
        assert keycloak.users == {}


class TestGestor:
    @pytest.mark.parametrize("role", ["gestor", "respondente"])
    async def test_convida_na_propria_organizacao(
        self, role: str, keycloak: FakeKeycloakAdmin
    ) -> None:
        scenario = Scenario()

        await scenario.invite(caller_role="gestor", role=role)

        assert scenario.links.items[0].organization_id == OWN_ORGANIZATION_ID
        assert list(keycloak.roles.values()) == [role]

    async def test_outra_organizacao_e_forbidden_sem_criar_nada(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        scenario = Scenario()

        with pytest.raises(ForbiddenError):
            await scenario.invite(OTHER_ORGANIZATION_ID, caller_role="gestor")

        assert scenario.nothing_was_created()
        assert keycloak.users == {}

    async def test_organizacao_inexistente_alheia_e_forbidden_antes_de_not_found(
        self,
    ) -> None:
        """P-033: a resposta não revela quais organizações existem."""
        scenario = Scenario()

        with pytest.raises(ForbiddenError):
            await scenario.invite(uuid.uuid4(), caller_role="gestor")

    async def test_convidar_admin_e_forbidden_sem_criar_nada(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """🟡 P-045: o gestor não cria administrador da plataforma."""
        scenario = Scenario()

        with pytest.raises(ForbiddenError, match="admin"):
            await scenario.invite(caller_role="gestor", role="admin")

        assert scenario.nothing_was_created()
        assert keycloak.users == {}


class TestAcesso:
    async def test_email_com_maiusculas_e_gravado_em_minusculas(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        scenario = Scenario()

        await scenario.invite(email="Pessoa@Exemplo.com")

        (user,) = scenario.users.items
        assert user.email == "pessoa@exemplo.com"
        assert keycloak.users == {user.keycloak_id: "pessoa@exemplo.com"}

    async def test_email_que_ja_tem_acesso_e_conflito_sem_chegar_ao_keycloak(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """Com outra caixa, o mesmo e-mail.

        Participante e vínculo ficam nos dublês; no banco, saem pelo rollback do
        `get_db`, não provado aqui.
        """
        existing = User(
            id=uuid.uuid4(),
            keycloak_id=uuid.uuid4(),
            name="Pessoa Exemplo",
            email="pessoa@exemplo.com",
            status=RecordStatus.ACTIVE,
            link_id=uuid.uuid4(),
        )
        scenario = Scenario(FakeUserRepository([existing]))

        with pytest.raises(ConflictError, match=re.escape("pessoa@exemplo.com")):
            await scenario.invite(email="Pessoa@exemplo.com")

        assert scenario.users.items == [existing]
        assert keycloak.users == {}
        assert keycloak.emails_sent == []

    async def test_smtp_fora_e_indisponivel_e_desfaz_no_keycloak(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        scenario = Scenario()
        keycloak.smtp_down = True

        with pytest.raises(ServiceUnavailableError):
            await scenario.invite()

        assert keycloak.users == {}
        assert len(keycloak.deleted) == 1


def test_member_invite_sem_type_tem_emprego_e_tira_espacos_do_nome() -> None:
    invite = MemberInvite.model_validate(
        {"name": "  Pessoa Exemplo  ", "email": "pessoa@exemplo.com", "role": "gestor"}
    )

    assert invite.type is LinkType.EMPREGO
    assert invite.name == "Pessoa Exemplo"


@pytest.mark.parametrize(
    "body",
    [
        {"role": "superadmin"},
        {"type": "estagio"},
        {"name": "A"},
        {"name": "   "},
        {"name": "Pessoa\x00Exemplo"},
        {"email": "nao-e-email"},
    ],
    ids=["papel", "tipo", "nome_curto", "nome_em_branco", "controle", "email"],
)
def test_member_invite_recusa_entrada_invalida(body: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        MemberInvite.model_validate(
            {
                "name": "Pessoa Exemplo",
                "email": "pessoa@exemplo.com",
                "role": "gestor",
                **body,
            }
        )
