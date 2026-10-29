"""Testes do registro de tabelas de app/models.py (CREED-365).

Rodam num processo Python novo: neste processo o pytest já importou todos os
models (pelo `app.main` dos outros testes), e o `Base.metadata` estaria completo
de qualquer jeito. Um script de seed começa do zero — é essa situação que importa.
"""

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

_ORDENAR_O_FLUSH = (
    "from app.domains.participants.models import Participant; "
    "Participant.__mapper__._sorted_tables"
)


def _python(codigo: str) -> subprocess.CompletedProcess[str]:
    # S603: o código executado é constante deste arquivo, não entrada externa.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", codigo],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )


def test_sem_o_registro_a_fk_por_nome_nao_resolve() -> None:
    # Documenta o problema: `participants` aponta para `documents` por texto.
    resultado = _python(_ORDENAR_O_FLUSH)

    assert "NoReferencedTableError" in resultado.stderr


def test_com_o_registro_a_fk_por_nome_resolve() -> None:
    resultado = _python("from app import models; " + _ORDENAR_O_FLUSH)

    assert resultado.returncode == 0, resultado.stderr
