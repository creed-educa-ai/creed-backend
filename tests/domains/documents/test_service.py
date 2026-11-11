"""Testes do service do domínio documents.

O repository é um dublê em memória: o que se prova é a resposta de
`document_exists`, que é o que `participants` consulta, o repasse de
`list_by_ids`, que é o que `organizacoes` lê, e a criação do CPF ou CNPJ do
cadastro público, com o 409 do documento repetido.

⚠️ O `IN` da consulta só roda com banco: aqui não se prova que o repository filtra.
"""

import uuid

import pytest

from app.domains.documents.models import DocType, Document
from app.domains.documents.service import DOCUMENT_ALREADY_REGISTERED, DocumentService
from app.shared.exceptions import ConflictError


class FakeDocumentRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(
        self,
        existentes: list[Document] | None = None,
        constraint_recusa: bool = False,
    ) -> None:
        self.itens: list[Document] = list(existentes or [])
        # Simula a constraint única recusando o INSERT: o que o repository real
        # devolve quando outro cadastro gravou o documento depois da checagem.
        self.constraint_recusa = constraint_recusa

    async def get_by_id(self, document_id: uuid.UUID) -> Document | None:
        return next((d for d in self.itens if d.id == document_id), None)

    async def get_by_type_value(self, doc_type: DocType, value: str) -> Document | None:
        return next(
            (d for d in self.itens if d.type is doc_type and d.value == value), None
        )

    async def list_by_ids(self, document_ids: list[uuid.UUID]) -> list[Document]:
        return [d for d in self.itens if d.id in document_ids]

    async def create(self, document: Document) -> Document | None:
        if self.constraint_recusa:
            return None
        # O `default=uuid.uuid4` do model só vale no flush; o dublê faz o papel dele.
        document.id = uuid.uuid4()
        self.itens.append(document)
        return document


def servico(repository: FakeDocumentRepository) -> DocumentService:
    return DocumentService(repository)  # type: ignore[arg-type]


async def test_documento_cadastrado_existe() -> None:
    documento = Document(id=uuid.uuid4(), type=DocType.CPF, value="000.000.000-00")

    assert await servico(FakeDocumentRepository([documento])).document_exists(
        documento.id
    )


async def test_documento_desconhecido_nao_existe() -> None:
    assert not await servico(FakeDocumentRepository()).document_exists(uuid.uuid4())


async def test_lista_so_os_documentos_pedidos() -> None:
    pedido = Document(id=uuid.uuid4(), type=DocType.CNPJ, value="12345678000190")
    outro = Document(id=uuid.uuid4(), type=DocType.CPF, value="12345678909")

    lidos = await servico(FakeDocumentRepository([pedido, outro])).list_by_ids(
        [pedido.id, uuid.uuid4()]
    )

    assert lidos == [pedido]


class TestCriarDocumentoBrasileiro:
    @pytest.mark.parametrize(
        ("numero", "tipo"),
        [("12345678909", DocType.CPF), ("12345678000190", DocType.CNPJ)],
        ids=["11_digitos_e_cpf", "14_digitos_e_cnpj"],
    )
    async def test_o_tamanho_escolhe_o_tipo(self, numero: str, tipo: DocType) -> None:
        repository = FakeDocumentRepository()

        criado = await servico(repository).create_brazilian_document(numero)

        assert (criado.type, criado.value) == (tipo, numero)
        assert criado.id is not None
        assert repository.itens == [criado]

    async def test_mesmo_tipo_e_numero_vira_conflito_sem_gravar(self) -> None:
        existente = Document(id=uuid.uuid4(), type=DocType.CNPJ, value="12345678000190")
        repository = FakeDocumentRepository([existente])

        with pytest.raises(ConflictError) as erro:
            await servico(repository).create_brazilian_document("12345678000190")

        assert erro.value.message == DOCUMENT_ALREADY_REGISTERED
        assert repository.itens == [existente]

    async def test_mesmo_numero_de_outro_tipo_nao_e_conflito(self) -> None:
        """A constraint é de tipo e número juntos: um `other` com os mesmos
        dígitos não impede o CNPJ."""
        outro_tipo = Document(id=uuid.uuid4(), type=DocType.OTHER, value="12345678000190")
        repository = FakeDocumentRepository([outro_tipo])

        criado = await servico(repository).create_brazilian_document("12345678000190")

        assert criado.type is DocType.CNPJ
        assert len(repository.itens) == 2

    async def test_corrida_na_gravacao_vira_conflito(self) -> None:
        """O caminho: create devolve None -> service traduz em ConflictError."""
        repository = FakeDocumentRepository(constraint_recusa=True)

        with pytest.raises(ConflictError, match=DOCUMENT_ALREADY_REGISTERED):
            await servico(repository).create_brazilian_document("12345678909")

        assert repository.itens == []

    @pytest.mark.parametrize("numero", ["123", "123456789012", ""])
    async def test_outro_tamanho_e_erro_de_quem_chamou(self, numero: str) -> None:
        """O schema já barra com 422; chegar aqui é bug, e não vira documento."""
        repository = FakeDocumentRepository()

        with pytest.raises(ValueError, match="não é CPF nem CNPJ"):
            await servico(repository).create_brazilian_document(numero)

        assert repository.itens == []
