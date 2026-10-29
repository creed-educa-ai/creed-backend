"""Testes do service do domínio users.

Sem banco, sem HTTP e sem Keycloak: repository, `LinkService` e a Admin API
(`keycloak_admin`) são substituídos por dublês em memória, que é o que a separação de
camadas do ADR-0004 compra. O que se prova aqui é a regra de negócio — conflito de
e-mail, vínculo inexistente ou já usado, usuário inexistente, o status de nascimento
(P-013), o tudo ou nada do cadastro (D7), o recorte do reenvio de convite por
organização e o reset que não diz se o e-mail tem acesso. O mapeamento para o
Postgres não passa por aqui, e o rollback do banco é do `get_db`, não do service.
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.domains.links.models import Link
from app.domains.users.models import User
from app.domains.users.schemas import UserCreate, UserResponse
from app.domains.users.service import UserService
from app.external_services.keycloak import admin as keycloak_admin
from app.external_services.keycloak.client import KeycloakUnavailableError
from app.shared.enums import LinkType, RecordStatus, Roles
from app.shared.exceptions import ConflictError, NotFoundError, ServiceUnavailableError


class FakeUserRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(self, existentes: list[User] | None = None) -> None:
        self.itens: list[User] = list(existentes or [])
        self.removidos: list[User] = []

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return next((u for u in self.itens if u.id == user_id), None)

    async def get_user_by_email(self, user_email: str) -> User | None:
        return next((u for u in self.itens if u.email == user_email), None)

    async def get_by_link_id(self, link_id: uuid.UUID) -> User | None:
        return next((u for u in self.itens if u.link_id == link_id), None)

    async def create(self, user: User) -> User:
        self.itens.append(user)
        return user

    async def delete(self, user: User) -> None:
        self.itens.remove(user)
        self.removidos.append(user)


class FakeIntegrityError(Exception):
    """Faz as vezes do `IntegrityError` que o flush levantaria."""


class FailingInsertRepository(FakeUserRepository):
    """O INSERT falha, como uma constraint que o banco recusa no flush."""

    async def create(self, user: User) -> User:
        raise FakeIntegrityError("duplicate key value violates unique constraint")


class FailingDeleteRepository(FakeUserRepository):
    """O DELETE falha no flush, como a FK de `dashboards.user_id` sem `ondelete`."""

    async def delete(self, user: User) -> None:
        raise FakeIntegrityError("update or delete violates foreign key constraint")


class FakeLinkService:
    """Dublê do `LinkService`: um dicionário `id -> Link`."""

    def __init__(self, existing: list[Link] | None = None) -> None:
        self.items: dict[uuid.UUID, Link] = {v.id: v for v in (existing or [])}

    async def get_link_by_id_service(self, link_id: uuid.UUID) -> Link | None:
        return self.items.get(link_id)


class FakeKeycloakAdmin:
    """Dublê de `app/external_services/keycloak/admin.py`: um realm em memória.

    `users` é o que existe no realm (`keycloak_id -> e-mail`). Pôr o nome de uma
    função em `failing` faz ela levantar `KeycloakUnavailableError`, como o Keycloak
    ou o SMTP fora do ar.
    """

    def __init__(self) -> None:
        self.users: dict[uuid.UUID, str] = {}
        self.roles: dict[uuid.UUID, str] = {}
        self.emails_sent: list[uuid.UUID] = []
        self.deleted: list[uuid.UUID] = []
        self.failing: set[str] = set()

    async def create_user(self, email: str) -> uuid.UUID:
        if "create_user" in self.failing:
            raise KeycloakUnavailableError("fora do ar")
        if email in self.users.values():
            raise keycloak_admin.KeycloakConflictError("409 User exists")
        keycloak_id = uuid.uuid4()
        self.users[keycloak_id] = email
        return keycloak_id

    async def assign_realm_role(self, keycloak_id: uuid.UUID, role: str) -> None:
        if "assign_realm_role" in self.failing:
            raise KeycloakUnavailableError("fora do ar")
        self.roles[keycloak_id] = role

    async def send_update_password_email(self, keycloak_id: uuid.UUID) -> None:
        if "send_update_password_email" in self.failing:
            raise KeycloakUnavailableError("SMTP fora do ar")
        self.emails_sent.append(keycloak_id)

    async def delete_user(self, keycloak_id: uuid.UUID) -> None:
        if "delete_user" in self.failing:
            raise KeycloakUnavailableError("fora do ar")
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


def make_link(**fields: object) -> Link:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "participant_id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "department_id": None,
        "type": LinkType.EMPREGO,
        "role": Roles.RESPONDENTE,
        "start_at": datetime(2026, 9, 24, tzinfo=UTC),
        "end_at": None,
        "created_at": datetime(2026, 9, 24, tzinfo=UTC),
        "updated_at": None,
    }
    return Link(**{**defaults, **fields})


def um_user(**campos: object) -> User:
    """User montado à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados no
    INSERT, então um User que nunca passou pela sessão tem `None` neles.

    `link_id` vem preenchido por padrão: a coluna é `NOT NULL`.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "keycloak_id": uuid.uuid4(),
        "name": "Naira Libermann",
        "email": "naira@pucrs.br",
        "status": RecordStatus.ACTIVE,
        "link_id": uuid.uuid4(),
        "created_at": datetime(2026, 9, 13, tzinfo=UTC),
    }
    return User(**{**padrao, **campos})


