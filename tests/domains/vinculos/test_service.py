"""Testes do service do domínio vinculos.

Sem banco e sem HTTP: o repository é substituído por um dublê em memória. Não há
regra de conflito para provar aqui — o `.dbml` não define unicidade em `Vinculo` —,
então o que se prova é que o service monta a entidade certa e delega ao repository.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domains.vinculos.models import Roles, VincType, Vinculo
from app.domains.vinculos.schemas import VinculoCreate, VinculoResponse
from app.domains.vinculos.service import VinculoService


class FakeVinculoRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(self, existentes: list[Vinculo] | None = None) -> None:
        self.itens: list[Vinculo] = list(existentes or [])

    async def insert(self, vinculo: Vinculo) -> Vinculo:
        self.itens.append(vinculo)
        return vinculo

    async def get_by_id(self, vinculo_id: uuid.UUID) -> Vinculo | None:
        return next((v for v in self.itens if v.id == vinculo_id), None)


def um_vinculo(**campos: object) -> Vinculo:
    """Vinculo montado à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados no
    INSERT, então um Vinculo que nunca passou pela sessão tem `None` neles.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "participant_id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "setor_id": None,
        "type": VincType.EMPREGO,
        "role": Roles.GESTOR,
        "start_at": datetime(2026, 9, 24, 14, 0, tzinfo=UTC),
        "end_at": None,
        "created_at": datetime(2026, 9, 24, 14, 0, tzinfo=UTC),
        "updated_at": None,
    }
    return Vinculo(**{**padrao, **campos})


def servico(repository: FakeVinculoRepository) -> VinculoService:
    return VinculoService(repository)  # type: ignore[arg-type]


class TestCriarVinculo:
    async def test_grava_organization_id_do_argumento_e_o_resto_do_payload(
        self,
    ) -> None:
        repository = FakeVinculoRepository()
        organization_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        setor_id = uuid.uuid4()

        criado = await servico(repository).create_vinculo_service(
            organization_id,
            VinculoCreate(
                participant_id=participant_id,
                setor_id=setor_id,
                type=VincType.MENTORIA,
                role=Roles.ADMIN,
            ),
        )

        assert criado.organization_id == organization_id
        assert criado.participant_id == participant_id
        assert criado.setor_id == setor_id
        assert criado.type is VincType.MENTORIA
        assert criado.role is Roles.ADMIN
        assert repository.itens == [criado]

    async def test_sem_setor_id_grava_none(self) -> None:
        repository = FakeVinculoRepository()

        criado = await servico(repository).create_vinculo_service(
            uuid.uuid4(),
            VinculoCreate(
                participant_id=uuid.uuid4(),
                type=VincType.ACADEMICO,
                role=Roles.RESPONDENTE,
            ),
        )

        assert criado.setor_id is None


class TestLerVinculo:
    async def test_id_existente_devolve_o_vinculo(self) -> None:
        vinculo = um_vinculo()
        repository = FakeVinculoRepository([vinculo])

        encontrado = await servico(repository).get_vinculo_by_id_service(vinculo.id)

        assert encontrado is vinculo

    async def test_id_inexistente_devolve_none_sem_excecao(self) -> None:
        repository = FakeVinculoRepository()

        encontrado = await servico(repository).get_vinculo_by_id_service(uuid.uuid4())

        assert encontrado is None


class TestVinculoCreate:
    def test_recusa_type_fora_do_enum(self) -> None:
        with pytest.raises(ValidationError):
            VinculoCreate(
                participant_id=uuid.uuid4(),
                type="inexistente",
                role=Roles.ADMIN,
            )

    def test_recusa_role_fora_do_enum(self) -> None:
        with pytest.raises(ValidationError):
            VinculoCreate(
                participant_id=uuid.uuid4(),
                type=VincType.EMPREGO,
                role="inexistente",
            )

    def test_recusa_participant_id_que_nao_e_uuid(self) -> None:
        with pytest.raises(ValidationError):
            VinculoCreate(
                participant_id="nao-e-um-uuid",
                type=VincType.EMPREGO,
                role=Roles.ADMIN,
            )

    def test_aceita_corpo_sem_setor_id(self) -> None:
        criado = VinculoCreate(
            participant_id=uuid.uuid4(),
            type=VincType.EMPREGO,
            role=Roles.ADMIN,
        )

        assert criado.setor_id is None


class TestVinculoResponse:
    def test_de_model_monta_a_saida(self) -> None:
        vinculo = um_vinculo(type=VincType.PESSOAL, role=Roles.GESTOR)

        resposta = VinculoResponse.de_model(vinculo)

        assert resposta.id == vinculo.id
        assert resposta.organization_id == vinculo.organization_id
        assert resposta.type is VincType.PESSOAL
        assert resposta.role is Roles.GESTOR

    def test_serializa_os_enums_pelo_valor_nao_pelo_nome(self) -> None:
        """O contrato manda `"emprego"` e `"gestor"`, não `"EMPREGO"`/`"GESTOR"`."""
        vinculo = um_vinculo(type=VincType.EMPREGO, role=Roles.GESTOR)
        resposta = VinculoResponse.de_model(vinculo)

        dump = resposta.model_dump(mode="json")

        assert dump["type"] == "emprego"
        assert dump["role"] == "gestor"
