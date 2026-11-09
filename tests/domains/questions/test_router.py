"""Testes de app/domains/questions/router.py — contrato HTTP e guarda.

A guarda roda de verdade: só o `validate_token` e o `UserService` são dublês, como
em `tests/domains/participants/test_router.py`. O `client` padrão já entra como
`admin`; os testes de papel e de token trocam isso explicitamente.

Não existe banco de teste no projeto: a app é montada só com este
roteador, e a service é trocada por um dublê em memória. Quem prova a
regra de negócio (conflito de posição) é tests/domains/questions/test_service.py;
quem prova ordenação e filtro de verdade, no banco, é a verificação manual
descrita na própria tarefa CREED-353.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.questions.dependencies import (
    get_option_translation_service,
    get_service,
    get_translation_service,
)
from app.domains.questions.models import (
    Question,
    QuestionLang,
    QuestionOption,
    QuestionOptionTranslation,
    QuestionSection,
    QuestionTranslation,
    QuestionType,
)
from app.domains.questions.router import router
from app.domains.questions.schemas import (
    QuestionCreate,
    QuestionOptionTranslationCreate,
    QuestionTranslationCreate,
)
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TOKEN = {"Authorization": "Bearer valido"}


class _FakeQuestionService:
    """Duble da service: devolve o que for configurado, sem reimplementar regra.

    `conflito=True` só faz `create` levantar `ConflictError` — não reproduz a
    lógica real de "mesma posição no mesmo formulário". Essa regra já está
    coberta em tests/domains/questions/test_service.py; aqui o que se prova é
    só a tradução ConflictError -> 409, que é trabalho do router.

    `formulario_inexistente=True` faz as duas rotas recusarem como o service real
    recusa um formulário que não existe: `ValidationError` no cadastro e
    `NotFoundError` na listagem. `proibido=True` faz as duas levantarem
    `ForbiddenError`, como o service real faz para formulário de outra organização.
    """

    def __init__(
        self,
        existentes: list[Question] | None = None,
        *,
        conflito: bool = False,
        formulario_inexistente: bool = False,
        proibido: bool = False,
    ) -> None:
        self.itens: list[Question] = list(existentes or [])
        self.conflito = conflito
        self.formulario_inexistente = formulario_inexistente
        self.proibido = proibido
        self.quem_pediu: tuple[str, uuid.UUID] | None = None
        self.idioma_pedido: QuestionLang | str | None = "nao chamado"

    async def create(
        self, request: QuestionCreate, *, role: str, organization_id: uuid.UUID
    ) -> Question:
        self.quem_pediu = (role, organization_id)
        if self.proibido:
            raise ForbiddenError("Sem acesso a formulário de outra organização")
        if self.formulario_inexistente:
            raise ValidationError(f"Formulário {request.form_id} não encontrado")
        if self.conflito:
            raise ConflictError(
                f"Já existe pergunta na posição {request.order_index} "
                f"do formulário {request.form_id}"
            )

        question = Question(
            id=uuid.uuid4(),
            form_id=request.form_id,
            text=request.text,
            order_index=request.order_index,
            type=request.type,
            section=request.section,
            required=request.required,
            dimensao=request.dimensao,
            prisma=request.prisma,
            created_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
        self.itens.append(question)
        return question

    async def list_for_form(
        self,
        form_id: uuid.UUID,
        section: QuestionSection | None = None,
        lang: QuestionLang | None = None,
        *,
        role: str,
        organization_id: uuid.UUID,
    ) -> list[Question]:
        self.quem_pediu = (role, organization_id)
        self.idioma_pedido = lang
        if self.proibido:
            raise ForbiddenError("Sem acesso a formulário de outra organização")
        if self.formulario_inexistente:
            raise NotFoundError(f"Formulário {form_id} não encontrado")
        resultado = [
            q
            for q in self.itens
            if q.form_id == form_id and (section is None or q.section == section)
        ]
        return sorted(resultado, key=lambda q: q.order_index)


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    return fastapi_app


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


def autenticar_como(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    organization_id: uuid.UUID = ORGANIZATION_ID,
) -> None:
    """Faz o token de teste valer como um usuário ativo com o papel indicado."""
    email = "dev@creed.example.com"

    async def _fake_validate_token(token: str) -> dict[str, Any]:
        return {"sub": "sub-dev", "email": email, "realm_access": {"roles": [role]}}

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=role,
        link_id=uuid.uuid4(),
        organization_id=organization_id,
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Entra como `admin`, com o token em toda requisição."""
    autenticar_como(app, monkeypatch, "admin")
    return TestClient(app, headers=TOKEN)


