"""Testes do service do domínio users.

Sem banco e sem HTTP: repository e `LinkService` são substituídos por dublês em
memória, que é o que a separação de camadas do ADR-0004 compra. O que se prova aqui é
a regra de negócio — conflito de e-mail, vínculo inexistente ou já usado, usuário
inexistente e o status de nascimento (P-013). O mapeamento para o Postgres não passa
por aqui.
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.domains.links.models import Link, LinkType, Roles
from app.domains.users.models import RecordStatus, User, UserRole
from app.domains.users.schemas import UserCreate, UserResponse
from app.domains.users.service import UserService
from app.shared.exceptions import ConflictError, NotFoundError


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


class FakeLinkService:
    """Dublê do `LinkService`: um dicionário `id -> Link`."""

    def __init__(self, existing: list[Link] | None = None) -> None:
        self.items: dict[uuid.UUID, Link] = {v.id: v for v in (existing or [])}

    async def get_link_by_id_service(self, link_id: uuid.UUID) -> Link | None:
        return self.items.get(link_id)


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

    `link_id` vem preenchido por padrão: é o caso comum a partir da
    CREED-32. `role` continua no padrão só porque a coluna ainda é `NOT NULL`
    — ninguém mais lê o valor.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "keycloak_id": uuid.uuid4(),
        "name": "Naira Libermann",
        "email": "naira@pucrs.br",
        "status": RecordStatus.ACTIVE,
        "role": UserRole.RESPONDENTE,
        "link_id": uuid.uuid4(),
        "created_at": datetime(2026, 9, 13, tzinfo=UTC),
    }
    return User(**{**padrao, **campos})


def servico(
    repository: FakeUserRepository, links: FakeLinkService | None = None
) -> UserService:
    return UserService(repository, links or FakeLinkService())  # type: ignore[arg-type]


class TestCriarUsuario:
    async def test_persists_payload_fields_and_link_role(self) -> None:
        link = make_link(role=Roles.GESTOR)
        repository = FakeUserRepository()
        keycloak_id = uuid.uuid4()

        created = await servico(repository, FakeLinkService([link])).create_user_service(
            UserCreate(
                name="Naira Libermann",
                email="naira@pucrs.br",
                keycloak_id=keycloak_id,
                link_id=link.id,
            )
        )

        assert created.user.email == "naira@pucrs.br"
        assert created.user.name == "Naira Libermann"
        assert created.user.keycloak_id == keycloak_id
        assert created.user.link_id == link.id
        assert created.role == "gestor"
        assert created.organization_id == link.organization_id
        assert repository.itens == [created.user]

    async def test_does_not_pass_role_and_output_uses_link_role(self) -> None:
        """`role` não vai no construtor do `User`: quem responde é o vínculo."""
        link = make_link(role=Roles.ADMIN)
        repository = FakeUserRepository()

        created = await servico(repository, FakeLinkService([link])).create_user_service(
            UserCreate(
                name="Naira Libermann",
                email="naira@pucrs.br",
                keycloak_id=uuid.uuid4(),
                link_id=link.id,
            )
        )

        # A coluna não recebe o papel do vínculo; só a saída o carrega.
        assert created.user.role is not UserRole.ADMIN
        assert created.role == "admin"

    async def test_nasce_ativo(self) -> None:
        """P-013 — se isto virar `inactive`, o primeiro login para de funcionar."""
        link = make_link()
        repository = FakeUserRepository()

        criado = await servico(repository, FakeLinkService([link])).create_user_service(
            UserCreate(
                name="Naira Libermann",
                email="naira@pucrs.br",
                keycloak_id=uuid.uuid4(),
                link_id=link.id,
            )
        )

        assert criado.user.status is RecordStatus.ACTIVE

    async def test_email_repetido_vira_conflito(self) -> None:
        link = make_link()
        repository = FakeUserRepository([um_user(email="naira@pucrs.br")])

        with pytest.raises(ConflictError, match=re.escape("naira@pucrs.br")):
            await servico(repository, FakeLinkService([link])).create_user_service(
                UserCreate(
                    name="Outra Pessoa",
                    email="naira@pucrs.br",
                    keycloak_id=uuid.uuid4(),
                    link_id=link.id,
                )
            )

        assert len(repository.itens) == 1

    async def test_unknown_link_raises_not_found(self) -> None:
        repository = FakeUserRepository()
        link_id = uuid.uuid4()

        with pytest.raises(NotFoundError, match=re.escape(str(link_id))):
            await servico(repository, FakeLinkService()).create_user_service(
                UserCreate(
                    name="Naira Libermann",
                    email="naira@pucrs.br",
                    keycloak_id=uuid.uuid4(),
                    link_id=link_id,
                )
            )

        assert repository.itens == []

    async def test_link_already_used_raises_conflict(self) -> None:
        link = make_link()
        current_owner = um_user(link_id=link.id)
        repository = FakeUserRepository([current_owner])

        with pytest.raises(ConflictError, match=re.escape(str(link.id))):
            await servico(repository, FakeLinkService([link])).create_user_service(
                UserCreate(
                    name="Outra Pessoa",
                    email="outra@pucrs.br",
                    keycloak_id=uuid.uuid4(),
                    link_id=link.id,
                )
            )

        assert repository.itens == [current_owner]


class TestRemoverUsuario:
    async def test_remove_o_usuario_encontrado(self) -> None:
        user = um_user()
        repository = FakeUserRepository([user])

        await servico(repository).delete_user_service(user.id)

        assert repository.removidos == [user]
        assert repository.itens == []

    async def test_usuario_inexistente_vira_not_found(self) -> None:
        """NotFoundError é o que o router traduz para 404 — não 409, não 500."""
        repository = FakeUserRepository()

        with pytest.raises(NotFoundError):
            await servico(repository).delete_user_service(uuid.uuid4())


class TestGetActiveUserAccessByEmail:
    """O método que a task 5 usa na guarda e no login."""

    async def test_returns_link_role_even_when_column_diverges(self) -> None:
        link = make_link(role=Roles.ADMIN)
        user = um_user(role=UserRole.RESPONDENTE, link_id=link.id)
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

    async def test_user_without_link_returns_none(self) -> None:
        user = um_user(link_id=None)
        repository = FakeUserRepository([user])

        access = await servico(repository).get_active_user_access_by_email(user.email)

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
            UserCreate(
                name="Alguém",
                email="abc",
                keycloak_id=uuid.uuid4(),
                link_id=uuid.uuid4(),
            )

    def test_rejects_body_without_link_id(self) -> None:
        with pytest.raises(ValueError):
            UserCreate.model_validate(
                {
                    "name": "Alguém",
                    "email": "alguem@pucrs.br",
                    "keycloak_id": str(uuid.uuid4()),
                }
            )
