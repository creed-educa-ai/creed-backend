"""Testes do `except IntegrityError` do `DepartmentRepository.create_if_absent`.

A suíte não roda contra banco, então a sessão é um dublê: o `flush()` levanta o
`IntegrityError` que o asyncpg levantaria, e o savepoint só deixa a exceção passar,
como o `begin_nested()` de verdade faz depois de desfazer o INSERT. O que estes
testes provam: a unicidade de organização + tipo vira `None` e qualquer outra
violação é relançada. O que não provam: que a sessão continua utilizável depois do
savepoint no Postgres de verdade, nem que o driver escreve o nome da constraint na
mensagem. Isso só um teste contra banco pegaria.
"""

import uuid
from types import TracebackType
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.domains.department.models import Department
from app.domains.department.repository import DepartmentRepository
from app.shared.enums import DepartmentType

VIOLA_UNIQUE = (
    "<class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value "
    'violates unique constraint "uq_departments_organization_type"'
)
VIOLA_FK = (
    "<class 'asyncpg.exceptions.ForeignKeyViolationError'>: insert or update on "
    'table "departments" violates foreign key constraint '
    '"fk_departments_organization_id_organizations"'
)


class _SavepointFalso:
    """Faz o papel do `begin_nested()`: não engole a exceção de dentro."""

    async def __aenter__(self) -> "_SavepointFalso":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


class _SessaoFalsa:
    """Sessão falsa: com `mensagem`, o `flush()` levanta o erro que o banco levantaria."""

    def __init__(self, mensagem: str | None = None) -> None:
        self.mensagem = mensagem

    def begin_nested(self) -> _SavepointFalso:
        return _SavepointFalso()

    def add(self, instance: Any) -> None:
        pass

    async def flush(self) -> None:
        if self.mensagem is not None:
            raise IntegrityError(
                "INSERT INTO departments ...", {}, Exception(self.mensagem)
            )

    async def refresh(self, instance: Any) -> None:
        pass


def _repository(mensagem: str | None = None) -> DepartmentRepository:
    return DepartmentRepository(_SessaoFalsa(mensagem))  # type: ignore[arg-type]


def _department() -> Department:
    return Department(organization_id=uuid.uuid4(), type=DepartmentType.MARKETING)


async def test_sem_conflito_devolve_o_setor_gravado() -> None:
    department = _department()

    resultado = await _repository().create_if_absent(department)

    assert resultado is department


async def test_constraint_unica_de_organizacao_e_tipo_devolve_none() -> None:
    resultado = await _repository(VIOLA_UNIQUE).create_if_absent(_department())

    assert resultado is None


async def test_outra_violacao_e_relancada() -> None:
    with pytest.raises(IntegrityError):
        await _repository(VIOLA_FK).create_if_absent(_department())
