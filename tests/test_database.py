"""Testes do `SessionDep` de app/core/database.py (CREED-364).

O `get_db` é trocado por um dublê cujo "commit" (o código depois do `yield`)
falha. Com `scope="function"`, a falha acontece antes de a resposta sair e vira
500. No escopo padrão do FastAPI a rota já teria respondido 200, e a falha do
commit não chegaria a ninguém.

Nos testes com `FakeSession`, o `get_db` é o de verdade e só a sessão é dublê: o
que se prova é quando ele grava e quando ele desfaz.
"""

from collections.abc import AsyncGenerator
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.core import database
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


class FakeSession:
    """Faz as vezes da `AsyncSession`: só anota se houve commit ou rollback."""

    def __init__(self) -> None:
        self.chamadas: list[str] = []

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def commit(self) -> None:
        self.chamadas.append("commit")

    async def rollback(self) -> None:
        self.chamadas.append("rollback")


def _app_com_get_db_de_verdade(
    monkeypatch: pytest.MonkeyPatch, sessao: FakeSession, *, falha: bool
) -> FastAPI:
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: sessao)
    app = FastAPI()

    @app.post("/convite")
    async def convite(db: SessionDep) -> dict[str, str]:
        # Como o 409 do convite de membro (CREED-23.8, D8): participante e vínculo
        # já passaram pelo flush quando a rota traduz o erro em HTTPException.
        if falha:
            raise HTTPException(status.HTTP_409_CONFLICT, "Já existe usuário")
        return {"ok": "sim"}

    return app


def test_rota_que_responde_grava(monkeypatch: pytest.MonkeyPatch) -> None:
    sessao = FakeSession()
    app = _app_com_get_db_de_verdade(monkeypatch, sessao, falha=False)

    response = TestClient(app).post("/convite")

    assert response.status_code == 200
    assert sessao.chamadas == ["commit"]


def test_http_exception_depois_de_gravar_desfaz_em_vez_de_gravar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O tudo ou nada da D8 depende disto: o erro HTTP chega ao `get_db`."""
    sessao = FakeSession()
    app = _app_com_get_db_de_verdade(monkeypatch, sessao, falha=True)

    response = TestClient(app).post("/convite")

    assert response.status_code == 409
    assert sessao.chamadas == ["rollback"]
