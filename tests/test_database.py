"""Testes do `SessionDep` de app/core/database.py (CREED-364).

O `get_db` é trocado por um dublê cujo "commit" (o código depois do `yield`)
falha. Com `scope="function"`, a falha acontece antes de a resposta sair e vira
500. No escopo padrão do FastAPI a rota já teria respondido 200, e a falha do
commit não chegaria a ninguém.
"""

from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.database import SessionDep, get_db


def _app(sessoes_abertas: list[object]) -> FastAPI:
    async def get_db_cujo_commit_falha() -> AsyncGenerator[object, None]:
        sessao = object()
        sessoes_abertas.append(sessao)
        yield sessao
        raise RuntimeError("commit falhou")

    # Dois "repositories" na mesma rota, como participants + documents.
    def repository_a(db: SessionDep) -> Any:
        return db

    def repository_b(db: SessionDep) -> Any:
        return db

    app = FastAPI()
    app.dependency_overrides[get_db] = get_db_cujo_commit_falha

    @app.post("/cadastro")
    async def cadastro(
        a: Annotated[Any, Depends(repository_a)],
        b: Annotated[Any, Depends(repository_b)],
    ) -> dict[str, bool]:
        return {"mesma_sessao": a is b}

    return app


def test_commit_que_falha_vira_500_e_nao_sucesso() -> None:
    app = _app([])

    response = TestClient(app, raise_server_exceptions=False).post("/cadastro")

    assert response.status_code == 500


def test_a_requisicao_abre_uma_sessao_so() -> None:
    sessoes_abertas: list[object] = []
    app = _app(sessoes_abertas)

    TestClient(app, raise_server_exceptions=False).post("/cadastro")

    assert len(sessoes_abertas) == 1
