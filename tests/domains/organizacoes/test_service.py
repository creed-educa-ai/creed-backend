"""Testes do service do domínio organizacoes.

Sem banco e sem HTTP: o repository e o `DocumentService` são dublês em memória.
O que se prova aqui é a regra de negócio — documento inexistente ou já usado,
o 403 do gestor em organização alheia e o PATCH parcial.

⚠️ Paginação e ordenação estão na consulta ao banco, e o dublê não roda consulta:
aqui só se prova que o service calcula o deslocamento e repassa o total.
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.domains.organizacoes.models import Organization
from app.domains.organizacoes.schemas import OrganizationCreate, OrganizationUpdate
from app.domains.organizacoes.service import OrganizationService
from app.shared.enums import RecordStatus
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)


class FakeOrganizationRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(
        self,
        existentes: list[Organization] | None = None,
        constraint_recusa: bool = False,
    ) -> None:
        self.itens: list[Organization] = list(existentes or [])
        # Simula a constraint única recusando o INSERT: o que o repository real
        # devolve quando outro cadastro levou o documento depois da checagem.
        self.constraint_recusa = constraint_recusa
        self.pagina_pedida: tuple[int, int] | None = None
        self.salvos: list[Organization] = []

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        return next((o for o in self.itens if o.id == organization_id), None)

    async def get_by_document_id(self, document_id: uuid.UUID) -> Organization | None:
        return next((o for o in self.itens if o.document_id == document_id), None)

    async def create(self, organization: Organization) -> Organization | None:
        if self.constraint_recusa:
            return None
        self.itens.append(organization)
        return organization

    async def save(self, organization: Organization) -> Organization:
        self.salvos.append(organization)
        return organization

    async def list_page(self, offset: int, limit: int) -> list[Organization]:
        self.pagina_pedida = (offset, limit)
        return self.itens[offset : offset + limit]

    async def count(self) -> int:
        return len(self.itens)


class FakeDocumentService:
    """Dublê do DocumentService: conhece só os ids que recebeu."""

    def __init__(self, existentes: list[uuid.UUID] | None = None) -> None:
        self.existentes = list(existentes or [])

    async def document_exists(self, document_id: uuid.UUID) -> bool:
        return document_id in self.existentes


def uma_organization(**campos: object) -> Organization:
    """Organization montada à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados no
    INSERT, então uma Organization que nunca passou pela sessão tem `None` neles.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Organização Exemplo",
        "address": "Av. Ipiranga, 6681, Porto Alegre",
        "document_id": uuid.uuid4(),
        "status": RecordStatus.ACTIVE,
        "created_at": datetime(2026, 10, 15, tzinfo=UTC),
        "updated_at": None,
    }
    return Organization(**{**padrao, **campos})


def servico(
    repository: FakeOrganizationRepository,
    documentos: FakeDocumentService | None = None,
) -> OrganizationService:
    return OrganizationService(
        repository,  # type: ignore[arg-type]
        documentos or FakeDocumentService(),  # type: ignore[arg-type]
    )


def um_cadastro(document_id: uuid.UUID) -> OrganizationCreate:
    return OrganizationCreate(
        name="Organização Exemplo",
        address="Av. Ipiranga, 6681, Porto Alegre",
        document_id=document_id,
    )


class TestCriarOrganization:
    async def test_persiste_os_campos_e_nasce_ativa(self) -> None:
        documento = uuid.uuid4()
        repository = FakeOrganizationRepository()

        criada = await servico(repository, FakeDocumentService([documento])).create(
            um_cadastro(documento)
        )

        assert criada.name == "Organização Exemplo"
        assert criada.document_id == documento
        assert criada.status is RecordStatus.ACTIVE
        assert repository.itens == [criada]

    async def test_documento_inexistente_vira_validation_error(self) -> None:
        """Documento veio no corpo: inexistente é 422, não 404."""
        repository = FakeOrganizationRepository()

        with pytest.raises(ValidationError):
            await servico(repository).create(um_cadastro(uuid.uuid4()))

        assert repository.itens == []

    async def test_documento_de_outra_organizacao_vira_conflito(self) -> None:
        documento = uuid.uuid4()
        repository = FakeOrganizationRepository([uma_organization(document_id=documento)])

        with pytest.raises(ConflictError, match=re.escape(str(documento))):
            await servico(repository, FakeDocumentService([documento])).create(
                um_cadastro(documento)
            )

        assert len(repository.itens) == 1

    async def test_corrida_na_gravacao_vira_conflito_sem_gravar(self) -> None:
        """O caminho: create devolve None -> service traduz em ConflictError."""
        documento = uuid.uuid4()
        repository = FakeOrganizationRepository(constraint_recusa=True)

        with pytest.raises(ConflictError, match=re.escape(str(documento))):
            await servico(repository, FakeDocumentService([documento])).create(
                um_cadastro(documento)
            )

        assert repository.itens == []


