"""Testes da aprovação de empresa (`OrganizationApprovalService.approve`, E-3).

Sem banco, sem HTTP e sem Keycloak. O `OrganizationService` é o de verdade, sobre um
repository e um `DocumentService` em memória: a regra de "só pendente" é a do dono.

Duas montagens:

- `TestAprovacao` usa um dublê do `MemberService` que guarda o `MemberInvite` que
  recebeu. Prova o que vai no convite e quando ele não é chamado.
- `TestConviteQueFalha` usa o `MemberService` de verdade, sobre os mesmos dublês de
  `test_member_service.py` (repositories e Admin API em memória). Prova que o 409 do
  e-mail com acesso (P-077) e o 503 do Keycloak ou do SMTP fora do ar sobem com a
  mensagem do convite, sem tradução no caminho.

O que não passa por aqui é o rollback: quando o convite falha, a empresa já está
`active` no dublê, e quem desfaz a troca no banco é o `get_db`, que não roda sem
requisição. A prova é o passo do Mailpit parado no "Como verificar" do PR.
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.domains.documents.models import DocType, Document
from app.domains.links.models import Link
from app.domains.links.service import LinkService
from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.domains.organizacoes.service import OrganizationService
from app.domains.participants.models import Participant
from app.domains.participants.service import ParticipantService
from app.domains.users.models import User
from app.domains.users.schemas import MemberInvite
from app.domains.users.service import (
    CreatedUser,
    MemberService,
    OrganizationApprovalService,
    UserService,
)
from app.external_services.keycloak import admin as keycloak_admin
from app.external_services.keycloak.client import KeycloakUnavailableError
from app.shared.enums import LinkType, RecordStatus, Roles
from app.shared.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)

# O 503 do convite, como o `create_user_service` o escreve.
CREATE_UNAVAILABLE = "Não foi possível criar o acesso agora. Tente de novo."

# A organização de quem aprova (a da CREED) e a empresa pendente são diferentes.
OWN_ORGANIZATION_ID = uuid.UUID("3f2b8c1e-7a4d-4e9b-9c0a-5d6e7f8a9b0c")


def a_pending_organization(**fields: object) -> Organization:
    """Uma empresa como o cadastro público grava: pendente, com contato."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Empresa Teste",
        "address": "[A informar]",
        "document_id": uuid.uuid4(),
        "status": OrganizationStatus.PENDING,
        "email": "gestora@empresa.com.br",
        "contact_name": "Gestora Teste",
        "phone": "51 99999-0000",
        "created_at": datetime(2026, 11, 10, tzinfo=UTC),
        "updated_at": None,
    }
    return Organization(**{**defaults, **fields})


class FakeOrganizationRepository:
    """Só o que a ativação, o `with_documents` e o convite consultam."""

    def __init__(self, organizations: list[Organization]) -> None:
        self.items = {organization.id: organization for organization in organizations}
        self.saved: list[Organization] = []

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        return self.items.get(organization_id)

    async def save(self, organization: Organization) -> Organization:
        self.saved.append(organization)
        return organization


class FakeDocumentService:
    """O documento de cada organização recebida, como o cadastro o gravou."""

    def __init__(self, organizations: list[Organization]) -> None:
        self.documents = [
            Document(
                id=organization.document_id, type=DocType.CNPJ, value="12345678000190"
            )
            for organization in organizations
        ]

    async def list_by_ids(self, document_ids: list[uuid.UUID]) -> list[Document]:
        return [d for d in self.documents if d.id in document_ids]


def an_organization_service(organizations: list[Organization]) -> OrganizationService:
    return OrganizationService(
        FakeOrganizationRepository(organizations),  # type: ignore[arg-type]
        FakeDocumentService(organizations),  # type: ignore[arg-type]
    )


# --- Com o convite como dublê ---------------------------------------------------


