"""Testes do `except IntegrityError` do `DocumentRepository.create`.

Mesmo formato de `tests/domains/participants/test_repository.py`: a suíte não roda
contra banco, então a sessão é um dublê que levanta o `IntegrityError` no
`flush()`, com a mensagem no formato do asyncpg. O que estes testes provam: a
constraint única de tipo e número vira `None` e qualquer outra violação é
relançada. O que não provam: que o Postgres dispara a constraint de verdade na
corrida de dois cadastros — isso só um teste contra banco pegaria.
"""

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.domains.documents.models import DocType, Document
from app.domains.documents.repository import DocumentRepository

VIOLA_UNIQUE = (
    "<class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value "
    'violates unique constraint "uq_documents_type_value"'
)
VIOLA_NOT_NULL = (
    "<class 'asyncpg.exceptions.NotNullViolationError'>: null value in column "
    '"value" of relation "documents" violates not-null constraint'
)


class _SessaoQueRecusa:
    """Sessão falsa: o `flush()` levanta o erro que o banco levantaria."""

    def __init__(self, mensagem: str) -> None:
        self.mensagem = mensagem

    def add(self, instance: Any) -> None:
        pass

    async def flush(self) -> None:
        raise IntegrityError("INSERT INTO documents ...", {}, Exception(self.mensagem))


def _repository(mensagem: str) -> DocumentRepository:
    return DocumentRepository(_SessaoQueRecusa(mensagem))  # type: ignore[arg-type]


def _documento() -> Document:
    return Document(type=DocType.CNPJ, value="12345678000190")


async def test_constraint_unica_de_tipo_e_numero_devolve_none() -> None:
    assert await _repository(VIOLA_UNIQUE).create(_documento()) is None


async def test_outra_violacao_e_relancada() -> None:
    with pytest.raises(IntegrityError):
        await _repository(VIOLA_NOT_NULL).create(_documento())
