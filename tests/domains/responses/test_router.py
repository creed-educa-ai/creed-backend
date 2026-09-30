"""Testes de contrato HTTP do domínio responses — contrato HTTP e guarda.

A guarda roda de verdade: só o `validate_token` e o `UserService` são dublês, como
em `tests/domains/participants/test_router.py`. O `client` padrão entra como
`respondente`, com o vínculo `LINK_ID`; os testes de token trocam isso
explicitamente.

A regra de dono e de organização é provada em test_service.py. Aqui se prova que
o vínculo chega do login ao service e que cada erro vira o status documentado.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.responses.dependencies import get_answer_service, get_service
from app.domains.responses.models import Answer, FormResponse, FormResponseStatus
from app.domains.responses.router import router
from app.domains.responses.schemas import AnswerCreate
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
LINK_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
TOKEN = {"Authorization": "Bearer valido"}


class _FakeFormResponseService:
    """Dublê do service: guarda as respostas abertas e registra quem pediu.

    `recusar` faz `create_form_response` levantar o erro dado, sem gravar. O
    `submit_form_response` recusa com `ForbiddenError` a resposta de outro
    vínculo, como o service real; a ordem das conferências é provada em
    test_service.py.
    """

    def __init__(
        self,
        existentes: list[FormResponse] | None = None,
        *,
        recusar: Exception | None = None,
    ) -> None:
        self.itens = {fr.id: fr for fr in existentes or []}
        self.recusar = recusar
        self.quem_pediu: tuple[uuid.UUID, uuid.UUID] | None = None

    async def create_form_response(
        self,
        form_id: uuid.UUID,
        *,
        link_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> FormResponse:
        self.quem_pediu = (link_id, organization_id)
        if self.recusar is not None:
            raise self.recusar
        form_response = um_form_response(form_id=form_id, vinculo_id=link_id)
        self.itens[form_response.id] = form_response
        return form_response

    async def submit_form_response(
        self, form_response_id: uuid.UUID, *, link_id: uuid.UUID
    ) -> FormResponse:
        form_response = self.itens.get(form_response_id)
        if form_response is None:
            raise NotFoundError(f"FormResponse {form_response_id} não encontrado")
        if form_response.vinculo_id != link_id:
            raise ForbiddenError(
                f"FormResponse {form_response_id} pertence a outro vínculo"
            )
        if form_response.status is not FormResponseStatus.IN_PROGRESS:
            raise ConflictError(f"FormResponse {form_response_id} já foi submetido")
        form_response.status = FormResponseStatus.SUBMITTED
        form_response.submitted_at = datetime(2026, 9, 30, tzinfo=UTC)
        return form_response


def um_form_response(**campos: object) -> FormResponse:
    """FormResponse montado à mão, com todo campo explícito."""
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "form_id": uuid.uuid4(),
        "vinculo_id": LINK_ID,
        "status": FormResponseStatus.IN_PROGRESS,
        "started_at": datetime(2026, 9, 30, tzinfo=UTC),
        "submitted_at": None,
    }
    return FormResponse(**{**padrao, **campos})


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


def autenticar_como(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    link_id: uuid.UUID = LINK_ID,
) -> None:
    """Faz o token de teste valer como um usuário ativo com o papel e o vínculo."""
    email = "dev@creed.example.com"

    async def _fake_validate_token(token: str) -> dict[str, Any]:
        return {"sub": "sub-dev", "email": email, "realm_access": {"roles": [role]}}

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=role,
        link_id=link_id,
        organization_id=ORGANIZATION_ID,
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Entra como `respondente`, com o token em toda requisição."""
    autenticar_como(app, monkeypatch, "respondente")
    return TestClient(app, headers=TOKEN)


def _use_fake_service(app: FastAPI, fake_service: _FakeFormResponseService) -> None:
    app.dependency_overrides[get_service] = lambda: fake_service