class FakeMemberService:
    """Guarda o convite recebido e o status da empresa no momento da chamada."""

    def __init__(self, organization: Organization) -> None:
        self.organization = organization
        self.invites: list[MemberInvite] = []
        self.calls: list[dict[str, object]] = []

    async def invite_member_service(
        self,
        organization_id: uuid.UUID,
        request: MemberInvite,
        *,
        role: str,
        own_organization_id: uuid.UUID,
    ) -> CreatedUser:
        self.invites.append(request)
        self.calls.append(
            {
                "organization_id": organization_id,
                "role": role,
                "own_organization_id": own_organization_id,
                "status_at_invite": self.organization.status,
            }
        )
        user = User(
            id=uuid.uuid4(),
            keycloak_id=uuid.uuid4(),
            name=request.name,
            email=request.email,
            status=RecordStatus.ACTIVE,
            link_id=uuid.uuid4(),
        )
        return CreatedUser(
            user=user, role=request.role.value, organization_id=organization_id
        )


def with_fake_invite(
    organization: Organization,
) -> tuple[OrganizationApprovalService, FakeMemberService]:
    organizations = an_organization_service([organization])
    members = FakeMemberService(organization)
    service = OrganizationApprovalService(
        organizations,
        members,  # type: ignore[arg-type]
    )
    return service, members


class TestAprovacao:
    async def test_pendente_fica_ativa_e_volta_com_o_documento(self) -> None:
        organization = a_pending_organization()
        service, _ = with_fake_invite(organization)

        approved = await service.approve(
            organization.id, own_organization_id=OWN_ORGANIZATION_ID
        )

        assert approved.organization is organization
        assert organization.status is OrganizationStatus.ACTIVE
        assert (approved.document_type, approved.document_value) == (
            "cnpj",
            "12345678000190",
        )

    async def test_convida_o_responsavel_no_email_do_cadastro_como_gestor(
        self,
    ) -> None:
        """🟡 P-053 e P-047: gestor, vínculo `emprego`, em nome de quem cadastrou."""
        organization = a_pending_organization()
        service, members = with_fake_invite(organization)

        await service.approve(organization.id, own_organization_id=OWN_ORGANIZATION_ID)

        (invite,) = members.invites
        assert invite.name == "Gestora Teste"
        assert invite.email == "gestora@empresa.com.br"
        assert invite.role is Roles.GESTOR
        assert invite.type is LinkType.EMPREGO

    async def test_convida_na_empresa_aprovada_como_admin_e_depois_de_ativar(
        self,
    ) -> None:
        """Status antes do convite: se o convite falha, o `get_db` desfaz os dois."""
        organization = a_pending_organization()
        service, members = with_fake_invite(organization)

        await service.approve(organization.id, own_organization_id=OWN_ORGANIZATION_ID)

        assert members.calls == [
            {
                "organization_id": organization.id,
                "role": "admin",
                "own_organization_id": OWN_ORGANIZATION_ID,
                "status_at_invite": OrganizationStatus.ACTIVE,
            }
        ]

    @pytest.mark.parametrize(
        "status", [OrganizationStatus.ACTIVE, OrganizationStatus.INACTIVE]
    )
    async def test_que_nao_esta_pendente_e_conflito_sem_convite(
        self, status: OrganizationStatus
    ) -> None:
        """Aprovar de novo não manda um segundo convite."""
        organization = a_pending_organization(status=status)
        service, members = with_fake_invite(organization)

        with pytest.raises(ConflictError, match="não está pendente"):
            await service.approve(
                organization.id, own_organization_id=OWN_ORGANIZATION_ID
            )

        assert organization.status is status
        assert members.invites == []

    async def test_inexistente_e_not_found_sem_convite(self) -> None:
        service, members = with_fake_invite(a_pending_organization())
        unknown = uuid.uuid4()

        with pytest.raises(NotFoundError, match=str(unknown)):
            await service.approve(unknown, own_organization_id=OWN_ORGANIZATION_ID)

        assert members.invites == []

    @pytest.mark.parametrize("field", ["email", "contact_name"])
    async def test_pendente_sem_contato_e_conflito_sem_convite(self, field: str) -> None:
        """Só com o banco editado à mão: o cadastro público exige os dois."""
        organization = a_pending_organization(**{field: None})
        service, members = with_fake_invite(organization)

        with pytest.raises(ConflictError, match="e-mail ou responsável"):
            await service.approve(
                organization.id, own_organization_id=OWN_ORGANIZATION_ID
            )

        assert members.invites == []

    async def test_documento_que_falha_para_antes_do_convite(self) -> None:
        """O `with_documents` roda antes: se ele quebra, nenhum e-mail saiu."""
        organization = a_pending_organization()
        organizations = OrganizationService(
            FakeOrganizationRepository([organization]),  # type: ignore[arg-type]
            FakeDocumentService([]),  # type: ignore[arg-type]
        )
        members = FakeMemberService(organization)
        service = OrganizationApprovalService(
            organizations,
            members,  # type: ignore[arg-type]
        )

        with pytest.raises(RuntimeError, match="que não existe"):
            await service.approve(
                organization.id, own_organization_id=OWN_ORGANIZATION_ID
            )

        assert members.invites == []


