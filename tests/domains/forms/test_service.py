"""Testes do service do domínio forms."""

import uuid
from datetime import UTC, datetime

import pytest

from app.domains.forms.models import Form, FormStatus
from app.domains.forms.schemas import FormCreate, FormRead
from app.domains.forms.service import FormService
from app.shared.exceptions import NotFoundError


class FakeFormRepository:
    def __init__(self, existentes: list[Form] | None = None) -> None:
        self.itens: list[Form] = list(existentes or [])

    async def get_by_id(self, form_id: uuid.UUID) -> Form | None:
        return next((f for f in self.itens if f.id == form_id), None)

    async def create(self, form: Form) -> Form:
        self.itens.append(form)
        return form


def um_form(**campos: object) -> Form:
    """Form montado à mão."""
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Plasticidade Humana",
        "organization_id": uuid.uuid4(),
        "status": FormStatus.DRAFT,
        "created_at": datetime(2026, 9, 13, tzinfo=UTC),
    }
    return Form(**{**padrao, **campos})


def servico(repository: FakeFormRepository) -> FormService:
    return FormService(repository)  # type: ignore[arg-type]


class TestCriarFormulario:
    async def test_persiste_os_campos_do_payload(self) -> None:
        repository = FakeFormRepository()
        organization_id = uuid.uuid4()

        criado = await servico(repository).create(
            FormCreate(name="Plasticidade Humana", organization_id=organization_id)
        )

        assert criado.name == "Plasticidade Humana"
        assert criado.organization_id == organization_id
        assert repository.itens == [criado]

    async def test_nasce_em_rascunho(self) -> None:
        """Um formulário publicado sem perguntas não seria respondível."""
        repository = FakeFormRepository()

        criado = await servico(repository).create(
            FormCreate(name="Plasticidade Humana", organization_id=uuid.uuid4())
        )

        assert criado.status is FormStatus.DRAFT


class TestBuscarFormulario:
    async def test_retorna_o_formulario_encontrado(self) -> None:
        form = um_form()
        repository = FakeFormRepository([form])

        encontrado = await servico(repository).get(form.id)

        assert encontrado is form

    async def test_formulario_inexistente_vira_not_found(self) -> None:
        """NotFoundError é o que o router traduz para 404 — não 409, não 500."""
        repository = FakeFormRepository()

        with pytest.raises(NotFoundError):
            await servico(repository).get(uuid.uuid4())


class TestFormRead:
    def test_de_model_monta_a_saida(self) -> None:
        form = um_form()

        resposta = FormRead.de_model(form)

        assert resposta.id == form.id
        assert resposta.name == form.name
        assert resposta.organization_id == form.organization_id
        assert resposta.status is FormStatus.DRAFT
        assert resposta.created_at == form.created_at

    def test_recusa_nome_curto(self) -> None:
        with pytest.raises(ValueError):
            FormCreate(name="A", organization_id=uuid.uuid4())

    def test_recusa_organization_id_invalido(self) -> None:
        with pytest.raises(ValueError):
            FormCreate(name="Formulário válido", organization_id="não-é-um-uuid")
