"""Testes do service do domínio participants.

Sem banco e sem HTTP: o repository é substituído por um dublê em memória. O que
se prova aqui é a regra de negócio — o status de nascimento, o participante
inexistente e as duas recusas de documento (P-021). O `DocumentService` também é
dublê: só responde se um id existe. O mapeamento para o Postgres não passa por aqui.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.domains.participants.models import Participant
from app.domains.participants.schemas import ParticipantCreate
from app.domains.participants.service import ParticipantService
from app.shared.enums import RecordStatus
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError


class FakeParticipantRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(
        self,
        existentes: list[Participant] | None = None,
        constraint_recusa: bool = False,
    ) -> None:
        self.itens: list[Participant] = list(existentes or [])
        # Simula a constraint única recusando o INSERT: o que o repository real
        # devolve quando outro cadastro levou o documento depois da checagem.
        self.constraint_recusa = constraint_recusa

    async def get_by_id(self, participant_id: uuid.UUID) -> Participant | None:
        return next((p for p in self.itens if p.id == participant_id), None)

    async def get_by_document_id(self, document_id: uuid.UUID) -> Participant | None:
        return next((p for p in self.itens if p.document_id == document_id), None)

    async def create(self, participant: Participant) -> Participant | None:
        if self.constraint_recusa:
            return None
        self.itens.append(participant)
        return participant


class FakeDocumentService:
    """Dublê do DocumentService: conhece só os ids que recebeu."""

    def __init__(self, existentes: list[uuid.UUID] | None = None) -> None:
        self.existentes = list(existentes or [])

    async def document_exists(self, document_id: uuid.UUID) -> bool:
        return document_id in self.existentes


def um_participant(**campos: object) -> Participant:
    """Participant montado à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados no
    INSERT, então um Participant que nunca passou pela sessão tem `None` neles.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Pessoa Exemplo",
        "document_id": None,
        "status": RecordStatus.ACTIVE,
        "created_at": datetime(2026, 9, 27, tzinfo=UTC),
        "updated_at": None,
    }
    return Participant(**{**padrao, **campos})


def servico(
    repository: FakeParticipantRepository,
    documents: FakeDocumentService | None = None,
) -> ParticipantService:
    return ParticipantService(
        repository,  # type: ignore[arg-type]
        documents or FakeDocumentService(),  # type: ignore[arg-type]
    )


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


class TestCadastrarComDocumento:
    async def test_sem_documento_nasce_com_document_id_nulo(self) -> None:
        criado = await servico(FakeParticipantRepository()).create_participant(
            ParticipantCreate(name="Pessoa Exemplo")
        )

        assert criado.document_id is None

    async def test_documento_existente_e_livre_fica_ligado(self) -> None:
        documento = uuid.uuid4()
        repository = FakeParticipantRepository()

        criado = await servico(
            repository, FakeDocumentService([documento])
        ).create_participant(
            ParticipantCreate(name="Pessoa Exemplo", document_id=documento)
        )

        assert criado.document_id == documento
        assert repository.itens == [criado]

    async def test_documento_inexistente_vira_validation_error(self) -> None:
        repository = FakeParticipantRepository()
        inexistente = uuid.uuid4()

        with pytest.raises(ValidationError, match=str(inexistente)):
            await servico(repository, FakeDocumentService()).create_participant(
                ParticipantCreate(name="Pessoa Exemplo", document_id=inexistente)
            )

        assert repository.itens == []

    async def test_documento_de_outra_pessoa_vira_conflito(self) -> None:
        documento = uuid.uuid4()
        repository = FakeParticipantRepository([um_participant(document_id=documento)])

        with pytest.raises(ConflictError, match=str(documento)):
            await servico(
                repository, FakeDocumentService([documento])
            ).create_participant(
                ParticipantCreate(name="Outra Pessoa", document_id=documento)
            )

        assert len(repository.itens) == 1

    async def test_corrida_recusada_pela_constraint_vira_conflito(self) -> None:
        """A checagem passa (documento livre), mas outro cadastro gravou antes."""
        documento = uuid.uuid4()
        repository = FakeParticipantRepository(constraint_recusa=True)

        with pytest.raises(ConflictError, match=str(documento)):
            await servico(
                repository, FakeDocumentService([documento])
            ).create_participant(
                ParticipantCreate(name="Pessoa Exemplo", document_id=documento)
            )


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