def _use_fake_service(app: FastAPI, fake_service: _FakeQuestionService) -> None:
    app.dependency_overrides[get_service] = lambda: fake_service


def _payload(**campos: object) -> dict[str, object]:
    padrao: dict[str, object] = {
        "form_id": str(uuid.uuid4()),
        "text": "Como voce avalia sua adaptabilidade?",
        "order_index": 0,
        "type": "objective",
        "section": "assessment",
    }
    return {**padrao, **campos}


class TestCriarPergunta:
    def test_com_corpo_valido_devolve_201_com_o_corpo_completo(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.post("/questions", json=_payload())

        assert response.status_code == 201
        body = response.json()
        assert set(body) == {
            "id",
            "form_id",
            "text",
            "order_index",
            "type",
            "section",
            "required",
            "dimensao",
            "prisma",
            "created_at",
        }
        assert body["section"] == "assessment"
        assert body["dimensao"] is None

    def test_com_dimensao_valida_devolve_a_dimensao(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.post("/questions", json=_payload(dimensao="S5A"))

        assert response.status_code == 201
        assert response.json()["dimensao"] == "S5A"

    def test_com_conflito_de_posicao_devolve_409(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Prova só a tradução do router: ConflictError -> 409.

        A regra "mesma posição, mesmo formulário, mesmo em outra seção" é
        provada com a service real em test_service.py — não é reimplementada
        aqui.
        """
        _use_fake_service(app, _FakeQuestionService(conflito=True))

        response = client.post("/questions", json=_payload())

        assert response.status_code == 409

    def test_com_formulario_inexistente_devolve_422_com_detail_texto(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService(formulario_inexistente=True))
        payload = _payload()

        response = client.post("/questions", json=payload)

        assert response.status_code == 422
        assert response.json()["detail"] == (
            f"Formulário {payload['form_id']} não encontrado"
        )

    def test_com_texto_vazio_devolve_422(self, app: FastAPI, client: TestClient) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.post("/questions", json=_payload(text=""))

        assert response.status_code == 422

    def test_sem_secao_devolve_422(self, app: FastAPI, client: TestClient) -> None:
        _use_fake_service(app, _FakeQuestionService())

        payload = _payload()
        del payload["section"]

        response = client.post("/questions", json=payload)

        assert response.status_code == 422

    def test_com_tipo_invalido_devolve_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.post("/questions", json=_payload(type="invalido"))

        assert response.status_code == 422

    def test_com_secao_invalida_devolve_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.post("/questions", json=_payload(section="invalida"))

        assert response.status_code == 422

    def test_com_form_id_que_nao_e_uuid_devolve_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.post("/questions", json=_payload(form_id="nao-e-uuid"))

        assert response.status_code == 422

    def test_com_order_index_negativo_devolve_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.post("/questions", json=_payload(order_index=-1))

        assert response.status_code == 422

    def test_com_prisma_fora_do_enum_devolve_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.post("/questions", json=_payload(prisma="inexistente"))

        assert response.status_code == 422

    def test_com_dimensao_fora_do_enum_devolve_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.post("/questions", json=_payload(dimensao="inexistente"))

        assert response.status_code == 422


class TestListarPerguntasDoFormulario:
    def test_devolve_200_com_a_lista_em_ordem_de_posicao(
        self, app: FastAPI, client: TestClient
    ) -> None:
        form_id = uuid.uuid4()
        segunda = Question(
            id=uuid.uuid4(),
            form_id=form_id,
            text="Segunda",
            order_index=1,
            type=QuestionType.DESCRIPTIVE,
            section=QuestionSection.PROFILE,
            required=True,
            dimensao=None,
            prisma=None,
            created_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
        primeira = Question(
            id=uuid.uuid4(),
            form_id=form_id,
            text="Primeira",
            order_index=0,
            type=QuestionType.OBJECTIVE,
            section=QuestionSection.ASSESSMENT,
            required=True,
            dimensao=None,
            prisma=None,
            created_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
        _use_fake_service(app, _FakeQuestionService([segunda, primeira]))

        response = client.get(f"/forms/{form_id}/questions")

        assert response.status_code == 200
        textos = [item["text"] for item in response.json()]
        assert textos == ["Primeira", "Segunda"]

    def test_formulario_sem_pergunta_devolve_200_com_lista_vazia(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.get(f"/forms/{uuid.uuid4()}/questions")

        assert response.status_code == 200
        assert response.json() == []

    def test_formulario_inexistente_devolve_404(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService(formulario_inexistente=True))

        response = client.get(f"/forms/{uuid.uuid4()}/questions")

        assert response.status_code == 404

    def test_filtro_por_secao_devolve_so_as_daquela_secao_em_ordem(
        self, app: FastAPI, client: TestClient
    ) -> None:
        form_id = uuid.uuid4()
        assessment_2 = Question(
            id=uuid.uuid4(),
            form_id=form_id,
            text="Assessment 2",
            order_index=2,
            type=QuestionType.OBJECTIVE,
            section=QuestionSection.ASSESSMENT,
            required=True,
            dimensao=None,
            prisma=None,
            created_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
        profile_1 = Question(
            id=uuid.uuid4(),
            form_id=form_id,
            text="Profile 1",
            order_index=1,
            type=QuestionType.DESCRIPTIVE,
            section=QuestionSection.PROFILE,
            required=True,
            dimensao=None,
            prisma=None,
            created_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
        assessment_0 = Question(
            id=uuid.uuid4(),
            form_id=form_id,
            text="Assessment 0",
            order_index=0,
            type=QuestionType.OBJECTIVE,
            section=QuestionSection.ASSESSMENT,
            required=True,
            dimensao=None,
            prisma=None,
            created_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
        _use_fake_service(
            app, _FakeQuestionService([assessment_2, profile_1, assessment_0])
        )

        response = client.get(f"/forms/{form_id}/questions?section=assessment")

        assert response.status_code == 200
        textos = [item["text"] for item in response.json()]
        assert textos == ["Assessment 0", "Assessment 2"]

    def test_secao_que_nao_existe_no_filtro_devolve_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.get(f"/forms/{uuid.uuid4()}/questions?section=inexistente")

        assert response.status_code == 422


class TestGuarda:
    def test_sem_token_criar_e_listar_devolvem_401(self, app: FastAPI) -> None:
        _use_fake_service(app, _FakeQuestionService())
        sem_token = TestClient(app)

        assert sem_token.post("/questions", json=_payload()).status_code == 401
        assert sem_token.get(f"/forms/{uuid.uuid4()}/questions").status_code == 401

    def test_respondente_criando_devolve_403_pela_guarda(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "respondente")
        service = _FakeQuestionService()
        _use_fake_service(app, service)

        response = client.post("/questions", json=_payload())

        assert response.status_code == 403
        assert service.quem_pediu is None

    def test_respondente_listando_passa_papel_e_organizacao_ao_service(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "respondente")
        service = _FakeQuestionService()
        _use_fake_service(app, service)

        response = client.get(f"/forms/{uuid.uuid4()}/questions")

        assert response.status_code == 200
        assert service.quem_pediu == ("respondente", ORGANIZATION_ID)

    def test_formulario_de_outra_organizacao_devolve_403_nas_duas_rotas(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "gestor")
        _use_fake_service(app, _FakeQuestionService(proibido=True))

        assert client.post("/questions", json=_payload()).status_code == 403
        assert client.get(f"/forms/{uuid.uuid4()}/questions").status_code == 403


def _pergunta_com_alternativas(form_id: uuid.UUID) -> Question:
    """Pergunta com tradução EN; das duas alternativas, só a primeira tem tradução."""
    question_id = uuid.uuid4()
    return Question(
        id=question_id,
        form_id=form_id,
        text="Você se adapta bem?",
        order_index=0,
        type=QuestionType.OBJECTIVE,
        section=QuestionSection.ASSESSMENT,
        required=True,
        dimensao=None,
        prisma=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
        translations=[
            QuestionTranslation(lang=QuestionLang.EN, text="Do you adapt well?")
        ],
        options=[
            QuestionOption(
                id=uuid.uuid4(),
                question_id=question_id,
                label="Sim",
                value="sim",
                order_index=0,
                created_at=datetime(2026, 10, 14, tzinfo=UTC),
                translations=[
                    QuestionOptionTranslation(lang=QuestionLang.EN, label="Yes")
                ],
            ),
            QuestionOption(
                id=uuid.uuid4(),
                question_id=question_id,
                label="Não",
                value="nao",
                order_index=1,
                created_at=datetime(2026, 10, 14, tzinfo=UTC),
            ),
        ],
    )


class TestListarPorIdioma:
    def test_cada_pergunta_vem_com_as_alternativas(
        self, app: FastAPI, client: TestClient
    ) -> None:
        form_id = uuid.uuid4()
        _use_fake_service(
            app, _FakeQuestionService([_pergunta_com_alternativas(form_id)])
        )

        response = client.get(f"/forms/{form_id}/questions")

        assert response.status_code == 200
        options = response.json()[0]["options"]
        assert set(options[0]) == {
            "id",
            "question_id",
            "label",
            "value",
            "order_index",
            "created_at",
        }
        assert [option["value"] for option in options] == ["sim", "nao"]

    @pytest.mark.parametrize("query", ["", "?lang=pt", "?lang=pt-BR"])
    def test_sem_lang_ou_com_pt_devolve_o_pt(
        self, app: FastAPI, client: TestClient, query: str
    ) -> None:
        form_id = uuid.uuid4()
        service = _FakeQuestionService([_pergunta_com_alternativas(form_id)])
        _use_fake_service(app, service)

        response = client.get(f"/forms/{form_id}/questions{query}")

        assert response.status_code == 200
        body = response.json()[0]
        assert body["text"] == "Você se adapta bem?"
        assert [option["label"] for option in body["options"]] == ["Sim", "Não"]
        assert service.idioma_pedido is None

    def test_lang_en_traduz_e_cai_no_pt_onde_nao_ha_traducao(
        self, app: FastAPI, client: TestClient
    ) -> None:
        form_id = uuid.uuid4()
        service = _FakeQuestionService([_pergunta_com_alternativas(form_id)])
        _use_fake_service(app, service)

        response = client.get(f"/forms/{form_id}/questions?lang=en")

        assert response.status_code == 200
        body = response.json()[0]
        assert body["text"] == "Do you adapt well?"
        assert [option["label"] for option in body["options"]] == ["Yes", "Não"]
        assert service.idioma_pedido is QuestionLang.EN

    def test_lang_fora_da_lista_devolve_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionService())

        response = client.get(f"/forms/{uuid.uuid4()}/questions?lang=fr")

        assert response.status_code == 422


QUESTION_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
OPTION_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


class _FakeTranslationService:
    """Duble da service de tradução de pergunta: devolve a tradução ou levanta o
    erro configurado. A regra (idioma repetido, acesso) é provada em test_service.py.
    """

    def __init__(self, erro: Exception | None = None) -> None:
        self.erro = erro
        self.pedido: tuple[uuid.UUID, str, uuid.UUID] | None = None

    async def create(
        self,
        question_id: uuid.UUID,
        request: QuestionTranslationCreate,
        *,
        role: str,
        organization_id: uuid.UUID,
    ) -> QuestionTranslation:
        self.pedido = (question_id, role, organization_id)
        if self.erro is not None:
            raise self.erro
        return QuestionTranslation(
            id=uuid.uuid4(),
            question_id=question_id,
            lang=request.lang,
            text=request.text,
            created_at=datetime(2026, 11, 7, tzinfo=UTC),
        )


class _FakeOptionTranslationService:
    """Mesmo duble, para a tradução de alternativa."""

    def __init__(self, erro: Exception | None = None) -> None:
        self.erro = erro
        self.pedido: tuple[uuid.UUID, str, uuid.UUID] | None = None

    async def create(
        self,
        option_id: uuid.UUID,
        request: QuestionOptionTranslationCreate,
        *,
        role: str,
        organization_id: uuid.UUID,
    ) -> QuestionOptionTranslation:
        self.pedido = (option_id, role, organization_id)
        if self.erro is not None:
            raise self.erro
        return QuestionOptionTranslation(
            id=uuid.uuid4(),
            option_id=option_id,
            lang=request.lang,
            label=request.label,
            created_at=datetime(2026, 11, 7, tzinfo=UTC),
        )


def _use_fake_translation_service(app: FastAPI, fake: _FakeTranslationService) -> None:
    app.dependency_overrides[get_translation_service] = lambda: fake


def _use_fake_option_translation_service(
    app: FastAPI, fake: _FakeOptionTranslationService
) -> None:
    app.dependency_overrides[get_option_translation_service] = lambda: fake


_URL_TRADUCAO_PERGUNTA = f"/questions/{QUESTION_ID}/translations"
_TRADUCAO_PERGUNTA = {"lang": "en", "text": "Do you adapt well?"}
_URL_TRADUCAO_ALTERNATIVA = f"/options/{OPTION_ID}/translations"
_TRADUCAO_ALTERNATIVA = {"lang": "es", "label": "Sí"}


class TestTraduzirPergunta:
    def test_com_corpo_valido_devolve_201_com_o_corpo_completo(
        self, app: FastAPI, client: TestClient
    ) -> None:
        service = _FakeTranslationService()
        _use_fake_translation_service(app, service)

        response = client.post(_URL_TRADUCAO_PERGUNTA, json=_TRADUCAO_PERGUNTA)

        assert response.status_code == 201
        body = response.json()
        assert set(body) == {"id", "question_id", "lang", "text", "created_at"}
        assert (body["question_id"], body["lang"]) == (str(QUESTION_ID), "en")
        assert service.pedido == (QUESTION_ID, "admin", ORGANIZATION_ID)

    def test_pergunta_inexistente_devolve_404(
        self, app: FastAPI, client: TestClient
    ) -> None:
        mensagem = f"Pergunta {QUESTION_ID} não encontrada"
        _use_fake_translation_service(
            app, _FakeTranslationService(NotFoundError(mensagem))
        )

        response = client.post(_URL_TRADUCAO_PERGUNTA, json=_TRADUCAO_PERGUNTA)

        assert response.status_code == 404
        assert response.json()["detail"] == mensagem

    def test_idioma_ja_traduzido_devolve_409(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_translation_service(
            app, _FakeTranslationService(ConflictError("Já existe tradução 'en'"))
        )

        response = client.post(_URL_TRADUCAO_PERGUNTA, json=_TRADUCAO_PERGUNTA)

        assert response.status_code == 409

    def test_pergunta_de_outra_organizacao_devolve_403(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "gestor")
        _use_fake_translation_service(
            app,
            _FakeTranslationService(
                ForbiddenError("Sem acesso a formulário de outra organização")
            ),
        )

        response = client.post(_URL_TRADUCAO_PERGUNTA, json=_TRADUCAO_PERGUNTA)

        assert response.status_code == 403

    def test_com_lang_pt_devolve_422_sem_chamar_o_service(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """O PT vive em `Question.text`: não é tradução."""
        service = _FakeTranslationService()
        _use_fake_translation_service(app, service)

        response = client.post(
            _URL_TRADUCAO_PERGUNTA, json={**_TRADUCAO_PERGUNTA, "lang": "pt"}
        )

        assert response.status_code == 422
        assert service.pedido is None

    def test_respondente_devolve_403_pela_guarda(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "respondente")
        service = _FakeTranslationService()
        _use_fake_translation_service(app, service)

        response = client.post(_URL_TRADUCAO_PERGUNTA, json=_TRADUCAO_PERGUNTA)

        assert response.status_code == 403
        assert service.pedido is None


class TestTraduzirAlternativa:
    def test_com_corpo_valido_devolve_201_com_o_corpo_completo(
        self, app: FastAPI, client: TestClient
    ) -> None:
        service = _FakeOptionTranslationService()
        _use_fake_option_translation_service(app, service)

        response = client.post(_URL_TRADUCAO_ALTERNATIVA, json=_TRADUCAO_ALTERNATIVA)

        assert response.status_code == 201
        body = response.json()
        assert set(body) == {"id", "option_id", "lang", "label", "created_at"}
        assert (body["option_id"], body["lang"]) == (str(OPTION_ID), "es")
        assert service.pedido == (OPTION_ID, "admin", ORGANIZATION_ID)

    def test_alternativa_inexistente_devolve_404(
        self, app: FastAPI, client: TestClient
    ) -> None:
        mensagem = f"Alternativa {OPTION_ID} não encontrada"
        _use_fake_option_translation_service(
            app, _FakeOptionTranslationService(NotFoundError(mensagem))
        )

        response = client.post(_URL_TRADUCAO_ALTERNATIVA, json=_TRADUCAO_ALTERNATIVA)

        assert response.status_code == 404
        assert response.json()["detail"] == mensagem

    def test_idioma_ja_traduzido_devolve_409(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_option_translation_service(
            app, _FakeOptionTranslationService(ConflictError("Já existe tradução 'es'"))
        )

        response = client.post(_URL_TRADUCAO_ALTERNATIVA, json=_TRADUCAO_ALTERNATIVA)

        assert response.status_code == 409

    def test_alternativa_de_outra_organizacao_devolve_403(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "gestor")
        _use_fake_option_translation_service(
            app,
            _FakeOptionTranslationService(
                ForbiddenError("Sem acesso a formulário de outra organização")
            ),
        )

        response = client.post(_URL_TRADUCAO_ALTERNATIVA, json=_TRADUCAO_ALTERNATIVA)

        assert response.status_code == 403

    def test_com_lang_pt_devolve_422_sem_chamar_o_service(
        self, app: FastAPI, client: TestClient
    ) -> None:
        service = _FakeOptionTranslationService()
        _use_fake_option_translation_service(app, service)

        response = client.post(
            _URL_TRADUCAO_ALTERNATIVA, json={**_TRADUCAO_ALTERNATIVA, "lang": "pt"}
        )

        assert response.status_code == 422
        assert service.pedido is None

    def test_respondente_devolve_403_pela_guarda(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "respondente")
        service = _FakeOptionTranslationService()
        _use_fake_option_translation_service(app, service)

        response = client.post(_URL_TRADUCAO_ALTERNATIVA, json=_TRADUCAO_ALTERNATIVA)

        assert response.status_code == 403
        assert service.pedido is None
