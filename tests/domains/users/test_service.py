"""Testes do service do domínio users.

Sem banco e sem HTTP: repository e `VinculoService` são substituídos por dublês em
memória, que é o que a separação de camadas do ADR-0004 compra. O que se prova aqui é
a regra de negócio — conflito de e-mail, vínculo inexistente ou já usado, usuário
inexistente e o status de nascimento (P-013). O mapeamento para o Postgres não passa
por aqui.
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.domains.users.models import RecordStatus, User, UserRole
from app.domains.users.schemas import UserCreate, UserResponse
from app.domains.users.service import UserService
from app.domains.vinculos.models import Roles, VincType, Vinculo
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

    async def get_by_vinculo_id(self, vinculo_id: uuid.UUID) -> User | None:
        return next((u for u in self.itens if u.vinculo_id == vinculo_id), None)

    async def create(self, user: User) -> User:
        self.itens.append(user)
        return user

    async def delete(self, user: User) -> None:
        self.itens.remove(user)
        self.removidos.append(user)


class FakeVinculoService:
    """Dublê do `VinculoService`: um dicionário `id -> Vinculo`."""

    def __init__(self, existentes: list[Vinculo] | None = None) -> None:
        self.itens: dict[uuid.UUID, Vinculo] = {v.id: v for v in (existentes or [])}

    async def get_vinculo_by_id_service(self, vinculo_id: uuid.UUID) -> Vinculo | None:
        return self.itens.get(vinculo_id)


def um_vinculo(**campos: object) -> Vinculo:
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "participant_id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "setor_id": None,
        "type": VincType.EMPREGO,
        "role": Roles.RESPONDENTE,
        "start_at": datetime(2026, 9, 24, tzinfo=UTC),
        "end_at": None,
        "created_at": datetime(2026, 9, 24, tzinfo=UTC),
        "updated_at": None,
    }
    return Vinculo(**{**padrao, **campos})


def um_user(**campos: object) -> User:
    """User montado à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados no
    INSERT, então um User que nunca passou pela sessão tem `None` neles.

    `vinculo_id` vem preenchido por padrão: é o caso comum a partir da
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
        "vinculo_id": uuid.uuid4(),
        "created_at": datetime(2026, 9, 13, tzinfo=UTC),
    }
    return User(**{**padrao, **campos})


def servico(
    repository: FakeUserRepository, vinculos: FakeVinculoService | None = None
) -> UserService:
    return UserService(repository, vinculos or FakeVinculoService())  # type: ignore[arg-type]