class TestLerOrganization:
    async def test_admin_le_qualquer_organizacao(self) -> None:
        organizacao = uma_organization()
        repository = FakeOrganizationRepository([organizacao])

        lida = await servico(repository).get(
            organizacao.id, role="admin", own_organization_id=uuid.uuid4()
        )

        assert lida is organizacao

    async def test_gestor_le_a_propria_organizacao(self) -> None:
        organizacao = uma_organization()
        repository = FakeOrganizationRepository([organizacao])

        lida = await servico(repository).get(
            organizacao.id, role="gestor", own_organization_id=organizacao.id
        )

        assert lida is organizacao

    async def test_gestor_em_organizacao_alheia_vira_forbidden(self) -> None:
        alheia = uma_organization()
        repository = FakeOrganizationRepository([alheia])

        with pytest.raises(ForbiddenError):
            await servico(repository).get(
                alheia.id, role="gestor", own_organization_id=uuid.uuid4()
            )

    async def test_gestor_em_organizacao_inexistente_alheia_vira_forbidden(
        self,
    ) -> None:
        """403 antes do 404: a resposta não revela quais organizações existem."""
        repository = FakeOrganizationRepository()

        with pytest.raises(ForbiddenError):
            await servico(repository).get(
                uuid.uuid4(), role="gestor", own_organization_id=uuid.uuid4()
            )

    async def test_organizacao_inexistente_vira_not_found(self) -> None:
        repository = FakeOrganizationRepository()

        with pytest.raises(NotFoundError):
            await servico(repository).get(
                uuid.uuid4(), role="admin", own_organization_id=uuid.uuid4()
            )


class TestOrganizacaoExiste:
    """O "existe?" que `links`, `department` e `forms` usam, sem regra de acesso."""

    async def test_existente_devolve_true(self) -> None:
        organizacao = uma_organization()
        repository = FakeOrganizationRepository([organizacao])

        assert await servico(repository).organization_exists(organizacao.id) is True

    async def test_inexistente_devolve_false_sem_levantar(self) -> None:
        repository = FakeOrganizationRepository()

        assert await servico(repository).organization_exists(uuid.uuid4()) is False


class TestListarOrganizations:
    async def test_calcula_o_deslocamento_e_devolve_o_total(self) -> None:
        repository = FakeOrganizationRepository([uma_organization() for _ in range(5)])

        itens, total = await servico(repository).list_page(pagina=2, tamanho_pagina=2)

        assert repository.pagina_pedida == (2, 2)
        assert len(itens) == 2
        assert total == 5

    async def test_sem_organizacao_devolve_pagina_vazia(self) -> None:
        repository = FakeOrganizationRepository()

        itens, total = await servico(repository).list_page(pagina=1, tamanho_pagina=20)

        assert itens == []
        assert total == 0


class TestAlterarOrganization:
    async def test_altera_so_os_campos_enviados(self) -> None:
        organizacao = uma_organization(name="Antigo", address="Rua A, 1")
        repository = FakeOrganizationRepository([organizacao])

        alterada = await servico(repository).update(
            organizacao.id, OrganizationUpdate(name="Novo")
        )

        assert alterada.name == "Novo"
        assert alterada.address == "Rua A, 1"
        assert repository.salvos == [organizacao]

    async def test_inativa_pela_alteracao_de_status(self) -> None:
        organizacao = uma_organization()
        repository = FakeOrganizationRepository([organizacao])

        alterada = await servico(repository).update(
            organizacao.id, OrganizationUpdate(status=RecordStatus.INACTIVE)
        )

        assert alterada.status is RecordStatus.INACTIVE

    async def test_organizacao_inexistente_vira_not_found(self) -> None:
        repository = FakeOrganizationRepository()

        with pytest.raises(NotFoundError):
            await servico(repository).update(
                uuid.uuid4(), OrganizationUpdate(name="Novo")
            )

        assert repository.salvos == []
