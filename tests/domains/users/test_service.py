"""Testes do service do domínio users.

Sem banco e sem HTTP: o repository é substituído por um dublê em memória, que é
o que a separação de camadas do ADR-0004 compra. O que se prova aqui é a regra
de negócio — conflito de e-mail, usuário inexistente e o status de nascimento
(P-013). O mapeamento para o Postgres não passa por aqui.
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

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

    async def create(self, user: User) -> User:
        self.itens.append(user)
        return user

    async def delete(self, user: User) -> None:
        self.itens.remove(user)
        self.removidos.append(user)


def um_user(**campos: object) -> User:
    """User montado à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados no
    INSERT, então um User que nunca passou pela sessão tem `None` neles.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "keycloak_id": uuid.uuid4(),
        "name": "Naira Libermann",
        "email": "naira@pucrs.br",
        "status": RecordStatus.ACTIVE,
        "role": UserRole.RESPONDENTE,
        "created_at": datetime(2026, 9, 13, tzinfo=UTC),
    }
    return User(**{**padrao, **campos})


def servico(repository: FakeUserRepository) -> UserService:
    return UserService(repository)  # type: ignore[arg-type]


class TestCriarUsuario:
    async def test_persiste_os_campos_do_payload(self) -> None:
        repository = FakeUserRepository()
        keycloak_id = uuid.uuid4()

        criado = await servico(repository).create_user_service(
            UserCreate(
                name="Naira Libermann",
                email="naira@pucrs.br",
                keycloak_id=keycloak_id,
            )
        )

        assert criado.email == "naira@pucrs.br"
        assert criado.name == "Naira Libermann"
        assert criado.keycloak_id == keycloak_id
        assert repository.itens == [criado]

    async def test_nasce_ativo(self) -> None:
        """P-013 — se isto virar `inactive`, o primeiro login para de funcionar."""
        repository = FakeUserRepository()

        criado = await servico(repository).create_user_service(
            UserCreate(
                name="Naira Libermann",
                email="naira@pucrs.br",
                keycloak_id=uuid.uuid4(),
            )
        )

        assert criado.status is RecordStatus.ACTIVE

    async def test_email_repetido_vira_conflito(self) -> None:
        repository = FakeUserRepository([um_user(email="naira@pucrs.br")])

        with pytest.raises(ConflictError, match=re.escape("naira@pucrs.br")):
            await servico(repository).create_user_service(
                UserCreate(
                    name="Outra Pessoa",
                    email="naira@pucrs.br",
                    keycloak_id=uuid.uuid4(),
                )
            )

        assert len(repository.itens) == 1


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


class TestUserResponse:
    def test_de_model_monta_a_saida(self) -> None:
        user = um_user(role=UserRole.ADMIN)

        resposta = UserResponse.de_model(user)

        assert resposta.id == user.id
        assert resposta.email == user.email
        assert resposta.role is UserRole.ADMIN

    def test_nao_expoe_o_keycloak_id(self) -> None:
        """O contrato-api.md não tem `keycloak_id` no `User` de saída."""
        resposta = UserResponse.de_model(um_user())

        assert "keycloak_id" not in resposta.model_dump()

    def test_recusa_email_invalido(self) -> None:
        with pytest.raises(ValueError):
            UserCreate(name="Alguém", email="abc", keycloak_id=uuid.uuid4())
