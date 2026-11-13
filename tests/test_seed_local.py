"""Testes de scripts/seed_local.py: o usuário de teste e o formulário de
demonstração (CREED-47). As perguntas não são do seed: o formulário aplica o
instrumento CREED, que entra por migration de dados.

Sem banco e sem Keycloak: os repositories são dublês em memória. O que se prova é o
que o seed decide — o que cria, com que conteúdo e que não duplica. Que o INSERT
passa no Postgres, só rodando o seed no banco local.
"""

import uuid

import pytest

from app.domains.documents.models import DocType, Document
from app.domains.forms.models import Form
from app.domains.organizacoes.models import Organization
from scripts.seed_local import (
    DEMO_CLOSES_AT,
    DEMO_FORM_ID,
    DEMO_OPENS_AT,
    EMAIL,
    LINK_ROLE,
    ORGANIZATION_DOCUMENT_ID,
    ORGANIZATION_ID,
    _ensure_demo_form,
    _ensure_organization,
    _new_link,
    _usuario_de_teste,
)

PAPEIS = {"admin", "gestor", "respondente"}


class TestUsuarioDeTeste:
    """O que o seed manda à Admin API para criar o usuário de teste no realm."""

    def test_entra_pelo_token_endpoint(self) -> None:
        """O `curl` do README e o login local dependem deste usuário.

        Sem `requiredActions` vazia e sem `temporary: False`, o Direct Access Grant
        responde `invalid_grant: "Account is not fully set up"` — que na tela vira
        "senha inválida" e manda o time procurar um bug que não existe.
        """
        usuario = _usuario_de_teste()

        assert usuario["username"] == usuario["email"] == EMAIL
        assert usuario["enabled"] is True
        assert usuario["requiredActions"] == []
        assert usuario["credentials"][0]["temporary"] is False

    def test_senha_passa_na_politica_do_realm(self) -> None:
        """O `length(8)` do realm (P-004 de 07/09) vale também para a Admin API.

        Com senha mais curta, ela recusa criar o usuário, e o seed para antes de
        gravar qualquer coisa no banco: ninguém entra no ambiente local.
        """
        senha = _usuario_de_teste()["credentials"][0]["value"]

        assert len(senha) >= 8

    def test_papel_do_realm_e_um_da_premissa_p006(self) -> None:
        """O papel dado no realm é o do vínculo, e precisa existir no realm."""
        assert LINK_ROLE.value in PAPEIS


class FakeFormRepository:
    def __init__(self) -> None:
        self.itens: list[Form] = []

    async def get_by_id(self, form_id: uuid.UUID) -> Form | None:
        return next((f for f in self.itens if f.id == form_id), None)

    async def create(self, form: Form) -> Form:
        self.itens.append(form)
        return form


@pytest.fixture
def forms() -> FakeFormRepository:
    return FakeFormRepository()


async def semear(forms: FakeFormRepository) -> bool:
    return await _ensure_demo_form(forms)  # type: ignore[arg-type]


class TestFormularioDeDemonstracao:
    async def test_cria_o_formulario_na_organizacao_do_vinculo_de_dev(
        self, forms: FakeFormRepository
    ) -> None:
        assert await semear(forms)

        [form] = forms.itens
        assert form.id == DEMO_FORM_ID
        assert form.organization_id == ORGANIZATION_ID

    async def test_nome_se_identifica_como_demonstracao(
        self, forms: FakeFormRepository
    ) -> None:
        await semear(forms)

        assert forms.itens[0].name.startswith("[Demonstração]")

    async def test_rodar_de_novo_nao_cria_nada(self, forms: FakeFormRepository) -> None:
        await semear(forms)

        assert not await semear(forms)
        assert len(forms.itens) == 1


class FakeSession:
    """Só o que o seed usa da sessão para o documento: `get`, `add` e `flush`."""

    def __init__(self) -> None:
        self.itens: list[Document] = []

    async def get(self, model: type[Document], document_id: uuid.UUID) -> Document | None:
        return next((d for d in self.itens if d.id == document_id), None)

    def add(self, document: Document) -> None:
        self.itens.append(document)

    async def flush(self) -> None:
        pass


