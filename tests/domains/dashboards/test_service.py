"""Testes do serviço do domínio dashboards."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.domains.dashboards.models import Dashboard
from app.domains.dashboards.repository import (
    DashboardRepository,
    DimensionAverage,
    InvitedLink,
)
from app.domains.dashboards.schemas import CompanyDashboardRead, DashboardCreate
from app.domains.dashboards.service import (
    DashboardService,
    GroupScores,
    PersonScores,
    _alignment,
    _highest_and_lowest,
    _most_common,
    _variation,
    group_average,
)
from app.domains.forms.models import Form, FormStatus
from app.domains.prismas.service import PrismaService
from app.shared.authorization import AuthenticatedUser
from app.shared.enums import DepartmentType, Dimension, LinkType, Prisma
from app.shared.exceptions import ForbiddenError, NotFoundError, ValidationError


@pytest.fixture
def fake_gestor() -> AuthenticatedUser:
    org_id = str(uuid.uuid4())
    return AuthenticatedUser(
        sub=str(uuid.uuid4()),
        email="gestor@empresa.com",
        roles=["gestor"],
        link_id=str(uuid.uuid4()),
        organization_id=org_id,
    )


@pytest.fixture
def fake_respondente() -> AuthenticatedUser:
    org_id = str(uuid.uuid4())
    return AuthenticatedUser(
        sub=str(uuid.uuid4()),
        email="respondente@empresa.com",
        roles=["respondente"],
        link_id=str(uuid.uuid4()),
        organization_id=org_id,
    )


@pytest.mark.asyncio
async def test_criar_dashboard() -> None:
    repository = AsyncMock(spec=DashboardRepository)
    repository.create.side_effect = lambda dashboard: dashboard
    service = DashboardService(repository)

    request = DashboardCreate(
        user_id=uuid.uuid4(),
        form_id=uuid.uuid4(),
        is_private=True,
    )

    resultado = await service.create(request)

    repository.create.assert_awaited_once()
    dashboard_enviado = repository.create.await_args.args[0]

    assert isinstance(dashboard_enviado, Dashboard)
    assert dashboard_enviado.user_id == request.user_id
    assert dashboard_enviado.form_id == request.form_id
    assert dashboard_enviado.is_private is True
    assert resultado is dashboard_enviado


@pytest.mark.asyncio
async def test_dashboard_nao_encontrado_lanca_not_found_error() -> None:
    repository = AsyncMock(spec=DashboardRepository)
    repository.get_by_id.return_value = None
    service = DashboardService(repository)

    dashboard_id = uuid.uuid4()

    with pytest.raises(NotFoundError):
        await service.get(dashboard_id)

    repository.get_by_id.assert_awaited_once_with(dashboard_id)


# ---------------------------------------------------------------------------
# GET /dashboards/me
# ---------------------------------------------------------------------------


def _periodo(mes: int) -> Form:
    return Form(
        id=uuid.uuid4(),
        name=f"Questionário 2026-{mes:02d}",
        organization_id=uuid.uuid4(),
        status=FormStatus.DRAFT,
        opens_at=datetime(2026, mes, 1, 12, tzinfo=UTC),
        closes_at=datetime(2026, mes, 15, 12, tzinfo=UTC),
    )


def _linhas(
    form: Form, link_id: uuid.UUID, media: float, sem: Dimension | None = None
) -> list[DimensionAverage]:
    """As 7 médias de uma pessoa num período, todas iguais (menos a que falta)."""
    return [
        DimensionAverage(form.id, link_id, None, dimension, media)
        for dimension in Dimension
        if dimension is not sem
    ]


def _servico_do_me(
    user: AuthenticatedUser, forms: list[Form], linhas: list[DimensionAverage]
) -> tuple[DashboardService, AsyncMock]:
    repo = AsyncMock()
    repo.list_answered_forms.return_value = forms
    repo.list_dimension_averages.return_value = linhas
    repo.get_organization_name.return_value = "Empresa Exemplo"
    return DashboardService(repo, PrismaService(AsyncMock())), repo


def _pessoa(prismas: float, dimensions: float) -> PersonScores:
    return PersonScores(
        form_id=uuid.uuid4(),
        link_id=uuid.uuid4(),
        department=None,
        prismas=dict.fromkeys(Prisma, prismas),
        dimensions=dict.fromkeys(Dimension, dimensions),
    )


def test_group_average_de_grupo_vazio_e_none() -> None:
    assert group_average([]) is None


def test_group_average_e_a_media_das_pessoas() -> None:
    media = group_average([_pessoa(40, 20), _pessoa(60, 80)])

    assert media is not None
    assert media.prismas[Prisma.SEGURANCA_PSICOLOGICA] == 50
    assert media.dimensions[Dimension.S2] == 50


def test_empate_em_destaque_e_oportunidade_segue_a_ordem_dos_prismas() -> None:
    destaque, oportunidade = _highest_and_lowest(dict.fromkeys(Prisma, 50.0))

    assert destaque is Prisma.SEGURANCA_PSICOLOGICA
    assert oportunidade is Prisma.SEGURANCA_PSICOLOGICA


@pytest.mark.asyncio
async def test_me_sem_resposta_enviada_e_404(
    fake_respondente: AuthenticatedUser,
) -> None:
    service, _ = _servico_do_me(fake_respondente, [], [])

    with pytest.raises(NotFoundError, match="ainda não tem resultado"):
        await service.get_user_dashboard(user=fake_respondente, period=None)


@pytest.mark.asyncio
async def test_me_mostra_o_periodo_mais_recente_e_compara_com_o_anterior(
    fake_respondente: AuthenticatedUser,
) -> None:
    outubro, setembro = _periodo(10), _periodo(9)
    link = fake_respondente.link_uuid
    service, repo = _servico_do_me(
        fake_respondente,
        [outubro, setembro],
        _linhas(outubro, link, 4.0) + _linhas(setembro, link, 3.0),
    )

    result = await service.get_user_dashboard(user=fake_respondente, period=None)

    # Só as respostas do próprio vínculo, dos períodos que ele respondeu.
    repo.list_answered_forms.assert_awaited_once_with(link)
    repo.list_dimension_averages.assert_awaited_once_with(
        [outubro.id, setembro.id], link_id=link
    )
    assert result.period == outubro.id
    assert [p.id for p in result.periods] == [outubro.id, setembro.id]
    # Média 4 de 1 a 5 é 75 de 0 a 100; média 3 é 50.
    assert result.scores[Prisma.SEGURANCA_PSICOLOGICA] == 75.0
    assert result.dimensions[Dimension.S2] == 75.0
    [comparacao] = result.comparisons
    assert comparacao.period == setembro.id
    assert comparacao.scope is None
    assert comparacao.scores[Prisma.SEGURANCA_PSICOLOGICA] == 50.0
    assert comparacao.variation[Prisma.SEGURANCA_PSICOLOGICA] == 25.0
    assert result.comparison_options.default_period == setembro.id
    assert result.comparison_options.departments == []
    assert result.organization_name == "Empresa Exemplo"


@pytest.mark.asyncio
async def test_me_com_periodo_pedido_mostra_aquele(
    fake_respondente: AuthenticatedUser,
) -> None:
    outubro, setembro = _periodo(10), _periodo(9)
    link = fake_respondente.link_uuid
    service, _ = _servico_do_me(
        fake_respondente,
        [outubro, setembro],
        _linhas(outubro, link, 4.0) + _linhas(setembro, link, 3.0),
    )

    result = await service.get_user_dashboard(user=fake_respondente, period=setembro.id)

    assert result.period == setembro.id
    # O mais antigo não tem período anterior.
    assert result.comparison_options.default_period is None
    assert result.comparisons[0].variation[Prisma.SEGURANCA_PSICOLOGICA] == -25.0


@pytest.mark.asyncio
async def test_me_periodo_que_a_pessoa_nao_respondeu_e_404(
    fake_respondente: AuthenticatedUser,
) -> None:
    outubro = _periodo(10)
    service, _ = _servico_do_me(
        fake_respondente, [outubro], _linhas(outubro, fake_respondente.link_uuid, 4.0)
    )

    with pytest.raises(NotFoundError, match="Sem resultado seu"):
        await service.get_user_dashboard(user=fake_respondente, period=uuid.uuid4())


@pytest.mark.asyncio
async def test_me_resposta_sem_todas_as_dimensoes_nao_vira_periodo(
    fake_respondente: AuthenticatedUser,
) -> None:
    outubro, setembro = _periodo(10), _periodo(9)
    link = fake_respondente.link_uuid
    service, _ = _servico_do_me(
        fake_respondente,
        [outubro, setembro],
        _linhas(outubro, link, 4.0, sem=Dimension.S8) + _linhas(setembro, link, 3.0),
    )

    result = await service.get_user_dashboard(user=fake_respondente, period=None)

    assert [p.id for p in result.periods] == [setembro.id]
    assert result.comparisons == []


@pytest.mark.asyncio
async def test_me_textos_do_creed_vem_vazios_e_os_cards_marcam_os_prismas(
    fake_respondente: AuthenticatedUser,
) -> None:
    outubro = _periodo(10)
    link = fake_respondente.link_uuid
    # S6 e S7 altos puxam Segurança Psicológica; S5A e S5B baixos derrubam
    # Adaptabilidade Cognitiva.
    linhas = [
        DimensionAverage(outubro.id, link, None, dimension, media)
        for dimension, media in {
            Dimension.S2: 3.0,
            Dimension.S4: 3.0,
            Dimension.S5A: 1.0,
            Dimension.S5B: 1.0,
            Dimension.S6: 5.0,
            Dimension.S7: 5.0,
            Dimension.S8: 3.0,
        }.items()
    ]
    service, _ = _servico_do_me(fake_respondente, [outubro], linhas)

    summary = (
        await service.get_user_dashboard(user=fake_respondente, period=None)
    ).creed_summary

    assert summary.analiseTexto == []
    assert summary.recomendacaoTexto == []
    assert summary.prismas == {}
    assert summary.destaque is Prisma.SEGURANCA_PSICOLOGICA
    assert summary.oportunidade is Prisma.ADAPTABILIDADE_COGNITIVA


# ---------------------------------------------------------------------------
# GET /dashboards/company
# ---------------------------------------------------------------------------

ORG = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


def _gestora() -> AuthenticatedUser:
    return AuthenticatedUser(
        sub=str(uuid.uuid4()),
        email="gestora@empresa.com",
        roles=["gestor"],
        link_id=str(uuid.uuid4()),
        organization_id=str(ORG),
    )


def _admin() -> AuthenticatedUser:
    return AuthenticatedUser(
        sub=str(uuid.uuid4()),
        email="admin@creed.com",
        roles=["admin"],
        link_id=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
    )


# Quatro pessoas da organização. A nota de cada uma é igual em todas as
# dimensões: média 4 vira 75, média 2 vira 25, e assim por diante.
ANA, BRUNO, CARLA, DIEGO, FORA = (uuid.uuid4() for _ in range(5))
SETOR = {
    ANA: DepartmentType.MARKETING,
    BRUNO: DepartmentType.MARKETING,
    CARLA: DepartmentType.FINANCEIRO,
    DIEGO: None,
    FORA: None,
}


def _respostas(form: Form, medias: dict[uuid.UUID, float]) -> list[DimensionAverage]:
    return [
        DimensionAverage(form.id, link, SETOR[link], dimension, media)
        for link, media in medias.items()
        for dimension in Dimension
    ]


def _servico_da_empresa(
    forms: list[Form],
    respostas: list[DimensionAverage],
    convidados: dict[uuid.UUID, list[uuid.UUID]],
) -> DashboardService:
    """`convidados`: o público de cada período (pelo id do formulário)."""
    repo = AsyncMock()
    repo.list_company_forms.return_value = forms
    repo.list_answered_forms.return_value = forms
    repo.list_dimension_averages.return_value = respostas
    repo.list_invited_links.side_effect = lambda form: [
        InvitedLink(link, SETOR.get(link)) for link in convidados.get(form.id, [])
    ]
    repo.list_departments.return_value = [
        DepartmentType.MARKETING,
        DepartmentType.FINANCEIRO,
        DepartmentType.RECURSOS_HUMANOS,
    ]
    repo.list_member_names.side_effect = lambda ids: {i: f"Pessoa {i}" for i in ids}
    repo.link_in_organization.return_value = True
    repo.get_organization_name.return_value = "Empresa Exemplo"
    return DashboardService(repo, PrismaService(AsyncMock()))


def _cenario() -> tuple[DashboardService, Form, Form]:
    """Outubro: as quatro pessoas. Setembro: Ana e Carla. `FORA` respondeu outubro,
    mas não é do público do período: não entra em nada."""
    outubro, setembro = _periodo(10), _periodo(9)
    for form in (outubro, setembro):
        form.organization_id = ORG
    publico = [ANA, BRUNO, CARLA, DIEGO]
    service = _servico_da_empresa(
        [outubro, setembro],
        _respostas(outubro, {ANA: 4, BRUNO: 2, CARLA: 5, DIEGO: 3, FORA: 1})
        + _respostas(setembro, {ANA: 3, CARLA: 4}),
        {outubro.id: [*publico, uuid.uuid4()], setembro.id: publico},
    )
    return service, outubro, setembro


async def _empresa(service: DashboardService, **recorte: object) -> CompanyDashboardRead:
    argumentos: dict[str, object] = {
        "user": _gestora(),
        "organization_id": None,
        "period": None,
        "department": None,
        "member_id": None,
    } | recorte
    return await service.get_company_dashboard(**argumentos)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_empresa_respondente_nao_ve(fake_respondente: AuthenticatedUser) -> None:
    service, _, _ = _cenario()

    with pytest.raises(ForbiddenError, match="Só gestores e administradores"):
        await _empresa(service, user=fake_respondente)


@pytest.mark.asyncio
async def test_empresa_admin_precisa_informar_a_organizacao() -> None:
    service, _, _ = _cenario()

    with pytest.raises(ValidationError, match="informar a organização"):
        await _empresa(service, user=_admin())

    result = await _empresa(service, user=_admin(), organization_id=ORG)
    assert result.organization_name == "Empresa Exemplo"


@pytest.mark.asyncio
async def test_empresa_gestora_nao_ve_outra_organizacao() -> None:
    service, _, _ = _cenario()

    with pytest.raises(ForbiddenError, match="outra organização"):
        await _empresa(service, organization_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_empresa_setor_e_pessoa_juntos_e_422() -> None:
    service, _, _ = _cenario()

    with pytest.raises(ValidationError, match="não os dois"):
        await _empresa(service, department=DepartmentType.MARKETING, member_id=ANA)


@pytest.mark.asyncio
async def test_empresa_sem_periodo_respondido_e_404() -> None:
    form = _periodo(10)
    service = _servico_da_empresa([form], [], {form.id: [ANA]})

    with pytest.raises(NotFoundError, match="Ainda não há resultados"):
        await _empresa(service)


@pytest.mark.asyncio
async def test_empresa_inteira_media_so_do_publico_e_resumo() -> None:
    service, outubro, setembro = _cenario()

    result = await _empresa(service)

    assert result.period == outubro.id
    assert [p.id for p in result.periods] == [outubro.id, setembro.id]
    # (75 + 25 + 100 + 50) / 4 = 62,5, arredondado para 62. `FORA` não entra.
    assert result.scores[Prisma.SEGURANCA_PSICOLOGICA] == 62
    summary = result.company_summary
    assert summary.concluidos == 4
    assert summary.convidados == 5
    # Todas as notas iguais entre prismas: a ordem de `Prisma` desempata.
    assert summary.destaque.prisma is Prisma.SEGURANCA_PSICOLOGICA
    assert summary.destaque.valor == 62
    assert result.department is None
    assert result.member_id is None
    # A gestora (de `_empresa`) não respondeu: não vê ninguém no filtro.
    assert result.members == []
    assert result.departments == [DepartmentType.MARKETING, DepartmentType.FINANCEIRO]


@pytest.mark.asyncio
async def test_empresa_inteira_compara_com_setores_e_outros_periodos() -> None:
    service, _, setembro = _cenario()

    result = await _empresa(service)

    combinacoes = {(c.period, c.scope) for c in result.comparisons}
    assert combinacoes == {
        (None, "Marketing"),
        (None, "Financeiro"),
        (setembro.id, None),
        (setembro.id, "Marketing"),
        (setembro.id, "Financeiro"),
        # A empresa toda é o próprio recorte: só em outro período.
        (setembro.id, "organization"),
    }
    marketing = next(
        c for c in result.comparisons if c.scope == "Marketing" and c.period is None
    )
    # Marketing em outubro: (75 + 25) / 2 = 50; exibido 62, variação 12.
    assert marketing.scores[Prisma.SEGURANCA_PSICOLOGICA] == 50
    assert marketing.variation[Prisma.SEGURANCA_PSICOLOGICA] == 12


@pytest.mark.asyncio
async def test_empresa_recorte_por_setor_muda_a_pagina_menos_o_mapa() -> None:
    service, _, setembro = _cenario()

    inteira = await _empresa(service)
    marketing = await _empresa(service, department=DepartmentType.MARKETING)

    assert marketing.department is DepartmentType.MARKETING
    assert marketing.scores[Prisma.SEGURANCA_PSICOLOGICA] == 50
    assert marketing.company_summary.concluidos == 2
    assert marketing.company_summary.convidados == 2
    assert marketing.department_matrix == inteira.department_matrix
    combinacoes = {(c.period, c.scope) for c in marketing.comparisons}
    # O próprio Marketing no período exibido não é comparação; a empresa toda é.
    assert (None, "Marketing") not in combinacoes
    assert (None, "organization") in combinacoes
    assert (setembro.id, None) in combinacoes


@pytest.mark.asyncio
async def test_empresa_recorte_por_pessoa_sem_alinhamento() -> None:
    service, _, _ = _cenario()

    result = await _empresa(service, user=_admin(), organization_id=ORG, member_id=CARLA)

    assert result.member_id == CARLA
    assert result.scores[Prisma.SEGURANCA_PSICOLOGICA] == 100
    assert result.alignment is None
    assert result.company_summary.concluidos == 1


@pytest.mark.asyncio
async def test_empresa_pessoa_de_outra_organizacao_e_404() -> None:
    service, _, _ = _cenario()
    service.repository.link_in_organization.return_value = False  # type: ignore[attr-defined]

    with pytest.raises(NotFoundError, match="não é desta organização"):
        await _empresa(
            service, user=_admin(), organization_id=ORG, member_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_empresa_setor_sem_resposta_no_periodo_e_404() -> None:
    service, _, _ = _cenario()

    with pytest.raises(NotFoundError, match="Sem respostas deste recorte"):
        await _empresa(service, department=DepartmentType.RECURSOS_HUMANOS)


@pytest.mark.asyncio
async def test_empresa_mapa_so_tem_setor_com_resposta() -> None:
    service, _, _ = _cenario()

    linhas = {r.department: r for r in (await _empresa(service)).department_matrix}

    # RH está cadastrado, mas ninguém dele respondeu: fica de fora do mapa.
    assert list(linhas) == [DepartmentType.MARKETING, DepartmentType.FINANCEIRO]
    assert linhas[DepartmentType.MARKETING].respondents == 2
    # Marketing 50 contra a organização 62.
    assert linhas[DepartmentType.MARKETING].difference == dict.fromkeys(Prisma, -12)


@pytest.mark.parametrize(
    ("notas", "nivel"),
    [
        ([80, 80, 80, 50], "alinhado"),  # 75% numa faixa só
        ([20, 30, 80, 90], "dividido"),  # metade em cada ponta
        ([20, 50, 60, 80], "moderado"),
    ],
)
def test_alinhamento_le_as_faixas(notas: list[int], nivel: str) -> None:
    pessoas = [_pessoa(nota, nota) for nota in notas]

    alinhamento = _alignment(pessoas)

    assert alinhamento.respondents == 4
    assert alinhamento.prismas is not None
    prisma = alinhamento.prismas[Prisma.SEGURANCA_PSICOLOGICA]
    assert prisma.level == nivel
    assert prisma.bands.baixa + prisma.bands.media + prisma.bands.alta == 4


def test_alinhamento_faixas_nos_limites() -> None:
    """40 ainda é baixa, 70 ainda é média (P-061)."""
    prismas = _alignment(
        [_pessoa(40, 40), _pessoa(41, 41), _pessoa(70, 70), _pessoa(71, 71)]
    ).prismas

    assert prismas is not None
    bands = prismas[Prisma.SEGURANCA_PSICOLOGICA].bands
    assert (bands.baixa, bands.media, bands.alta) == (1, 2, 1)


def test_variacao_usa_os_valores_arredondados() -> None:
    """A tela mostra "62 / 59, aumentou 3", nunca 4."""
    variacao = _variation(dict.fromkeys(Prisma, 62.4), dict.fromkeys(Prisma, 58.6))

    assert variacao[Prisma.SEGURANCA_PSICOLOGICA] == 3


def test_mais_comum_e_o_prisma_que_mais_vezes_e_o_maior() -> None:
    def pessoa(maior: Prisma) -> PersonScores:
        prismas = dict.fromkeys(Prisma, 50.0) | {maior: 90.0}
        return PersonScores(uuid.uuid4(), uuid.uuid4(), None, prismas, {})

    pessoas = [
        pessoa(Prisma.CULTURA_EMPREENDEDORA),
        pessoa(Prisma.CULTURA_EMPREENDEDORA),
        pessoa(Prisma.LIDERANCA_ADAPTATIVA),
    ]
    grupo = GroupScores(
        prismas=dict.fromkeys(Prisma, 50.0) | {Prisma.LIDERANCA_ADAPTATIVA: 99.0},
        dimensions={},
    )

    # A moda vence a maior média do grupo.
    assert _most_common(pessoas, grupo) is Prisma.CULTURA_EMPREENDEDORA


def _gestora_que_respondeu() -> AuthenticatedUser:
    """A gestora com o vínculo de `DIEGO`, que respondeu outubro."""
    return AuthenticatedUser(
        sub=str(uuid.uuid4()),
        email="gestora@empresa.com",
        roles=["gestor"],
        link_id=str(DIEGO),
        organization_id=str(ORG),
    )


@pytest.mark.asyncio
async def test_empresa_admin_ve_todas_as_pessoas_no_filtro() -> None:
    service, _, _ = _cenario()

    result = await _empresa(service, user=_admin(), organization_id=ORG)

    assert {m.id for m in result.members} == {ANA, BRUNO, CARLA, DIEGO}


@pytest.mark.asyncio
async def test_empresa_gestora_ve_so_ela_no_filtro() -> None:
    """O resultado individual é anônimo para a empresa."""
    service, _, _ = _cenario()

    result = await _empresa(service, user=_gestora_que_respondeu())

    assert [m.id for m in result.members] == [DIEGO]


@pytest.mark.asyncio
async def test_empresa_gestora_ve_o_proprio_resultado() -> None:
    service, _, _ = _cenario()

    result = await _empresa(service, user=_gestora_que_respondeu(), member_id=DIEGO)

    assert result.member_id == DIEGO
    # Média 3 de 1 a 5 é 50 de 0 a 100.
    assert result.scores[Prisma.SEGURANCA_PSICOLOGICA] == 50
    # E pode se comparar com a empresa toda e com os setores.
    assert {c.scope for c in result.comparisons if c.period is None} == {
        "Marketing",
        "Financeiro",
        "organization",
    }


@pytest.mark.asyncio
async def test_empresa_gestora_nao_ve_o_resultado_de_outra_pessoa() -> None:
    service, _, _ = _cenario()

    with pytest.raises(ForbiddenError, match="só o próprio resultado individual"):
        await _empresa(service, user=_gestora_que_respondeu(), member_id=ANA)


# ---------------------------------------------------------------------------
# GET /dashboards/overview — o retrato atual
# ---------------------------------------------------------------------------

EMPRESA_A, EMPRESA_B = uuid.uuid4(), uuid.uuid4()


def _servico_do_retrato(
    forms: list[Form],
    respostas: list[DimensionAverage],
    convidados: dict[uuid.UUID, list[uuid.UUID]],
    *,
    mentorandos: list[uuid.UUID] | None = None,
) -> DashboardService:
    repo = AsyncMock()
    repo.list_companies.return_value = [
        (EMPRESA_A, "Empresa A"),
        (EMPRESA_B, "Empresa B"),
    ]
    repo.list_opened_forms.return_value = forms
    repo.list_dimension_averages.return_value = respostas
    repo.list_invited_links.side_effect = lambda form: [
        InvitedLink(link, None) for link in convidados.get(form.id, [])
    ]
    repo.list_link_ids.return_value = mentorandos or []
    return DashboardService(repo, PrismaService(AsyncMock()))


def _periodo_de(organization_id: uuid.UUID, mes: int) -> Form:
    form = _periodo(mes)
    form.organization_id = organization_id
    return form


@pytest.mark.asyncio
async def test_retrato_so_da_administradora() -> None:
    service = _servico_do_retrato([], [], {})

    with pytest.raises(ForbiddenError, match="Só a administradora"):
        await service.get_overview(user=_gestora(), kind="companies")


@pytest.mark.asyncio
async def test_retrato_sem_resposta_e_404() -> None:
    service = _servico_do_retrato([], [], {})

    with pytest.raises(NotFoundError, match="Ainda não há resultados"):
        await service.get_overview(user=_admin(), kind="companies")


@pytest.mark.asyncio
async def test_retrato_cada_pessoa_entra_com_a_resposta_mais_recente() -> None:
    a_set, a_out, b_out = (
        _periodo_de(EMPRESA_A, 9),
        _periodo_de(EMPRESA_A, 10),
        _periodo_de(EMPRESA_B, 10),
    )
    service = _servico_do_retrato(
        [a_set, a_out, b_out],
        # Ana respondeu setembro (2) e outubro (4): entra com outubro.
        # Bruno só setembro (5): entra com setembro. Carla é da Empresa B (3).
        _respostas(a_set, {ANA: 2, BRUNO: 5})
        + _respostas(a_out, {ANA: 4})
        + _respostas(b_out, {CARLA: 3}),
        {a_set.id: [ANA, BRUNO], a_out.id: [ANA, BRUNO], b_out.id: [CARLA]},
    )

    result = await service.get_overview(user=_admin(), kind="companies")

    # (75 + 100 + 50) / 3 = 75.
    assert result.scores[Prisma.SEGURANCA_PSICOLOGICA] == 75
    assert result.company_summary.concluidos == 3
    assert result.responses_from == a_set.opens_at
    assert result.responses_to == b_out.closes_at


@pytest.mark.asyncio
async def test_retrato_das_empresas_compara_e_mapeia_cada_empresa() -> None:
    a, b = _periodo_de(EMPRESA_A, 10), _periodo_de(EMPRESA_B, 10)
    service = _servico_do_retrato(
        [a, b],
        _respostas(a, {ANA: 5, BRUNO: 5}) + _respostas(b, {CARLA: 2}),
        {a.id: [ANA, BRUNO], b.id: [CARLA]},
    )

    result = await service.get_overview(user=_admin(), kind="companies")

    # Média geral: (100 + 100 + 25) / 3 = 75.
    grupos = {g.label: g for g in result.groups}
    assert grupos["Empresa A"].respondents == 2
    assert grupos["Empresa A"].difference[Prisma.SEGURANCA_PSICOLOGICA] == 25
    assert grupos["Empresa B"].difference[Prisma.SEGURANCA_PSICOLOGICA] == -50
    comparacoes = {c.scope: c for c in result.comparisons}
    assert set(comparacoes) == {str(EMPRESA_A), str(EMPRESA_B)}
    assert all(c.period is None for c in result.comparisons)
    # Exibido (75) menos a Empresa B (25).
    assert comparacoes[str(EMPRESA_B)].variation[Prisma.SEGURANCA_PSICOLOGICA] == 50


@pytest.mark.asyncio
async def test_retrato_dos_mentorandos_so_conta_vinculo_mentoria() -> None:
    individual = _periodo(10)
    service = _servico_do_retrato(
        [individual],
        # A gestora da CREED respondeu, mas não é mentoranda: fica de fora.
        _respostas(individual, {ANA: 4, DIEGO: 1}),
        {individual.id: [ANA, DIEGO]},
        mentorandos=[ANA],
    )
    nomes = service.repository.list_member_names  # type: ignore[attr-defined]
    nomes.side_effect = lambda ids: dict.fromkeys(ids, "Ana")

    result = await service.get_overview(user=_admin(), kind="mentees")

    assert result.kind == "mentees"
    assert result.company_summary.concluidos == 1
    assert result.company_summary.convidados == 1
    assert result.scores[Prisma.SEGURANCA_PSICOLOGICA] == 75
    # Uma linha e uma comparação por mentorando.
    assert [(g.id, g.label) for g in result.groups] == [(ANA, "Ana")]
    assert [c.scope for c in result.comparisons] == [str(ANA)]


def _mentoria(link: uuid.UUID) -> tuple[DashboardService, AsyncMock]:
    """A administradora pedindo o resultado de um mentorando que respondeu outubro."""
    outubro = _periodo(10)
    service, repo = _servico_do_me(_admin(), [outubro], _linhas(outubro, link, 4.0))
    repo.list_link_ids.return_value = [link]
    repo.list_member_names.return_value = {link: "Mentorando 1"}
    return service, repo


@pytest.mark.asyncio
async def test_admin_ve_o_dashboard_individual_do_mentorando() -> None:
    admin, mentorando = _admin(), uuid.uuid4()
    service, repo = _mentoria(mentorando)

    result = await service.get_member_dashboard(
        user=admin, member_id=mentorando, period=None
    )

    # Só as respostas do mentorando, e ele precisa ser da mentoria da CREED.
    repo.list_answered_forms.assert_awaited_once_with(mentorando)
    repo.list_link_ids.assert_awaited_once_with(
        admin.organization_uuid, LinkType.MENTORIA
    )
    assert result.member_name == "Mentorando 1"
    assert result.scores[Prisma.SEGURANCA_PSICOLOGICA] == 75.0


@pytest.mark.asyncio
async def test_resultado_de_mentorando_e_so_da_admin(
    fake_gestor: AuthenticatedUser,
) -> None:
    mentorando = uuid.uuid4()
    service, _ = _mentoria(mentorando)

    with pytest.raises(ForbiddenError):
        await service.get_member_dashboard(
            user=fake_gestor, member_id=mentorando, period=None
        )


@pytest.mark.asyncio
async def test_vinculo_que_nao_e_mentorando_e_404() -> None:
    service, _ = _mentoria(uuid.uuid4())

    with pytest.raises(NotFoundError, match="não encontrado"):
        await service.get_member_dashboard(
            user=_admin(), member_id=uuid.uuid4(), period=None
        )


@pytest.mark.asyncio
async def test_mentorando_sem_resposta_e_404() -> None:
    mentorando = uuid.uuid4()
    service, repo = _mentoria(mentorando)
    repo.list_answered_forms.return_value = []
    repo.list_dimension_averages.return_value = []

    with pytest.raises(NotFoundError, match="ainda não tem resultado"):
        await service.get_member_dashboard(
            user=_admin(), member_id=mentorando, period=None
        )
