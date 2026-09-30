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

# Exceção declarada: schemas.py pode reexportar um tipo de VALOR de
# models.py (Enum — nunca model de tabela) para o router usar, em vez de
# duplicar os mesmos valores num segundo enum só de API. Sem esta lista,
# reexportar é o mesmo desvio de `router.py` importar de `models.py` direto,
# só que escondido atrás de schemas.py. Formato: nome do domínio -> motivo.
REEXPORT_DE_TIPO_PERMITIDO: dict[str, str] = {
    "questions": (
        "QuestionSection, QuestionType e Prisma são tipos de valor (Enum), não ORM. "
        "schemas.py os reexporta para o filtro ?section= de router.py usar, "
        "sem duplicar os valores em um segundo enum."
    ),
}


COMPOE_COM_SERVICE_DE: dict[str, str] = {
    "authentication": "le o usuario pelo UserService",
    "links": "confere o participante pelo ParticipantService",
    "participants": "consulta documento pelo DocumentService",
    "questions": "confere o formulario pelo FormService",
    "responses": "confere o formulario pelo FormService",
    "users": "le o papel e a organizacao do vinculo pelo LinkService",
}

SUBMODULOS_DE_COMPOSICAO = {"service", "dependencies"}

IMPORT_DE_DOMINIO = re.compile(r"from app\.domains\.(\w+)\.(\w+)")


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
def test_reexport_de_tipo_do_model_e_declarado(dominio: Path) -> None:
    """`schemas.py` pode importar de `models.py` — é o normal de `de_model()`.

    O que precisa de exceção declarada é REEXPORTAR esse tipo (`__all__`) para
    outra camada importar: aí o acoplamento com `models.py` continua existindo,
    só que por um desvio que passa no grep de `test_router_nao_conhece_models_nem_orm`.
    """
    linhas_schemas = _codigo(dominio / "schemas.py")
    importa_de_models = any(
        f"from app.domains.{dominio.name}.models import" in linha
        for linha in _imports(linhas_schemas)
    )
    reexporta = any(linha.strip().startswith("__all__") for linha in linhas_schemas)

    if importa_de_models and reexporta:
        assert dominio.name in REEXPORT_DE_TIPO_PERMITIDO, (
            f"{dominio.name}/schemas.py reexporta tipo de models.py (tem `__all__`) "
            "sem motivo declarado em REEXPORT_DE_TIPO_PERMITIDO."
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
            for alvo, submodulo in IMPORT_DE_DOMINIO.findall(linha):
                if alvo == dominio.name:
                    continue
                leitura_por_join = (
                    dominio.name in LEITURA_ENTRE_DOMINIOS
                    and arquivo.name == "repository.py"
                )
                composicao_por_service = (
                    dominio.name in COMPOE_COM_SERVICE_DE
                    and submodulo in SUBMODULOS_DE_COMPOSICAO
                )
                if not (leitura_por_join or composicao_por_service):
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


@pytest.mark.parametrize("dominio", DOMINIOS, ids=NOMES)
def test_models_do_dominio_esta_no_registro(dominio: Path) -> None:
    if not (dominio / "models.py").exists():
        pytest.skip(f"{dominio.name} não tem models.py")

    registro = _imports(_codigo(APP / "models.py"))
    assert f"from app.domains.{dominio.name} import models" in "\n".join(registro), (
        f"{dominio.name}/models.py não está em app/models.py. Sem o registro, o "
        "autogenerate não enxerga a tabela e FK por nome para ela quebra no flush."
    )


def test_sessao_so_pelo_session_dep() -> None:
    database = APP / "core" / "database.py"
    culpados = [
        str(arquivo.relative_to(APP))
        for arquivo in sorted(APP.rglob("*.py"))
        if arquivo != database
        and any("Depends(get_db" in linha for linha in _codigo(arquivo))
    ]
    assert not culpados, (
        f"Depends(get_db) solto em: {culpados}. "
        "Use SessionDep: ele fecha a sessão (commit) antes de a resposta sair."
    )


def test_nao_existe_utils_global() -> None:
    assert not (APP / "shared" / "utils.py").exists(), (
        "app/shared/utils.py é proibido: compartilhado sobe com nome de assunto "
        "(paginacao.py, datas.py), não para um depósito sem dono."
    )