def um_cadastro(link_id: uuid.UUID, **campos: object) -> UserCreate:
    padrao: dict[str, object] = {
        "name": "Naira Libermann",
        "email": "naira@pucrs.br",
        "link_id": link_id,
    }
    return UserCreate.model_validate({**padrao, **campos})


def servico(
    repository: FakeUserRepository, links: FakeLinkService | None = None
) -> UserService:
    return UserService(repository, links or FakeLinkService())  # type: ignore[arg-type]


class TestCriarUsuario:
    async def test_cria_nos_dois_lados_com_o_papel_do_vinculo_e_convida(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        link = make_link(role=Roles.GESTOR)
        repository = FakeUserRepository()

        created = await servico(repository, FakeLinkService([link])).create_user_service(
            um_cadastro(link.id)
        )

        assert created.user.email == "naira@pucrs.br"
        assert created.user.name == "Naira Libermann"
        assert created.user.link_id == link.id
        assert created.role == "gestor"
        assert created.organization_id == link.organization_id
        assert repository.itens == [created.user]
        # O `keycloak_id` gravado é o que o realm devolveu.
        assert keycloak.users == {created.user.keycloak_id: "naira@pucrs.br"}
        assert keycloak.roles == {created.user.keycloak_id: "gestor"}
        assert keycloak.emails_sent == [created.user.keycloak_id]

    async def test_nasce_ativo(self) -> None:
        """P-013 — se isto virar `inactive`, o primeiro login para de funcionar."""
        link = make_link()
        repository = FakeUserRepository()

        criado = await servico(repository, FakeLinkService([link])).create_user_service(
            um_cadastro(link.id)
        )

        assert criado.user.status is RecordStatus.ACTIVE

    async def test_grava_o_email_em_minusculas_dos_dois_lados(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """O Keycloak guarda em minúsculas, e o login procura pelo e-mail do token."""
        link = make_link()
        repository = FakeUserRepository()

        criado = await servico(repository, FakeLinkService([link])).create_user_service(
            um_cadastro(link.id, email="Naira@pucrs.br")
        )

        assert criado.user.email == "naira@pucrs.br"
        assert keycloak.users == {criado.user.keycloak_id: "naira@pucrs.br"}

    async def test_email_repetido_com_outra_caixa_vira_conflito(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        link = make_link()
        repository = FakeUserRepository([um_user(email="naira@pucrs.br")])

        with pytest.raises(ConflictError, match=re.escape("naira@pucrs.br")):
            await servico(repository, FakeLinkService([link])).create_user_service(
                um_cadastro(link.id, email="NAIRA@pucrs.br")
            )

        assert keycloak.users == {}

    async def test_email_repetido_vira_conflito_sem_chamar_o_keycloak(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        link = make_link()
        repository = FakeUserRepository([um_user(email="naira@pucrs.br")])

        with pytest.raises(ConflictError, match=re.escape("naira@pucrs.br")):
            await servico(repository, FakeLinkService([link])).create_user_service(
                um_cadastro(link.id, name="Outra Pessoa")
            )

        assert len(repository.itens) == 1
        assert keycloak.users == {}

    async def test_unknown_link_raises_not_found_without_calling_keycloak(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        repository = FakeUserRepository()
        link_id = uuid.uuid4()

        with pytest.raises(NotFoundError, match=re.escape(str(link_id))):
            await servico(repository, FakeLinkService()).create_user_service(
                um_cadastro(link_id)
            )

        assert repository.itens == []
        assert keycloak.users == {}

    async def test_link_already_used_raises_conflict_without_calling_keycloak(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        link = make_link()
        current_owner = um_user(link_id=link.id)
        repository = FakeUserRepository([current_owner])

        with pytest.raises(ConflictError, match=re.escape(str(link.id))):
            await servico(repository, FakeLinkService([link])).create_user_service(
                um_cadastro(link.id, name="Outra Pessoa", email="outra@pucrs.br")
            )

        assert repository.itens == [current_owner]
        assert keycloak.users == {}

    async def test_email_que_so_existe_no_keycloak_vira_conflito_sem_gravar(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """Acesso criado à mão no realm, ou que sobrou de falha: não é reaproveitado."""
        link = make_link()
        repository = FakeUserRepository()
        orphan_id = uuid.uuid4()
        keycloak.users[orphan_id] = "naira@pucrs.br"

        with pytest.raises(ConflictError, match="Já existe acesso com o e-mail"):
            await servico(repository, FakeLinkService([link])).create_user_service(
                um_cadastro(link.id)
            )

        assert repository.itens == []
        assert keycloak.users == {orphan_id: "naira@pucrs.br"}
        assert keycloak.deleted == []

    async def test_keycloak_fora_na_criacao_fica_indisponivel_sem_gravar(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        link = make_link()
        repository = FakeUserRepository()
        keycloak.failing.add("create_user")

        with pytest.raises(ServiceUnavailableError):
            await servico(repository, FakeLinkService([link])).create_user_service(
                um_cadastro(link.id)
            )

        assert repository.itens == []
        assert keycloak.deleted == []

    async def test_falha_no_papel_apaga_no_keycloak_e_fica_indisponivel(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        link = make_link()
        repository = FakeUserRepository()
        keycloak.failing.add("assign_realm_role")

        with pytest.raises(ServiceUnavailableError):
            await servico(repository, FakeLinkService([link])).create_user_service(
                um_cadastro(link.id)
            )

        assert keycloak.users == {}
        assert len(keycloak.deleted) == 1
        assert repository.itens == []
        assert keycloak.emails_sent == []

    async def test_falha_no_insert_apaga_no_keycloak_e_propaga_o_erro_original(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        link = make_link()

        with pytest.raises(FakeIntegrityError):
            await servico(
                FailingInsertRepository(), FakeLinkService([link])
            ).create_user_service(um_cadastro(link.id))

        assert keycloak.users == {}
        assert len(keycloak.deleted) == 1
        assert keycloak.emails_sent == []

    async def test_falha_no_envio_apaga_no_keycloak_e_fica_indisponivel(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """O INSERT já passou pelo flush: quem o desfaz é o rollback do `get_db`."""
        link = make_link()
        repository = FakeUserRepository()
        keycloak.failing.add("send_update_password_email")

        with pytest.raises(ServiceUnavailableError):
            await servico(repository, FakeLinkService([link])).create_user_service(
                um_cadastro(link.id)
            )

        assert keycloak.users == {}
        assert keycloak.deleted == [repository.itens[0].keycloak_id]

    async def test_compensacao_que_falha_loga_o_id_e_mantem_o_erro_original(
        self, keycloak: FakeKeycloakAdmin, caplog: pytest.LogCaptureFixture
    ) -> None:
        """O Keycloak cai entre a criação e a compensação: o log guia a limpeza."""
        link = make_link()
        repository = FakeUserRepository()
        keycloak.failing.update({"send_update_password_email", "delete_user"})

        with (
            caplog.at_level("ERROR"),
            pytest.raises(ServiceUnavailableError),
        ):
            await servico(repository, FakeLinkService([link])).create_user_service(
                um_cadastro(link.id)
            )

        (orphan_id,) = keycloak.users
        assert str(orphan_id) in caplog.text


class TestRemoverUsuario:
    async def test_remove_no_banco_e_no_keycloak(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        user = um_user()
        repository = FakeUserRepository([user])

        await servico(repository).delete_user_service(user.id)

        assert repository.removidos == [user]
        assert repository.itens == []
        assert keycloak.deleted == [user.keycloak_id]

    async def test_usuario_inexistente_vira_not_found(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """NotFoundError é o que o router traduz para 404 — não 409, não 500."""
        repository = FakeUserRepository()

        with pytest.raises(NotFoundError):
            await servico(repository).delete_user_service(uuid.uuid4())

        assert keycloak.deleted == []

    async def test_keycloak_fora_fica_indisponivel(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """O delete do banco já passou pelo flush: o rollback do `get_db` o desfaz."""
        user = um_user()
        repository = FakeUserRepository([user])
        keycloak.failing.add("delete_user")

        with pytest.raises(ServiceUnavailableError):
            await servico(repository).delete_user_service(user.id)

        assert keycloak.deleted == []

    async def test_delete_que_o_banco_recusa_nao_chega_ao_keycloak(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """Banco antes do Keycloak: se o flush falha, o realm não foi tocado.

        Na ordem contrária, o usuário sairia do realm e ficaria no banco, com um
        `keycloak_id` que não existe mais.
        """
        user = um_user()
        keycloak.users[user.keycloak_id] = user.email

        with pytest.raises(FakeIntegrityError):
            await servico(FailingDeleteRepository([user])).delete_user_service(user.id)

        assert keycloak.deleted == []
        assert keycloak.users == {user.keycloak_id: user.email}


class TestReenviarConvite:
    """Quem pede é `admin` ou `gestor`: o `respondente` a guarda barra antes (router)."""

    async def test_admin_reenvia_para_usuario_de_qualquer_organizacao(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        link = make_link()
        user = um_user(link_id=link.id)
        repository = FakeUserRepository([user])

        await servico(repository, FakeLinkService([link])).resend_invitation_service(
            user.id, role="admin", own_organization_id=uuid.uuid4()
        )

        assert keycloak.emails_sent == [user.keycloak_id]

    async def test_gestor_reenvia_para_usuario_da_propria_organizacao(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        link = make_link()
        user = um_user(link_id=link.id)
        repository = FakeUserRepository([user])

        await servico(repository, FakeLinkService([link])).resend_invitation_service(
            user.id, role="gestor", own_organization_id=link.organization_id
        )

        assert keycloak.emails_sent == [user.keycloak_id]

    async def test_gestor_de_outra_organizacao_recebe_o_mesmo_not_found_do_inexistente(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """Decisão 4 do contrato da CREED-23: "existe, mas não é seu" vaza cadastro."""
        link = make_link()
        user = um_user(link_id=link.id)
        missing_id = uuid.uuid4()
        service = servico(FakeUserRepository([user]), FakeLinkService([link]))

        with pytest.raises(NotFoundError) as other_organization:
            await service.resend_invitation_service(
                user.id, role="gestor", own_organization_id=uuid.uuid4()
            )
        with pytest.raises(NotFoundError) as missing:
            await service.resend_invitation_service(
                missing_id, role="gestor", own_organization_id=uuid.uuid4()
            )

        assert other_organization.value.message == f"Usuário {user.id} não encontrado"
        assert missing.value.message == f"Usuário {missing_id} não encontrado"
        assert keycloak.emails_sent == []

    async def test_gestor_com_vinculo_que_o_link_service_nao_acha_e_not_found(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        user = um_user()
        repository = FakeUserRepository([user])

        with pytest.raises(NotFoundError):
            await servico(repository, FakeLinkService()).resend_invitation_service(
                user.id, role="gestor", own_organization_id=uuid.uuid4()
            )

        assert keycloak.emails_sent == []

    async def test_usuario_inexistente_e_not_found_sem_mandar_email(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        with pytest.raises(NotFoundError):
            await servico(FakeUserRepository()).resend_invitation_service(
                uuid.uuid4(), role="admin", own_organization_id=uuid.uuid4()
            )

        assert keycloak.emails_sent == []

    async def test_acesso_inativo_tambem_recebe(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """🟡 Premissa P-058 — o reenvio não olha o status do acesso."""
        user = um_user(status=RecordStatus.INACTIVE)
        repository = FakeUserRepository([user])

        await servico(repository).resend_invitation_service(
            user.id, role="admin", own_organization_id=uuid.uuid4()
        )

        assert keycloak.emails_sent == [user.keycloak_id]

    async def test_gestor_tambem_reenvia_para_admin_da_propria_organizacao(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """🟡 Premissa P-058 — o reenvio não olha o papel do acesso de destino."""
        link = make_link(role=Roles.ADMIN)
        user = um_user(link_id=link.id)
        repository = FakeUserRepository([user])

        await servico(repository, FakeLinkService([link])).resend_invitation_service(
            user.id, role="gestor", own_organization_id=link.organization_id
        )

        assert keycloak.emails_sent == [user.keycloak_id]

    async def test_keycloak_ou_smtp_fora_fica_indisponivel(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        user = um_user()
        repository = FakeUserRepository([user])
        keycloak.failing.add("send_update_password_email")

        with pytest.raises(ServiceUnavailableError):
            await servico(repository).resend_invitation_service(
                user.id, role="admin", own_organization_id=uuid.uuid4()
            )


class TestRedefinirSenha:
    """Sem acesso não é erro: quem chama responde igual para qualquer e-mail."""

    async def test_email_com_acesso_ativo_recebe_o_email(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        user = um_user(email="naira@pucrs.br")
        repository = FakeUserRepository([user])

        await servico(repository).send_password_reset_service("naira@pucrs.br")

        assert keycloak.emails_sent == [user.keycloak_id]

    async def test_email_digitado_com_maiusculas_acha_o_acesso_gravado_em_minusculas(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """O banco guarda em minúsculas desde o cadastro; a pessoa digita como quiser."""
        user = um_user(email="pessoa@x.com")
        repository = FakeUserRepository([user])

        await servico(repository).send_password_reset_service("Pessoa@x.com")

        assert keycloak.emails_sent == [user.keycloak_id]

    async def test_email_sem_acesso_nao_manda_nada_e_nao_levanta(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        repository = FakeUserRepository([um_user(email="naira@pucrs.br")])

        await servico(repository).send_password_reset_service("ninguem@pucrs.br")

        assert keycloak.emails_sent == []

    async def test_acesso_inativo_nao_recebe(self, keycloak: FakeKeycloakAdmin) -> None:
        user = um_user(email="naira@pucrs.br", status=RecordStatus.INACTIVE)
        repository = FakeUserRepository([user])

        await servico(repository).send_password_reset_service("naira@pucrs.br")

        assert keycloak.emails_sent == []

    async def test_keycloak_ou_smtp_fora_com_acesso_fica_indisponivel(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        repository = FakeUserRepository([um_user(email="naira@pucrs.br")])
        keycloak.failing.add("send_update_password_email")

        with pytest.raises(ServiceUnavailableError):
            await servico(repository).send_password_reset_service("naira@pucrs.br")

    async def test_keycloak_fora_sem_acesso_continua_sem_erro(
        self, keycloak: FakeKeycloakAdmin
    ) -> None:
        """Sem acesso, o Keycloak nem é chamado: a falha não revela o e-mail."""
        keycloak.failing.add("send_update_password_email")

        await servico(FakeUserRepository()).send_password_reset_service(
            "ninguem@pucrs.br"
        )

        assert keycloak.emails_sent == []


class TestGetActiveUserAccessByEmail:
    """O método que a task 5 usa na guarda e no login."""

    async def test_returns_role_and_organization_from_link(self) -> None:
        link = make_link(role=Roles.ADMIN)
        user = um_user(link_id=link.id)
        repository = FakeUserRepository([user])

        access = await servico(
            repository, FakeLinkService([link])
        ).get_active_user_access_by_email(user.email)

        assert access is not None
        assert access.role == "admin"
        assert access.link_id == link.id
        assert access.organization_id == link.organization_id

    async def test_unknown_user_returns_none(self) -> None:
        repository = FakeUserRepository()

        access = await servico(repository).get_active_user_access_by_email(
            "ninguem@pucrs.br"
        )

        assert access is None

    async def test_inactive_user_returns_none(self) -> None:
        user = um_user(status=RecordStatus.INACTIVE)
        repository = FakeUserRepository([user])

        access = await servico(
            repository, FakeLinkService([make_link(id=user.link_id)])
        ).get_active_user_access_by_email(user.email)

        assert access is None

    async def test_link_not_found_by_link_service_returns_none(self) -> None:
        """`user.link_id` aponta para algo que o `LinkService` não acha."""
        user = um_user()
        repository = FakeUserRepository([user])

        access = await servico(
            repository, FakeLinkService()
        ).get_active_user_access_by_email(user.email)

        assert access is None


class TestUserResponse:
    def test_de_model_builds_output_with_link_role_and_organization(self) -> None:
        link_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        user = um_user(link_id=link_id)

        response = UserResponse.de_model(
            user, role="admin", link_id=link_id, organization_id=organization_id
        )

        assert response.id == user.id
        assert response.email == user.email
        assert response.role == "admin"
        assert response.link_id == link_id
        assert response.organization_id == organization_id

    def test_nao_expoe_o_keycloak_id(self) -> None:
        """O contrato-api.md não tem `keycloak_id` no `User` de saída."""
        user = um_user()

        resposta = UserResponse.de_model(
            user,
            role="respondente",
            link_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
        )

        assert "keycloak_id" not in resposta.model_dump()

    def test_recusa_email_invalido(self) -> None:
        with pytest.raises(ValueError):
            UserCreate(name="Alguém", email="abc", link_id=uuid.uuid4())

    def test_rejects_body_without_link_id(self) -> None:
        with pytest.raises(ValueError):
            UserCreate.model_validate({"name": "Alguém", "email": "alguem@pucrs.br"})

    def test_ignora_keycloak_id_no_corpo(self) -> None:
        """Quem ainda manda o campo antigo não quebra, e o valor não vai a lugar algum."""
        cadastro = UserCreate.model_validate(
            {
                "name": "Alguém",
                "email": "alguem@pucrs.br",
                "link_id": str(uuid.uuid4()),
                "keycloak_id": str(uuid.uuid4()),
            }
        )

        assert "keycloak_id" not in cadastro.model_dump()
