"""Testes de arquitetura: as regras de camada de conventions/camadas-do-back.md.

Camada furada não dá erro de compilação nem de tipo — só aparece no review, se
alguém lembrar. Este arquivo é esse "se alguém lembrar", em forma de CI
(ADR-0004, item 6).

Exceção legítima entra na lista de permitidos aqui, com o motivo escrito ao lado.
Lista crescendo muito não é sinal de afrouxar o teste: é sinal de que a fronteira
está no lugar errado.
"""

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

DOMINIOS = sorted(
    caminho
    for caminho in (APP / "domains").iterdir()
    if caminho.is_dir() and not caminho.name.startswith("__")
)
NOMES = [caminho.name for caminho in DOMINIOS]

# Exceções declaradas (ADR-0004, item 4): domínio de LEITURA pode ler tabela de
# outro domínio por JOIN, no repository — escrever fora do próprio domínio, nunca.
# Formato: nome do domínio -> motivo. Exemplo de como preencher:
#     "dashboards": "agrega respondentes e prismas; ver docstring do repository"
LEITURA_ENTRE_DOMINIOS: dict[str, str] = {}

IMPORT_DE_DOMINIO = re.compile(r"from app\.domains\.(\w+)")


def _codigo(arquivo: Path) -> list[str]:
    """Linhas do arquivo, fora as que são só comentário."""
    if not arquivo.exists():
        return []
    return [
        linha
        for linha in arquivo.read_text(encoding="utf-8").splitlines()
        if not linha.strip().startswith("#")
    ]


def _imports(linhas: list[str]) -> list[str]:
    """Só as linhas de import de nível de módulo."""
    return [linha for linha in linhas if linha.startswith(("import ", "from "))]


@pytest.mark.parametrize("dominio", DOMINIOS, ids=NOMES)
def test_service_nao_conhece_http_nem_orm(dominio: Path) -> None:
    linhas = _codigo(dominio / "service.py")

    frameworks = [
        linha for linha in _imports(linhas) if "fastapi" in linha or "sqlalchemy" in linha
    ]
    assert not frameworks, (
        f"{dominio.name}/service.py importa framework web ou ORM: {frameworks}. "
        "HTTP é do router; query é do repository."
    )

    consultas = [linha for linha in linhas if "select(" in linha or "self.db" in linha]
    assert not consultas, (
        f"{dominio.name}/service.py monta query: {consultas}. Isso é repository."
    )


@pytest.mark.parametrize("dominio", DOMINIOS, ids=NOMES)
def test_router_nao_conhece_models_nem_orm(dominio: Path) -> None:
    proibidos = [
        linha
        for linha in _imports(_codigo(dominio / "router.py"))
        if ".models import" in linha or "sqlalchemy" in linha
    ]
    assert not proibidos, (
        f"{dominio.name}/router.py conhece a tabela: {proibidos}. "
        "O mapeamento model -> schema é `de_model()`, em schemas.py."
    )


@pytest.mark.parametrize("dominio", DOMINIOS, ids=NOMES)
def test_repository_nao_decide_regra(dominio: Path) -> None:
    proibidos = [
        linha
        for linha in _codigo(dominio / "repository.py")
        if "shared.exceptions" in linha or "HTTPException" in linha
    ]
    assert not proibidos, (
        f"{dominio.name}/repository.py levanta erro de negócio: {proibidos}. "
        "Devolva None e deixe o service decidir."
    )


@pytest.mark.parametrize("dominio", DOMINIOS, ids=NOMES)
def test_dominio_nao_importa_dominio(dominio: Path) -> None:
    invasores = []
    for arquivo in sorted(dominio.glob("*.py")):
        for linha in _imports(_codigo(arquivo)):
            for alvo in IMPORT_DE_DOMINIO.findall(linha):
                if alvo == dominio.name:
                    continue
                permitido = (
                    dominio.name in LEITURA_ENTRE_DOMINIOS
                    and arquivo.name == "repository.py"
                )
                if not permitido:
                    invasores.append(f"{arquivo.name}: {linha.strip()}")

    assert not invasores, (
        f"{dominio.name} importa outro domínio: {invasores}. "
        "Passe pelo service do dono, ou declare a leitura em LEITURA_ENTRE_DOMINIOS."
    )


def test_commit_so_no_get_db() -> None:
    database = APP / "core" / "database.py"
    culpados = [
        str(arquivo.relative_to(APP))
        for arquivo in sorted(APP.rglob("*.py"))
        if arquivo != database and any(".commit()" in linha for linha in _codigo(arquivo))
    ]
    assert not culpados, (
        f"commit fora do get_db em: {culpados}. "
        "A unidade de trabalho é a requisição; repository usa flush()."
    )


def test_nao_existe_utils_global() -> None:
    assert not (APP / "shared" / "utils.py").exists(), (
        "app/shared/utils.py é proibido: compartilhado sobe com nome de assunto "
        "(paginacao.py, datas.py), não para um depósito sem dono."
    )
