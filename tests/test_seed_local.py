"""Testes de scripts/seed_local.py: as organizações, as pessoas de teste e os
períodos de demonstração do ambiente local. O seed não cria período aberto nem
pergunta: o período aberto nasce pelo painel, como em produção, e as perguntas são do
instrumento CREED, que entra por migration de dados.

Sem banco e sem Keycloak: os repositories são dublês em memória. O que se prova é o
que o seed decide — o que cria, com que conteúdo e que não duplica. Que o INSERT
passa no Postgres, só rodando o seed no banco local.
"""

import uuid
from datetime import UTC, datetime
from itertools import combinations
from statistics import mean

import pytest

from app.domains.documents.models import DocType, Document
from app.domains.organizacoes.models import Organization
from app.domains.questions.models import Question, QuestionOption
from app.shared.enums import DepartmentType, Dimension, LinkType, Roles
from scripts.seed_local import (
    ADMIN,
    AUSENTE_NO_SEGUNDO_PERIODO,
    CREED,
    EMPRESA,
    OLD_DEMO_FORM_ID,
    ORGANIZACOES,
    OUTRA_EMPRESA,
    PERFIL_DO_SETOR,
    PERIODOS_DE_DEMONSTRACAO,
    PESSOAS,
    RESPONDENTES_DA_EMPRESA,
    OrganizacaoDeTeste,
    PeriodoDeDemonstracao,
    PessoaDeTeste,
    _ensure_organization,
    _new_link,
    _pessoa,
    _usuario_de_teste,
    nota_de_demonstracao,
    respostas_de_demonstracao,
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


class TestEquipeDaEmpresa:
    """A equipe que os dashboards de demonstração recortam."""

    def test_tem_respondentes_para_o_alinhamento(self) -> None:
        assert len(RESPONDENTES_DA_EMPRESA) >= 8

    def test_tem_tres_setores_e_alguem_sem_setor(self) -> None:
        setores = [_pessoa(email).department for email in RESPONDENTES_DA_EMPRESA]

        assert {s for s in setores if s is not None} == {
            DepartmentType.MARKETING,
            DepartmentType.FINANCEIRO,
            DepartmentType.TECNOLOGIA_INFORMACAO,
        }
        assert None in setores

    def test_setor_so_em_quem_e_da_empresa(self) -> None:
        """O setor é criado na organização da pessoa: só a empresa tem setores."""
        assert all(
            p.organization_id == EMPRESA.id for p in PESSOAS if p.department is not None
        )

    def test_vinculo_comeca_antes_dos_periodos_de_demonstracao(self) -> None:
        """Senão o resumo da empresa não conta a pessoa nos períodos passados."""
        link = _new_link(ADMIN)
        primeiro = min(p.opens_at for p in PERIODOS_DE_DEMONSTRACAO)

        assert link.start_at < primeiro
        assert link.created_at < primeiro

    def test_vinculo_leva_o_setor(self) -> None:
        department_id = uuid.uuid4()

        assert _new_link(ADMIN, department_id).department_id == department_id
        assert _new_link(ADMIN).department_id is None


class TestPeriodosDeDemonstracao:
    """Os períodos encerrados que dão dado aos dashboards."""

    def test_ids_nao_se_repetem_nem_reusam_o_formulario_antigo(self) -> None:
        ids = [periodo.id for periodo in PERIODOS_DE_DEMONSTRACAO]

        assert len(set(ids)) == len(ids)
        assert OLD_DEMO_FORM_ID not in ids

    def test_todos_ja_terminaram(self) -> None:
        """Nenhum aparece como questionário aberto, nem bloqueia abrir um novo."""
        agora = datetime.now(UTC)

        assert all(periodo.closes_at < agora for periodo in PERIODOS_DE_DEMONSTRACAO)
        assert all(p.opens_at < p.closes_at for p in PERIODOS_DE_DEMONSTRACAO)

    def test_periodos_do_mesmo_publico_nao_se_sobrepoem(self) -> None:
        def publico(periodo: PeriodoDeDemonstracao) -> tuple[uuid.UUID, str | None]:
            return (periodo.organization_id, periodo.individual_de)

        for a, b in combinations(PERIODOS_DE_DEMONSTRACAO, 2):
            if publico(a) == publico(b):
                assert a.closes_at <= b.opens_at or b.closes_at <= a.opens_at

    def test_empresa_tem_dois_periodos_para_comparar(self) -> None:
        da_empresa = [
            p
            for p in PERIODOS_DE_DEMONSTRACAO
            if p.organization_id == EMPRESA.id and p.individual_de is None
        ]

        assert len(da_empresa) == 2

    def test_alguem_falta_no_segundo_periodo(self) -> None:
        """A taxa de conclusão do período mais recente não fica em 100%."""
        primeiro, segundo = (
            p for p in PERIODOS_DE_DEMONSTRACAO if p.organization_id == EMPRESA.id
        )

        assert AUSENTE_NO_SEGUNDO_PERIODO in primeiro.respondentes
        assert AUSENTE_NO_SEGUNDO_PERIODO not in segundo.respondentes

    def test_periodo_individual_e_de_um_mentorando_da_creed(self) -> None:
        [individual] = [p for p in PERIODOS_DE_DEMONSTRACAO if p.individual_de]
        mentorando = _pessoa(individual.individual_de or "")

        assert individual.organization_id == CREED.id == mentorando.organization_id
        assert mentorando.type is LinkType.MENTORIA
        assert individual.respondentes == (mentorando.email,)


class TestNotaDeDemonstracao:
    """A fórmula das notas: sem sorteio, sempre de 1 a 5."""

    @pytest.mark.parametrize("pessoa", PESSOAS, ids=lambda p: p.email)
    def test_fica_entre_1_e_5(self, pessoa: PessoaDeTeste) -> None:
        notas = {
            nota_de_demonstracao(pessoa, dimensao, posicao, melhora=melhora)
            for dimensao in Dimension
            for posicao in range(47)
            for melhora in (False, True)
        }

        assert notas <= {1, 2, 3, 4, 5}

    def test_da_sempre_o_mesmo_resultado(self) -> None:
        pessoa = _pessoa(RESPONDENTES_DA_EMPRESA[0])

        assert nota_de_demonstracao(
            pessoa, Dimension.S2, 3, melhora=False
        ) == nota_de_demonstracao(pessoa, Dimension.S2, 3, melhora=False)

    def test_periodo_com_melhora_nunca_e_pior_e_sobe_na_media(self) -> None:
        pares = [
            (
                nota_de_demonstracao(pessoa, dimensao, posicao, melhora=False),
                nota_de_demonstracao(pessoa, dimensao, posicao, melhora=True),
            )
            for pessoa in map(_pessoa, RESPONDENTES_DA_EMPRESA)
            for dimensao in Dimension
            for posicao in range(47)
        ]

        assert all(depois >= antes for antes, depois in pares)
        assert mean(d for _, d in pares) > mean(a for a, _ in pares)

    @pytest.mark.parametrize("setor", list(PERFIL_DO_SETOR), ids=lambda s: s.value)
    def test_setor_puxa_as_dimensoes_do_perfil(self, setor: DepartmentType) -> None:
        """Dimensão que o setor puxa para cima dá nota maior que a que puxa para baixo."""
        pessoas = [
            _pessoa(email)
            for email in RESPONDENTES_DA_EMPRESA
            if _pessoa(email).department is setor
        ]
        perfil = PERFIL_DO_SETOR[setor]
        acima = [d for d, ajuste in perfil.items() if ajuste > 0]
        abaixo = [d for d, ajuste in perfil.items() if ajuste < 0]

        def media(dimensoes: list[Dimension]) -> float:
            return mean(
                nota_de_demonstracao(p, d, posicao, melhora=False)
                for p in pessoas
                for d in dimensoes
                for posicao in range(47)
            )

        assert media(acima) > media(abaixo)


def _pergunta(order_index: int, dimensao: Dimension | None) -> Question:
    pergunta = Question(id=uuid.uuid4(), order_index=order_index, dimensao=dimensao)
    pergunta.options = (
        [
            QuestionOption(id=uuid.uuid4(), question_id=pergunta.id, value=str(valor))
            for valor in range(1, 6)
        ]
        if dimensao is not None
        else []
    )
    return pergunta


class TestRespostasDeDemonstracao:
    """O que o seed grava para cada pergunta do instrumento."""

    def test_uma_resposta_por_pergunta(self) -> None:
        perguntas = [_pergunta(0, Dimension.S2), _pergunta(1, None)]
        form_response_id = uuid.uuid4()

        respostas = respostas_de_demonstracao(
            form_response_id, perguntas, ADMIN, melhora=False
        )

        assert [r.question_id for r in respostas] == [p.id for p in perguntas]
        assert all(r.form_response_id == form_response_id for r in respostas)

    def test_objetiva_escolhe_uma_alternativa_da_propria_pergunta(self) -> None:
        pergunta = _pergunta(4, Dimension.S6)
        pessoa = _pessoa(RESPONDENTES_DA_EMPRESA[0])

        [resposta] = respostas_de_demonstracao(
            uuid.uuid4(), [pergunta], pessoa, melhora=False
        )

        alternativa = next(o for o in pergunta.options if o.id == resposta.option_id)
        assert alternativa.value == str(
            nota_de_demonstracao(pessoa, Dimension.S6, 4, melhora=False)
        )
        assert resposta.value is None

    def test_aberta_leva_texto_e_nenhuma_alternativa(self) -> None:
        [resposta] = respostas_de_demonstracao(
            uuid.uuid4(), [_pergunta(47, None)], ADMIN, melhora=False
        )

        assert resposta.option_id is None
        assert resposta.value