# --- Com o convite de verdade ---------------------------------------------------


class FakeKeycloakAdmin:
    """Dublê de `app/external_services/keycloak/admin.py`: um realm em memória.

    `taken_emails` já existem no realm; `keycloak_down` faz a criação do usuário
    levantar `KeycloakUnavailableError`, como o Keycloak fora do ar; `smtp_down` faz
    o mesmo no envio do convite, como o SMTP fora do ar.
    """

    def __init__(self) -> None:
        self.users: dict[uuid.UUID, str] = {}
        self.taken_emails: set[str] = set()
        self.emails_sent: list[uuid.UUID] = []
        self.keycloak_down = False
        self.smtp_down = False

    async def create_user(self, email: str) -> uuid.UUID:
        if self.keycloak_down:
            raise KeycloakUnavailableError("Keycloak fora do ar")
        if email in self.taken_emails:
            raise keycloak_admin.KeycloakConflictError(email)
        keycloak_id = uuid.uuid4()
        self.users[keycloak_id] = email
        return keycloak_id

    async def assign_realm_role(self, keycloak_id: uuid.UUID, role: str) -> None:
        return None

    async def send_update_password_email(self, keycloak_id: uuid.UUID) -> None:
        if self.smtp_down:
            raise KeycloakUnavailableError("SMTP fora do ar")
        self.emails_sent.append(keycloak_id)

    async def delete_user(self, keycloak_id: uuid.UUID) -> None:
        self.users.pop(keycloak_id, None)


@pytest.fixture
def keycloak(monkeypatch: pytest.MonkeyPatch) -> FakeKeycloakAdmin:
    fake = FakeKeycloakAdmin()
    monkeypatch.setattr(keycloak_admin, "create_user", fake.create_user)
    monkeypatch.setattr(keycloak_admin, "assign_realm_role", fake.assign_realm_role)
    monkeypatch.setattr(
        keycloak_admin, "send_update_password_email", fake.send_update_password_email
    )
    monkeypatch.setattr(keycloak_admin, "delete_user", fake.delete_user)
    return fake


class FakeParticipantRepository:
    def __init__(self) -> None:
        self.items: list[Participant] = []

    async def get_by_id(self, participant_id: uuid.UUID) -> Participant | None:
        return next((p for p in self.items if p.id == participant_id), None)

    async def create(self, participant: Participant) -> Participant | None:
        participant.id = uuid.uuid4()
        self.items.append(participant)
        return participant


class FakeLinkRepository:
    def __init__(self) -> None:
        self.items: list[Link] = []

    async def insert(self, link: Link) -> Link:
        link.id = uuid.uuid4()
        self.items.append(link)
        return link

    async def get_by_id(self, link_id: uuid.UUID) -> Link | None:
        return next((v for v in self.items if v.id == link_id), None)


