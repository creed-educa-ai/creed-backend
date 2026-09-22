"""Testes do service do domínio responses.

Sem banco e sem HTTP: o repository é substituído por um dublê em memória
(ADR-002). O que se prova aqui é a regra de negócio da submissão — status
muda para SUBMITTED e submitted_at é registrado — não o mapeamento SQL.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.domains.responses.models import FormResponse, FormResponseStatus
from app.domains.responses.service import FormResponseService
from app.shared.exceptions import NotFoundError


class FakeFormResponseRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(self, existentes: list[FormResponse] | None = None) -> None:
        self.itens: list[FormResponse] = list(existentes or [])

    async def get_by_id(self, form_response_id: uuid.UUID) -> FormResponse | None:
        return next((fr for fr in self.itens if fr.id == form_response_id), None)

    async def get_by_form_and_vinculo(
        self,
        form_id: uuid.UUID,
        vinculo_id: uuid.UUID,
    ) -> FormResponse | None:
        return next(
            (
                fr
                for fr in self.itens
                if fr.form_id == form_id and fr.vinculo_id == vinculo_id
            ),
            None,
        )

    async def create(self, form_response: FormResponse) -> FormResponse:
        self.itens.append(form_response)
        return form_response


def um_form_response(**campos: object) -> FormResponse:
    """FormResponse montado à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados
    no INSERT, então um FormResponse que nunca passou pela sessão tem `None`
    neles.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "form_id": uuid.uuid4(),
        "vinculo_id": uuid.uuid4(),
        "status": FormResponseStatus.IN_PROGRESS,
        "started_at": datetime(2026, 9, 19, tzinfo=UTC),
        "submitted_at": None,
    }
    return FormResponse(**{**padrao, **campos})


def servico(repository: FakeFormResponseRepository) -> FormResponseService:
    return FormResponseService(repository)  # type: ignore[arg-type]


class TestSubmitFormResponse:
    async def test_marca_como_submitted_e_registra_data(self) -> None:
        form_response = um_form_response()
        repository = FakeFormResponseRepository([form_response])

        antes = datetime.now(UTC)
        resultado = await servico(repository).submit_form_response(form_response.id)
        depois = datetime.now(UTC)

        assert resultado.status == FormResponseStatus.SUBMITTED
        assert resultado.submitted_at is not None
        assert antes <= resultado.submitted_at <= depois

    async def test_inexistente_vira_not_found(self) -> None:
        repository = FakeFormResponseRepository()

        with pytest.raises(NotFoundError):
            await servico(repository).submit_form_response(uuid.uuid4())


class TestCreateFormResponse:
    async def test_nasce_em_progresso_com_os_ids_do_payload(self) -> None:
        repository = FakeFormResponseRepository()
        form_id, vinculo_id = uuid.uuid4(), uuid.uuid4()

        resultado = await servico(repository).create_form_response(
            form_id=form_id,
            vinculo_id=vinculo_id,
        )

        assert resultado.form_id == form_id
        assert resultado.vinculo_id == vinculo_id
        assert resultado.status == FormResponseStatus.IN_PROGRESS
        assert resultado.submitted_at is None
