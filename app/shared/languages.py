"""Os idiomas da plataforma.

São os mesmos da tela (`IDIOMAS` em `creed-frontend/src/i18n/config.ts`). O idioma
escolhido na tela vai no envio da resposta e decide em que língua o insight é
escrito.
"""

from typing import Literal, get_args

Language = Literal["pt-BR", "en", "es"]

LANGUAGES: tuple[str, ...] = get_args(Language)

# Quem não diz o idioma (um cliente antigo, por exemplo) recebe o texto em pt-BR.
DEFAULT_LANGUAGE: Language = "pt-BR"
