"""Injeção de dependência do domínio demographics."""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.demographics.repository import DemographicRepository
from app.domains.demographics.service import DemographicService
from app.domains.links.dependencies import ServiceDep as LinkServiceDep


def get_repository(db: SessionDep) -> DemographicRepository:
    return DemographicRepository(db)


def get_service(
    repository: Annotated[DemographicRepository, Depends(get_repository)],
    links: LinkServiceDep,
) -> DemographicService:
    return DemographicService(repository, links)


ServiceDep = Annotated[DemographicService, Depends(get_service)]