class TestIniciarResposta:
    def test_devolve_201_com_o_vinculo_do_login(
        self, app: FastAPI, client: TestClient
    ) -> None:
        fake = _FakeFormResponseService()
        _use_fake_service(app, fake)
        form_id = uuid.uuid4()

        response = client.post("/form-responses", json={"form_id": str(form_id)})

        assert response.status_code == 201
        assert response.json()["form_id"] == str(form_id)
        assert response.json()["vinculo_id"] == str(LINK_ID)
        assert fake.quem_pediu == (LINK_ID, ORGANIZATION_ID)

    def test_vinculo_id_no_corpo_e_ignorado(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeFormResponseService())
        payload = {"form_id": str(uuid.uuid4()), "vinculo_id": str(uuid.uuid4())}

        response = client.post("/form-responses", json=payload)

        assert response.status_code == 201
        assert response.json()["vinculo_id"] == str(LINK_ID)

    def test_formulario_de_outra_organizacao_devolve_403(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(
            app,
            _FakeFormResponseService(
                recusar=ForbiddenError("Sem acesso a formulário de outra organização")
            ),
        )

        response = client.post("/form-responses", json={"form_id": str(uuid.uuid4())})

        assert response.status_code == 403

    def test_resposta_ja_aberta_devolve_409(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(
            app,
            _FakeFormResponseService(
                recusar=ConflictError("Já existe uma resposta para o formulário")
            ),
        )

        response = client.post("/form-responses", json={"form_id": str(uuid.uuid4())})

        assert response.status_code == 409
        assert response.json()["detail"].startswith("Já existe uma resposta")

    def test_formulario_inexistente_devolve_422_com_detail_texto(
        self, app: FastAPI, client: TestClient
    ) -> None:
        form_id = uuid.uuid4()
        _use_fake_service(
            app,
            _FakeFormResponseService(
                recusar=ValidationError(f"Formulário {form_id} não encontrado")
            ),
        )

        response = client.post("/form-responses", json={"form_id": str(form_id)})

        assert response.status_code == 422
        assert response.json()["detail"] == f"Formulário {form_id} não encontrado"

    def test_sem_token_devolve_401(self, app: FastAPI) -> None:
        _use_fake_service(app, _FakeFormResponseService())

        response = TestClient(app).post(
            "/form-responses", json={"form_id": str(uuid.uuid4())}
        )

        assert response.status_code == 401


class TestSubmeterResposta:
    def test_a_propria_devolve_200_submetida(
        self, app: FastAPI, client: TestClient
    ) -> None:
        propria = um_form_response()
        _use_fake_service(app, _FakeFormResponseService([propria]))

        response = client.patch(f"/form-responses/{propria.id}")

        assert response.status_code == 200
        assert response.json()["status"] == "submitted"

    def test_a_de_outro_vinculo_devolve_403(
        self, app: FastAPI, client: TestClient
    ) -> None:
        alheia = um_form_response(vinculo_id=uuid.uuid4())
        _use_fake_service(app, _FakeFormResponseService([alheia]))

        response = client.patch(f"/form-responses/{alheia.id}")

        assert response.status_code == 403
        assert alheia.status is FormResponseStatus.IN_PROGRESS

    def test_ja_submetida_devolve_409(self, app: FastAPI, client: TestClient) -> None:
        submetida = um_form_response(status=FormResponseStatus.SUBMITTED)
        _use_fake_service(app, _FakeFormResponseService([submetida]))

        response = client.patch(f"/form-responses/{submetida.id}")

        assert response.status_code == 409
        assert response.json()["detail"].endswith("já foi submetido")

    def test_inexistente_devolve_404(self, app: FastAPI, client: TestClient) -> None:
        _use_fake_service(app, _FakeFormResponseService())

        response = client.patch(f"/form-responses/{uuid.uuid4()}")

        assert response.status_code == 404

    def test_sem_token_devolve_401(self, app: FastAPI) -> None:
        propria = um_form_response()
        _use_fake_service(app, _FakeFormResponseService([propria]))

        response = TestClient(app).patch(f"/form-responses/{propria.id}")

        assert response.status_code == 401


class _FakeAnswerService:
    """Dublê do `AnswerService`: grava em lista e registra o vínculo que chegou.

    `recusar` faz as duas rotas levantarem o erro dado. A ordem das conferências
    e a regra de cada uma são provadas em test_service.py; aqui se prova só a
    tradução de cada erro para o status documentado.
    """

    def __init__(self, *, recusar: Exception | None = None) -> None:
        self.recusar = recusar
        self.itens: list[Answer] = []
        self.link_recebido: uuid.UUID | None = None

    async def record(
        self, form_response_id: uuid.UUID, dados: AnswerCreate, *, link_id: uuid.UUID
    ) -> Answer:
        self.link_recebido = link_id
        if self.recusar is not None:
            raise self.recusar
        answer = Answer(
            id=uuid.uuid4(),
            form_response_id=form_response_id,
            question_id=dados.question_id,
            option_id=None,
            value=dados.value,
            created_at=datetime(2026, 9, 30, tzinfo=UTC),
        )
        self.itens.append(answer)
        return answer

    async def list_for_form_response(
        self, form_response_id: uuid.UUID, *, link_id: uuid.UUID
    ) -> list[Answer]:
        self.link_recebido = link_id
        if self.recusar is not None:
            raise self.recusar
        return [a for a in self.itens if a.form_response_id == form_response_id]


def _use_fake_answer_service(app: FastAPI, fake_service: _FakeAnswerService) -> None:
    app.dependency_overrides[get_answer_service] = lambda: fake_service


ERROS_DO_SERVICE = [
    (NotFoundError("FormResponse não encontrado"), 404),
    (ForbiddenError("FormResponse pertence a outro vínculo"), 403),
    (ConflictError("A pergunta já foi respondida nesta resposta"), 409),
    (ValidationError("Respostas a perguntas objetivas chegam com as alternativas"), 422),
]


class TestGravarAnswer:
    def test_devolve_201_com_a_resposta_de_formulario_e_a_pergunta(
        self, app: FastAPI, client: TestClient
    ) -> None:
        fake = _FakeAnswerService()
        _use_fake_answer_service(app, fake)
        form_response_id, question_id = uuid.uuid4(), uuid.uuid4()

        response = client.post(
            f"/form-responses/{form_response_id}/answers",
            json={"question_id": str(question_id), "value": "minha resposta"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["form_response_id"] == str(form_response_id)
        assert body["question_id"] == str(question_id)
        assert body["value"] == "minha resposta"
        assert fake.link_recebido == LINK_ID

    @pytest.mark.parametrize(("erro", "status_esperado"), ERROS_DO_SERVICE)
    def test_erro_do_service_vira_o_status_documentado(
        self,
        app: FastAPI,
        client: TestClient,
        erro: Exception,
        status_esperado: int,
    ) -> None:
        _use_fake_answer_service(app, _FakeAnswerService(recusar=erro))

        response = client.post(
            f"/form-responses/{uuid.uuid4()}/answers",
            json={"question_id": str(uuid.uuid4()), "value": "texto"},
        )

        assert response.status_code == status_esperado
        assert response.json()["detail"] == str(erro)

    def test_sem_token_devolve_401(self, app: FastAPI) -> None:
        _use_fake_answer_service(app, _FakeAnswerService())

        response = TestClient(app).post(
            f"/form-responses/{uuid.uuid4()}/answers",
            json={"question_id": str(uuid.uuid4()), "value": "texto"},
        )

        assert response.status_code == 401


class TestListarAnswers:
    def test_devolve_200_com_o_que_foi_gravado_em_ordem(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_answer_service(app, _FakeAnswerService())
        form_response_id = uuid.uuid4()
        url = f"/form-responses/{form_response_id}/answers"
        for texto in ("primeira", "segunda"):
            client.post(url, json={"question_id": str(uuid.uuid4()), "value": texto})

        response = client.get(url)

        assert response.status_code == 200
        assert [item["value"] for item in response.json()] == ["primeira", "segunda"]

    @pytest.mark.parametrize(
        ("erro", "status_esperado"),
        [
            (NotFoundError("FormResponse não encontrado"), 404),
            (ForbiddenError("FormResponse pertence a outro vínculo"), 403),
        ],
    )
    def test_erro_do_service_vira_o_status_documentado(
        self,
        app: FastAPI,
        client: TestClient,
        erro: Exception,
        status_esperado: int,
    ) -> None:
        _use_fake_answer_service(app, _FakeAnswerService(recusar=erro))

        response = client.get(f"/form-responses/{uuid.uuid4()}/answers")

        assert response.status_code == status_esperado

    def test_sem_token_devolve_401(self, app: FastAPI) -> None:
        _use_fake_answer_service(app, _FakeAnswerService())

        response = TestClient(app).get(f"/form-responses/{uuid.uuid4()}/answers")

        assert response.status_code == 401
