"""Testes do service do domínio links.

Sem banco e sem HTTP: o repository é substituído por um dublê em memória. Não há
regra de conflito para provar aqui — o `.dbml` não define unicidade no vínculo —,
então o que se prova é que o service monta a entidade certa e delega ao repository.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domains.links.models import Link, LinkType, Roles
from app.domains.links.schemas import LinkCreate, LinkResponse
from app.domains.links.service import LinkService


class FakeLinkRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(self, existing: list[Link] | None = None) -> None:
        self.items: list[Link] = list(existing or [])

    async def insert(self, link: Link) -> Link:
        self.items.append(link)
        return link

    async def get_by_id(self, link_id: uuid.UUID) -> Link | None:
        return next((v for v in self.items if v.id == link_id), None)


def make_link(**fields: object) -> Link:
    """Link montado à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados no
    INSERT, então um Link que nunca passou pela sessão tem `None` neles.
    """
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "participant_id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "department_id": None,
        "type": LinkType.EMPREGO,
        "role": Roles.GESTOR,
        "start_at": datetime(2026, 9, 24, 14, 0, tzinfo=UTC),
        "end_at": None,
        "created_at": datetime(2026, 9, 24, 14, 0, tzinfo=UTC),
        "updated_at": None,
    }
    return Link(**{**defaults, **fields})


def service(repository: FakeLinkRepository) -> LinkService:
    return LinkService(repository)  # type: ignore[arg-type]


class TestCreateLink:
    async def test_saves_organization_id_from_argument_and_rest_from_payload(
        self,
    ) -> None:
        repository = FakeLinkRepository()
        organization_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        department_id = uuid.uuid4()

        created = await service(repository).create_link_service(
            organization_id,
            LinkCreate(
                participant_id=participant_id,
                department_id=department_id,
                type=LinkType.MENTORIA,
                role=Roles.ADMIN,
            ),
        )

        assert created.organization_id == organization_id
        assert created.participant_id == participant_id
        assert created.department_id == department_id
        assert created.type is LinkType.MENTORIA
        assert created.role is Roles.ADMIN
        assert repository.items == [created]

    async def test_without_department_id_saves_none(self) -> None:
        repository = FakeLinkRepository()

        created = await service(repository).create_link_service(
            uuid.uuid4(),
            LinkCreate(
                participant_id=uuid.uuid4(),
                type=LinkType.ACADEMICO,
                role=Roles.RESPONDENTE,
            ),
        )

        assert created.department_id is None


class TestGetLink:
    async def test_existing_id_returns_the_link(self) -> None:
        link = make_link()
        repository = FakeLinkRepository([link])

        found = await service(repository).get_link_by_id_service(link.id)

        assert found is link

    async def test_unknown_id_returns_none_without_exception(self) -> None:
        repository = FakeLinkRepository()

        found = await service(repository).get_link_by_id_service(uuid.uuid4())

        assert found is None


class TestLinkCreate:
    def test_rejects_type_outside_enum(self) -> None:
        with pytest.raises(ValidationError):
            LinkCreate(
                participant_id=uuid.uuid4(),
                type="inexistente",
                role=Roles.ADMIN,
            )

    def test_rejects_role_outside_enum(self) -> None:
        with pytest.raises(ValidationError):
            LinkCreate(
                participant_id=uuid.uuid4(),
                type=LinkType.EMPREGO,
                role="inexistente",
            )

    def test_rejects_participant_id_that_is_not_uuid(self) -> None:
        with pytest.raises(ValidationError):
            LinkCreate(
                participant_id="nao-e-um-uuid",
                type=LinkType.EMPREGO,
                role=Roles.ADMIN,
            )

    def test_accepts_body_without_department_id(self) -> None:
        created = LinkCreate(
            participant_id=uuid.uuid4(),
            type=LinkType.EMPREGO,
            role=Roles.ADMIN,
        )

        assert created.department_id is None


class TestLinkResponse:
    def test_from_model_builds_the_output(self) -> None:
        link = make_link(type=LinkType.PESSOAL, role=Roles.GESTOR)

        response = LinkResponse.from_model(link)

        assert response.id == link.id
        assert response.organization_id == link.organization_id
        assert response.type is LinkType.PESSOAL
        assert response.role is Roles.GESTOR

    def test_serializes_enums_by_value_not_by_name(self) -> None:
        """O contrato manda `"emprego"` e `"gestor"`, não `"EMPREGO"`/`"GESTOR"`."""
        link = make_link(type=LinkType.EMPREGO, role=Roles.GESTOR)
        response = LinkResponse.from_model(link)

        dump = response.model_dump(mode="json")

        assert dump["type"] == "emprego"
        assert dump["role"] == "gestor"
