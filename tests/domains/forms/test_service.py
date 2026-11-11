"""Testes do service do domínio forms.

Inclui a regra de organização (P-033): o `admin` age em qualquer organização,
`gestor` e `respondente` só na do próprio vínculo. E a de quem responde (P-031):
só na própria organização, qualquer que seja o papel.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domains.forms.models import Form, FormStatus
from app.domains.forms.schemas import FormCreate, FormRead, PeriodCreate, PeriodStatus
from app.domains.forms.service import FormService
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PeriodClosedError,
    ValidationError,
)


class FakeFormRepository:
    def __init__(self, existentes: list[Form] | None = None) -> None:
        self.itens: list[Form] = list(existentes or [])

    async def get_by_id(self, form_id: uuid.UUID) -> Form | None:
        return next((f for f in self.itens if f.id == form_id), None)

    async def create(self, form: Form) -> Form:
        self.itens.append(form)
        return form

    async def list_ids_by_organization(
        self, organization_id: uuid.UUID
    ) -> list[uuid.UUID]:
        return [f.id for f in self.itens if f.organization_id == organization_id]

    async def delete_by_ids(self, form_ids: list[uuid.UUID]) -> None:
        self.itens = [f for f in self.itens if f.id not in form_ids]

    async def lock_period_audience(
        self, organization_id: uuid.UUID, link_id: uuid.UUID | None
    ) -> None:
        pass

    async def has_overlapping_period(
        self,
        organization_id: uuid.UUID,
        link_id: uuid.UUID | None,
        opens_at: datetime,
        closes_at: datetime,
    ) -> bool:
        return any(
            form.organization_id == organization_id
            and form.link_id == link_id
            and form.opens_at is not None
            and form.closes_at is not None
            and form.opens_at <= closes_at
            and form.closes_at >= opens_at
            for form in self.itens
        )


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


class FakeOrganizationService:
    """Dublê do `OrganizationService`: só responde se a organização existe."""

    def __init__(self, *, existe: bool = True) -> None:
        self.existe = existe

    async def organization_exists(self, organization_id: uuid.UUID) -> bool:
        return self.existe


def servico(
    repository: FakeFormRepository,
    organizations: FakeOrganizationService | None = None,
    links: object | None = None,
) -> FormService:
    return FormService(
        repository,  # type: ignore[arg-type]
        organizations or FakeOrganizationService(),  # type: ignore[arg-type]
        links,  # type: ignore[arg-type]
    )


class FakePeriodLinkService:
    def __init__(self, *, encontrado: bool = True) -> None:
        self.encontrado = encontrado

    async def validate_mentee_link(
        self, organization_id: uuid.UUID, link_id: uuid.UUID
    ) -> None:
        if not self.encontrado:
            raise NotFoundError(f"Membro {link_id} não encontrado")


class TestCriarFormulario:
    async def test_persiste_os_campos_do_payload(self) -> None:
        repository = FakeFormRepository()
        organization_id = uuid.uuid4()

        criado = await servico(repository).create(
            FormCreate(name="Plasticidade Humana", organization_id=organization_id),
            role="gestor",
            organization_id=organization_id,
        )

        assert criado.name == "Plasticidade Humana"
        assert criado.organization_id == organization_id
        assert repository.itens == [criado]

    async def test_nasce_em_rascunho(self) -> None:
        """Um formulário publicado sem perguntas não seria respondível."""
        repository = FakeFormRepository()

        organization_id = uuid.uuid4()

        criado = await servico(repository).create(
            FormCreate(name="Plasticidade Humana", organization_id=organization_id),
            role="gestor",
            organization_id=organization_id,
        )

        assert criado.status is FormStatus.DRAFT

    async def test_gestor_em_outra_organizacao_vira_forbidden_sem_gravar(
        self,
    ) -> None:
        repository = FakeFormRepository()

        with pytest.raises(ForbiddenError):
            await servico(repository).create(
                FormCreate(name="Plasticidade Humana", organization_id=uuid.uuid4()),
                role="gestor",
                organization_id=uuid.uuid4(),
            )

        assert repository.itens == []

    async def test_admin_cadastra_em_qualquer_organizacao(self) -> None:
        repository = FakeFormRepository()
        outra_organizacao = uuid.uuid4()

        criado = await servico(repository).create(
            FormCreate(name="Plasticidade Humana", organization_id=outra_organizacao),
            role="admin",
            organization_id=uuid.uuid4(),
        )

        assert criado.organization_id == outra_organizacao

    async def test_organizacao_inexistente_vira_validation_error_sem_gravar(
        self,
    ) -> None:
        """A organização veio no corpo: inexistente é 422, não 404 (CREED-47)."""
        repository = FakeFormRepository()
        organization_id = uuid.uuid4()

        with pytest.raises(ValidationError, match=str(organization_id)):
            await servico(repository, FakeOrganizationService(existe=False)).create(
                FormCreate(name="Plasticidade Humana", organization_id=organization_id),
                role="admin",
                organization_id=uuid.uuid4(),
            )

        assert repository.itens == []

    async def test_gestor_em_organizacao_alheia_inexistente_vira_forbidden(
        self,
    ) -> None:
        """403 antes de 422: a resposta não revela quais organizações existem."""
        repository = FakeFormRepository()

        with pytest.raises(ForbiddenError):
            await servico(repository, FakeOrganizationService(existe=False)).create(
                FormCreate(name="Plasticidade Humana", organization_id=uuid.uuid4()),
                role="gestor",
                organization_id=uuid.uuid4(),
            )

        assert repository.itens == []


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


class TestQuestionariosDaOrganizacao:
    """O que a exclusão de empresa (E-6) lê e apaga."""

    async def test_lista_os_para_todos_e_os_individuais_so_da_organizacao(
        self,
    ) -> None:
        organization_id = uuid.uuid4()
        para_todos = um_form(organization_id=organization_id, link_id=None)
        individual = um_form(organization_id=organization_id, link_id=uuid.uuid4())
        de_outra = um_form()
        repository = FakeFormRepository([para_todos, de_outra, individual])

        ids = await servico(repository).list_organization_form_ids(organization_id)

        assert ids == [para_todos.id, individual.id]

    async def test_apaga_so_os_questionarios_pedidos(self) -> None:
        apagado = um_form()
        mantido = um_form()
        repository = FakeFormRepository([apagado, mantido])

        await servico(repository).delete_organization_forms([apagado.id])

        assert repository.itens == [mantido]


class TestBuscarFormularioParaQuemPede:
    async def test_mesma_organizacao_devolve_o_formulario(self) -> None:
        form = um_form()
        repository = FakeFormRepository([form])

        encontrado = await servico(repository).get_for_user(
            form.id, role="respondente", organization_id=form.organization_id
        )

        assert encontrado is form

    async def test_outra_organizacao_vira_forbidden(self) -> None:
        form = um_form()
        repository = FakeFormRepository([form])

        with pytest.raises(ForbiddenError):
            await servico(repository).get_for_user(
                form.id, role="gestor", organization_id=uuid.uuid4()
            )

    async def test_admin_le_de_qualquer_organizacao(self) -> None:
        form = um_form()
        repository = FakeFormRepository([form])

        encontrado = await servico(repository).get_for_user(
            form.id, role="admin", organization_id=uuid.uuid4()
        )

        assert encontrado is form

    async def test_inexistente_vira_not_found_antes_de_conferir_organizacao(
        self,
    ) -> None:
        """404 antes de 403: não há organização para comparar."""
        repository = FakeFormRepository()

        with pytest.raises(NotFoundError):
            await servico(repository).get_for_user(
                uuid.uuid4(), role="gestor", organization_id=uuid.uuid4()
            )


class TestConferirMesmaOrganizacao:
    """A regra de quem responde (P-031): sem exceção para o `admin`."""

    def test_mesma_organizacao_passa(self) -> None:
        organization_id = uuid.uuid4()

        servico(FakeFormRepository()).check_same_organization(
            organization_id, organization_id=organization_id
        )

    def test_outra_organizacao_vira_forbidden(self) -> None:
        with pytest.raises(ForbiddenError):
            servico(FakeFormRepository()).check_same_organization(
                uuid.uuid4(), organization_id=uuid.uuid4()
            )


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


class TestGetCurrent:
    async def test_devolve_o_formulario_aberto_e_repassa_quem_pede(self) -> None:
        form = um_form()
        link_id, organization_id = uuid.uuid4(), uuid.uuid4()
        chamadas: list[tuple[uuid.UUID, uuid.UUID, datetime]] = []

        class _Repository(FakeFormRepository):
            async def get_open_for_link(
                self, organization_id: uuid.UUID, link_id: uuid.UUID, now: datetime
            ) -> Form | None:
                chamadas.append((organization_id, link_id, now))
                return form

        antes = datetime.now(UTC)
        resultado = await servico(_Repository()).get_current(
            link_id=link_id, organization_id=organization_id
        )

        assert resultado is form
        assert chamadas[0][:2] == (organization_id, link_id)
        assert antes <= chamadas[0][2] <= datetime.now(UTC)

    async def test_sem_formulario_aberto_levanta_not_found(self) -> None:
        class _Repository(FakeFormRepository):
            async def get_open_for_link(
                self, organization_id: uuid.UUID, link_id: uuid.UUID, now: datetime
            ) -> Form | None:
                return None

        with pytest.raises(NotFoundError):
            await servico(_Repository()).get_current(
                link_id=uuid.uuid4(), organization_id=uuid.uuid4()
            )


class TestCheckAcceptsAnswers:
    AGORA = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    ABRE = datetime(2026, 11, 1, tzinfo=UTC)
    FECHA = datetime(2026, 11, 30, tzinfo=UTC)

    @pytest.fixture(autouse=True)
    def relogio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.definir_agora(monkeypatch, self.AGORA)

    def definir_agora(self, monkeypatch: pytest.MonkeyPatch, agora: datetime) -> None:
        class _Relogio(datetime):
            @classmethod
            def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
                return agora

        monkeypatch.setattr("app.domains.forms.service.datetime", _Relogio)

    async def conferir(self, form: Form, link_id: uuid.UUID | None = None) -> None:
        await servico(FakeFormRepository([form])).check_accepts_answers(
            form.id, link_id=link_id or uuid.uuid4()
        )

    def aberto(self, **campos: object) -> Form:
        return um_form(opens_at=self.ABRE, closes_at=self.FECHA, **campos)

    async def test_para_todos_aceita_qualquer_vinculo(self) -> None:
        await self.conferir(self.aberto(link_id=None))

    async def test_individual_aceita_o_proprio_vinculo(self) -> None:
        link_id = uuid.uuid4()

        await self.conferir(self.aberto(link_id=link_id), link_id)

    async def test_individual_recusa_outro_vinculo(self) -> None:
        with pytest.raises(ForbiddenError):
            await self.conferir(self.aberto(link_id=uuid.uuid4()))

    async def test_publico_vem_antes_do_periodo(self) -> None:
        form = um_form(
            opens_at=self.ABRE - timedelta(days=9),
            closes_at=self.ABRE,
            link_id=uuid.uuid4(),
        )

        with pytest.raises(ForbiddenError):
            await self.conferir(form)

    async def test_no_instante_de_abertura_aceita(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.definir_agora(monkeypatch, self.ABRE)

        await self.conferir(self.aberto())

    async def test_antes_da_abertura_recusa_e_diz_o_motivo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.definir_agora(monkeypatch, self.ABRE - timedelta(seconds=1))

        with pytest.raises(PeriodClosedError, match="ainda não começou"):
            await self.conferir(self.aberto())

    async def test_no_instante_de_fechamento_recusa_e_diz_o_motivo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.definir_agora(monkeypatch, self.FECHA)

        with pytest.raises(PeriodClosedError, match="terminou"):
            await self.conferir(self.aberto())

    async def test_sem_periodo_recusa(self) -> None:
        with pytest.raises(PeriodClosedError, match="não tem período"):
            await self.conferir(um_form(opens_at=None, closes_at=None))

    async def test_formulario_inexistente_levanta_not_found(self) -> None:
        with pytest.raises(NotFoundError):
            await servico(FakeFormRepository()).check_accepts_answers(
                uuid.uuid4(), link_id=uuid.uuid4()
            )


class TestListPeriods:
    ORG = uuid.UUID("00000000-0000-0000-0000-00000000000a")
    OUTRA_ORG = uuid.UUID("00000000-0000-0000-0000-00000000000b")

    def repositorio(self, forms: list[Form] | None = None) -> FakeFormRepository:
        class _Repository(FakeFormRepository):
            pedido: tuple[uuid.UUID, uuid.UUID | None] | None = None

            async def list_periods(
                self, organization_id: uuid.UUID, link_id: uuid.UUID | None
            ) -> list[Form]:
                type(self).pedido = (organization_id, link_id)
                return list(forms or [])

        return _Repository()

    def periodo(self, abre: timedelta, fecha: timedelta) -> Form:
        agora = datetime.now(UTC)
        return um_form(opens_at=agora + abre, closes_at=agora + fecha, link_id=None)

    async def test_calcula_a_situacao_de_cada_periodo(self) -> None:
        dia = timedelta(days=1)
        forms = [
            self.periodo(dia, 2 * dia),
            self.periodo(-dia, dia),
            self.periodo(-2 * dia, -dia),
        ]

        periodos = await servico(self.repositorio(forms)).list_periods(
            self.ORG, link_id=None, role="gestor", organization_id=self.ORG
        )

        assert [p.period_status for p in periodos] == [
            PeriodStatus.SCHEDULED,
            PeriodStatus.OPEN,
            PeriodStatus.PAST,
        ]
        assert [p.id for p in periodos] == [f.id for f in forms]

    async def test_gestor_em_outra_organizacao_e_recusado(self) -> None:
        with pytest.raises(ForbiddenError):
            await servico(self.repositorio()).list_periods(
                self.OUTRA_ORG, link_id=None, role="gestor", organization_id=self.ORG
            )

    async def test_admin_em_outra_organizacao_e_recusado(self) -> None:
        with pytest.raises(ForbiddenError):
            await servico(self.repositorio()).list_periods(
                self.OUTRA_ORG, link_id=None, role="admin", organization_id=self.ORG
            )

    async def test_gestor_nao_filtra_por_pessoa(self) -> None:
        with pytest.raises(ForbiddenError):
            await servico(self.repositorio()).list_periods(
                self.ORG, link_id=uuid.uuid4(), role="gestor", organization_id=self.ORG
            )

    async def test_admin_filtra_por_pessoa(self) -> None:
        link_id = uuid.uuid4()
        repository = self.repositorio()

        assert (
            await servico(repository).list_periods(
                self.ORG, link_id=link_id, role="admin", organization_id=self.ORG
            )
            == []
        )
        assert type(repository).pedido == (self.ORG, link_id)  # type: ignore[attr-defined]


class TestCreatePeriod:
    ORG = uuid.UUID("00000000-0000-0000-0000-00000000000a")
    OTHER_ORG = uuid.UUID("00000000-0000-0000-0000-00000000000b")

    def request(
        self, *, link_id: uuid.UUID | None = None, opens_at: datetime | None = None
    ) -> PeriodCreate:
        opens = opens_at or datetime.now(UTC) + timedelta(days=3)
        return PeriodCreate(
            opens_at=opens,
            closes_at=opens + timedelta(days=5),
            link_id=link_id,
        )

    async def test_gestor_cria_periodo_para_toda_a_organizacao(self) -> None:
        repository = FakeFormRepository()
        request = self.request()

        form = await servico(repository).create_period(
            self.ORG,
            request,
            role="gestor",
            organization_id_user=self.ORG,
        )

        assert form.link_id is None
        assert form.opens_at == request.opens_at
        assert form.closes_at == request.closes_at
        assert form.name == (
            f"Questionário {request.opens_at:%Y-%m-%d} a {request.closes_at:%Y-%m-%d}"
        )

    async def test_admin_cria_periodo_para_vinculo_da_organizacao(self) -> None:
        link_id = uuid.uuid4()
        request = self.request(link_id=link_id)
        links = FakePeriodLinkService()

        form = await servico(FakeFormRepository(), links=links).create_period(
            self.ORG,
            request,
            role="admin",
            organization_id_user=self.ORG,
        )

        assert form.link_id == link_id

    async def test_admin_sem_link_id_devolve_forbidden(self) -> None:
        repository = FakeFormRepository()

        with pytest.raises(ForbiddenError):
            await servico(repository).create_period(
                self.ORG,
                self.request(),
                role="admin",
                organization_id_user=self.ORG,
            )

        assert repository.itens == []

    async def test_gestor_com_link_id_devolve_forbidden(self) -> None:
        with pytest.raises(ForbiddenError):
            await servico(FakeFormRepository()).create_period(
                self.ORG,
                self.request(link_id=uuid.uuid4()),
                role="gestor",
                organization_id_user=self.ORG,
            )

    @pytest.mark.parametrize("role", ["gestor", "admin"])
    async def test_fora_da_organizacao_permitida_devolve_forbidden(
        self, role: str
    ) -> None:
        with pytest.raises(ForbiddenError):
            await servico(FakeFormRepository()).create_period(
                self.OTHER_ORG,
                self.request(link_id=uuid.uuid4() if role == "admin" else None),
                role=role,
                organization_id_user=self.ORG,
            )

    async def test_organizacao_inexistente_devolve_not_found(self) -> None:
        with pytest.raises(NotFoundError):
            await servico(
                FakeFormRepository(), FakeOrganizationService(existe=False)
            ).create_period(
                self.ORG,
                self.request(),
                role="gestor",
                organization_id_user=self.ORG,
            )

    async def test_abertura_no_passado_devolve_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="passado"):
            await servico(FakeFormRepository()).create_period(
                self.ORG,
                self.request(opens_at=datetime.now(UTC) - timedelta(days=1)),
                role="gestor",
                organization_id_user=self.ORG,
            )

    async def test_link_de_outra_organizacao_devolve_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="não encontrado"):
            await servico(
                FakeFormRepository(), links=FakePeriodLinkService(encontrado=False)
            ).create_period(
                self.ORG,
                self.request(link_id=uuid.uuid4()),
                role="admin",
                organization_id_user=self.ORG,
            )

    async def test_periodos_para_todos_e_individual_coexistem(self) -> None:
        opens = datetime.now(UTC) + timedelta(days=4)
        repository = FakeFormRepository(
            [
                um_form(
                    organization_id=self.ORG,
                    link_id=None,
                    opens_at=opens,
                    closes_at=opens + timedelta(days=4),
                )
            ]
        )

        individual = await servico(
            repository, links=FakePeriodLinkService()
        ).create_period(
            self.ORG,
            self.request(link_id=uuid.uuid4(), opens_at=opens),
            role="admin",
            organization_id_user=self.ORG,
        )

        assert individual.link_id is not None

    async def test_periodos_do_mesmo_publico_que_se_encostam_conflitam(self) -> None:
        opens = datetime.now(UTC) + timedelta(days=4)
        closes = opens + timedelta(days=4)
        repository = FakeFormRepository(
            [
                um_form(
                    organization_id=self.ORG,
                    link_id=None,
                    opens_at=opens,
                    closes_at=closes,
                )
            ]
        )

        with pytest.raises(ConflictError):
            await servico(repository).create_period(
                self.ORG,
                self.request(opens_at=closes),
                role="gestor",
                organization_id_user=self.ORG,
            )

    def test_fechamento_antes_da_abertura_devolve_validation_error(self) -> None:
        opens = datetime.now(UTC) + timedelta(days=4)

        with pytest.raises(ValueError, match="posterior"):
            PeriodCreate(
                opens_at=opens,
                closes_at=opens - timedelta(seconds=1),
            )