class FakeUserRepository:
    def __init__(self, existing: list[User] | None = None) -> None:
        self.items: list[User] = list(existing or [])

    async def get_user_by_email(self, user_email: str) -> User | None:
        return next((u for u in self.items if u.email == user_email), None)

    async def get_by_link_id(self, link_id: uuid.UUID) -> User | None:
        return next((u for u in self.items if u.link_id == link_id), None)

    async def create(self, user: User) -> User:
        self.items.append(user)
        return user


def with_real_invite(
    organization: Organization, users: FakeUserRepository | None = None
) -> OrganizationApprovalService:
    """Os services de verdade, como o `Scenario` de `test_member_service.py`."""
    organizations = an_organization_service([organization])
    participants = ParticipantService(
        FakeParticipantRepository(),  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
    )
    links = LinkService(
        FakeLinkRepository(),  # type: ignore[arg-type]
        participants,
        organizations,
        None,  # type: ignore[arg-type]
    )
    members = MemberService(
        UserService(users or FakeUserRepository(), links),  # type: ignore[arg-type]
        participants,
        links,
        organizations,
    )
    return OrganizationApprovalService(organizations, members)


class TestConviteQueFalha:
    """Os erros do convite sobem como vieram; o `get_db` desfaz a ativação."""

    async def test_aprova_e_manda_o_convite(self, keycloak: FakeKeycloakAdmin) -> None:
        organization = a_pending_organization()

        await with_real_invite(organization).approve(
            organization.id, own_organization_id=OWN_ORGANIZATION_ID
        )

        assert list(keycloak.users.values()) == ["gestora@empresa.com.br"]
        assert len(keycloak.emails_sent) == 1

    async def test_email_que_ja_tem_acesso_sobe_o_conflito(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """🟡 P-077: o cadastro não confere o e-mail; a aprovação, sim."""
        existing = User(
            id=uuid.uuid4(),
            keycloak_id=uuid.uuid4(),
            name="Outra Pessoa",
            email="gestora@empresa.com.br",
            status=RecordStatus.ACTIVE,
            link_id=uuid.uuid4(),
        )
        organization = a_pending_organization()
        service = with_real_invite(organization, FakeUserRepository([existing]))

        with pytest.raises(
            ConflictError,
            match=re.escape("Já existe usuário com o e-mail gestora@empresa.com.br"),
        ):
            await service.approve(
                organization.id, own_organization_id=OWN_ORGANIZATION_ID
            )

        assert keycloak.users == {}
        assert keycloak.emails_sent == []

    async def test_email_que_ja_existe_no_realm_sobe_o_conflito(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """A segunda mensagem do mesmo 409: o acesso existe só no Keycloak."""
        keycloak.taken_emails.add("gestora@empresa.com.br")
        organization = a_pending_organization()

        with pytest.raises(
            ConflictError,
            match=re.escape("Já existe acesso com o e-mail gestora@empresa.com.br"),
        ):
            await with_real_invite(organization).approve(
                organization.id, own_organization_id=OWN_ORGANIZATION_ID
            )

        assert keycloak.emails_sent == []

    async def test_smtp_fora_sobe_indisponivel_e_desfaz_no_keycloak(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        keycloak.smtp_down = True
        organization = a_pending_organization()

        with pytest.raises(ServiceUnavailableError, match=re.escape(CREATE_UNAVAILABLE)):
            await with_real_invite(organization).approve(
                organization.id, own_organization_id=OWN_ORGANIZATION_ID
            )

        assert keycloak.users == {}

    async def test_keycloak_fora_sobe_indisponivel_sem_usuario_no_realm(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """Cai no `create_user`: ainda não há usuário no realm para desfazer."""
        keycloak.keycloak_down = True
        organization = a_pending_organization()

        with pytest.raises(ServiceUnavailableError, match=re.escape(CREATE_UNAVAILABLE)):
            await with_real_invite(organization).approve(
                organization.id, own_organization_id=OWN_ORGANIZATION_ID
            )

        assert keycloak.users == {}
        assert keycloak.emails_sent == []
