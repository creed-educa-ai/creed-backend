"""Testes de app/domains/questions/router.py — só contrato HTTP.

Não existe banco de teste no projeto: a app é montada só com este
roteador, e a service é trocada por um dublê em memória. Quem prova a
regra de negócio (conflito de posição) é tests/domains/questions/test_service.py;
quem prova ordenação e filtro de verdade, no banco, é a verificação manual
descrita na própria tarefa CREED-353.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.questions.dependencies import get_service
from app.domains.questions.models import Question, QuestionSection, QuestionType
from app.domains.questions.router import router
from app.domains.questions.schemas import QuestionCreate
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError


class _FakeQuestionService:
    """Duble da service: devolve o que for configurado, sem reimplementar regra.

    `conflito=True` só faz `create` levantar `ConflictError` — não reproduz a
    lógica real de "mesma posição no mesmo formulário". Essa regra já está
    coberta em tests/domains/questions/test_service.py; aqui o que se prova é
    só a tradução ConflictError -> 409, que é trabalho do router.

    `formulario_inexistente=True` faz as duas rotas recusarem como o service real
    recusa um formulário que não existe: `ValidationError` no cadastro e
    `NotFoundError` na listagem.
    """

    def __init__(
        self,
        existentes: list[Question] | None = None,
        *,
        conflito: bool = False,
        formulario_inexistente: bool = False,
    ) -> None:
        self.itens: list[Question] = list(existentes or [])
        self.conflito = conflito
        self.formulario_inexistente = formulario_inexistente

    async def create(self, request: QuestionCreate) -> Question:
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
            prisma=request.prisma,
            created_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
        self.itens.append(question)
        return question

    async def list_for_form(
        self, form_id: uuid.UUID, section: QuestionSection | None = None
    ) -> list[Question]:
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


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


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
            "prisma",
            "created_at",
        }
        assert body["section"] == "assessment"

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
