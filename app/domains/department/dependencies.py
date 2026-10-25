"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.department.repository import DepartmentRepository
from app.domains.department.service import DepartmentService


def get_repository(
    db: SessionDep,
) -> DepartmentRepository:
    return DepartmentRepository(db)


def get_service(
    repository: Annotated[DepartmentRepository, Depends(get_repository)],
) -> DepartmentService:
    return DepartmentService(repository)


ServiceDep = Annotated[DepartmentService, Depends(get_service)]