class TestCriarUsuario:
    async def test_persiste_os_campos_do_payload_e_o_papel_do_vinculo(self) -> None:
        vinculo = um_vinculo(role=Roles.GESTOR)
        repository = FakeUserRepository()
        keycloak_id = uuid.uuid4()

        criado = await servico(
            repository, FakeVinculoService([vinculo])
        ).create_user_service(
            UserCreate(
                name="Naira Libermann",
                email="naira@pucrs.br",
                keycloak_id=keycloak_id,
                vinculo_id=vinculo.id,
            )
        )

        assert criado.user.email == "naira@pucrs.br"
        assert criado.user.name == "Naira Libermann"
        assert criado.user.keycloak_id == keycloak_id
        assert criado.user.vinculo_id == vinculo.id
        assert criado.role == "gestor"
        assert criado.organization_id == vinculo.organization_id
        assert repository.itens == [criado.user]

    async def test_nao_passa_role_e_a_saida_usa_o_papel_do_vinculo(self) -> None:
        """`role` não vai no construtor do `User`: quem responde é o vínculo."""
        vinculo = um_vinculo(role=Roles.ADMIN)
        repository = FakeUserRepository()

        criado = await servico(
            repository, FakeVinculoService([vinculo])
        ).create_user_service(
            UserCreate(
                name="Naira Libermann",
                email="naira@pucrs.br",
                keycloak_id=uuid.uuid4(),
                vinculo_id=vinculo.id,
            )
        )

        # A coluna não recebe o papel do vínculo; só a saída o carrega.
        assert criado.user.role is not UserRole.ADMIN
        assert criado.role == "admin"
        assert criado.role == "admin"

    async def test_nasce_ativo(self) -> None:
        """P-013 — se isto virar `inactive`, o primeiro login para de funcionar."""
        vinculo = um_vinculo()
        repository = FakeUserRepository()

        criado = await servico(
            repository, FakeVinculoService([vinculo])
        ).create_user_service(
            UserCreate(
                name="Naira Libermann",
                email="naira@pucrs.br",
                keycloak_id=uuid.uuid4(),
                vinculo_id=vinculo.id,
            )
        )

        assert criado.user.status is RecordStatus.ACTIVE

    async def test_email_repetido_vira_conflito(self) -> None:
        vinculo = um_vinculo()
        repository = FakeUserRepository([um_user(email="naira@pucrs.br")])

        with pytest.raises(ConflictError, match=re.escape("naira@pucrs.br")):
            await servico(repository, FakeVinculoService([vinculo])).create_user_service(
                UserCreate(
                    name="Outra Pessoa",
                    email="naira@pucrs.br",
                    keycloak_id=uuid.uuid4(),
                    vinculo_id=vinculo.id,
                )
            )

        assert len(repository.itens) == 1

    async def test_vinculo_inexistente_vira_not_found(self) -> None:
        repository = FakeUserRepository()
        vinculo_id = uuid.uuid4()

        with pytest.raises(NotFoundError, match=re.escape(str(vinculo_id))):
            await servico(repository, FakeVinculoService()).create_user_service(
                UserCreate(
                    name="Naira Libermann",
                    email="naira@pucrs.br",
                    keycloak_id=uuid.uuid4(),
                    vinculo_id=vinculo_id,
                )
            )

        assert repository.itens == []

    async def test_vinculo_ja_usado_vira_conflito(self) -> None:
        vinculo = um_vinculo()
        dono_atual = um_user(vinculo_id=vinculo.id)
        repository = FakeUserRepository([dono_atual])

        with pytest.raises(ConflictError, match=re.escape(str(vinculo.id))):
            await servico(repository, FakeVinculoService([vinculo])).create_user_service(
                UserCreate(
                    name="Outra Pessoa",
                    email="outra@pucrs.br",
                    keycloak_id=uuid.uuid4(),
                    vinculo_id=vinculo.id,
                )
            )

        assert repository.itens == [dono_atual]


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

    async def test_devolve_o_papel_do_vinculo_mesmo_com_a_coluna_divergindo(self) -> None:
        vinculo = um_vinculo(role=Roles.ADMIN)
        user = um_user(role=UserRole.RESPONDENTE, vinculo_id=vinculo.id)
        repository = FakeUserRepository([user])

        acesso = await servico(
            repository, FakeVinculoService([vinculo])
        ).get_active_user_access_by_email(user.email)

        assert acesso is not None
        assert acesso.role == "admin"
        assert acesso.vinculo_id == vinculo.id
        assert acesso.organization_id == vinculo.organization_id

    async def test_usuario_inexistente_devolve_none(self) -> None:
        repository = FakeUserRepository()

        acesso = await servico(repository).get_active_user_access_by_email(
            "ninguem@pucrs.br"
        )

        assert acesso is None

    async def test_usuario_inativo_devolve_none(self) -> None:
        user = um_user(status=RecordStatus.INACTIVE)
        repository = FakeUserRepository([user])

        acesso = await servico(
            repository, FakeVinculoService([um_vinculo(id=user.vinculo_id)])
        ).get_active_user_access_by_email(user.email)

        assert acesso is None

    async def test_usuario_sem_vinculo_devolve_none(self) -> None:
        user = um_user(vinculo_id=None)
        repository = FakeUserRepository([user])

        acesso = await servico(repository).get_active_user_access_by_email(user.email)

        assert acesso is None

    async def test_vinculo_que_o_vinculo_service_nao_encontra_devolve_none(self) -> None:
        """`user.vinculo_id` aponta para algo que o `VinculoService` não acha."""
        user = um_user()
        repository = FakeUserRepository([user])

        acesso = await servico(
            repository, FakeVinculoService()
        ).get_active_user_access_by_email(user.email)

        assert acesso is None


class TestUserResponse:
    def test_de_model_monta_a_saida_com_o_papel_e_a_organizacao_do_vinculo(self) -> None:
        vinculo_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        user = um_user(vinculo_id=vinculo_id)

        resposta = UserResponse.de_model(
            user, role="admin", vinculo_id=vinculo_id, organization_id=organization_id
        )

        assert resposta.id == user.id
        assert resposta.email == user.email
        assert resposta.role == "admin"
        assert resposta.vinculo_id == vinculo_id
        assert resposta.organization_id == organization_id

    def test_nao_expoe_o_keycloak_id(self) -> None:
        """O contrato-api.md não tem `keycloak_id` no `User` de saída."""
        user = um_user()

        resposta = UserResponse.de_model(
            user,
            role="respondente",
            vinculo_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
        )

        assert "keycloak_id" not in resposta.model_dump()

    def test_recusa_email_invalido(self) -> None:
        with pytest.raises(ValueError):
            UserCreate(
                name="Alguém",
                email="abc",
                keycloak_id=uuid.uuid4(),
                vinculo_id=uuid.uuid4(),
            )

    def test_recusa_corpo_sem_vinculo_id(self) -> None:
        with pytest.raises(ValueError):
            UserCreate.model_validate(
                {
                    "name": "Alguém",
                    "email": "alguem@pucrs.br",
                    "keycloak_id": str(uuid.uuid4()),
                }
            )