class FakeOrganizationRepository:
    def __init__(self) -> None:
        self.itens: list[Organization] = []

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        return next((o for o in self.itens if o.id == organization_id), None)

    async def create(self, organization: Organization) -> Organization:
        self.itens.append(organization)
        return organization


@pytest.fixture
def documents() -> FakeSession:
    return FakeSession()


@pytest.fixture
def organizations() -> FakeOrganizationRepository:
    return FakeOrganizationRepository()


async def semear_organizacao(
    documents: FakeSession, organizations: FakeOrganizationRepository
) -> bool:
    return await _ensure_organization(documents, organizations)  # type: ignore[arg-type]


class TestOrganizacaoDeDev:
    """A organização que o vínculo e o formulário de dev usam (CREED-38)."""

    async def test_cria_a_organizacao_que_o_vinculo_de_dev_aponta(
        self, documents: FakeSession, organizations: FakeOrganizationRepository
    ) -> None:
        """Sem ela, a FK de `links.organization_id` recusa o vínculo do seed."""
        assert await semear_organizacao(documents, organizations)

        [organizacao] = organizations.itens
        assert organizacao.id == ORGANIZATION_ID == _new_link().organization_id

    async def test_aponta_para_o_documento_sintetico(
        self, documents: FakeSession, organizations: FakeOrganizationRepository
    ) -> None:
        """`document_id` é obrigatório e não há endpoint de documento (P-022)."""
        await semear_organizacao(documents, organizations)

        [documento] = documents.itens
        assert documento.id == ORGANIZATION_DOCUMENT_ID
        assert organizations.itens[0].document_id == ORGANIZATION_DOCUMENT_ID

    async def test_dado_se_identifica_como_demonstracao(
        self, documents: FakeSession, organizations: FakeOrganizationRepository
    ) -> None:
        """Nada pode parecer organização ou CNPJ real."""
        await semear_organizacao(documents, organizations)

        assert documents.itens[0].type is DocType.OTHER
        assert organizations.itens[0].name.startswith("[Demonstração]")

    async def test_rodar_de_novo_nao_cria_nada(
        self, documents: FakeSession, organizations: FakeOrganizationRepository
    ) -> None:
        await semear_organizacao(documents, organizations)

        assert not await semear_organizacao(documents, organizations)
        assert len(documents.itens) == 1
        assert len(organizations.itens) == 1

    async def test_banco_com_documento_e_sem_organizacao_cria_so_a_organizacao(
        self, documents: FakeSession, organizations: FakeOrganizationRepository
    ) -> None:
        await semear_organizacao(documents, organizations)
        organizations.itens = []

        assert await semear_organizacao(documents, organizations)
        assert len(documents.itens) == 1
        assert len(organizations.itens) == 1


class TestPeriodoDoFormularioDeDemonstracao:
    async def test_nasce_com_o_periodo_aberto(self, forms: FakeFormRepository) -> None:
        await semear(forms)

        assert forms.itens[0].opens_at == DEMO_OPENS_AT
        assert forms.itens[0].closes_at == DEMO_CLOSES_AT

    async def test_formulario_antigo_sem_periodo_recebe_o_periodo(
        self, forms: FakeFormRepository
    ) -> None:
        await semear(forms)
        forms.itens[0].opens_at = None
        forms.itens[0].closes_at = None

        assert await semear(forms) is True
        assert forms.itens[0].opens_at == DEMO_OPENS_AT

    async def test_periodo_existente_nao_e_alterado(
        self, forms: FakeFormRepository
    ) -> None:
        await semear(forms)
        forms.itens[0].closes_at = DEMO_OPENS_AT

        assert await semear(forms) is False
        assert forms.itens[0].closes_at == DEMO_OPENS_AT
