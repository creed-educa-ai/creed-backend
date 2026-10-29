"""Testes de scripts/convidar_primeiro_admin.py: o primeiro admin por convite (P-052).

Sem banco e sem Keycloak. Os services são os de verdade — `MemberService`,
`UserService`, `OrganizationService`, `ParticipantService` e `LinkService` —, e só a
sessão, os repositories e a Admin API são dublês em memória. O que se prova é o que o
script decide: o que cria, quando só reenvia, e que só faz commit quando tudo deu
certo.

O que não passa por aqui é o rollback: quando o convite falha, participante e vínculo
já estão nos dublês, e quem os desfaz no banco é a sessão fechada sem commit. Que o
INSERT passa no Postgres, só rodando o script num banco que já tem `organizations`
(CREED-57).

Os dublês são deste arquivo, como em todo arquivo de teste do repo.
"""

import uuid

import pydantic
import pytest

from app.domains.documents.models import DocType, Document
from app.domains.links.models import Link
from app.domains.links.service import LinkService
from app.domains.organizacoes.models import Organization
from app.domains.organizacoes.service import OrganizationService
from app.domains.participants.models import Participant
from app.domains.participants.service import ParticipantService
from app.domains.users.models import User
from app.domains.users.service import MemberService, UserService
from app.external_services.keycloak import admin as keycloak_admin
from app.external_services.keycloak.client import KeycloakUnavailableError
from app.shared.enums import LinkType, RecordStatus, Roles
from app.shared.exceptions import ConflictError, ServiceUnavailableError
from scripts import seed_local
from scripts.convidar_primeiro_admin import (
    CREED_ORGANIZATION_DOCUMENT_ID,
    CREED_ORGANIZATION_ID,
    invite_first_admin,
    parse_invite,
)

OTHER_ORGANIZATION_ID = uuid.UUID("0b6a4c2e-1d3f-4e5a-9b8c-7d6e5f4a3b2c")


class FakeKeycloakAdmin:
    """Dublê de `app/external_services/keycloak/admin.py`: um realm em memória.

    `users` é o que existe no realm (`keycloak_id -> e-mail`), `roles` é o papel dado
    a cada um e `emails_sent` é cada envio do e-mail de convite. Com `smtp_down`, o
    envio levanta `KeycloakUnavailableError`, como o SMTP fora do ar.
    """

    def __init__(self) -> None:
        self.users: dict[uuid.UUID, str] = {}
        self.roles: dict[uuid.UUID, str] = {}
        self.emails_sent: list[uuid.UUID] = []
        self.smtp_down = False

    async def create_user(self, email: str) -> uuid.UUID:
        if email in self.users.values():
            raise keycloak_admin.KeycloakConflictError("409")
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


class FakeSession:
    """Só o que o script usa da sessão: o documento (`get`, `add`, `flush`) e o
    `commit`, que aqui só é contado."""

    def __init__(self) -> None:
        self.documents: list[Document] = []
        self.commits = 0

    async def get(self, model: type[Document], document_id: uuid.UUID) -> Document | None:
        return next((d for d in self.documents if d.id == document_id), None)

    def add(self, document: Document) -> None:
        self.documents.append(document)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1


class FakeOrganizationRepository:
    """Com `document_taken`, o `create` devolve `None`, como o de verdade quando o
    documento já está ligado a outra organização (`uq_organizations_document_id`)."""

    def __init__(self) -> None:
        self.items: list[Organization] = []
        self.document_taken = False

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        return next((o for o in self.items if o.id == organization_id), None)

    async def create(self, organization: Organization) -> Organization | None:
        if self.document_taken:
            return None
        self.items.append(organization)
        return organization


class FakeParticipantRepository:
    """Guarda em lista. O id é dado aqui, como o default do model no flush."""

    def __init__(self) -> None:
        self.items: list[Participant] = []

    async def get_by_id(self, participant_id: uuid.UUID) -> Participant | None:
        return next((p for p in self.items if p.id == participant_id), None)

    async def create(self, participant: Participant) -> Participant:
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
    """Guarda em lista. A busca por e-mail é exata, como a do repository de verdade."""

    def __init__(self) -> None:
        self.items: list[User] = []

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return next((u for u in self.items if u.id == user_id), None)

    async def get_user_by_email(self, user_email: str) -> User | None:
        return next((u for u in self.items if u.email == user_email), None)

    async def get_by_link_id(self, link_id: uuid.UUID) -> User | None:
        return next((u for u in self.items if u.link_id == link_id), None)

    async def create(self, user: User) -> User:
        user.id = uuid.uuid4()
        self.items.append(user)
        return user


