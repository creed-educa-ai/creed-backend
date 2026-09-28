"""Testes do service do domínio participants.

Sem banco e sem HTTP: o repository é substituído por um dublê em memória. O que
se prova aqui é a regra de negócio — o status de nascimento e o participante
inexistente. O mapeamento para o Postgres não passa por aqui.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.domains.participants.models import Participant
from app.domains.participants.schemas import ParticipantCreate
from app.domains.participants.service import ParticipantService
from app.shared.enums import RecordStatus
from app.shared.exceptions import NotFoundError


class FakeParticipantRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(self, existentes: list[Participant] | None = None) -> None:
        self.itens: list[Participant] = list(existentes or [])

    async def get_by_id(self, participant_id: uuid.UUID) -> Participant | None:
        return next((p for p in self.itens if p.id == participant_id), None)

    async def create(self, participant: Participant) -> Participant:
        self.itens.append(participant)
        return participant


def um_participant(**campos: object) -> Participant:
    """Participant montado à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados no
    INSERT, então um Participant que nunca passou pela sessão tem `None` neles.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Pessoa Exemplo",
        "status": RecordStatus.ACTIVE,
        "created_at": datetime(2026, 9, 27, tzinfo=UTC),
        "updated_at": None,
    }
    return Participant(**{**padrao, **campos})


def servico(repository: FakeParticipantRepository) -> ParticipantService:
    return ParticipantService(repository)  # type: ignore[arg-type]


class TestCadastrarParticipante:
    async def test_persiste_o_nome_do_payload(self) -> None:
        repository = FakeParticipantRepository()

        criado = await servico(repository).create_participant(
            ParticipantCreate(name="Pessoa Exemplo")
        )

        assert criado.name == "Pessoa Exemplo"
        assert repository.itens == [criado]

    async def test_nasce_ativo(self) -> None:
        criado = await servico(FakeParticipantRepository()).create_participant(
            ParticipantCreate(name="Pessoa Exemplo")
        )

        assert criado.status is RecordStatus.ACTIVE


class TestConsultarParticipante:
    async def test_devolve_o_participante_pelo_id(self) -> None:
        existente = um_participant()

        encontrado = await servico(
            FakeParticipantRepository([existente])
        ).get_participant(existente.id)

        assert encontrado is existente

    async def test_id_inexistente_vira_not_found(self) -> None:
        inexistente = uuid.uuid4()

        with pytest.raises(NotFoundError, match=str(inexistente)):
            await servico(FakeParticipantRepository([um_participant()])).get_participant(
                inexistente
            )
