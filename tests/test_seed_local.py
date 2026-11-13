"""Testes de scripts/seed_local.py: as organizações e as pessoas de teste do
ambiente local. O seed não cria período nem pergunta: o período nasce pelo painel,
como em produção, e as perguntas são do instrumento CREED, que entra por migration
de dados.

Sem banco e sem Keycloak: os repositories são dublês em memória. O que se prova é o
que o seed decide — o que cria, com que conteúdo e que não duplica. Que o INSERT
passa no Postgres, só rodando o seed no banco local.
"""

import uuid

import pytest

from app.domains.documents.models import DocType, Document
from app.domains.organizacoes.models import Organization
from app.shared.enums import LinkType, Roles
from scripts.seed_local import (
    ADMIN,
    CREED,
    EMPRESA,
    ORGANIZACOES,
    OUTRA_EMPRESA,
    PESSOAS,
    OrganizacaoDeTeste,
    PessoaDeTeste,
    _ensure_organization,
    _new_link,
    _usuario_de_teste,
)

PAPEIS = {"admin", "gestor", "respondente"}


class TestPessoasDeTeste:
    """O que o seed manda à Admin API e o vínculo de cada pessoa."""

    @pytest.mark.parametrize("pessoa", PESSOAS, ids=lambda p: p.email)
    def test_entra_pelo_token_endpoint(self, pessoa: PessoaDeTeste) -> None:
        """O `curl` do README e o login local dependem destes usuários.

        Sem `requiredActions` vazia e sem `temporary: False`, o Direct Access Grant
        responde `invalid_grant: "Account is not fully set up"` — que na tela vira
        "senha inválida" e manda o time procurar um bug que não existe.
        """
        usuario = _usuario_de_teste(pessoa)

        assert usuario["username"] == usuario["email"] == pessoa.email
        assert usuario["enabled"] is True
        assert usuario["requiredActions"] == []
        assert usuario["credentials"][0]["temporary"] is False

    def test_senha_passa_na_politica_do_realm(self) -> None:
        """O `length(8)` do realm (P-004 de 07/09) vale também para a Admin API.

        Com senha mais curta, ela recusa criar o usuário, e o seed para antes de
        gravar qualquer coisa no banco: ninguém entra no ambiente local.
        """
        senha = _usuario_de_teste(ADMIN)["credentials"][0]["value"]

        assert len(senha) >= 8

    @pytest.mark.parametrize("pessoa", PESSOAS, ids=lambda p: p.email)
    def test_papel_do_realm_e_um_da_premissa_p006(self, pessoa: PessoaDeTeste) -> None:
        """O papel dado no realm é o do vínculo, e precisa existir no realm."""
        assert pessoa.role.value in PAPEIS
        assert _new_link(pessoa).role is pessoa.role

    def test_emails_e_participantes_nao_se_repetem(self) -> None:
        assert len({p.email for p in PESSOAS}) == len(PESSOAS)
        assert len({p.participant_id for p in PESSOAS}) == len(PESSOAS)

    def test_vinculos_apontam_para_organizacoes_do_seed(self) -> None:
        ids = {o.id for o in ORGANIZACOES}
        assert {_new_link(p).organization_id for p in PESSOAS} <= ids

    def test_admin_fica_na_organizacao_da_creed(self) -> None:
        """Como em produção (P-048): é onde estão os mentorandos dela."""
        assert ADMIN.role is Roles.ADMIN
        assert ADMIN.organization_id == CREED.id

    def test_mentorandos_ficam_na_organizacao_da_creed(self) -> None:
        """O período individual da admin só aceita vínculo `mentoria` da CREED."""
        mentorandos = [p for p in PESSOAS if p.type is LinkType.MENTORIA]

        assert len(mentorandos) >= 2
        assert all(p.organization_id == CREED.id for p in mentorandos)
        assert all(p.role is Roles.RESPONDENTE for p in mentorandos)

    @pytest.mark.parametrize("empresa", [EMPRESA, OUTRA_EMPRESA], ids=lambda o: o.name)
    def test_cada_empresa_tem_quem_responde(self, empresa: OrganizacaoDeTeste) -> None:
        """Com respondente nas duas, dá para ver que uma não vê o período da outra."""
        assert any(
            p.organization_id == empresa.id and p.role is Roles.RESPONDENTE
            for p in PESSOAS
        )

    def test_empresa_tem_gestora_para_abrir_periodo(self) -> None:
        assert any(
            p.organization_id == EMPRESA.id and p.role is Roles.GESTOR for p in PESSOAS
        )


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
    documents: FakeSession,
    organizations: FakeOrganizationRepository,
    organizacao: OrganizacaoDeTeste = EMPRESA,
) -> bool:
    return await _ensure_organization(
        documents,  # type: ignore[arg-type]
        organizations,  # type: ignore[arg-type]
        organizacao,
    )


class TestOrganizacoesDeTeste:
    """As organizações para onde os vínculos das pessoas de teste apontam."""

    @pytest.mark.parametrize("organizacao", ORGANIZACOES, ids=lambda o: o.name)
    async def test_cria_a_organizacao_com_o_documento(
        self,
        documents: FakeSession,
        organizations: FakeOrganizationRepository,
        organizacao: OrganizacaoDeTeste,
    ) -> None:
        """Sem ela, a FK de `links.organization_id` recusa o vínculo do seed."""
        assert await semear_organizacao(documents, organizations, organizacao)

        [criada] = organizations.itens
        assert criada.id == organizacao.id
        assert criada.document_id == documents.itens[0].id == organizacao.document_id

    async def test_aponta_para_o_documento_sintetico(
        self, documents: FakeSession, organizations: FakeOrganizationRepository
    ) -> None:
        """`document_id` é obrigatório e não há endpoint de documento (P-022)."""
        await semear_organizacao(documents, organizations)

        [documento] = documents.itens
        assert documento.id == EMPRESA.document_id
        assert organizations.itens[0].document_id == EMPRESA.document_id

    @pytest.mark.parametrize(
        "organizacao", [EMPRESA, OUTRA_EMPRESA], ids=lambda o: o.name
    )
    async def test_empresa_se_identifica_como_demonstracao(
        self,
        documents: FakeSession,
        organizations: FakeOrganizationRepository,
        organizacao: OrganizacaoDeTeste,
    ) -> None:
        """Nada pode parecer organização ou CNPJ real."""
        await semear_organizacao(documents, organizations, organizacao)

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