class Scenario:
    """Um ambiente em memória, com os services de verdade sobre os dublês."""

    def __init__(self) -> None:
        self.session = FakeSession()
        self.organizations = FakeOrganizationRepository()
        self.participants = FakeParticipantRepository()
        self.links = FakeLinkRepository()
        self.users = FakeUserRepository()

        # Sem `DocumentService`: o convite não traz documento, então ele não é chamado.
        participant_service = ParticipantService(
            self.participants,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
        link_service = LinkService(self.links, participant_service)  # type: ignore[arg-type]
        self.user_service = UserService(self.users, link_service)  # type: ignore[arg-type]
        self.member_service = MemberService(
            self.user_service,
            participant_service,
            link_service,
            OrganizationService(self.organizations, None),  # type: ignore[arg-type]
        )

    async def run(
        self, email: str = "admin@exemplo.com", name: str = "Admin Exemplo"
    ) -> bool:
        invite = parse_invite(["--email", email, "--nome", name])
        return await invite_first_admin(
            self.session,  # type: ignore[arg-type]
            self.organizations,  # type: ignore[arg-type]
            self.user_service,
            self.member_service,
            invite,
        )

    def existing_user(
        self, email: str, *, role: Roles, organization_id: uuid.UUID, status: RecordStatus
    ) -> User:
        """Um acesso que já estava no banco antes do script, com o vínculo dele."""
        link = Link(
            id=uuid.uuid4(),
            organization_id=organization_id,
            participant_id=uuid.uuid4(),
            type=LinkType.EMPREGO,
            role=role,
        )
        self.links.items.append(link)
        user = User(
            id=uuid.uuid4(),
            keycloak_id=uuid.uuid4(),
            name="Pessoa Exemplo",
            email=email,
            status=status,
            link_id=link.id,
        )
        self.users.items.append(user)
        return user


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


class TestPrimeiraExecucao:
    async def test_cria_a_organizacao_da_creed_com_o_documento(
        self, scenario: Scenario
    ) -> None:
        await scenario.run()

        [organization] = scenario.organizations.items
        [document] = scenario.session.documents
        assert organization.id == CREED_ORGANIZATION_ID
        assert organization.document_id == document.id == CREED_ORGANIZATION_DOCUMENT_ID

    async def test_documento_e_sintetico(self, scenario: Scenario) -> None:
        """🟡 P-048 — `other`, com valor que não pode parecer um CNPJ real."""
        await scenario.run()

        [document] = scenario.session.documents
        assert document.type is DocType.OTHER
        assert not document.value.isdigit()

    async def test_cria_participante_vinculo_admin_e_acesso_na_organizacao_da_creed(
        self, scenario: Scenario
    ) -> None:
        assert await scenario.run(name="Admin Exemplo")

        [participant] = scenario.participants.items
        [link] = scenario.links.items
        [user] = scenario.users.items
        assert participant.name == user.name == "Admin Exemplo"
        assert link.participant_id == participant.id
        assert link.organization_id == CREED_ORGANIZATION_ID
        assert link.role is Roles.ADMIN
        assert link.type is LinkType.EMPREGO
        assert user.link_id == link.id

    async def test_cria_no_realm_com_o_papel_admin_e_manda_o_convite(
        self, scenario: Scenario, keycloak: FakeKeycloakAdmin
    ) -> None:
        await scenario.run()

        [user] = scenario.users.items
        assert keycloak.users == {user.keycloak_id: "admin@exemplo.com"}
        assert keycloak.roles[user.keycloak_id] == "admin"
        assert keycloak.emails_sent == [user.keycloak_id]

    async def test_faz_um_commit_no_fim(self, scenario: Scenario) -> None:
        await scenario.run()

        assert scenario.session.commits == 1

    async def test_avisa_para_olhar_o_spam(
        self, scenario: Scenario, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A conta do Gmail é nova, e o primeiro e-mail de teste caiu no spam."""
        await scenario.run()

        assert "spam" in capsys.readouterr().out


class TestSegundaExecucao:
    async def test_mesmo_email_nao_cria_nada_e_reenvia_o_convite(
        self, scenario: Scenario, keycloak: FakeKeycloakAdmin
    ) -> None:
        await scenario.run()

        assert not await scenario.run()

        [user] = scenario.users.items
        assert len(scenario.organizations.items) == 1
        assert len(scenario.session.documents) == 1
        assert len(scenario.participants.items) == 1
        assert len(scenario.links.items) == 1
        assert len(keycloak.users) == 1
        assert keycloak.emails_sent == [user.keycloak_id, user.keycloak_id]
        assert scenario.session.commits == 2

    async def test_email_com_maiusculas_cai_no_reenvio(
        self, scenario: Scenario, keycloak: FakeKeycloakAdmin
    ) -> None:
        """O banco guarda em minúsculas e a busca é exata (decisão de 28/10, opção A).

        Sem o `lower()`, o script tentaria criar de novo e pararia no 409.
        """
        await scenario.run(email="admin@exemplo.com")

        assert not await scenario.run(email="Admin@Exemplo.com")

        assert len(scenario.users.items) == 1
        assert len(keycloak.emails_sent) == 2

    async def test_outro_email_cria_outro_admin_na_mesma_organizacao(
        self, scenario: Scenario, keycloak: FakeKeycloakAdmin
    ) -> None:
        await scenario.run(email="admin@exemplo.com")

        assert await scenario.run(email="outra@exemplo.com", name="Outra Pessoa")

        assert len(scenario.organizations.items) == 1
        assert len(scenario.session.documents) == 1
        assert [u.email for u in scenario.users.items] == [
            "admin@exemplo.com",
            "outra@exemplo.com",
        ]
        assert all(
            link.organization_id == CREED_ORGANIZATION_ID for link in scenario.links.items
        )
        assert all(link.role is Roles.ADMIN for link in scenario.links.items)
        assert len(keycloak.emails_sent) == 2


class TestQuemJaTemAcesso:
    async def test_acesso_de_outro_papel_so_recebe_o_convite_de_novo(
        self,
        scenario: Scenario,
        keycloak: FakeKeycloakAdmin,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """🟡 P-060 — o script não muda papel nem organização de quem já tem acesso."""
        user = scenario.existing_user(
            "gestora@exemplo.com",
            role=Roles.GESTOR,
            organization_id=OTHER_ORGANIZATION_ID,
            status=RecordStatus.ACTIVE,
        )

        assert not await scenario.run(email="gestora@exemplo.com")

        [link] = scenario.links.items
        assert link.role is Roles.GESTOR
        assert link.organization_id == OTHER_ORGANIZATION_ID
        assert keycloak.emails_sent == [user.keycloak_id]
        assert "papel gestor" in capsys.readouterr().out

    async def test_acesso_inativo_para_no_conflito_sem_mandar_e_mail(
        self, scenario: Scenario, keycloak: FakeKeycloakAdmin
    ) -> None:
        """🟡 P-060 — o script não reativa acesso. Sem commit, o banco volta."""
        scenario.existing_user(
            "inativa@exemplo.com",
            role=Roles.ADMIN,
            organization_id=CREED_ORGANIZATION_ID,
            status=RecordStatus.INACTIVE,
        )

        with pytest.raises(ConflictError):
            await scenario.run(email="inativa@exemplo.com")

        assert keycloak.emails_sent == []
        assert keycloak.users == {}
        assert scenario.session.commits == 0


class TestFalhas:
    async def test_smtp_fora_do_ar_nao_deixa_nada_no_realm_nem_faz_commit(
        self, scenario: Scenario, keycloak: FakeKeycloakAdmin
    ) -> None:
        """O tudo ou nada é o do `create_user_service` (D7): o realm é desfeito lá, e
        o banco volta porque a sessão fecha sem commit."""
        keycloak.smtp_down = True

        with pytest.raises(ServiceUnavailableError):
            await scenario.run()

        assert keycloak.users == {}
        assert scenario.session.commits == 0

    async def test_email_que_so_existe_no_realm_e_conflito_sem_commit(
        self, scenario: Scenario, keycloak: FakeKeycloakAdmin
    ) -> None:
        """Um acesso criado à mão no realm, ou que sobrou de uma falha: não é
        reaproveitado (spec, D7)."""
        keycloak.users[uuid.uuid4()] = "admin@exemplo.com"

        with pytest.raises(ConflictError):
            await scenario.run()

        assert keycloak.emails_sent == []
        assert scenario.session.commits == 0

    async def test_reenvio_com_smtp_fora_do_ar_nao_faz_commit(
        self, scenario: Scenario, keycloak: FakeKeycloakAdmin
    ) -> None:
        await scenario.run()
        keycloak.smtp_down = True

        with pytest.raises(ServiceUnavailableError):
            await scenario.run()

        assert scenario.session.commits == 1

    async def test_documento_da_creed_em_outra_organizacao_para_sem_commit(
        self, scenario: Scenario, keycloak: FakeKeycloakAdmin
    ) -> None:
        """O `create` devolve `None` no conflito do documento: o script para ali, sem
        dizer "criada", sem chegar ao Keycloak e sem commit."""
        scenario.organizations.document_taken = True

        with pytest.raises(ConflictError, match="já pertence a outra organização"):
            await scenario.run()

        assert scenario.organizations.items == []
        assert keycloak.users == {}
        assert keycloak.emails_sent == []
        assert scenario.session.commits == 0


class TestArgumentos:
    def test_papel_e_sempre_admin_e_o_vinculo_emprego(self) -> None:
        invite = parse_invite(
            ["--email", "admin@exemplo.com", "--nome", " Admin Exemplo "]
        )

        assert invite.role is Roles.ADMIN
        assert invite.type is LinkType.EMPREGO
        assert invite.name == "Admin Exemplo"

    def test_email_invalido_e_recusado_antes_de_tocar_em_qualquer_coisa(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            parse_invite(["--email", "nao-e-email", "--nome", "Admin Exemplo"])

    def test_nome_e_obrigatorio(self) -> None:
        with pytest.raises(SystemExit):
            parse_invite(["--email", "admin@exemplo.com"])


def test_ids_fixos_nao_colidem_com_os_do_seed() -> None:
    """No ambiente local, a organização da CREED convive com a de dev do seed."""
    seed_ids = {
        seed_local.ORGANIZATION_ID,
        seed_local.ORGANIZATION_DOCUMENT_ID,
        seed_local.PARTICIPANT_ID,
        seed_local.DEMO_FORM_ID,
    }

    assert CREED_ORGANIZATION_ID not in seed_ids
    assert CREED_ORGANIZATION_DOCUMENT_ID not in seed_ids
