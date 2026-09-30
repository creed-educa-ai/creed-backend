"""Testes do `except IntegrityError` do `ParticipantRepository.create`.

A suíte não roda contra banco, então a sessão é um dublê que levanta o
`IntegrityError` no `flush()`. As mensagens são as que o asyncpg devolve de
verdade (conferidas em Postgres descartável no PR #28). O que estes testes
provam: a constraint única vira `None` e qualquer outra violação é relançada. O
que não provam: que o driver continua escrevendo o nome da constraint na
mensagem — isso só um teste contra banco pegaria.
"""

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.domains.participants.models import Participant
from app.domains.participants.repository import ParticipantRepository

VIOLA_UNIQUE = (
    "<class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value "
    'violates unique constraint "uq_participants_document_id"'
)
VIOLA_FK = (
    "<class 'asyncpg.exceptions.ForeignKeyViolationError'>: insert or update on "
    'table "participants" violates foreign key constraint '
    '"participants_document_id_fkey"'
)


class _SessaoQueRecusa:
    """Sessão falsa: o `flush()` levanta o erro que o banco levantaria."""

    def __init__(self, mensagem: str) -> None:
        self.mensagem = mensagem

    def add(self, instance: Any) -> None:
        pass

    async def flush(self) -> None:
        raise IntegrityError("INSERT INTO participants ...", {}, Exception(self.mensagem))


def _repository(mensagem: str) -> ParticipantRepository:
    return ParticipantRepository(_SessaoQueRecusa(mensagem))  # type: ignore[arg-type]


async def test_constraint_unica_do_documento_devolve_none() -> None:
    resultado = await _repository(VIOLA_UNIQUE).create(Participant(name="Pessoa"))

    assert resultado is None


async def test_outra_violacao_e_relancada() -> None:
    with pytest.raises(IntegrityError):
        await _repository(VIOLA_FK).create(Participant(name="Pessoa"))
