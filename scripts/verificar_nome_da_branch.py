"""Avisa antes de empurrar uma branch fora do padrão (CONTRIBUTING.md).

Rodado pelo pre-commit no estágio de pre-push. É conveniência, não garantia:
`--no-verify` passa por cima. A garantia é o check `nome-da-branch`,
obrigatório no PR.

Em Python, e não em shell, porque `language: script` depende do shebang — que
o Windows não honra, e o time desenvolve no Windows. O pre-commit sempre tem
um Python à mão; `/bin/sh`, não.

O padrão abaixo é o mesmo de `.github/workflows/nome-da-branch.yml`.
"""

import re
import subprocess
import sys

PADRAO = re.compile(
    r"^(feat|fix|refactor|perf|test|docs|style|chore|ci|build|hotfix|release)"
    r"/[a-z0-9]*[0-9][a-z0-9]*-[a-z][a-z0-9]*(-[a-z0-9]+)*$"
)

PERMANENTES = frozenset({"main", "dev"})

# Sem acento de propósito: o Python encoda o stderr no locale do sistema, que no
# Windows é cp1252 — o texto sairia quebrado em qualquer terminal UTF-8, e este
# recado aparece no `git push` de quem estiver em qualquer shell.
AJUDA = """
Nome de branch fora do padrao: {branch}

  Esperado: <slug>/<id-clickup>-<contexto>
  Exemplo:  feat/1-criar-usuarios

  Slugs: feat fix refactor perf test docs style chore ci build hotfix release
  O ID precisa ter pelo menos um digito; tudo em minusculas, sem acento.

Renomeie antes de empurrar:

  git branch -m feat/1-criar-usuarios

Detalhes em CONTRIBUTING.md.
"""


def branch_atual() -> str | None:
    """Nome da branch, ou None se o HEAD estiver solto (nada a validar)."""
    try:
        # S607: `git` pelo PATH, sem caminho absoluto — é o mesmo git que o
        # próprio hook já está usando, com argumentos fixos e sem shell.
        saida = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if saida.returncode != 0:
        return None
    return saida.stdout.strip() or None


def main() -> int:
    branch = branch_atual()
    if branch is None or branch in PERMANENTES:
        return 0
    if PADRAO.match(branch):
        return 0
    print(AJUDA.format(branch=branch), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
